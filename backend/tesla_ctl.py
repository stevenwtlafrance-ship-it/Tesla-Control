#!/usr/bin/env python3
"""tesla-ctl — Fleet API backend for the Omarchy Tesla bar widget.

Handles OAuth tokens, vehicle state, and vehicle commands for a personal
Tesla Fleet API application. Supports Fleet REST commands and, on vehicles
that require it, Tesla Vehicle Command Protocol (signed) commands.

State lives under:
  ~/.config/tesla-ctl/          config.json, private_key.pem, well-known/
  ~/.local/state/tesla-ctl/     token.json, status.json (read by the bar)
"""

import argparse
import asyncio
import base64
import fcntl
import json
import os
import stat
import sys
import tempfile
import time
import urllib.parse

import aiohttp
import aiohttp.web

from tesla_fleet_api import TeslaFleetOAuth
from tesla_fleet_api.exceptions import TeslaFleetError

CONFIG_DIR = os.path.expanduser("~/.config/tesla-ctl")
STATE_DIR = os.path.expanduser("~/.local/state/tesla-ctl")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
TOKEN_PATH = os.path.join(STATE_DIR, "token.json")
TOKEN_LOCK_PATH = os.path.join(STATE_DIR, "token.lock")
KEY_PATH = os.path.join(CONFIG_DIR, "private_key.pem")
STATUS_PATH = os.path.join(STATE_DIR, "status.json")
WELLKNOWN_DIR = os.path.join(CONFIG_DIR, "well-known")
LOCALHOST_PORT = 8642

HOME = os.path.expanduser("~")
DEFAULT_REDIRECT_URI = f"http://localhost:{LOCALHOST_PORT}/callback"

REQUIRED_SCOPES = [
    "openid",
    "email",
    "offline_access",
    "vehicle_device_data",
    "vehicle_cmds",
    "vehicle_charging_cmds",
    "vehicle_location",
    "partner_accounts",
]


# ---------------------------------------------------------------- helpers

def fail(msg, code=1):
    print(f"tesla-ctl: {msg}", file=sys.stderr)
    sys.exit(code)


def json_dump(path, data, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.chmod(os.path.dirname(path), 0o700)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def json_load(path, default=None):
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception:
        return default


def load_config():
    cfg = json_load(CONFIG_PATH) or {}
    cfg.setdefault("region", "na")
    cfg.setdefault("redirect_uri", DEFAULT_REDIRECT_URI)
    cfg.setdefault("vin", "")
    return cfg


def save_token(oauth):
    with token_lock():
        json_dump(TOKEN_PATH, {
            "refresh_token": oauth.refresh_token,
            "expires": oauth.expires,
        })


def load_token():
    tok = json_load(TOKEN_PATH, None)
    if not tok or not tok.get("refresh_token"):
        return None
    return tok


class token_lock:
    """File lock (advisory, cross-process) serialising token refresh + save.

    Tesla rotates the refresh token on every refresh and invalidates the
    previous one. Multiple concurrent `tesla-ctl status`/`command`/`watch`
    invocations must not load the same token and race: one winner refreshes,
    writes the rotated token, and the losers must re-read before retrying.
    """

    def __enter__(self):
        ensure_dir(STATE_DIR)
        self.fh = open(TOKEN_LOCK_PATH, "w")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()


def ensure_dir(path, mode=0o700):
    os.makedirs(path, exist_ok=True)
    os.chmod(path, mode)


def boolean(value):
    return str(value).lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- oauth

class PersistingOAuth(TeslaFleetOAuth):
    """TeslaFleetOAuth that writes every rotated refresh token back to disk.

    Tesla rotates the refresh token on each token refresh and invalidates the
    previous one. Without persisting the rotation here, the stored token goes
    stale at the next refresh and every later run fails with 'login_required'.
    """

    async def refresh_access_token(self):
        with token_lock():
            tok = load_token()
            if tok and tok.get("refresh_token"):
                self.refresh_token = tok["refresh_token"]
                self.expires = int(tok.get("expires") or 0)
            try:
                return await self._refresh_locked()
            except ValueError as e:
                if "login_required" not in str(e):
                    raise
            # refresh_token already rotated/used by a concurrent invocation:
            # re-read the freshest token from disk and try once more.
            tok = load_token()
            if tok and tok.get("refresh_token") and tok["refresh_token"] != self.refresh_token:
                self.refresh_token = tok["refresh_token"]
                self.expires = int(tok.get("expires") or 0)
                return await self._refresh_locked()
            raise ValueError("refresh_token is invalid (login_required). Run `tesla-ctl login`.")

    async def _refresh_locked(self):
        data = await super().refresh_access_token()
        json_dump(TOKEN_PATH, {
            "refresh_token": self.refresh_token,
            "expires": self.expires,
        })
        return data


def make_oauth(session, cfg, token=None):
    token = token or load_token()
    return PersistingOAuth(
        session=session,
        region=cfg["region"],
        client_id=cfg["client_id"],
        client_secret=cfg.get("client_secret"),
        redirect_uri=cfg.get("redirect_uri") or DEFAULT_REDIRECT_URI,
        refresh_token=token.get("refresh_token") if token else None,
        expires=int(token.get("expires") or 0) if token else 0,
    )


async def resolve_vehicle(api, cfg):
    vin = (cfg.get("vin") or "").strip()
    if vin:
        return vin
    data = await api.products()
    products = (data.get("response") or []) if isinstance(data, dict) else []
    vehicles = [p for p in products if p.get("vin")]
    if not vehicles:
        fail("No vehicles on this Tesla account.")
    vin = vehicles[0].get("vin")
    if not vin:
        fail("Could not determine a VIN. Select one with: tesla-ctl select <vin>")
    cfg["vin"] = vin
    json_dump(CONFIG_PATH, cfg)
    return vin


async def login(session, cfg):
    if not (cfg.get("client_id") or "").strip():
        fail("client_id not configured. Run `tesla-ctl configure` first.")
    oauth = make_oauth(session, cfg)

    url = oauth.get_login_url(scopes=REQUIRED_SCOPES)
    redirect_path = urllib.parse.urlparse(cfg["redirect_uri"]).path or "/callback"

    auth_future = asyncio.get_running_loop().create_future()

    async def handle(request):
        query = urllib.parse.parse_qs(request.query_string)
        code = (query.get("code") or [None])[0]
        error = (query.get("error") or [None])[0]
        if error:
            auth_future.set_result({"error": error})
        elif code:
            auth_future.set_result({"code": code})
        else:
            auth_future.set_result({"error": "no code in callback"})
        return aiohttp.web.Response(
            text="<html><body><h2>tesla-ctl</h2><p>You can close this tab.</p></body></html>",
            content_type="text/html",
        )

    app = aiohttp.web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", LOCALHOST_PORT)
    await site.start()

    print("Opening Tesla sign-in in your browser…")
    print("If it does not open, paste this URL in a browser:")
    print()
    print("  " + url)
    print()
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    try:
        result = await asyncio.wait_for(auth_future, timeout=300)
    except asyncio.TimeoutError:
        fail("Timed out waiting for the Tesla sign-in callback.")
    finally:
        await runner.cleanup()

    if result.get("error"):
        fail(f"Sign-in failed: {result['error']}")

    await oauth.get_refresh_token(result["code"])
    if not oauth.refresh_token:
        fail("No refresh token returned by Tesla.")
    save_token(oauth)
    print("Signed in. Token saved to", TOKEN_PATH)


def require_oauth(session, cfg):
    token = load_token()
    if not token:
        fail("Not signed in. Run `tesla-ctl login` first.")
    return make_oauth(session, cfg, token)


# ---------------------------------------------------------------- status

def normalise_status(resp):
    v = resp.get("response") or {}
    v = v.get("vehicle_data") if "vehicle_data" in v else v

    charge = v.get("charge_state") or {}
    climate = v.get("climate_state") or {}
    veh = v.get("vehicle_state") or {}
    gui = v.get("gui_settings") or {}
    drive = v.get("drive_state") or {}
    closures = v.get("closures_state") or {}
    config = v.get("vehicle_config") or {}

    def f(vals):
        return next((x for x in vals if x not in (None, "", False)), None)

    units = gui.get("gui_range_display") or "mi"
    temp_unit = gui.get("gui_temperature_units") or "C"
    speed_unit = gui.get("gui_distance_units") or "mi/hr"

    locked = veh.get("locked", False)
    if locked is None:
        locked = not (closures.get("driver_front_open") or False)

    loc = None
    if drive.get("latitude") is not None and drive.get("longitude") is not None:
        loc = {"lat": drive["latitude"], "lon": drive["longitude"]}

    def window_open(key):
        return bool(closures.get(key))

    return {
        "ok": True,
        "error": None,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "vehicle": {
            "name": v.get("display_name") or model_label(config.get("car_type")),
            "model": model_label(config.get("car_type")) or "",
            "vin": v.get("vin") or "",
            "online": v.get("state") == "online" if v.get("state") else False,
            "connected": bool(v.get("state")),
            "battery_level": charge.get("battery_level"),
            "usable_battery_level": charge.get("usable_battery_level"),
            "battery_range_miles": charge.get("battery_range"),
            "est_battery_range_miles": charge.get("estimated_battery_range"),
            "charging_state": charge.get("charging_state"),
            "charge_enable_request": charge.get("charge_enable_request"),
            "charge_cable_connected": charge.get("charge_cable_connected"),
            "charge_limit_soc": charge.get("charge_limit_soc"),
            "charge_port_open": bool(veh.get("charge_port_door_open")),
            "locked": bool(locked),
            "sentry_mode": bool(veh.get("sentry_mode")),
            "is_climate_on": bool(climate.get("is_climate_on")),
            "preconditioning": bool(climate.get("preconditioning")),
            "inside_temp_c": climate.get("inside_temp"),
            "outside_temp_c": climate.get("outside_temp"),
            "driver_temp_setting_c": climate.get("driver_temp_setting"),
            "passenger_temp_setting_c": climate.get("passenger_temp_setting"),
            "windows_open": any([
                window_open("f0"),
                window_open("f1"),
                window_open("r0"),
                window_open("r1"),
            ]),
            "front_trunk_open": bool(closures.get("front_trunk_open") or veh.get("frunk_open")),
            "rear_trunk_open": bool(closures.get("rear_trunk_open") or veh.get("trunk_open")),
            "door_open": bool(closures.get("driver_front_open") or closures.get("passenger_front_open")
                              or closures.get("driver_rear_open") or closures.get("passenger_rear_open")),
            "odometer_miles": f([drive.get("odometer"), veh.get("odometer")]),
            "speed_units": speed_unit,
            "temp_units": temp_unit,
            "range_units": units,
            "location": loc,
            "last_updated": v.get("timestamp"),
        },
    }


async def fetch_status(api, vin):
    vehicle = api.vehicles.createFleet(vin)
    data = await vehicle.vehicle_data()
    resp = data.get("response") or {}
    raw = resp.get("vehicle_data") if "vehicle_data" in resp else resp
    status = normalise_status(data)
    if not raw.get("display_name"):
        status["vehicle"]["name"] = await fetch_display_name(api, vin) or status["vehicle"]["name"]
    return status


async def fetch_display_name(api, vin):
    try:
        data = await api.products()
        products = (data.get("response") or []) if isinstance(data, dict) else []
        for p in products:
            if p.get("vin") == vin and p.get("display_name"):
                return p.get("display_name")
    except Exception:
        pass
    return None


MODEL_LABELS = {
    "models": "Model S",
    "modelx": "Model X",
    "model3": "Model 3",
    "modely": "Model Y",
    "cybertruck": "Cybertruck",
}


def model_label(ct):
    return MODEL_LABELS.get(str(ct or "").lower(), ct) or ""


async def get_status(api, vin, write=True):
    status = await fetch_status(api, vin)
    if write:
        json_dump(STATUS_PATH, status, 0o644)
    return status


# ---------------------------------------------------------------- commands

COMMANDS = {
    "lock": ("door_lock", [], "Lock the doors"),
    "unlock": ("door_unlock", [], "Unlock the doors"),
    "climate-on": ("auto_conditioning_start", [], "Start climate"),
    "climate-off": ("auto_conditioning_stop", [], "Stop climate"),
    "temps": ("set_temps", ["float", "float"], "Set driver/passenger temps (°C)"),
    "flash": ("flash_lights", [], "Flash the lights"),
    "honk": ("honk_horn", [], "Honk the horn"),
    "vent": ("window_control", ["vent"], "Vent all windows"),
    "close-windows": ("window_control", ["close"], "Close all windows"),
    "charge-port-open": ("charge_port_door_open", [], "Open the charge port"),
    "charge-port-close": ("charge_port_door_close", [], "Close the charge port"),
    "charge-start": ("charge_start", [], "Start charging"),
    "charge-stop": ("charge_stop", [], "Stop charging"),
    "charge-limit": ("set_charge_limit", ["int"], "Set charge limit percent"),
    "trunk-open": ("actuate_trunk", ["rear"], "Open the rear trunk"),
    "frunk-open": ("actuate_trunk", ["front"], "Open the front trunk"),
    "sentry-on": ("set_sentry_mode", [True], "Enable Sentry Mode"),
    "sentry-off": ("set_sentry_mode", [False], "Disable Sentry Mode"),
    "wake": ("wake_up", [], "Wake the vehicle"),
    "remote-start": ("remote_start_drive", [], "Remote start"),
}

SIGNED_SAFE = False  # signed commands re-issue on retry; prefer explicit control


async def run_command(api, vin, name, args, force_fleet=False):
    if name not in COMMANDS:
        fail(f"Unknown command '{name}'. Run `tesla-ctl commands` to list them.")
    method_name, spec, _ = COMMANDS[name]

    bound = []
    for i, want in enumerate(spec):
        if isinstance(want, bool):
            bound.append(want)
        elif want in ("vent", "close", "rear", "front"):
            bound.append(want)
        elif want == "float":
            if i >= len(args):
                fail(f"Command '{name}' requires a numeric argument.")
            bound.append(float(args[i]))
        elif want == "int":
            if i >= len(args):
                fail(f"Command '{name}' requires an integer argument.")
            bound.append(int(args[i]))

    candidate_modes = []
    if not force_fleet:
        candidate_modes.append("signed")
    candidate_modes.append("fleet")

    last_error = None
    for mode in candidate_modes:
        vehicle = api.vehicles.createSigned(vin) if mode == "signed" else api.vehicles.createFleet(vin)
        method = getattr(vehicle, method_name)
        try:
            result = await method(*bound)
        except TeslaFleetError as e:
            last_error = e
            if mode == "signed":
                continue
            raise
        except ValueError as e:
            last_error = e
            if mode == "signed":
                continue
            raise

        try:
            payload = result.get("response") or {}
            ok = payload.get("result", True)
            reason = payload.get("reason") or ""
        except AttributeError:
            payload = result if isinstance(result, dict) else {}
            ok = payload.get("result", True)
            reason = payload.get("reason") or ""

        if ok is False:
            fail(f"Command '{name}' was rejected by the car: {reason or 'unknown reason'}"
                 + (". Signed commands are required for most vehicles (2021+). "
                    "Run `tesla-ctl doctor` and finish the VCP setup." if "signed" in str(reason).lower() else ""))

        # Refresh the status cache so the bar reflects the change.
        try:
            await get_status(api, vin)
        except Exception:
            pass

        out = {"command": name, "result": ok, "reason": reason}
        print(json.dumps(out))
        return 0

    raise last_error or TeslaFleetError("command failed")


# ---------------------------------------------------------------- keygen / vcp

def public_key_to_pem(point_hex):
    """Encode an uncompressed EC point (hex, e.g. '04…') as a SubjectPublicKeyInfo PEM."""
    point = bytes.fromhex(point_hex)
    oid_id_ecpublickey = bytes.fromhex("06 07 2a 86 48 ce 3d 02 01")
    oid_prime256v1 = bytes.fromhex("06 08 2a 86 48 ce 3d 03 01 07")
    alg_id = b"\x30\x13" + oid_id_ecpublickey + oid_prime256v1
    bit_string = b"\x03" + bytes([len(point) + 1]) + b"\x00" + point
    spki = b"\x30" + bytes([len(alg_id) + len(bit_string)]) + alg_id + bit_string
    b64 = base64.b64encode(spki).decode()
    lines = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{lines}\n-----END PUBLIC KEY-----\n"


async def register_key(session, cfg, domain):
    if not domain:
        fail("Registering requires --domain <your-domain>")
    token = load_token()
    if not token:
        fail("Not signed in. Run `tesla-ctl login` first.")

    # Tesla's OAuth JWT ou_code does not always match the account's real
    # region, so the domain must be registered on every region to avoid
    # "third party isn't registered" errors during in-app virtual-key pairing.
    regions = ("na", "eu", "cn")
    public_key = None
    ca = ""
    done = []
    errors = []
    has_private_key = False
    for region in regions:
        api = PersistingOAuth(
            session=session,
            region=region,
            client_id=cfg["client_id"],
            client_secret=cfg.get("client_secret"),
            redirect_uri=cfg.get("redirect_uri") or DEFAULT_REDIRECT_URI,
            refresh_token=token.get("refresh_token"),
            expires=int(token.get("expires") or 0),
        )
        try:
            await api.partner_login(cfg["client_id"], cfg["client_secret"])
            await api.get_private_key(KEY_PATH)
            has_private_key = has_private_key or bool(api.has_private_key)
            data = await api.partner.register(domain)
        except TeslaFleetError as e:
            errors.append(f"{region}: {e}")
            continue
        done.append(region.upper())
        if public_key is None:
            public_key = (data.get("public_key") or data.get("response", {}).get("public_key")) if isinstance(data, dict) else None
            ca = (data.get("ca") or data.get("response", {}).get("ca")) if isinstance(data, dict) else None
            if ca is None:
                ca = ""

    if public_key is None:
        fail(f"Registration failed in every region: {'; '.join(errors) or 'unknown error'}")
    if not has_private_key:
        fail("Could not set up the EC private key.")
    for r in errors:
        print(f"  note: {r}")

    ensure_dir(WELLKNOWN_DIR)
    pem = public_key_to_pem(public_key)
    with open(os.path.join(WELLKNOWN_DIR, "com.tesla.3p.public-key.pem"), "w") as fh:
        fh.write(pem + (ca + "\n" if ca else ""))
    if ca:
        with open(os.path.join(WELLKNOWN_DIR, "CA.pem"), "w") as fh:
            fh.write(ca + "\n")

    print(f"Registration succeeded for domain {domain} on: {', '.join(done)}.")
    print("1. Host this content so it is publicly reachable at:")
    print(f"     https://{domain}/.well-known/appspecific/com.tesla.3p.public-key.pem")
    print(f"   The file to host is: {os.path.join(WELLKNOWN_DIR, 'com.tesla.3p.public-key.pem')}")
    print()
    print("2. Then enroll the key with your car:")
    print(f"   - Open https://tesla.com/_ak/{domain} on a phone/tablet using the")
    print("     official Tesla app (v4.27.3+), approve the new key, and start the")
    print("     enrollment from the app — your car must be online and near you.")
    print("   - Or pair over BLE with the vehicle-command tools")
    print("     (`tesla-control -ble -vin <VIN> add-key-request owner cloud_key`,")
    print("     then tap an NFC key card on the center console when prompted).")
    print()
    print("3. Confirm it took: `tesla-ctl doctor` should report 'VCP key: enrolled'.")


# ---------------------------------------------------------------- doctor

def doctor(cfg):
    print("tesla-ctl doctor")
    print("-" * 40)
    chek = lambda ok: "OK" if ok else "MISSING"
    print(f"client_id         : {chek(bool((cfg.get('client_id') or '').strip()))}")
    print(f"region            : {cfg.get('region')}")
    print(f"redirect_uri      : {cfg.get('redirect_uri') or DEFAULT_REDIRECT_URI}")
    token = load_token()
    print(f"refresh token     : {chek(bool(token and token.get('refresh_token')))}")
    print(f"private key       : {chek(os.path.exists(KEY_PATH))}")
    print(f"default VIN       : {cfg.get('vin') or 'auto (first vehicle)'}")

    wk = os.path.join(WELLKNOWN_DIR, "com.tesla.3p.public-key.pem")
    domain = cfg.get("domain") or ""
    print(f"well-known key    : {chek(os.path.exists(wk))}" + (f" ({domain})" if domain else ""))
    print()
    if not (cfg.get("client_id") or "").strip():
        print("-> Run: tesla-ctl configure")
    if not (token and token.get("refresh_token")):
        print("-> Run: tesla-ctl login")
    elif os.path.exists(KEY_PATH) and not os.path.exists(wk):
        print("-> VCP key not registered: build the dev-app credential steps in")
        print("   ~/.config/tesla-ctl/SETUP.md then run `tesla-ctl register --domain <d>`.")
    print("-> Live check: tesla-ctl status")


# ---------------------------------------------------------------- daemon

async def daemon(session, cfg, interval):
    """Keep the OAuth refresh token alive by refreshing proactively.

    Runs forever, refreshing the token slightly before it expires.  If the
    refresh fails (refresh token revoked / expired), writes a marker file
    that the bar widget can display as a "re-login needed" notice, then
    retries every 60 seconds until a fresh login is performed externally.
    """
    LOGIN_NEEDED_PATH = os.path.join(STATE_DIR, "login_needed")

    interval = max(60, interval)
    print(f"tesla-ctl daemon: interval={interval}s", flush=True)
    while True:
        token = load_token()
        if not token or not token.get("refresh_token"):
            print("[daemon] no refresh token — waiting for login", flush=True)
            _write_marker(LOGIN_NEEDED_PATH, "no refresh token")
            await asyncio.sleep(60)
            continue

        expires = int(token.get("expires") or 0)
        now = int(time.time())
        ttl = expires - now

        # Refresh if within half the interval of expiry, or already expired
        if ttl > interval // 2:
            wait = min(ttl - interval // 2, interval)
            await asyncio.sleep(wait)
            continue

        try:
            oauth = make_oauth(session, cfg, token)
            await oauth.refresh_access_token()
            _clear_marker(LOGIN_NEEDED_PATH)
            new_token = load_token()
            new_ttl = int(new_token.get("expires") or 0) - int(time.time())
            print(f"[daemon] refreshed OK — next refresh in ~{new_ttl // 60}m", flush=True)
        except Exception as e:
            print(f"[daemon] refresh failed: {e}", flush=True)
            _write_marker(LOGIN_NEEDED_PATH, str(e))

        await asyncio.sleep(interval)


def _write_marker(path, reason):
    try:
        json_dump(path, {"reason": reason, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, 0o644)
    except Exception:
        pass


def _clear_marker(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------- cli

async def main():
    parser = argparse.ArgumentParser(prog="tesla-ctl", description="Control a Tesla via the Fleet API")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("configure", help="Set up client_id / redirect_uri / region interactively")
    sub.add_parser("login", help="Sign in with your Tesla account (opens browser)")
    sub.add_parser("vehicles", help="List vehicles on the account")
    p_sel = sub.add_parser("select", help="Choose the default vehicle")
    p_sel.add_argument("vin", help="VIN to use as default")
    sub.add_parser("status", help="Show vehicle status (updates the bar cache)")
    p_watch = sub.add_parser("watch", help="Continuously refresh the status cache")
    p_watch.add_argument("--interval", type=float, default=120, help="seconds between refreshes")
    sub.add_parser("keygen", help="Generate the EC command-signing key")
    p_reg = sub.add_parser("register", help="Register the public key & domain for VCP")
    p_reg.add_argument("--domain", default=None, help="your domain (e.g. tesla.example.com)")
    p_cmd = sub.add_parser("command", help="Send a vehicle command")
    p_cmd.add_argument("name")
    p_cmd.add_argument("args", nargs="*")
    p_cmd.add_argument("--fleet", action="store_true", help="force legacy Fleet REST (not signed) transport")
    sub.add_parser("commands", help="List available commands")
    sub.add_parser("doctor", help="Check setup readiness")
    p_daemon = sub.add_parser("daemon", help="Background token-refresher (run via systemd)")
    p_daemon.add_argument("--interval", type=float, default=900,
                          help="seconds between refresh attempts (default: 900)")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 1

    cfg = load_config()
    if args.cmd == "commands":
        for name, (_m, _s, desc) in COMMANDS.items():
            print(f"  {name:<18} {desc}")
        return 0

    if args.cmd == "configure":
        print("Tesla Fleet API app credentials (developer.tesla.com → Create App)")
        client_id = input(f"client_id [{cfg.get('client_id', '')}]: ").strip() or cfg.get("client_id", "")
        client_secret = input("client_secret (public/partner apps can leave blank) []: ").strip() or cfg.get("client_secret") or ""
        redirect_uri = input(f"redirect_uri [{cfg.get('redirect_uri') or DEFAULT_REDIRECT_URI}]: ").strip() \
            or cfg.get("redirect_uri") or DEFAULT_REDIRECT_URI
        region = input(f"region [na] (na/eu/cn): ").strip() or cfg.get("region") or "na"
        vin = input(f"vin [{cfg.get('vin', '')}] (blank = auto-pick first vehicle): ").strip() or cfg.get("vin", "")
        cfg.update({
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "region": region,
            "vin": vin,
        })
        json_dump(CONFIG_PATH, cfg)
        print("Saved config to", CONFIG_PATH)
        return 0

    async with aiohttp.ClientSession() as session:
        if args.cmd == "login":
            await login(session, cfg)
            return 0

        if args.cmd == "doctor":
            doctor(cfg)
            return 0

        if args.cmd == "daemon":
            return await daemon(session, cfg, args.interval)

        if args.cmd == "keygen":
            api = require_oauth(session, cfg)
            await api.get_private_key(KEY_PATH)
            print("EC private key ready:", KEY_PATH)
            print("Public key:")
            print(api.public_pem.strip())
            return 0

        if args.cmd == "vehicles":
            api = require_oauth(session, cfg)
            data = await api.products()
            products = (data.get("response") or []) if isinstance(data, dict) else []
            vehicles = [p for p in products if p.get("vin")]
            for v in vehicles:
                star = " *" if v.get("vin") == cfg.get("vin") else ""
                print(f"{v.get('vin')}{star}  {v.get('display_name')}  ({v.get('car_type')}, {v.get('state')})")
            if not vehicles:
                print("No vehicles.")
            return 0

        if args.cmd == "select":
            cfg["vin"] = args.vin
            json_dump(CONFIG_PATH, cfg)
            print(f"Default vehicle set to {args.vin}")
            return 0

        if args.cmd == "register":
            if args.domain:
                cfg["domain"] = args.domain
                json_dump(CONFIG_PATH, cfg)
            await register_key(session, cfg, args.domain or cfg.get("domain") or "")
            return 0

        api = require_oauth(session, cfg)
        if args.cmd == "status":
            vin = await resolve_vehicle(api, cfg)
            status = await get_status(api, vin)
            print(json.dumps(status, indent=2))
            return 0

        if args.cmd == "watch":
            vin = await resolve_vehicle(api, cfg)
            interval = max(15, args.interval)
            while True:
                try:
                    status = await get_status(api, vin)
                    print(f"[{status['ts']}] battery={status['vehicle']['battery_level']}% "
                          f"{status['vehicle']['charging_state']} locked={status['vehicle']['locked']}")
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] refresh failed: {e}")
                await asyncio.sleep(interval)

        if args.cmd == "command":
            await api.get_private_key(KEY_PATH)
            vin = await resolve_vehicle(api, cfg)
            return await run_command(api, vin, args.name, args.args, force_fleet=args.fleet)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
    except ValueError as e:
        fail(str(e))
    except TeslaFleetError as e:
        fail(f"Tesla API error: {e}")
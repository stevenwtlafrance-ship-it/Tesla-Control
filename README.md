# Omarchy Tesla Control

An Omarchy bar widget for viewing Tesla battery status and sending vehicle
commands through the Tesla Fleet API.

The repository contains only the widget and backend code. Account credentials,
refresh tokens, VINs, private keys, vehicle names, and location data are
created locally at runtime and must never be committed.

## Before You Start

- Omarchy with Quickshell plugin support
- Python 3.10 or newer
- A Tesla account with at least one vehicle
- A Tesla Fleet API application from [developer.tesla.com](https://developer.tesla.com/)

You do not need to put your VIN, Tesla password, or token in this folder.

## Easy Installation

1. Open a terminal in this plugin folder. For example:

   ```sh
   cd /path/to/omarchy-tesla-control
   ```

   Replace `/path/to/omarchy-tesla-control` with the actual folder location.
2. Run the installer:

   ```sh
   sh install.sh
   ```

   This installs the backend and its Python dependencies automatically.
3. Install the widget using Omarchy's plugin installer, or link this folder
   into the Quickshell plugin directory used by your Omarchy release. The
   folder containing `manifest.json` is the plugin folder.

If `tesla-ctl` is not found afterward, start a new terminal or add
`~/.local/bin` to your `PATH`.

## First-Time Setup

1. Create a Tesla Fleet API app at [developer.tesla.com](https://developer.tesla.com/).
2. In the Tesla app settings, set the redirect URI to:
   `http://localhost:8642/callback`.
3. Save your app details locally:

   ```sh
   tesla-ctl configure
   ```

   Enter the client ID, optional client secret, and region. Use `na` for North
   America, `eu` for Europe, or `cn` for China. Leave VIN blank to select the
   first vehicle automatically.
4. Sign in:

   ```sh
   tesla-ctl login
   ```

   A browser window opens. Sign in to Tesla and approve access.
5. Check that everything works:

   ```sh
   tesla-ctl doctor
   tesla-ctl status
   ```

   The Tesla status should now appear in the Omarchy bar.

Configuration is stored in `~/.config/tesla-ctl/config.json`. The refresh
token is stored in `~/.local/state/tesla-ctl/token.json`; both locations are
created with private permissions.

## Vehicle commands

```sh
tesla-ctl vehicles
tesla-ctl select <VIN>
tesla-ctl commands
tesla-ctl command climate-on
tesla-ctl command charge-limit 80
```

The widget reads its status cache from
`~/.local/state/tesla-ctl/status.json`. Use the middle mouse button on the
widget to refresh it.

## Optional signed commands

Some newer vehicles require Tesla Vehicle Command Protocol (VCP) signing.
The widget first attempts a signed command and falls back to Fleet REST when
available.

Generate and register a key only if signed commands are required:

```sh
tesla-ctl keygen
tesla-ctl register --domain <your-public-domain>
```

Follow the instructions printed by `register`, including hosting the generated
`.well-known` file and enrolling the key in the Tesla app. This step requires
a domain you control and is not needed for read-only status or vehicles that
accept Fleet commands.

## Privacy and security

Do not commit any files from these paths:

- `~/.config/tesla-ctl/config.json`
- `~/.config/tesla-ctl/private_key.pem`
- `~/.config/tesla-ctl/well-known/`
- `~/.local/state/tesla-ctl/`

Refresh tokens can control the vehicle. Treat them like passwords and revoke
the Tesla app authorization if one is exposed. The widget may display the VIN
locally because Tesla requires it for vehicle selection, but the repository
contains no personal vehicle data.

## Troubleshooting

- `client_id not configured`: run `tesla-ctl configure`.
- `Not signed in`: run `tesla-ctl login`.
- No status in the bar: run `tesla-ctl status`, then restart or reload the
  Quickshell widget.
- Signed command errors: run `tesla-ctl doctor` and complete the optional VCP
  registration steps.
- Dependency errors: ensure the launcher uses the virtual environment shown in
  the installation instructions.

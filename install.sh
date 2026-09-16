#!/bin/sh
set -eu

PLUGIN_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="$HOME/.local/share/tesla-ctl"
VENV="$INSTALL_DIR/venv"

printf '%s\n' "Installing Tesla backend..."
mkdir -p "$INSTALL_DIR"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --require-hashes --no-deps -r "$PLUGIN_DIR/backend/requirements.lock"

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/tesla-ctl" <<EOF
#!/bin/sh
exec "$VENV/bin/python" "$PLUGIN_DIR/backend/tesla_ctl.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/tesla-ctl"

printf '\n%s\n' "Backend installed. Run: tesla-ctl doctor"

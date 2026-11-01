#!/usr/bin/env bash
# Install a `vocalfry` launcher on your PATH (~/.local/bin by default).
# VocalFry runs from its own virtualenv (.venv, sharing the system PyQt6)
# because pyworld isn't packaged by the distribution.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${1:-$HOME/.local/bin}"
LAUNCHER="$BIN_DIR/vocalfry"
VENV="$APP_DIR/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/python" -c "import pyworld, numpy" 2>/dev/null || \
  "$VENV/bin/pip" install --quiet numpy pyworld imageio-ffmpeg

mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<EOT
#!/usr/bin/env bash
exec "$VENV/bin/python" "$APP_DIR/vocalfry.py" "\$@"
EOT
chmod +x "$LAUNCHER"
echo "Installed: $LAUNCHER"

if [ -x "$APP_DIR/install-desktop.sh" ]; then
  "$APP_DIR/install-desktop.sh" "$BIN_DIR" || true
fi

python3 -c "import PyQt6.QtWidgets" 2>/dev/null || \
  echo "NOTE: VocalFry needs PyQt6:  sudo apt install python3-pyqt6"

if ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
  echo "NOTE: $BIN_DIR is not on your PATH."
else
  echo "Run it with:  vocalfry"
fi

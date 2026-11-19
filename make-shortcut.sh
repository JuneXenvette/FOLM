#!/bin/sh
# Add FOLM to your app menu. Uses FOLM's own icon (assets/).
#   --desktop      also put an icon on the desktop
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ICON_DIR="$HOME/.local/share/icons/hicolor"; APPS="$HOME/.local/share/applications"
for s in 48 64 128 256 512; do
  mkdir -p "$ICON_DIR/${s}x${s}/apps"
  cp "$HERE/assets/folm-icon-$s.png" "$ICON_DIR/${s}x${s}/apps/folm.png"
done
mkdir -p "$APPS"
cat > "$APPS/folm.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=FOLM
GenericName=Fallout Linux Manager
Comment=Mod manager for Fallout: New Vegas and Fallout 3 on Linux
Exec="$HERE/run-folm.sh"
Path=$HERE
Icon=folm
Terminal=false
Categories=Game;Utility;
DESK
chmod +x "$APPS/folm.desktop"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$ICON_DIR" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
echo "app menu entry: $APPS/folm.desktop"
if [ "$1" = "--desktop" ] && [ -d "$HOME/Desktop" ]; then
  cp "$APPS/folm.desktop" "$HOME/Desktop/folm.desktop"; chmod +x "$HOME/Desktop/folm.desktop"
  command -v gio >/dev/null && gio set "$HOME/Desktop/folm.desktop" metadata::trusted true 2>/dev/null || true
  echo "desktop shortcut: $HOME/Desktop/folm.desktop"
fi

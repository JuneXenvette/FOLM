#!/bin/sh
# Add FOLM to your app menu. Uses FOLM's own icon (assets/).
#   --desktop      also put an icon on the desktop
#   --nexus        make FOLM open Nexus "Mod Manager Download" links (remembers the previous handler)
#   --nexus-undo   give those links back to the previous handler
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
cat > "$APPS/folm-nxm.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=FOLM (Nexus downloads)
Comment=Install Nexus Mods "Mod Manager Download" links with FOLM
Exec="$HERE/run-folm.sh" --nxm %u
Path=$HERE
Icon=folm
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/nxm;
DESK
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$ICON_DIR" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
echo "app menu entry: $APPS/folm.desktop"
if [ "$1" = "--desktop" ] && [ -d "$HOME/Desktop" ]; then
  cp "$APPS/folm.desktop" "$HOME/Desktop/folm.desktop"; chmod +x "$HOME/Desktop/folm.desktop"
  command -v gio >/dev/null && gio set "$HOME/Desktop/folm.desktop" metadata::trusted true 2>/dev/null || true
  echo "desktop shortcut: $HOME/Desktop/folm.desktop"
fi
PREV="${FOLM_HOME:-$HOME/Games/FOLM}/nxm-previous-handler.txt"
if [ "$1" = "--nexus" ] || [ "$2" = "--nexus" ]; then
  cur="$(xdg-mime query default x-scheme-handler/nxm 2>/dev/null || true)"
  if [ "$cur" != "folm-nxm.desktop" ]; then mkdir -p "$(dirname "$PREV")"; echo "$cur" > "$PREV"; fi
  xdg-mime default folm-nxm.desktop x-scheme-handler/nxm
  echo "Nexus 'Mod Manager Download' links now open in FOLM (was: ${cur:-nothing})."
fi
if [ "$1" = "--nexus-undo" ]; then
  old="$(cat "$PREV" 2>/dev/null || true)"
  if [ -n "$old" ]; then xdg-mime default "$old" x-scheme-handler/nxm; echo "Nexus links open in $old again.";
  else echo "No previous handler recorded."; fi
fi

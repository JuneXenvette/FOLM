#!/usr/bin/env bash
# backup.sh - back up The FOLM Project and your FOLM setup into ~/FOLM-Backups/<date-time>/
#
#   project.bundle     the whole git history (restore: git clone project.bundle nv-linux-kit)
#   project.tar.zst    the project folder as it is now, including uncommitted work (no .venv)
#   folm-data.tar.zst  ~/Games/FOLM: profiles, staged mods, game-file backups, LOOT data, the TTW
#                      installer. Left out: the built TTW folder (18 GB; the installer rebuilds it)
#                      and scratch folders.
#   ttw-files.txt      size + name of every file in the TTW folder, to check a rebuild against
#   saves-ini.tar.zst  your game saves and INI files from the Proton prefix (both editions)
#
# Usage: ./backup.sh [destination folder]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FOLM="${FOLM_HOME:-$HOME/Games/FOLM}"
DEST="${1:-$HOME/FOLM-Backups}/$(date +%Y-%m-%d_%H%M)"
COMPAT="$HOME/.local/share/Steam/steamapps/compatdata"
mkdir -p "$DEST"
z() { zstd -q -T0 -3; }

echo "Backing up to $DEST"
echo "1/4 project..."
git -C "$HERE" bundle create "$DEST/project.bundle" --all 2>/dev/null
tar -C "$(dirname "$HERE")" --exclude=.venv --exclude=__pycache__ -cf - "$(basename "$HERE")" | z > "$DEST/project.tar.zst"

echo "2/4 FOLM data (a few minutes)..."
tar -C "$(dirname "$FOLM")" \
    --exclude="$(basename "$FOLM")/*/mods/Tale of Two Wastelands" \
    --exclude="$(basename "$FOLM")/work/pn-root" --exclude="$(basename "$FOLM")/work/legacy-test" \
    --exclude="$(basename "$FOLM")/work/*.png" --exclude="$(basename "$FOLM")/prefixes" \
    -cf - "$(basename "$FOLM")" | z > "$DEST/folm-data.tar.zst"

echo "3/4 TTW file list..."
for ttw in "$FOLM"/*/mods/"Tale of Two Wastelands"; do
    [ -d "$ttw" ] && (cd "$ttw" && find . -type f -printf '%s\t%p\n' | sort -k2) > "$DEST/ttw-files.txt"
done

echo "4/4 saves and INIs..."
dirs=()
for id in 22380 22370; do
    d="$COMPAT/$id/pfx/drive_c/users/steamuser/Documents/My Games"
    [ -d "$d" ] && dirs+=("$d")
done
[ ${#dirs[@]} -gt 0 ] && tar -cf - "${dirs[@]}" 2>/dev/null | z > "$DEST/saves-ini.tar.zst"

(cd "$DEST" && sha256sum ./* > SHA256SUMS)
echo "Done: $(du -sh "$DEST" | cut -f1) in $DEST"

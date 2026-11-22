#!/bin/bash
# Build FOLM-<version>-x86_64.AppImage: FOLM with its own Python, Qt (PySide6) and 7-Zip inside,
# so players only need the one file (plus Steam). The same script runs on GitHub's release
# builder (.github/workflows/release.yml) and on your own PC.
#
#   packaging/build-appimage.sh [VERSION]        VERSION defaults to VERSION in folm_core/version.py
#
# Every download is pinned to one exact version and checked against its SHA-256, so a build
# always contains the same pieces. To update one, change its line below (file, URL and checksum).
set -Eeuo pipefail
# On GitHub, show the failing line as a public note on the run (logs need a sign-in to read)
[ -n "${GITHUB_ACTIONS:-}" ] && trap 'echo "::error file=packaging/build-appimage.sh,line=$LINENO::failed: $BASH_COMMAND"' ERR

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/folm_core/version.py")}"
BUILD="${BUILD_DIR:-$ROOT/build}"
CACHE="$BUILD/cache"
APPDIR="$BUILD/FOLM.AppDir"
OUT="${OUT_DIR:-$ROOT/dist}"
[ -n "$VERSION" ] || { echo "no version given and none found in folm_core/version.py" >&2; exit 1; }

# file | url | sha256
PINS="
cpython-3.12.16+20261026-x86_64-unknown-linux-gnu-install_only.tar.gz|https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only.tar.gz|6a79e922e50006b601f29e688407659da1c2b86ebcd4e9c7254cf234be8b89de
7z2605-linux-x64.tar.xz|https://github.com/ip7z/7zip/releases/download/26.05/7z2605-linux-x64.tar.xz|22cf82fcc6eb7474f1d5bb4f02c0f8ebd573a718089d6833dc30f8350a3b232e
appimagetool-1.9.1-x86_64.AppImage|https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage|ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
runtime-20251108-x86_64|https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64|2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
"
# Qt's X11 window plugin needs these, and fresh installs of some distros don't have them.
XCB_LIBS="libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-image.so.0 libxcb-keysyms.so.1
          libxcb-render-util.so.0 libxcb-util.so.1 libxkbcommon-x11.so.0"

say() { printf '\n== %s\n' "$*"; }

fetch() {          # fetch FILE -> path in the cache, downloaded once and always checksum-checked
  local line file url sum
  line="$(printf '%s\n' "$PINS" | grep "^$1|")"
  IFS='|' read -r file url sum <<<"$line"
  if [ ! -f "$CACHE/$file" ]; then
    curl -fL --retry 3 --silent --show-error -o "$CACHE/$file.part" "$url"
    mv "$CACHE/$file.part" "$CACHE/$file"
  fi
  if ! echo "$sum  $CACHE/$file" | sha256sum -c --quiet - >/dev/null 2>&1; then
    rm -f "$CACHE/$file"
    echo "checksum mismatch for $file: not using it" >&2; exit 1
  fi
  echo "$CACHE/$file"
}

mkdir -p "$CACHE" "$OUT"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/folm" "$APPDIR/usr/share/doc"

say "Python"
tar -xzf "$(fetch cpython-3.12.16+20261026-x86_64-unknown-linux-gnu-install_only.tar.gz)" -C "$APPDIR/usr"
PY="$APPDIR/usr/python/bin/python3"
"$PY" -s -E -m pip install --quiet --no-cache-dir --disable-pip-version-check --only-binary :all: \
      -r "$ROOT/requirements.txt"
SP="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"

say "Trimming what FOLM never uses"
P="$APPDIR/usr/python"
rm -rf "$P"/share "$P"/include "$P"/bin/idle* "$P"/bin/pydoc* "$P"/bin/2to3* "$P"/bin/pip* \
       "$P"/lib/tcl* "$P"/lib/tk* "$P"/lib/itcl* "$P"/lib/thread* "$P"/lib/libtcl* "$P"/lib/libtk* \
       "$P"/lib/python3.12/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3} \
       "$P"/lib/python3.12/lib-dynload/_tkinter* "$P"/lib/python3.12/lib-dynload/_test* \
       "$SP"/pip "$SP"/pip-*
Q="$SP/PySide6"
rm -rf "$Q"/Qt/qml "$Q"/Qt/libexec "$Q"/Qt/metatypes "$Q"/Qt/plugins/{designer,qmltooling,sqldrivers,qmlls} \
       "$Q"/Qt/plugins/wayland-graphics-integration-server "$Q"/Qt/lib/libQt6WaylandEglCompositor* \
       "$Q"/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so "$Q"/Qt/plugins/imageformats/libqpdf.so \
       "$Q"/Qt/plugins/egldeviceintegrations "$Q"/Qt/lib/libQt6EglFs* "$Q"/libpyside6qml* \
       "$Q"/include "$Q"/typesystems "$Q"/glue "$Q"/scripts
for m in Quick Qml Designer UiTools Help Test Sql QuickControls2 QuickWidgets QuickTest QmlModels \
         QmlWorkerScript QmlCompiler QmlMeta QuickShapes QuickParticles QuickEffects QuickLayouts \
         QuickTemplates2 QuickDialogs2 Labs ShaderTools WaylandCompositor; do
  rm -f "$Q"/Qt$m*.abi3.so "$Q"/Qt$m*.pyi "$Q"/Qt/lib/libQt6$m*.so*
done
find "$Q" -maxdepth 1 -type f -perm -u+x ! -name '*.so*' -delete        # designer, linguist, ...
find "$Q"/Qt/translations -type f ! -name 'qtbase_*' -delete 2>/dev/null || true
find "$Q"/Qt/plugins -type d -empty -delete

say "Qt's X11 helper libraries"
for lib in $XCB_LIBS; do
  src="$(/sbin/ldconfig -p | awk -v l="$lib" '$1 == l && /x86-64/ {print $NF; exit}')"
  [ -n "$src" ] || { echo "$lib is not installed on this PC (needed to build)" >&2; exit 1; }
  cp -L "$src" "$Q/Qt/lib/$lib"
done

say "7-Zip"
mkdir -p "$BUILD/7z" "$APPDIR/usr/share/doc/7-Zip"
tar -xJf "$(fetch 7z2605-linux-x64.tar.xz)" -C "$BUILD/7z" 7zzs License.txt readme.txt
install -m 755 "$BUILD/7z/7zzs" "$APPDIR/usr/bin/7zz"
cp "$BUILD/7z/License.txt" "$BUILD/7z/readme.txt" "$APPDIR/usr/share/doc/7-Zip/"

say "FOLM $VERSION"
cp -r "$ROOT"/folm.py "$ROOT"/folm_gui.py "$ROOT"/folm_core "$ROOT"/games "$ROOT"/lists "$ROOT"/assets \
      "$ROOT"/LICENSE "$ROOT"/README.md "$APPDIR/usr/share/folm/"
find "$APPDIR/usr/share/folm" -name __pycache__ -prune -exec rm -rf {} +
# The memory gauge's helper: a tiny Windows program that runs in the game's own Wine (memwatch/memwatch.c)
command -v i686-w64-mingw32-gcc >/dev/null || { echo "i686-w64-mingw32-gcc is needed to build (MinGW)" >&2; exit 1; }
mkdir -p "$APPDIR/usr/share/folm/memwatch"
cp "$ROOT/memwatch/memwatch.c" "$APPDIR/usr/share/folm/memwatch/"
i686-w64-mingw32-gcc -O2 -s -o "$APPDIR/usr/share/folm/memwatch/folm-memwatch.exe" "$ROOT/memwatch/memwatch.c"
"$PY" -s -E -m compileall -q -j0 --invalidation-mode unchecked-hash "$APPDIR/usr/share/folm" "$SP" >/dev/null
mkdir -p "$APPDIR/usr/share/doc/FOLM"
cp "$ROOT/packaging/THIRD-PARTY.txt" "$APPDIR/usr/share/doc/FOLM/"
cp "$P"/lib/python3.12/LICENSE.txt "$APPDIR/usr/share/doc/FOLM/Python-LICENSE.txt"

install -m 755 "$ROOT/packaging/AppRun" "$APPDIR/AppRun"
sed "s/@VERSION@/$VERSION/" "$ROOT/packaging/folm.desktop" > "$APPDIR/folm.desktop"
cp "$ROOT/assets/folm-icon-256.png" "$APPDIR/folm.png"
ln -s folm.png "$APPDIR/.DirIcon"

say "Checking every library is there"
missing="$(find "$APPDIR/usr" -name '*.so*' -type f -print0 | xargs -0 ldd 2>/dev/null | awk '/not found/ {print $1}' | sort -u)"
# Qt and PySide must come from the AppImage itself: a PC with its own Qt 6 would otherwise
# hide a part the AppImage is missing.
missing="$missing$(find "$APPDIR/usr" -name '*.so*' -type f -print0 | xargs -0 ldd 2>/dev/null |
          awk -v d="$APPDIR/" '$1 ~ /^lib(Qt6|pyside6|shiboken6)/ && $3 != "" && index($3, d) != 1 {print $1}' | sort -u)"
missing="$(echo "$missing" | sed '/^$/d' | sort -u)"
if [ -n "$missing" ]; then
  echo "libraries that are neither in the AppImage nor on this PC:" >&2; echo "$missing" >&2
  for l in $missing; do
    users="$(find "$APPDIR/usr" -name '*.so*' -type f -print0 | xargs -0 ldd 2>/dev/null |
             awk -v l="$l" '/^\// {f=$1; sub(/:$/, "", f)} $1 == l && /not found/ {print f}' | sed "s|$APPDIR/||" | head -3 | tr '\n' ' ')"
    [ -n "${GITHUB_ACTIONS:-}" ] && echo "::error::missing library $l (needed by $users)"
  done
  exit 1
fi
QT_QPA_PLATFORM=offscreen "$APPDIR/AppRun" --self-test

say "Packing"
TOOL="$(fetch appimagetool-1.9.1-x86_64.AppImage)"; chmod +x "$TOOL"
NAME="FOLM-$VERSION-x86_64.AppImage"
rm -f "$OUT/$NAME" "$OUT/$NAME.sha256"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream \
     --runtime-file "$(fetch runtime-20251108-x86_64)" "$APPDIR" "$OUT/$NAME" >"$BUILD/appimagetool.log" 2>&1 \
  || { cat "$BUILD/appimagetool.log" >&2; exit 1; }
(cd "$OUT" && sha256sum "$NAME" > "$NAME.sha256")
say "Done: $OUT/$NAME ($(du -h "$OUT/$NAME" | cut -f1))"

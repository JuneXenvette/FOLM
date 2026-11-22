#!/bin/sh
# Builds Second Wind NVHR on Linux (MinGW) and packs it as a mod for FOLM (or any manager).
#   secondwind/build/build.sh            -> secondwind/dist/Second Wind NVHR vN.zip
#   secondwind/build/build.sh test [s]   -> also runs the allocator stress test in Wine for s seconds
# Needs: i686-w64-mingw32-gcc, zip; wine for the test.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/../nvhr-src/heap_replacer"
OUT="$HERE/../dist"
NAME="Second Wind NVHR v4"
STAGE="$OUT/stage/$NAME"
DATA="$STAGE/Data"
CFLAGS="-O2 -fno-strict-aliasing -msse2 -include $HERE/compat_mingw.h -DFNV -DWIN32_LEAN_AND_MEAN -DHR_NAME=\"NVHR\" \
 -DHR_NAME_LOWER=\"nvhr\" -DUNICODE -D_UNICODE -D_CRT_SECURE_NO_WARNINGS -I$SRC -I$SRC/main -static-libgcc"

# NVHR's source isn't kept in FOLM's repository: fetch NVHR 4.3 (commit 4e1ec8b) and apply Second Wind's changes
if [ ! -d "$HERE/../nvhr-src" ]; then
    git clone -q https://github.com/iranrmrf/Heap-Replacer.git "$HERE/../nvhr-src"
    git -C "$HERE/../nvhr-src" checkout -q 4e1ec8b
    git -C "$HERE/../nvhr-src" apply "$HERE/../second-wind-changes.diff"
    git -C "$HERE/../nvhr-src" add -N heap_replacer
fi
rm -rf "$OUT/stage"
mkdir -p "$DATA/NVHR"
# shellcheck disable=SC2086
i686-w64-mingw32-gcc $CFLAGS -shared -s -o "$OUT/stage/nvhr.dll" "$SRC/main/main.c" 2>&1 \
    | grep -v "_InterlockedExchangePointer\|In function\|^ *|\|^ *[0-9]* |\|note:" || true
# NVHR's loader (d3dx9_38.dll, from NVHR 4.3) picks one of these by CPU; they're all the same build here
for cpu in ia32 sse sse2 avx avx2 avx512; do
    cp "$OUT/stage/nvhr.dll" "$DATA/NVHR/nvhr_$cpu.dll"
done
cp "$HERE/../nvhr-src/LICENSE.md" "$DATA/NVHR/LICENSE-NVHR-GPL-2.0.md"
cp "$HERE/README-measuring.txt" "$STAGE/README - $NAME.txt"
# v4's one setting (Windows line ends: it's read by GetPrivateProfileInt)
printf '%s\r\n' "; Second Wind NVHR settings" \
    "; GiveBackHeap=1 hands empty 16 MB blocks of NVHR's big-object heap back to Windows (tested, but new)." \
    "; 0 keeps every block, as NVHR 4.3 does. Read when the game starts." \
    "[Second Wind]" "GiveBackHeap=0" > "$DATA/NVHR/secondwind.ini"
(cd "$HERE/../nvhr-src" && git diff 4e1ec8b -- heap_replacer > "$DATA/NVHR/second-wind-changes.diff" 2>/dev/null \
    || cp "$HERE/../second-wind-changes.diff" "$DATA/NVHR/")
rm -f "$OUT/$NAME.zip"
(cd "$OUT/stage" && zip -qr "../$NAME.zip" "$NAME")
echo "built: $OUT/$NAME.zip"

if [ "$1" = "test" ]; then
    T="$OUT/test"
    mkdir -p "$T"
    # shellcheck disable=SC2086
    i686-w64-mingw32-gcc $CFLAGS -Wl,--large-address-aware -o "$T/stress_test.exe" "$HERE/stress_test.c"
    (cd "$T" && WINEPREFIX="$T/wineprefix" WINEDEBUG=-all WINEDLLOVERRIDES="winedbg.exe=d" \
        wine ./stress_test.exe "${2:-60}" | grep -v "<dheap_create_new_block>\|<mheap_init_pools>\|block .* at 0x\|new sheap" )
fi

"""wineprefix - per-game Wine DLL overrides for mods that ship "proxy" DLLs.

Some mods work by putting a DLL that Windows normally provides next to the game's exe
(NVHR's d3dx9_38.dll, input/sound hooks as dinput8.dll or dsound.dll...). Windows loads the
copy in the game folder. Wine implements those DLLs itself and, by default, loads its own
built-in copy, so under Proton the mod silently does nothing.

FOLM fixes that by setting "native,builtin" for exactly those DLLs in the game's own Proton
prefix (HKCU\\Software\\Wine\\DllOverrides in user.reg), and undoes it on undeploy. Proton
already handles d3d9/dxgi/d3d11 itself (that's DXVK), so those are left alone.

user.reg is only edited while nothing is running in the prefix (Wine rewrites the file on exit).
"""

import os
import re
import subprocess

# DLLs Wine provides that mods commonly replace with their own copy in the game folder.
PROXY_DLLS = re.compile(r"^(d3dx9_\d+|d3dx10_\d+|d3dx11_\d+|dinput8|dinput|dsound|xinput1_[1-4]|xinput9_1_0|"
                        r"winmm|version|winhttp|d3d8|ddraw|msacm32|binkw32)\.dll$", re.I)
SECTION = "[Software\\\\Wine\\\\DllOverrides]"
NATIVE_FIRST = "native,builtin"


def user_reg(prefix):
    return os.path.join(prefix, "pfx", "user.reg")


def prefix_busy(prefix):
    """True if Wine is running in this prefix (then user.reg must not be edited)."""
    pfx = os.path.realpath(os.path.join(prefix, "pfx"))
    r = subprocess.run(["pgrep", "-a", "wineserver"], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        pid = line.split()[0]
        try:
            env = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
        except OSError:
            return True                                      # can't tell: be safe
        for e in env:
            if e.startswith(b"WINEPREFIX=") and os.path.realpath(e[11:].decode(errors="replace")) == pfx:
                return True
    return False


def _read(path):
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        return fh.read().split("\n")


def _write(path, lines):
    tmp = path + ".folm-tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write("\n".join(lines))
    os.replace(tmp, path)


def _section(lines):
    """(start index of the section body, end index) or None."""
    start = None
    for i, l in enumerate(lines):
        if l.startswith("["):
            if start is not None:
                return start, i
            if l.split(" ")[0] == SECTION:
                start = i + 1
    return (start, len(lines)) if start is not None else None


def get(prefix, dll):
    lines = _read(user_reg(prefix))
    b = _section(lines)
    if not b:
        return None
    for l in lines[b[0]:b[1]]:
        m = re.match(r'^"([^"]+)"="([^"]*)"$', l.strip())
        if m and m.group(1).lower() == dll.lower():
            return m.group(2)
    return None


def set_overrides(prefix, values):
    """values {dll name without .dll: "native,builtin" or None (remove)}. Returns {dll: previous value}."""
    path = user_reg(prefix)
    lines = _read(path)
    b = _section(lines)
    if b is None:
        lines += ["", SECTION + " 0", "#time=0"]
        b = (len(lines), len(lines))
    previous = {}
    for dll, value in values.items():
        b = _section(lines)
        idx = None
        for i in range(*b):
            m = re.match(r'^"([^"]+)"="([^"]*)"$', lines[i].strip())
            if m and m.group(1).lower() == dll.lower():
                idx, previous[dll] = i, m.group(2)
                break
        else:
            previous[dll] = None
        if value is None:
            if idx is not None:
                del lines[idx]
        elif idx is not None:
            lines[idx] = f'"{dll}"="{value}"'
        else:
            at = b[0]
            while at < b[1] and lines[at].startswith("#"):          # after the #time= line
                at += 1
            lines.insert(at, f'"{dll}"="{value}"')
    _write(path, lines)
    return previous


def needed(game_dir, manifest):
    """Proxy DLLs that deployed mods put next to the game's exe: [(dll name, mod)]."""
    out = []
    for r in manifest.get("files", []):
        if os.path.dirname(r["target"]) == game_dir and PROXY_DLLS.match(os.path.basename(r["target"])):
            out.append((os.path.basename(r["target"])[:-4].lower(), r["mod"]))
    return out

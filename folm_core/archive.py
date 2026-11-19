"""archive - unpack mod archives (.7z / .zip / .rar / .fomod), with fallbacks.

7-Zip handles almost everything, but Ubuntu's build can't unpack some RAR
compression methods ("Unsupported Method"). For those, FOLM falls back to
`unrar` (or `unar` / `bsdtar` if that's what the player has).
"""

import os
import shutil
import subprocess


class ArchiveError(RuntimeError):
    pass


def is_rar(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"Rar!"
    except OSError:
        return False


def seven_zip():
    """The 7-Zip program to use: the copy inside FOLM's AppImage (FOLM_7Z), else the system's
    (7zz is the official 7-Zip build, 7z is p7zip). None if there is none."""
    bundled = os.environ.get("FOLM_7Z")
    if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    return shutil.which("7zz") or shutil.which("7z")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    msg = (r.stderr + r.stdout)
    ok = r.returncode == 0 and "Unsupported Method" not in msg and "ERROR" not in msg.upper().split("ERRORS:")[0]
    return ok, msg


def extract(archive, dest):
    """Unpack archive into dest (created if needed). Raises ArchiveError with the reason."""
    os.makedirs(dest, exist_ok=True)
    sz = seven_zip()
    if not sz:
        raise ArchiveError("7-Zip is needed to unpack mods (package p7zip-full / 7zip)")
    ok, msg = _run([sz, "x", "-y", f"-o{dest}", archive])
    if ok:
        return "7z"
    tried = ["7-Zip"]
    if is_rar(archive) or archive.lower().endswith(".rar"):
        for tool, cmd in (("unrar", ["unrar", "x", "-o+", "-idq", archive, dest + os.sep]),
                          ("unar", ["unar", "-q", "-f", "-o", dest, archive]),
                          ("bsdtar", ["bsdtar", "-xf", archive, "-C", dest])):
            if shutil.which(tool):
                tried.append(tool)
                ok2, msg2 = _run(cmd)
                if ok2:
                    return tool
                msg = msg2
        if len(tried) == 1:
            raise ArchiveError("this RAR file uses a compression method 7-Zip can't unpack here. "
                               "Install unrar (sudo apt install unrar) and try again.")
    last = [l for l in msg.splitlines() if l.strip()][-3:]
    raise ArchiveError(f"couldn't unpack {os.path.basename(archive)} (tried {', '.join(tried)}): "
                       + " | ".join(last)[:300])

"""bsa - list the files inside Fallout 3 / New Vegas BSA archives (version 104), natively.

Only reads the name tables; never extracts. Used for conflict checks between
loose files and archive contents.
"""

import struct

INCLUDE_DIR_NAMES, INCLUDE_FILE_NAMES = 0x1, 0x2


def list_files(path):
    """Return every file path inside the archive, lowercase, '/'-separated."""
    with open(path, "rb") as f:
        head = f.read(36)
        magic, ver, off, flags, nfolders, nfiles, _dlen, flen, _ff = struct.unpack("<4sIIIIIIII", head)
        if magic != b"BSA\0" or ver not in (103, 104):
            raise ValueError(f"{path}: not a FO3/FNV BSA (version {ver})")
        f.seek(off)
        folders = [struct.unpack("<QII", f.read(16)) for _ in range(nfolders)]
        dirs = []
        for _hash, count, _ofs in folders:
            name = ""
            if flags & INCLUDE_DIR_NAMES:
                n = f.read(1)[0]
                name = f.read(n).rstrip(b"\0").decode("cp1252")
            f.seek(16 * count, 1)                 # skip the file records
            dirs.append((name, count))
        names = []
        if flags & INCLUDE_FILE_NAMES:
            names = f.read(flen).split(b"\0")[:nfiles]
    out, i = [], 0
    for d, count in dirs:
        for _ in range(count):
            fn = names[i].decode("cp1252") if i < len(names) else f"#{i}"
            out.append(f"{d}/{fn}".replace("\\", "/").lower().strip("/"))
            i += 1
    return out

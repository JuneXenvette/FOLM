"""esp - read and write Fallout 3 / New Vegas plugin files (.esm/.esp), natively.

The foundation for the FO3 -> TTW converter. A plugin is a TES4 header record
followed by GRUPs (groups) of records. Both FO3 and FNV use:

  record header (24 bytes): type[4] data_size:u32 flags:u32 form_id:u32 vc1:u32 form_version:u16 vc2:u16
  GRUP header   (24 bytes): "GRUP" group_size:u32 label[4] group_type:i32 stamp:u16 u1:u16 version:u16 u2:u16
  subrecord:                type[4] size:u16 data   (an XXXX subrecord carries a u32 size for the next one)

Compressed records (flag 0x40000) hold u32 uncompressed_size + a zlib stream.
Records keep their original bytes, so an unchanged plugin writes back identically.
"""

import struct
import zlib
from collections import Counter

HDR = struct.Struct("<4sIIIIHH")
GRP = struct.Struct("<4sI4siHHHH")
COMPRESSED = 0x00040000


class Subrecord:
    __slots__ = ("type", "data")

    def __init__(self, typ, data):
        self.type, self.data = typ, data

    def __repr__(self):
        return f"<{self.type.decode()} {len(self.data)}b>"


class Record:
    __slots__ = ("type", "flags", "form_id", "vc1", "form_version", "vc2", "raw", "_subs", "dirty")

    def __init__(self, typ, flags, form_id, vc1, form_version, vc2, raw):
        self.type, self.flags, self.form_id = typ, flags, form_id
        self.vc1, self.form_version, self.vc2 = vc1, form_version, vc2
        self.raw, self._subs, self.dirty = raw, None, False

    @property
    def compressed(self):
        return bool(self.flags & COMPRESSED)

    def payload(self):
        if self.compressed:
            (size,) = struct.unpack_from("<I", self.raw)
            out = zlib.decompress(self.raw[4:])
            if len(out) != size:
                raise ValueError(f"{self.type} {self.form_id:08X}: bad compressed size")
            return out
        return self.raw

    @property
    def subrecords(self):
        if self._subs is None:
            self._subs = parse_subrecords(self.payload())
        return self._subs

    def touch(self):
        """Mark as edited; it will be re-serialised from subrecords on write."""
        self.subrecords
        self.dirty = True

    def to_bytes(self):
        if self.dirty:
            body = build_subrecords(self._subs)
            if self.compressed:
                body = struct.pack("<I", len(body)) + zlib.compress(body)
            self.raw, self.dirty = body, False
        return HDR.pack(self.type, len(self.raw), self.flags, self.form_id,
                        self.vc1, self.form_version, self.vc2) + self.raw

    def __repr__(self):
        return f"<{self.type.decode()} {self.form_id:08X}>"


class Group:
    __slots__ = ("label", "group_type", "stamp", "u1", "version", "u2", "children")

    def __init__(self, label, group_type, stamp, u1, version, u2):
        self.label, self.group_type = label, group_type
        self.stamp, self.u1, self.version, self.u2 = stamp, u1, version, u2
        self.children = []

    def to_bytes(self):
        body = b"".join(c.to_bytes() for c in self.children)
        return GRP.pack(b"GRUP", len(body) + GRP.size, self.label, self.group_type,
                        self.stamp, self.u1, self.version, self.u2) + body

    def records(self):
        for c in self.children:
            if isinstance(c, Group):
                yield from c.records()
            else:
                yield c


def parse_subrecords(data):
    subs, pos, big = [], 0, None
    while pos + 6 <= len(data):
        typ = data[pos:pos + 4]
        (size,) = struct.unpack_from("<H", data, pos + 4)
        if big is not None:
            size, big = big, None
        body = data[pos + 6:pos + 6 + size]
        if typ == b"XXXX":
            (big,) = struct.unpack_from("<I", body)
        subs.append(Subrecord(typ, body))
        pos += 6 + size
    if pos != len(data):
        raise ValueError(f"subrecord data runs {len(data) - pos} bytes past the end")
    return subs


def build_subrecords(subs):
    out = bytearray()
    for i, s in enumerate(subs):
        if s.type == b"XXXX":
            continue                      # re-created below when needed
        if len(s.data) > 0xFFFF:
            out += b"XXXX" + struct.pack("<H", 4) + struct.pack("<I", len(s.data))
            out += s.type + struct.pack("<H", 0) + s.data
        else:
            out += s.type + struct.pack("<H", len(s.data)) + s.data
    return bytes(out)


def _parse(buf, pos, end, out):
    while pos < end:
        if buf[pos:pos + 4] == b"GRUP":
            _, size, label, gtype, stamp, u1, ver, u2 = GRP.unpack_from(buf, pos)
            g = Group(label, gtype, stamp, u1, ver, u2)
            _parse(buf, pos + GRP.size, pos + size, g.children)
            out.append(g)
            pos += size
        else:
            typ, size, flags, fid, vc1, fv, vc2 = HDR.unpack_from(buf, pos)
            start = pos + HDR.size
            out.append(Record(typ, flags, fid, vc1, fv, vc2, bytes(buf[start:start + size])))
            pos = start + size
    if pos != end:
        raise ValueError("group size doesn't match its contents")


class Plugin:
    def __init__(self, header, groups, name=""):
        self.header, self.groups, self.name = header, groups, name

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            buf = f.read()
        if buf[:4] != b"TES4":
            raise ValueError(f"{path}: not a FO3/FNV plugin")
        items = []
        _parse(memoryview(buf), 0, len(buf), items)
        return cls(items[0], items[1:], name=path.rsplit("/", 1)[-1])

    def to_bytes(self):
        return self.header.to_bytes() + b"".join(g.to_bytes() for g in self.groups)

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def records(self):
        for g in self.groups:
            yield from g.records()

    @property
    def masters(self):
        return [s.data.split(b"\0", 1)[0].decode("cp1252") for s in self.header.subrecords if s.type == b"MAST"]

    @property
    def version(self):
        for s in self.header.subrecords:
            if s.type == b"HEDR":
                return round(struct.unpack_from("<f", s.data)[0], 2)
        return None


def analyze(path):
    """What's in a plugin, and what converting it to TTW will involve."""
    p = Plugin.load(path)
    masters = p.masters
    n = len(masters)
    types, new, overrides, compressed = Counter(), Counter(), Counter(), 0
    for r in p.records():
        types[r.type.decode()] += 1
        compressed += r.compressed
        idx = r.form_id >> 24
        if idx >= n:
            new[r.type.decode()] += 1
        else:
            overrides[masters[idx]] += 1
    game = {0.94: "Fallout 3", 1.34: "New Vegas"}.get(p.version, f"unknown (HEDR {p.version})")
    return {
        "plugin": p.name, "format": game, "header_version": p.version, "masters": masters,
        "records": sum(types.values()), "by_type": dict(types.most_common()),
        "new_records": sum(new.values()), "overrides": dict(overrides), "compressed": compressed,
        "fo3_masters": [m for m in masters if m.lower() in
                        {"fallout3.esm", "anchorage.esm", "thepitt.esm", "brokensteel.esm", "pointlookout.esm", "zeta.esm"}],
    }

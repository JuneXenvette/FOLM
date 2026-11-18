"""scriptcode - read, edit and write compiled FO3/FNV scripts (the SCDA bytes GECK produces).

Lets FOLM make small, exact changes to a mod's script on Linux, where GECK doesn't run:
split the compiled code into statements, insert or remove statements, and write it back with
every if/elseif jump and Begin-block length recomputed.

Format (same for Fallout 3 and New Vegas):
  statement:  opcode:u16 length:u16 data[length]
  0x1C        "call on a reference": ref index:u16, then the real statement follows
  0x10 Begin  data = block type:u16, block length:u32 (bytes of the block's statements, incl. End)
  0x11 End    0x15 Set    0x16 If    0x17 Else    0x18 ElseIf    0x19 EndIf    0x1E Return
  If/ElseIf   data = jump:u16 (statements to skip to the next ElseIf/Else/EndIf), expr length:u16, expr
  Else        data = jump:u16
Expressions are postfix tokens separated by spaces: numbers as text ("0", "0.30"),
s/f/r + u16 for local short/float/ref variables, r + u16 for references, X + opcode + params for
function calls, and operators as text ("==", "&&", "||").
"""

import struct

BEGIN, END, SET, IF, ELSE, ELSEIF, ENDIF, REFCALL, RETURN = 0x10, 0x11, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1C, 0x1E


class Statement:
    """One statement. `ref` is set for calls on a reference (player.UnequipItem ...)."""
    __slots__ = ("op", "data", "ref")

    def __init__(self, op, data=b"", ref=None):
        self.op, self.data, self.ref = op, bytes(data), ref

    def to_bytes(self):
        body = struct.pack("<HH", self.op, len(self.data)) + self.data
        return (struct.pack("<HH", REFCALL, self.ref) + body) if self.ref is not None else body

    def __repr__(self):
        return f"<{self.op:04X}{' on ref ' + str(self.ref) if self.ref is not None else ''} {self.data.hex()}>"


def parse(code):
    out, pos = [], 0
    while pos < len(code):
        op, ln = struct.unpack_from("<HH", code, pos)
        if op == REFCALL:
            ref = ln
            op, ln = struct.unpack_from("<HH", code, pos + 4)
            out.append(Statement(op, code[pos + 8:pos + 8 + ln], ref))
            pos += 8 + ln
        else:
            out.append(Statement(op, code[pos + 4:pos + 4 + ln]))
            pos += 4 + ln
    if pos != len(code):
        raise ValueError("compiled script ends mid-statement")
    return out


def _targets(stmts):
    """For each If/ElseIf/Else, the index of the statement its jump lands on (next branch at its level)."""
    targets, stack = {}, []
    for i, s in enumerate(stmts):
        if s.op == IF:
            stack.append(i)
        elif s.op in (ELSEIF, ELSE, ENDIF):
            if not stack:
                raise ValueError(f"statement {i}: {s.op:#x} without If")
            targets[stack.pop()] = i
            if s.op != ENDIF:
                stack.append(i)
    if stack:
        raise ValueError("If without EndIf")
    return targets


def check(stmts):
    """Raise if any stored jump or block length disagrees with the structure."""
    for i, t in _targets(stmts).items():
        (jump,) = struct.unpack_from("<H", stmts[i].data)
        if jump != t - i - 1:
            raise ValueError(f"statement {i}: jump {jump}, structure says {t - i - 1}")
    for i, s in enumerate(stmts):
        if s.op == BEGIN:
            (length,) = struct.unpack_from("<I", s.data, 2)
            if length != _block_bytes(stmts, i):
                raise ValueError(f"Begin at {i}: length {length}, structure says {_block_bytes(stmts, i)}")


def _block_bytes(stmts, begin):
    n = 0
    for s in stmts[begin + 1:]:
        n += len(s.to_bytes())
        if s.op == END:
            return n
    raise ValueError("Begin without End")


def build(stmts):
    """Recompute jumps and block lengths, return the compiled bytes."""
    for i, t in _targets(stmts).items():
        s = stmts[i]
        s.data = struct.pack("<H", t - i - 1) + s.data[2:]
    for i, s in enumerate(stmts):
        if s.op == BEGIN:
            s.data = s.data[:2] + struct.pack("<I", _block_bytes(stmts, i)) + s.data[6:]
    code = b"".join(s.to_bytes() for s in stmts)
    check(parse(code))
    return code


# ---------------------------------------------------------------- small builders (match GECK's output)

def expr(*tokens):
    """Tokens are bytes (pre-encoded) or str (text tokens like "==", "1"); joined GECK-style with spaces."""
    return b"".join(b" " + (t.encode() if isinstance(t, str) else t) for t in tokens)


def local(kind, index):
    return kind.encode() + struct.pack("<H", index)          # kind: "s" short, "f" float, "r" ref


def ref(index):
    return b"r" + struct.pack("<H", index)


def call(opcode, *params, on=None):
    """A function call inside an expression. params: pre-encoded parameter bytes."""
    body = struct.pack("<H", len(params)) + b"".join(params)
    head = (b"r" + struct.pack("<H", on)) if on is not None else b""
    return head + b"X" + struct.pack("<HH", opcode, len(body)) + body


def if_(op, e):
    return Statement(op, struct.pack("<HH", 0, len(e)) + e)


def int_param(n):
    return b"n" + struct.pack("<i", n)

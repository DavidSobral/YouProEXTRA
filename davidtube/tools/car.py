"""Minimal reader and block patcher for Apple asset catalogs (Assets.car).

A .car file is a BOM container (big-endian structures). Tree nodes are
big-endian too, but KEYFORMAT, FACETKEYS tokens and rendition keys are
little-endian.
"""
import struct
from dataclasses import dataclass

MAGIC = b"BOMStore"
HEADER_SIZE = 32


class CarError(Exception):
    pass


@dataclass
class Rendition:
    attrs: dict
    key_block: int
    value_block: int


def _unpack(fmt, data, off=0):
    try:
        return struct.unpack_from(fmt, data, off)
    except struct.error as e:
        raise CarError("truncated data at offset %d" % off) from e


class Car:
    def __init__(self, data):
        self._buf = bytearray(data)
        if len(self._buf) < HEADER_SIZE or bytes(self._buf[:8]) != MAGIC:
            raise CarError("not a BOMStore file")
        (_, _, self._index_off, self._index_len,
         vars_off, _) = _unpack(">IIIIII", self._buf, 8)
        self._nblocks, = _unpack(">I", self._buf, self._index_off)
        if self._index_off + 4 + 8 * self._nblocks > len(self._buf):
            raise CarError("index table out of range")
        self._vars = self._parse_vars(vars_off)

    def _parse_vars(self, off):
        n, = _unpack(">I", self._buf, off)
        p = off + 4
        out = {}
        for _ in range(n):
            idx, ln = _unpack(">IB", self._buf, p)
            name = bytes(self._buf[p + 5:p + 5 + ln])
            if len(name) != ln:
                raise CarError("truncated vars table")
            out[name.decode("latin1")] = idx
            p += 5 + ln
        return out

    def block_count(self):
        return self._nblocks

    def block(self, i):
        if not 0 <= i < self._nblocks:
            raise CarError("block %d out of range" % i)
        addr, length = _unpack(">II", self._buf, self._index_off + 4 + 8 * i)
        if addr + length > len(self._buf):
            raise CarError("block %d out of file range" % i)
        return bytes(self._buf[addr:addr + length])

    def replace_block(self, i, data):
        """Append data to the file and point block i's index entry at it."""
        if not 1 <= i < self._nblocks:
            raise CarError("block %d cannot be replaced" % i)
        addr = len(self._buf)
        self._buf += data
        struct.pack_into(">II", self._buf, self._index_off + 4 + 8 * i, addr, len(data))

    def to_bytes(self):
        return bytes(self._buf)

    def _var(self, name):
        if name not in self._vars:
            raise CarError("missing %s" % name)
        return self._vars[name]

    def _tree(self, var):
        """Return [(value_block, key_block)] by walking leaves via forward links."""
        t = self.block(self._var(var))
        if t[:4] != b"tree":
            raise CarError("%s is not a tree" % var)
        _, root, _, _, _ = _unpack(">IIIIB", t, 4)
        n, seen = root, set()
        while True:  # descend to the first leaf
            if n in seen:
                raise CarError("cycle in %s" % var)
            seen.add(n)
            b = self.block(n)
            leaf, _, _, _ = _unpack(">HHII", b)
            if leaf:
                break
            n = _unpack(">I", b, 12)[0]
        seen.clear()
        out = []
        while n:
            if n in seen:
                raise CarError("cycle in %s" % var)
            seen.add(n)
            b = self.block(n)
            _, count, fw, _ = _unpack(">HHII", b)
            out.extend(_unpack(">II", b, 12 + 8 * k) for k in range(count))
            n = fw
        return out

    def _keyformat(self):
        kf = self.block(self._var("KEYFORMAT"))
        magic, _, count = _unpack("<4sII", kf)
        if magic != b"tmfk":  # u32 "kfmt" stored little-endian
            raise CarError("bad KEYFORMAT")
        return _unpack("<%dI" % count, kf, 12)

    def facets(self):
        out = {}
        for v, k in self._tree("FACETKEYS"):
            name = self.block(k).decode("latin1")
            val = self.block(v)
            _, _, num = _unpack("<HHH", val)
            pairs = [_unpack("<HH", val, 6 + 4 * i) for i in range(num)]
            out[name] = dict(pairs)
        return out

    def renditions(self):
        attrs = self._keyformat()
        out = []
        for v, k in self._tree("RENDITIONS"):
            key = self.block(k)
            vals = _unpack("<%dH" % (len(key) // 2), key)
            out.append(Rendition(dict(zip(attrs, vals)), k, v))
        return out

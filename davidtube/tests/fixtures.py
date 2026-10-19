"""Tiny in-memory BOM/CAR writer used to build synthetic catalogs for tests."""
import struct

DEFAULT_KEYFORMAT = (7, 13, 12, 15, 16, 8, 17, 1, 2)
IDENT = 17
SCALE = 12


def facet_token(attrs, hotspot=(0, 0)):
    """FACETKEYS value: little-endian hotspot x,y, count, then (name, value) pairs."""
    out = struct.pack("<HHH", hotspot[0], hotspot[1], len(attrs))
    for k, v in attrs.items():
        out += struct.pack("<HH", k, v)
    return out


def rendition_key(attrs, keyformat=DEFAULT_KEYFORMAT):
    return struct.pack("<%dH" % len(keyformat), *(attrs.get(k, 0) for k in keyformat))


def keyformat_block(keyformat=DEFAULT_KEYFORMAT):
    return b"tmfk" + struct.pack("<II", 0, len(keyformat)) + struct.pack(
        "<%dI" % len(keyformat), *keyformat)


def csi_blob(tag=b"CTSI", payload=b"", name=b"x"):
    """A CSI-like blob: 'ISTC' header, padded name, then payload (not a real CSI)."""
    return b"ISTC" + struct.pack("<I", 1) + name.ljust(32, b"\0") + payload


class _Bom:
    def __init__(self):
        self.blocks = [b""]  # block 0 is the null block
        self.vars = []

    def add(self, data):
        self.blocks.append(bytes(data))
        return len(self.blocks) - 1

    def add_tree(self, entries, leaf_size=2):
        """entries: [(value_block, key_block)]. Builds linked leaves plus a root
        node when more than one leaf is needed. Returns the tree block index."""
        chunks = [entries[i:i + leaf_size] for i in range(0, len(entries), leaf_size)] or [[]]
        leaves = [self.add(b"") for _ in chunks]  # reserve indices
        for n, (idx, chunk) in enumerate(zip(leaves, chunks)):
            fw = leaves[n + 1] if n + 1 < len(leaves) else 0
            bw = leaves[n - 1] if n else 0
            body = struct.pack(">HHII", 1, len(chunk), fw, bw)
            body += b"".join(struct.pack(">II", v, k) for v, k in chunk)
            self.blocks[idx] = body
        root = leaves[0]
        if len(leaves) > 1:
            body = struct.pack(">HHII", 0, len(leaves), 0, 0)
            body += b"".join(struct.pack(">II", leaf, 0) for leaf in leaves)
            root = self.add(body)
        tree = b"tree" + struct.pack(">IIIIB", 1, root, 4096, len(entries), 0)
        return self.add(tree)

    def to_bytes(self):
        pos = 32
        addrs = []
        body = b""
        for b in self.blocks:
            addrs.append((pos + len(body), len(b)))
            body += b
        addrs[0] = (0, 0)
        index = struct.pack(">I", len(self.blocks)) + b"".join(
            struct.pack(">II", a, l) for a, l in addrs)
        vars_ = struct.pack(">I", len(self.vars)) + b"".join(
            struct.pack(">IB", i, len(n)) + n for n, i in self.vars)
        io = 32 + len(body)
        vo = io + len(index)
        hdr = b"BOMStore" + struct.pack(">IIIIII", 1, len(self.blocks), io, len(index),
                                        vo, len(vars_))
        return hdr + body + index + vars_


def build_catalog(facets, renditions, keyformat=DEFAULT_KEYFORMAT, leaf_size=2):
    """facets: [(name, attrs_dict)], renditions: [(attrs_dict, value_bytes)].
    Returns the bytes of a synthetic BOM catalog."""
    bom = _Bom()
    kf = bom.add(keyformat_block(keyformat))
    fentries = [(bom.add(facet_token(a)), bom.add(n.encode())) for n, a in facets]
    rentries = [(bom.add(v), bom.add(rendition_key(a, keyformat))) for a, v in renditions]
    ft = bom.add_tree(fentries, leaf_size)
    rt = bom.add_tree(rentries, leaf_size)
    bom.vars = [(b"KEYFORMAT", kf), (b"FACETKEYS", ft), (b"RENDITIONS", rt)]
    return bom.to_bytes()


def sample_catalog():
    """3 facets, 5 renditions (3 leaves joined by forward links). Returns
    (bytes, facets, renditions)."""
    facets = [("alpha", {IDENT: 100, 1: 1}), ("beta", {IDENT: 200, 1: 1}),
              ("gamma", {IDENT: 300, 1: 1})]
    renditions = [({IDENT: 100, SCALE: 1}, csi_blob(payload=b"a1")),
                  ({IDENT: 100, SCALE: 2}, csi_blob(payload=b"a2")),
                  ({IDENT: 200, SCALE: 2}, csi_blob(payload=b"b2")),
                  ({IDENT: 300, SCALE: 1}, csi_blob(payload=b"c1")),
                  ({IDENT: 300, SCALE: 3}, csi_blob(payload=b"c3"))]
    return build_catalog(facets, renditions), facets, renditions

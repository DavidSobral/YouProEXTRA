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


# --- CSI helpers (modelled on the real renditions of the target catalog) ---

SLICES, METRICS, COMPOSITION, BITMAP_INFO, BYTES_PER_ROW, LINK = 1001, 1003, 1004, 1006, 1007, 1010


def tlv(tag, data):
    return struct.pack("<II", tag, len(data)) + data


def make_csi(width=20, height=10, scale100=200, name=b"tmpl@2x.png", pixel_format=b"BGRA",
             layout=12, flags=0x10, entries=None, payload=None):
    """A CSI modelled on the real standalone renditions of the target catalog."""
    if entries is None:
        entries = [tlv(SLICES, struct.pack("<5I", 1, 0, 0, width, height)),
                   tlv(METRICS, struct.pack("<7I", 1, 0, 0, 0, 0, width, height)),
                   tlv(COMPOSITION, struct.pack("<If", 0, 1.0)),
                   tlv(BITMAP_INFO, struct.pack("<I", 1)),
                   tlv(BYTES_PER_ROW, struct.pack("<I", (width * 4 + 31) // 32 * 32))]
    if payload is None:  # DeepMap2-style CELM (compression 11), opaque data
        data = b"\x01\x00\x00\x00\x04\x00\x00\x00" + b"\xAB" * 40
        payload = b"MLEC" + struct.pack("<III", 0, 11, len(data)) + data
    infos = b"".join(entries)
    head = b"ISTC" + struct.pack("<IIIII", 1, flags, width, height, scale100)
    head += pixel_format + struct.pack("<IIHH", 1, 0, layout, 0)
    head += name.ljust(128, b"\0")
    head += struct.pack("<IIII", len(infos), 1, 0, len(payload))
    assert len(head) == 184
    return head + infos + payload


def make_link_csi(width=244, height=96, scale100=200, name=b"youtube_logo@2x.png"):
    link = b"KLNI" + struct.pack("<IIIIIII", 0, 2, 100, width, height, 0, 0)
    entries = [tlv(SLICES, struct.pack("<5I", 1, 0, 0, width, height)),
               tlv(METRICS, struct.pack("<7I", 1, 0, 0, 0, 0, width, height)),
               tlv(LINK, link), tlv(COMPOSITION, struct.pack("<If", 0, 1.0)),
               tlv(BITMAP_INFO, struct.pack("<I", 1))]
    return make_csi(width, height, scale100, layout=1003, name=name,
                    entries=entries, payload=b"")


# --- Synthetic catalog shaped like Innertube_Resources.bundle/Assets.car ---

LOGO_FACETS = ("youtube_logo", "youtube_logo_dark", "youtube_logo_cairo",
               "youtube_logo_dark_cairo", "youtube_premium_logo", "youtube_premium_logo_white",
               "youtube_premium_logo_cairo", "youtube_premium_logo_dark_cairo")
# The real catalog names the two plain premium renditions "yt_premium_logo...".
_STEMS = {"youtube_premium_logo": "yt_premium_logo",
          "youtube_premium_logo_white": "yt_premium_logo_white"}
# Like the real catalog, the premium @3x renditions are already standalone.
STANDALONE = {(n, 3) for n in LOGO_FACETS if n.startswith("youtube_premium")}


def logo_rendition_name(facet, scale):
    return "%s%s.png" % (_STEMS.get(facet, facet), "" if scale == 1 else "@%dx" % scale)


def logo_size(facet, scale):
    """Small stand-ins for 122x48 / 129x48 per point scale."""
    return ((11 if "premium" in facet else 10) * scale, 4 * scale)


def link_catalog_parts():
    """(facets, renditions) lists for build_catalog: the 8 logo facets x 3 scales
    (links, except STANDALONE), a template image, an atlas, a non-target link and a
    gray image. Tests may edit the lists before building."""
    facets, rends = [], []
    for i, name in enumerate(LOGO_FACETS):
        ident = 1000 + i
        facets.append((name, {1: 85, 2: 181, IDENT: ident}))
        for s in (1, 2, 3):
            w, h = logo_size(name, s)
            nm = logo_rendition_name(name, s).encode()
            if (name, s) in STANDALONE:
                blob = make_csi(w, h, 100 * s, name=nm)
            else:
                blob = make_link_csi(w, h, 100 * s, name=nm)
            rends.append(({1: 85, 2: 181, IDENT: ident, SCALE: s}, blob))
    facets += [("ic_checkbox", {IDENT: 7}), ("ZZZZPackedAsset-2.0.0-gamut0", {IDENT: 8}),
               ("other_logo", {IDENT: 9}), ("gray_icon", {IDENT: 10})]
    rends += [({IDENT: 7, SCALE: 3}, make_csi(6, 6, 300, name=b"ic_checkbox@3x.png")),
              ({IDENT: 8, SCALE: 2}, make_csi(40, 40, 200, layout=1004,
                                              name=b"ZZZZPackedAsset-2.0.0-gamut0")),
              ({IDENT: 9, SCALE: 2}, make_link_csi(8, 4, 200, name=b"other_logo@2x.png")),
              ({IDENT: 10, SCALE: 2}, make_csi(4, 4, 200, pixel_format=b" 8AG",
                                               name=b"gray_icon@2x.png"))]
    return facets, rends


def link_catalog():
    return build_catalog(*link_catalog_parts(), leaf_size=3)


# --- Synthetic IPA ---

CAR_PATH = "Payload/YouTube.app/Innertube_Resources.bundle/Assets.car"


def write_ipa(path, car=None, app="YouTube.app", car_compress=None):
    """Write a small IPA with stored and deflated members; `car` (bytes) becomes
    <app>/Innertube_Resources.bundle/Assets.car unless None. Returns member names."""
    import zipfile
    if car_compress is None:
        car_compress = zipfile.ZIP_DEFLATED
    base = "Payload/%s/" % app
    members = [("Payload/", b"", zipfile.ZIP_STORED, 0o40755),
               (base + "Info.plist", b"<plist>" * 50, zipfile.ZIP_DEFLATED, 0o100644),
               (base + "YouTube", bytes(range(256)) * 20, zipfile.ZIP_STORED, 0o100755)]
    if car is not None:
        members.append((base + "Innertube_Resources.bundle/Assets.car", car, car_compress,
                        0o100755))
    members += [(base + "Innertube_Resources.bundle/Info.plist", b"bundle" * 30,
                 zipfile.ZIP_DEFLATED, 0o100644),
                (base + "Assets.car", b"BOMStore-other", zipfile.ZIP_STORED, 0o100644),
                (base + "_CodeSignature/CodeResources", b"<sig/>" * 40, zipfile.ZIP_DEFLATED,
                 0o100644)]
    with zipfile.ZipFile(path, "w") as z:
        for n, (name, data, ct, mode) in enumerate(members):
            zi = zipfile.ZipInfo(name, (2026, 10, 1 + n, 12, 30, 2 * n))
            zi.compress_type = ct
            zi.external_attr = mode << 16
            zi.create_system = 3
            z.writestr(zi, data)
    return [m[0] for m in members]

#!/usr/bin/env python3
"""PC5 UEFI boot image (ESP) builder.

The UEFI El Torito entry in a PC5 ISO points at a *floppy-format FAT
filesystem* that contains the boot application:

    El Torito "no emulation" UEFI entry  ->  this image (FAT12/FAT16)
                                         ->  \\EFI\\BOOT\\BOOTX64.EFI

This is the same mechanism Debian and other distributions use for their
`efi.img`; firmware mounts the El Torito image as if it were a small hard
disk and reads the removable-media default path from it.

The tool is written from the Microsoft FAT specification and needs no
external dependencies, so the release build stays reproducible on a machine
with only python3, binutils, gcc and make.  Image contents and timestamps
honour SOURCE_DATE_EPOCH exactly like tools/mkiso.py, so two builds of the
same commit are byte-identical.

Usage:

    python3 tools/mkefiimg.py --size-kb 1440 \
        --file build/bootx64.efi=EFI/BOOT/BOOTX64.EFI \
        --output build/efi.img --info build/efi-info.json

`--list` parses an image back and prints the directory tree; the host tests
use it to prove that what was written can be read by an independent walk of
the FAT chains.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import struct
import sys

SECTOR = 512
MEDIA_DESCRIPTOR = 0xF0          # 3.5" 1.44 MB, as FAT floppies use
ATTR_READ_ONLY = 0x01
ATTR_HIDDEN = 0x02
ATTR_SYSTEM = 0x04
ATTR_VOLUME_ID = 0x08
ATTR_DIRECTORY = 0x10
ATTR_ARCHIVE = 0x20
ATTR_LFN = 0x0F
FAT12 = 12
FAT16 = 16
MAX_ROOT_ENTRIES = 224           # what floppy media use; 14 sectors
FAT_EOC12 = 0xFFF
FAT_EOC16 = 0xFFFF


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def build_time() -> datetime.datetime:
    """Timestamp written into directory entries (honours SOURCE_DATE_EPOCH)."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc)


def fat_datetime(now: datetime.datetime) -> tuple[int, int]:
    """FAT (time, date) pair for a UTC timestamp."""
    date = ((now.year - 1980) << 9) | (now.month << 5) | now.day
    time = (now.hour << 11) | (now.minute << 5) | (now.second // 2)
    return time, date


def short_name(name: str) -> tuple[bytes, bytes]:
    """Split an 8.3 name into (base, extension); reject anything longer."""
    upper = name.upper()
    if upper in (".", ".."):
        # dot entries: the dot(s) left-justified in the 8-byte base area
        return upper.ljust(8).encode("ascii"), b"   "
    if upper == "":
        raise SystemExit("invalid FAT file name ''")
    if "." in upper:
        base, ext = upper.rsplit(".", 1)
    else:
        base, ext = upper, ""
    if len(base) < 1 or len(base) > 8 or len(ext) > 3:
        raise SystemExit(
            f"{name!r} is not a valid 8.3 FAT name (base 1-8, extension 0-3)"
        )
    for char in base + ext:
        if char in ' "+,/:;<=>[\\]|*?':
            raise SystemExit(f"{name!r} contains a character FAT forbids")
    return base.ljust(8).encode("ascii"), ext.ljust(3).encode("ascii")


def dir_entry(name83: tuple[bytes, bytes], attr: int, cluster: int, size: int,
              now: datetime.datetime) -> bytes:
    base, ext = name83
    when_time, when_date = fat_datetime(now)
    out = bytearray(32)
    out[0:8] = base
    out[8:11] = ext
    out[11] = attr
    out[12] = 0                       # NT reserved
    out[13] = 0                       # creation tenths
    struct.pack_into("<H", out, 14, when_time)
    struct.pack_into("<H", out, 16, when_date)
    struct.pack_into("<H", out, 18, when_date)   # last access date
    struct.pack_into("<H", out, 22, when_time)
    struct.pack_into("<H", out, 24, when_date)
    struct.pack_into("<H", out, 20, cluster >> 16)
    struct.pack_into("<H", out, 26, cluster & 0xFFFF)
    struct.pack_into("<I", out, 28, size)
    return bytes(out)


def volume_label_entry(label: str, now: datetime.datetime) -> bytes:
    base = label.upper().ljust(11)[:11].encode("ascii")
    out = bytearray(32)
    out[0:11] = base
    out[11] = ATTR_VOLUME_ID
    when_time, when_date = fat_datetime(now)
    struct.pack_into("<H", out, 22, when_time)
    struct.pack_into("<H", out, 24, when_date)
    return bytes(out)


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def geometry(total_sectors: int, sectors_per_cluster: int, reserved: int = 1,
             nfats: int = 2, root_entries: int = MAX_ROOT_ENTRIES) -> dict:
    """Work out a self-consistent BPB for a given image size.

    The FAT type is not a free choice: the specification fixes it from the
    cluster count (< 4085 clusters is FAT12, < 65525 is FAT16).  The FAT size
    itself depends on the cluster count, so the two are solved together.
    """
    if sectors_per_cluster not in (1, 2, 4, 8, 16, 32, 64, 128):
        raise SystemExit("sectors per cluster must be a power of two, 1..128")
    root_dir_sectors = (root_entries * 32 + SECTOR - 1) // SECTOR
    fat_sectors = 1
    for _ in range(64):
        data_sectors = total_sectors - reserved - nfats * fat_sectors - root_dir_sectors
        if data_sectors <= 0:
            raise SystemExit(f"image of {total_sectors} sectors is too small")
        clusters = data_sectors // sectors_per_cluster
        if clusters + 2 < 4085:
            fat_bits, entry_bytes, per_sector = FAT12, 1.5, SECTOR * 2 // 3
        elif clusters + 2 < 65525:
            fat_bits, entry_bytes, per_sector = FAT16, 2.0, SECTOR // 2
        else:
            raise SystemExit("too many clusters for FAT16; reduce --size-kb")
        needed = int(((clusters + 2) * entry_bytes + SECTOR - 1) // SECTOR)
        if needed == fat_sectors:
            break
        fat_sectors = needed
    else:  # pragma: no cover - the loop converges in two or three rounds
        raise SystemExit("FAT geometry did not converge")

    if total_sectors >= 0x10000:
        total16, total32 = 0, total_sectors
    else:
        total16, total32 = total_sectors, 0
    return {
        "fat_bits": fat_bits,
        "fat_sectors": fat_sectors,
        "reserved_sectors": reserved,
        "num_fats": nfats,
        "root_entries": root_entries,
        "root_dir_sectors": root_dir_sectors,
        "sectors_per_cluster": sectors_per_cluster,
        "total_sectors": total_sectors,
        "total_sectors_16": total16,
        "total_sectors_32": total32,
        "clusters": clusters,
        "data_start_sector": reserved + nfats * fat_sectors + root_dir_sectors,
    }


def boot_sector(geo: dict, volume_label: str) -> bytes:
    """BPB + extended boot record (FAT12/FAT16, 512-byte sectors)."""
    bs = bytearray(SECTOR)
    bs[0:3] = b"\xeb\x3c\x90"
    bs[3:11] = b"PC5EFI  "                       # OEM name, 8 bytes
    struct.pack_into("<H", bs, 11, SECTOR)        # bytes per sector
    bs[13] = geo["sectors_per_cluster"]
    struct.pack_into("<H", bs, 14, geo["reserved_sectors"])
    bs[16] = geo["num_fats"]
    struct.pack_into("<H", bs, 17, geo["root_entries"])
    struct.pack_into("<H", bs, 19, geo["total_sectors_16"])
    bs[21] = MEDIA_DESCRIPTOR
    struct.pack_into("<H", bs, 22, geo["fat_sectors"])
    struct.pack_into("<H", bs, 24, 18)            # sectors per track
    struct.pack_into("<H", bs, 26, 2)             # heads
    struct.pack_into("<I", bs, 28, 0)             # hidden sectors
    struct.pack_into("<I", bs, 32, geo["total_sectors_32"])
    if geo["fat_bits"] == FAT16:
        bs[36] = 0x80                             # drive number
        bs[38] = 0x29                             # extended boot signature
        struct.pack_into("<I", bs, 39, volume_serial(volume_label))
        bs[43:54] = volume_label.upper().ljust(11)[:11].encode("ascii")
        bs[54:62] = b"FAT16   "
    else:
        bs[36] = 0x00
        bs[38] = 0x29
        struct.pack_into("<I", bs, 39, volume_serial(volume_label))
        bs[43:54] = volume_label.upper().ljust(11)[:11].encode("ascii")
        bs[54:62] = b"FAT12   "
    bs[510:512] = b"\x55\xaa"
    return bytes(bs)


def volume_serial(label: str) -> int:
    """Deterministic volume serial (no clock, no randomness)."""
    return int.from_bytes(hashlib.sha256(label.encode("ascii")).digest()[:4], "little") | 1


# --------------------------------------------------------------------------
# builder
# --------------------------------------------------------------------------
class EfiImageBuilder:
    """Builds a FAT image from a list of (source path, FAT path) pairs."""

    def __init__(self, size_kb: int = 1440, volume_label: str = "PC5EFI",
                 sectors_per_cluster: int | None = None):
        if size_kb % 1 or size_kb < 32:
            raise SystemExit("--size-kb must be a whole number of at least 32")
        self.total_sectors = int(size_kb) * 1024 // SECTOR
        if sectors_per_cluster is None:
            # one cluster per 512 bytes up to 16 MiB, then grow the cluster
            sectors_per_cluster = 1 if size_kb <= 16384 else (
                4 if size_kb <= 65536 else 8)
        self.geometry = geometry(self.total_sectors, sectors_per_cluster)
        self.volume_label = volume_label
        self.files: list[tuple[str, bytes]] = []

    # -- inputs ---------------------------------------------------------
    def add_file(self, fat_path: str, data: bytes):
        parts = [p for p in fat_path.replace("\\", "/").split("/") if p]
        if not parts:
            raise SystemExit(f"invalid FAT path {fat_path!r}")
        for part in parts:
            short_name(part)          # validate every component up front
        if len(parts) > 8:
            raise SystemExit(f"FAT path too deep: {fat_path!r}")
        self.files.append(("/".join(parts), data))

    def add_file_from_disk(self, fat_path: str, host_path: str):
        with open(host_path, "rb") as fh:
            self.add_file(fat_path, fh.read())

    # -- layout ---------------------------------------------------------
    def _tree(self) -> dict:
        """Nested dict: name -> bytes (file) or dict (directory)."""
        root: dict = {}
        for path, data in self.files:
            parts = path.split("/")
            node = root
            for part in parts[:-1]:
                node = node.setdefault(part, {})
                if not isinstance(node, dict):
                    raise SystemExit(f"{path!r} needs {part!r} to be a directory")
            if parts[-1] in node:
                raise SystemExit(f"duplicate FAT path {path!r}")
            node[parts[-1]] = data
        return root

    def build(self) -> tuple[bytes, dict]:
        geo = self.geometry
        now = build_time()
        tree = self._tree()

        image = bytearray(geo["total_sectors"] * SECTOR)
        eoc = FAT_EOC12 if geo["fat_bits"] == FAT12 else FAT_EOC16
        # entries[0] and entries[1] are the media/EOF markers; a cluster
        # number N is stored in entries[N].
        fat: list[int] = [0x0FF0 if geo["fat_bits"] == FAT12 else 0xFFF0, eoc]
        state = {"next": 2}

        def cluster_offset(cluster: int) -> int:
            return (geo["data_start_sector"]
                    + (cluster - 2) * geo["sectors_per_cluster"]) * SECTOR

        def take_clusters(count: int) -> int:
            """Reserve `count` clusters and link them into a chain."""
            first = state["next"]
            for index in range(count):
                cluster = first + index
                if cluster >= geo["clusters"] + 2:
                    raise SystemExit("image full: no free clusters left")
                fat.append(cluster + 1 if index + 1 < count else eoc)
            state["next"] += count
            return first

        def store(data: bytes) -> int:
            """Write file data into a fresh cluster chain."""
            cluster_bytes = geo["sectors_per_cluster"] * SECTOR
            count = max(1, (len(data) + cluster_bytes - 1) // cluster_bytes)
            first = take_clusters(count)
            for index in range(count):
                start = cluster_offset(first + index)
                chunk = data[index * cluster_bytes:(index + 1) * cluster_bytes]
                image[start:start + len(chunk)] = chunk
            return first

        def write_dir(directory: dict, parent: int | None) -> int:
            """Create a directory (dot entries included) and return its cluster."""
            cluster_bytes = geo["sectors_per_cluster"] * SECTOR
            first = take_clusters(1)
            blob = bytearray()
            if parent is not None:
                blob += dir_entry(short_name("."), ATTR_DIRECTORY, first, 0, now)
                blob += dir_entry(short_name(".."), ATTR_DIRECTORY, parent, 0, now)
            for name, value in sorted(directory.items()):
                if isinstance(value, dict):
                    child = write_dir(value, first)
                    blob += dir_entry(short_name(name), ATTR_DIRECTORY, child, 0, now)
                else:
                    blob += dir_entry(short_name(name), ATTR_ARCHIVE, store(value),
                                      len(value), now)
            if len(blob) > cluster_bytes:
                raise SystemExit(
                    f"directory needs {len(blob)} bytes, one cluster holds {cluster_bytes}")
            start = cluster_offset(first)
            image[start:start + len(blob)] = blob
            return first

        # The root directory is a fixed area, not part of the data region.
        root_area = (geo["reserved_sectors"] + geo["num_fats"] * geo["fat_sectors"]) * SECTOR
        root_entries: list[bytes] = [volume_label_entry(self.volume_label, now)]
        # Subdirectories are written first so the root can point at them; a
        # root entry needs the child's cluster, and the child's ".." needs the
        # root cluster, which for FAT12/16 is the reserved value 0.
        children = {name: write_dir(value, 0)
                    for name, value in sorted(tree.items()) if isinstance(value, dict)}
        for name, value in sorted(tree.items()):
            if isinstance(value, dict):
                root_entries.append(dir_entry(short_name(name), ATTR_DIRECTORY,
                                              children[name], 0, now))
            else:
                root_entries.append(dir_entry(short_name(name), ATTR_ARCHIVE,
                                              store(value), len(value), now))
            if len(root_entries) > geo["root_entries"]:
                raise SystemExit("root directory is full")
        root_blob = b"".join(root_entries)
        if len(root_blob) > geo["root_dir_sectors"] * SECTOR:
            raise SystemExit("root directory overflows its reserved area")
        image[root_area:root_area + len(root_blob)] = root_blob

        clusters_used = state["next"] - 2
        if clusters_used > geo["clusters"]:
            raise SystemExit(
                f"image too small: {clusters_used} clusters needed, "
                f"{geo['clusters']} available")

        # -- boot sector and both FAT copies ---------------------------
        image[0:SECTOR] = boot_sector(geo, self.volume_label)
        fat_bytes = self._pack_fat(fat, geo)
        for copy in range(geo["num_fats"]):
            offset = (geo["reserved_sectors"] + copy * geo["fat_sectors"]) * SECTOR
            image[offset:offset + len(fat_bytes)] = fat_bytes

        info = {
            "bytes": len(image),
            "sha256": hashlib.sha256(image).hexdigest(),
            "volume_label": self.volume_label,
            "fat_type": f"FAT{geo['fat_bits']}",
            "cluster_count": geo["clusters"],
            "clusters_used": clusters_used,
            "bytes_free": (geo["clusters"] - clusters_used)
                          * geo["sectors_per_cluster"] * SECTOR,
            "layout": {
                "bytes_per_sector": SECTOR,
                "sectors_per_cluster": geo["sectors_per_cluster"],
                "reserved_sectors": geo["reserved_sectors"],
                "num_fats": geo["num_fats"],
                "fat_sectors": geo["fat_sectors"],
                "root_entries": geo["root_entries"],
                "root_dir_sectors": geo["root_dir_sectors"],
                "total_sectors": geo["total_sectors"],
                "data_start_sector": geo["data_start_sector"],
            },
            "files": [
                {"path": path, "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest()}
                for path, data in self.files
            ],
        }
        return bytes(image), info


    @staticmethod
    def _pack_fat(entries: list[int], geo: dict) -> bytes:
        if geo["fat_bits"] == FAT12:
            out = bytearray()
            # FAT12 pairs are packed into three bytes: entry[even] in the low
            # 12 bits, entry[odd] in the high 12 bits.
            for index in range(0, len(entries), 2):
                low = entries[index] & 0xFFF
                high = entries[index + 1] & 0xFFF if index + 1 < len(entries) else 0
                out += (low | (high << 12)).to_bytes(3, "little")
            packed = bytes(out)
        else:
            packed = b"".join(struct.pack("<H", v & 0xFFFF) for v in entries)
        size = geo["fat_sectors"] * SECTOR
        if len(packed) > size:
            raise SystemExit("FAT is larger than the space reserved for it")
        return packed.ljust(size, b"\0")


# --------------------------------------------------------------------------
# reader (used by --list and by the host tests)
# --------------------------------------------------------------------------
class FatVolume:
    """Minimal read-only FAT12/FAT16 walker.

    It deliberately re-derives everything from the on-disk bytes instead of
    trusting what the builder recorded, so a test can prove that the image is
    self-describing.
    """

    def __init__(self, image: bytes):
        self.image = image
        if len(image) < SECTOR:
            raise SystemExit("image is shorter than one sector")
        if image[510:512] != b"\x55\xaa":
            raise SystemExit("missing 0x55AA boot signature")
        self.bytes_per_sector = struct.unpack_from("<H", image, 11)[0]
        self.sectors_per_cluster = image[13]
        self.reserved = struct.unpack_from("<H", image, 14)[0]
        self.num_fats = image[16]
        self.root_entries = struct.unpack_from("<H", image, 17)[0]
        self.total16 = struct.unpack_from("<H", image, 19)[0]
        self.fat_sectors = struct.unpack_from("<H", image, 22)[0]
        self.total32 = struct.unpack_from("<I", image, 32)[0]
        if self.bytes_per_sector != SECTOR:
            raise SystemExit(f"unexpected sector size {self.bytes_per_sector}")
        if self.sectors_per_cluster & (self.sectors_per_cluster - 1):
            raise SystemExit("sectors per cluster is not a power of two")
        self.total_sectors = self.total16 or self.total32
        self.root_dir_sectors = (self.root_entries * 32 + SECTOR - 1) // SECTOR
        self.first_data_sector = (self.reserved + self.num_fats * self.fat_sectors
                                  + self.root_dir_sectors)
        data_sectors = self.total_sectors - self.first_data_sector
        clusters = data_sectors // self.sectors_per_cluster
        self.fat_bits = FAT12 if clusters + 2 < 4085 else FAT16
        self.cluster_count = clusters
        self.fat = image[self.reserved * SECTOR:
                         (self.reserved + self.fat_sectors) * SECTOR]

    # -- FAT chain ------------------------------------------------------
    def next_cluster(self, cluster: int) -> int:
        if self.fat_bits == FAT12:
            offset = cluster + cluster // 2
            if offset + 2 > len(self.fat):
                raise SystemExit("FAT12 entry out of range")
            value = struct.unpack_from("<H", self.fat, offset)[0]
            value = value >> 4 if cluster & 1 else value & 0xFFF
            return None if value >= 0xFF8 else value
        offset = cluster * 2
        if offset + 2 > len(self.fat):
            raise SystemExit("FAT16 entry out of range")
        value = struct.unpack_from("<H", self.fat, offset)[0]
        return None if value >= 0xFFF8 else value

    def chain(self, first: int) -> list[int]:
        out, seen = [], set()
        cluster = first
        while cluster and cluster not in seen:
            seen.add(cluster)
            if cluster < 2 or cluster >= self.cluster_count + 2:
                raise SystemExit(f"cluster {cluster} outside the data region")
            out.append(cluster)
            cluster = self.next_cluster(cluster)
        return out

    def cluster_bytes(self, cluster: int) -> bytes:
        offset = (self.first_data_sector
                  + (cluster - 2) * self.sectors_per_cluster) * SECTOR
        length = self.sectors_per_cluster * SECTOR
        if offset + length > len(self.image):
            raise SystemExit("cluster reads past the end of the image")
        return self.image[offset:offset + length]

    def read_file(self, first: int, size: int) -> bytes:
        data = b"".join(self.cluster_bytes(c) for c in self.chain(first))
        if len(data) < size:
            raise SystemExit(f"file claims {size} bytes, chain holds {len(data)}")
        return data[:size]

    # -- directories ----------------------------------------------------
    def root_dir_bytes(self) -> bytes:
        offset = (self.reserved + self.num_fats * self.fat_sectors) * SECTOR
        return self.image[offset:offset + self.root_dir_sectors * SECTOR]

    def dir_bytes(self, first: int) -> bytes:
        return b"".join(self.cluster_bytes(c) for c in self.chain(first))

    @staticmethod
    def parse_entries(blob: bytes) -> list[dict]:
        entries = []
        for off in range(0, len(blob) - 31, 32):
            raw = blob[off:off + 32]
            if raw[0] == 0x00:
                break
            if raw[0] == 0xE5:
                continue
            if raw[11] == ATTR_LFN:
                continue                     # long names are not written
            base = raw[0:8].decode("ascii", "replace").rstrip()
            ext = raw[8:11].decode("ascii", "replace").rstrip()
            entries.append({
                "name": base + ("." + ext if ext else ""),
                "attributes": raw[11],
                "dir": bool(raw[11] & ATTR_DIRECTORY),
                "cluster": struct.unpack_from("<H", raw, 26)[0],
                "size": struct.unpack_from("<I", raw, 28)[0],
            })
        return entries

    def walk(self) -> dict[str, dict]:
        """Return {"EFI/BOOT/BOOTX64.EFI": {...}} for every file."""
        found: dict[str, dict] = {}

        def descend(blob: bytes, prefix: str, depth: int):
            for entry in self.parse_entries(blob):
                if entry["attributes"] & ATTR_VOLUME_ID:
                    continue
                path = f"{prefix}{entry['name']}"
                if entry["name"] in (".", ".."):
                    continue
                if entry["dir"]:
                    if depth > 8:
                        raise SystemExit("directory nesting too deep")
                    descend(self.dir_bytes(entry["cluster"]), path + "/", depth + 1)
                else:
                    data = self.read_file(entry["cluster"], entry["size"])
                    found[path] = {"bytes": len(data), "data": data,
                                   "attributes": entry["attributes"],
                                   "cluster": entry["cluster"]}
        descend(self.root_dir_bytes(), "", 0)
        return found


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="build a PC5 UEFI boot (ESP) image")
    ap.add_argument("--size-kb", type=int, default=1440,
                    help="image size in KiB (default 1440 = 1.44 MB floppy)")
    ap.add_argument("--volume-label", default="PC5EFI")
    ap.add_argument("--file", action="append", default=[], metavar="SRC=DEST",
                    help="add SRC from the host at FAT path DEST")
    ap.add_argument("--output", help="write the image here")
    ap.add_argument("--info", help="write build info JSON here")
    ap.add_argument("--list", metavar="IMAGE", help="list an existing image and exit")
    args = ap.parse_args(argv)

    if args.list:
        volume = FatVolume(open(args.list, "rb").read())
        print(f"{args.list}: {volume.fat_bits}-bit, "
              f"{volume.cluster_count} clusters of "
              f"{volume.sectors_per_cluster * SECTOR} bytes")
        for path, meta in sorted(volume.walk().items()):
            print(f"  {meta['bytes']:>8}  {path}")
        return 0

    if not args.output:
        raise SystemExit("--output is required unless --list is used")
    if not args.file:
        raise SystemExit("at least one --file SRC=DEST is required")

    builder = EfiImageBuilder(size_kb=args.size_kb, volume_label=args.volume_label)
    for spec in args.file:
        source, _, dest = spec.partition("=")
        if not dest:
            raise SystemExit(f"--file expects SRC=DEST, got {spec!r}")
        builder.add_file_from_disk(dest, source)

    image, info = builder.build()
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "wb") as fh:
        fh.write(image)
    if args.info:
        with open(args.info, "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=2, sort_keys=True)
            fh.write("\n")
    print(f"pc5: wrote {args.output} ({info['fat_type']}, {info['bytes']} bytes, "
          f"{info['clusters_used']}/{info['cluster_count']} clusters used)")
    print(f"pc5: sha256 {info['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

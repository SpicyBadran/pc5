#!/usr/bin/env python3
"""PC5 ISO image builder.

This tool writes a spec-conformant ISO9660 (ECMA-119) image with an
El Torito (ECMA-2/TPP) boot catalog.  It exists because the PC5 build is
required to be reproducible on machines that do not have `xorriso`
installed, and because PC5 needs byte-exact control of the boot
descriptor that the stage-1 loader reads.

Layout produced (2048-byte logical blocks):

    LBA 0..15    system area (all zero)
    LBA 16       primary volume descriptor
    LBA 17       boot record volume descriptor (El Torito)
    LBA 18       volume descriptor set terminator
    LBA 19..20   little-endian path table
    LBA 21..22   big-endian path table
    LBA 23       El Torito boot catalog
    LBA 24..     boot image(s) (BIOS no-emulation image, optional UEFI image)
    then         root directory, then file data

The BIOS boot image is *not* required to be 512 bytes: the whole image is
loaded contiguously by the firmware at 07C0:0000, so the stage-1 loader can
carry its own code past the first virtual sector.

Every build writes `build/build-info.json` with the layout and SHA-256 of
each input, so a rebuild can be compared byte for byte.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import struct
import sys
import zlib

SECTOR = 2048
SYSTEM_AREA_SECTORS = 16
BOOT_DESC_MAGIC = b"PC5BOOT1"
BOOT_DESC_SIZE = 64


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def both16(value: int) -> bytes:
    """16-bit both-endian (little then big) field."""
    return struct.pack("<H", value) + struct.pack(">H", value)


def both32(value: int) -> bytes:
    """32-bit both-endian (little then big) field."""
    return struct.pack("<I", value) + struct.pack(">I", value)


def pad(text: str | bytes, length: int, fill: bytes = b" ") -> bytes:
    if isinstance(text, str):
        raw = text.encode("ascii", "replace")
    else:
        raw = text
    return raw[:length].ljust(length, fill)


def dir_record(name: bytes, extent: int, size: int, is_dir: bool) -> bytes:
    """Build one ISO9660 directory record."""
    now = datetime.datetime.now(datetime.timezone.utc)
    date7 = bytes(
        [
            max(0, now.year - 1900),
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second,
            0,  # GMT offset, already UTC
        ]
    )
    nlen = len(name)
    rec_len = 33 + nlen + (0 if nlen % 2 else 1)
    out = bytearray(rec_len)
    out[0] = rec_len
    out[1] = 0  # extended attribute record length
    out[2:10] = both32(extent)
    out[10:18] = both32(size)
    out[18:25] = date7
    out[25] = 0x02 if is_dir else 0x00
    out[26] = 0  # file unit size
    out[27] = 0  # interleave gap
    out[28:32] = both16(1)  # volume sequence number
    out[32] = nlen
    out[33 : 33 + nlen] = name
    return bytes(out)


def iso_name(name: str) -> bytes:
    """Normalise a file name to an ISO9660 level-1 identifier."""
    upper = name.upper()
    if "." in upper:
        base, ext = upper.rsplit(".", 1)
        return f"{base[:8]}.{ext[:3]};1".encode("ascii")
    return f"{upper[:8]};1".encode("ascii")


# --------------------------------------------------------------------------
# boot descriptor
# --------------------------------------------------------------------------
def make_boot_descriptor(
    kernel_lba: int,
    kernel_bytes: int,
    boot_image_lba: int,
    iso_sectors: int,
    volume_id: str,
    flags: int = 0,
) -> bytes:
    body = bytearray(BOOT_DESC_SIZE)
    body[0:8] = BOOT_DESC_MAGIC
    struct.pack_into("<I", body, 8, kernel_lba)
    struct.pack_into("<I", body, 12, kernel_bytes)
    struct.pack_into("<I", body, 16, boot_image_lba)
    struct.pack_into("<I", body, 20, SYSTEM_AREA_SECTORS)  # LBA of the PVD
    struct.pack_into("<I", body, 24, iso_sectors)
    struct.pack_into("<I", body, 32, flags)
    body[36:60] = pad(volume_id, 24, b"\0")
    struct.pack_into("<I", body, 60, zlib.crc32(bytes(body[0:60])) & 0xFFFFFFFF)
    return bytes(body)


# --------------------------------------------------------------------------
# builder
# --------------------------------------------------------------------------
class IsoBuilder:
    def __init__(self, volume_id="PC5", publisher="PC5 Project", app_id="PC5"):
        self.volume_id = volume_id
        self.publisher = publisher
        self.app_id = app_id
        self.files: list[tuple[bytes, bytes]] = []  # (identifier, data)
        self.bios_image: bytes | None = None
        self.uefi_image: bytes | None = None
        self.boot_desc_offset = 0x100
        self.descriptor_builder = make_boot_descriptor
        self.uefi_sectors = 0

    # -- inputs ---------------------------------------------------------
    def add_file(self, name: str, data: bytes):
        self.files.append((iso_name(name), data))

    def set_bios_boot_image(self, data: bytes, desc_offset: int = 0x100):
        if len(data) < desc_offset + BOOT_DESC_SIZE:
            raise SystemExit(
                f"boot image too small for descriptor at {desc_offset:#x} "
                f"(size {len(data)})"
            )
        self.bios_image = data
        self.boot_desc_offset = desc_offset

    def set_uefi_image(self, data: bytes):
        self.uefi_image = data

    # -- layout ---------------------------------------------------------
    @staticmethod
    def _sectors(n: int) -> int:
        return (n + SECTOR - 1) // SECTOR

    def build(self) -> tuple[bytes, dict]:
        if not self.bios_image:
            raise SystemExit("a BIOS boot image is required")

        sectors = SYSTEM_AREA_SECTORS + 3  # pvd, brvd, terminator
        l_path_lba = sectors
        sectors += 2
        m_path_lba = sectors
        sectors += 2
        catalog_lba = sectors
        sectors += 1

        bios_lba = sectors
        bios_sectors = self._sectors(len(self.bios_image))
        # El Torito counts virtual 512-byte sectors, not ISO blocks
        bios_vsectors = (len(self.bios_image) + 511) // 512
        sectors += bios_sectors

        uefi_lba = 0
        if self.uefi_image:
            uefi_lba = sectors
            self.uefi_sectors = self._sectors(len(self.uefi_image))
            sectors += self.uefi_sectors

        root_lba = sectors
        sectors += 1  # root directory occupies one sector

        file_layout = []
        for ident, data in self.files:
            file_layout.append((ident, data, sectors, self._sectors(len(data)) or 1))
            sectors += self._sectors(len(data)) or 1

        iso_sectors = sectors

        # -- root directory --------------------------------------------
        root_entries = bytearray()
        root_entries += dir_record(b"\x00", root_lba, SECTOR, True)
        root_entries += dir_record(b"\x01", root_lba, SECTOR, True)
        for ident, data, lba, _ in file_layout:
            root_entries += dir_record(ident, lba, len(data), False)
        if len(root_entries) > SECTOR:
            raise SystemExit("root directory does not fit in one sector")
        root_dir = bytes(root_entries).ljust(SECTOR, b"\0")

        # -- boot image with patched descriptor ------------------------
        kernel = next((f for f in file_layout if f[0].startswith(b"KERNEL")), None)
        kernel_lba = kernel[2] if kernel else 0
        kernel_size = len(kernel[1]) if kernel else 0
        boot_image = bytearray(self.bios_image)
        desc = self.descriptor_builder(
            kernel_lba=kernel_lba,
            kernel_bytes=kernel_size,
            boot_image_lba=bios_lba,
            iso_sectors=iso_sectors,
            volume_id=self.volume_id,
        )
        off = self.boot_desc_offset
        boot_image[off : off + BOOT_DESC_SIZE] = desc
        boot_image = bytes(boot_image)

        # -- path table (root only) ------------------------------------
        pt = bytearray()
        pt += bytes([1, 0])                      # id length, ext attr length
        pt += struct.pack("<I", root_lba)        # extent
        pt += struct.pack("<H", 1)               # parent directory number
        pt += b"\x00"                            # root identifier
        pt += b"\x00"                            # pad to even length
        l_path = bytes(pt).ljust(SECTOR, b"\0")
        m_pt = bytearray()
        m_pt += bytes([1, 0])
        m_pt += struct.pack(">I", root_lba)
        m_pt += struct.pack(">H", 1)
        m_pt += b"\x00\x00"
        m_path = bytes(m_pt).ljust(SECTOR, b"\0")

        # -- boot catalog ----------------------------------------------
        catalog = bytearray(SECTOR)
        # validation entry
        catalog[0] = 0x01                       # header id
        catalog[1] = 0x00                       # platform: 80x86
        catalog[4:28] = pad("PC5 Boot Catalog", 24, b"\0")
        catalog[30:32] = b"\x55\xaa"
        words = sum(struct.unpack("<16H", bytes(catalog[0:32])))
        catalog[28:30] = struct.pack("<H", (0x10000 - (words & 0xFFFF)) & 0xFFFF)
        # default (BIOS) entry
        e = 32
        catalog[e + 0] = 0x88                   # bootable
        catalog[e + 1] = 0x00                   # no emulation
        catalog[e + 2: e + 4] = struct.pack("<H", 0x07C0)
        catalog[e + 4] = 0
        catalog[e + 6: e + 8] = struct.pack("<H", bios_vsectors)
        catalog[e + 8: e + 12] = struct.pack("<I", bios_lba)
        if self.uefi_image:
            # section header for the UEFI platform, then its entry
            s = 64
            catalog[s + 0] = 0x91               # final section header
            catalog[s + 1] = 0xEF               # platform: UEFI
            catalog[s + 2: s + 4] = struct.pack("<H", 1)
            e = 96
            catalog[e + 0] = 0x88
            catalog[e + 1] = 0x00
            catalog[e + 2: e + 4] = struct.pack("<H", 0x0000)
            catalog[e + 4] = 0
            catalog[e + 6: e + 8] = struct.pack("<H", (len(self.uefi_image) + 511) // 512)
            catalog[e + 8: e + 12] = struct.pack("<I", uefi_lba)

        # -- primary volume descriptor ---------------------------------
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp = now.strftime("%Y%m%d%H%M%S").encode("ascii")
        pvd = bytearray(SECTOR)
        pvd[0] = 1
        pvd[1:6] = b"CD001"
        pvd[6] = 1
        pvd[8:40] = pad("PC5", 32)
        pvd[40:72] = pad(self.volume_id, 32)
        pvd[80:88] = both32(iso_sectors)              # volume space size
        pvd[120:124] = both16(1)                      # volume set size
        pvd[124:128] = both16(1)                      # volume sequence number
        pvd[128:136] = both16(SECTOR)                 # logical block size
        pvd[136:144] = both32(len(l_path))            # path table size
        pvd[144:148] = struct.pack("<I", l_path_lba)  # type L path table
        pvd[152:156] = struct.pack(">I", m_path_lba)  # type M path table
        root_rec = dir_record(b"\x00", root_lba, SECTOR, True)
        pvd[156 : 156 + len(root_rec)] = root_rec
        pvd[190:322] = pad("PC5", 128)                # volume set identifier
        pvd[322:450] = pad(self.publisher, 128)
        pvd[450:578] = pad("PC5 build system", 128)   # data preparer
        pvd[578:706] = pad(self.app_id, 128)
        pvd[706:743] = pad("", 37)                    # copyright file id
        pvd[743:780] = pad("", 37)                    # abstract file id
        pvd[780:817] = pad("", 37)                    # bibliographic file id
        pvd[813:830] = stamp + b"\x00"
        pvd[830:847] = stamp + b"\x00"
        pvd[847:864] = pad("0" * 16, 16) + b"\x00"
        pvd[864:881] = pad("0" * 16, 16) + b"\x00"
        pvd[881] = 1                                  # file structure version

        # -- boot record volume descriptor -----------------------------
        brvd = bytearray(SECTOR)
        brvd[0] = 0
        brvd[1:6] = b"CD001"
        brvd[6] = 1
        brvd[7:39] = pad("EL TORITO SPECIFICATION", 32, b"\0")
        brvd[39:71] = pad("PC5", 32, b"\0")
        brvd[71:75] = struct.pack("<I", catalog_lba)

        term = bytearray(SECTOR)
        term[0] = 255
        term[1:6] = b"CD001"
        term[6] = 1

        # -- assemble ---------------------------------------------------
        image = bytearray(iso_sectors * SECTOR)

        def put(offset: int, payload: bytes):
            """Write bytes without ever resizing the image."""
            end = offset + len(payload)
            if end > len(image):
                raise SystemExit(
                    f"internal error: write at {offset} (+{len(payload)}) "
                    f"past end of image ({len(image)})"
                )
            image[offset:end] = payload

        put(bios_lba * SECTOR, boot_image)
        if self.uefi_image:
            put(uefi_lba * SECTOR, self.uefi_image)
        put(l_path_lba * SECTOR, l_path)
        put(m_path_lba * SECTOR, m_path)
        put(catalog_lba * SECTOR, bytes(catalog))
        put(root_lba * SECTOR, root_dir)
        for ident, data, lba, _ in file_layout:
            put(lba * SECTOR, data)
        put(16 * SECTOR, bytes(pvd))
        put(17 * SECTOR, bytes(brvd))
        put(18 * SECTOR, bytes(term))
        if len(image) != iso_sectors * SECTOR:
            raise SystemExit(
                f"internal error: image resized to {len(image)} bytes "
                f"(expected {iso_sectors * SECTOR})"
            )

        info = {
            "volume_id": self.volume_id,
            "iso_sectors": iso_sectors,
            "iso_bytes": iso_sectors * SECTOR,
            "sha256": hashlib.sha256(image).hexdigest(),
            "layout": {
                "pvd_lba": 16,
                "brvd_lba": 17,
                "path_table_l_lba": l_path_lba,
                "path_table_m_lba": m_path_lba,
                "boot_catalog_lba": catalog_lba,
                "bios_boot_image_lba": bios_lba,
                "bios_boot_image_sectors": bios_sectors,
                "bios_boot_virtual_sectors": bios_vsectors,
                "bios_boot_image_bytes": len(boot_image),
                "uefi_image_lba": uefi_lba,
                "uefi_image_sectors": self.uefi_sectors,
                "root_dir_lba": root_lba,
            },
            "kernel": {"lba": kernel_lba, "bytes": kernel_size},
            "files": [
                {"identifier": ident.decode("ascii"), "lba": lba, "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest()}
                for ident, data, lba, _ in file_layout
            ],
        }
        return bytes(image), info


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="build a PC5 ISO image")
    ap.add_argument("--volume-id", default="PC5")
    ap.add_argument("--boot-image", required=True, help="BIOS no-emulation boot image")
    ap.add_argument("--uefi-image", help="FAT image for the UEFI El Torito entry")
    ap.add_argument("--file", action="append", default=[], metavar="NAME=PATH",
                    help="add a file to the ISO root")
    ap.add_argument("--output", required=True)
    ap.add_argument("--info", help="write build info JSON here")
    ap.add_argument("--desc-offset", type=lambda s: int(s, 0), default=0x100)
    args = ap.parse_args(argv)

    builder = IsoBuilder(volume_id=args.volume_id)
    with open(args.boot_image, "rb") as fh:
        builder.set_bios_boot_image(fh.read(), desc_offset=args.desc_offset)
    if args.uefi_image:
        with open(args.uefi_image, "rb") as fh:
            builder.set_uefi_image(fh.read())
    for spec in args.file:
        name, _, path = spec.partition("=")
        if not path:
            raise SystemExit(f"--file expects NAME=PATH, got {spec!r}")
        with open(path, "rb") as fh:
            builder.add_file(name, fh.read())

    image, info = builder.build()
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "wb") as fh:
        fh.write(image)
    with open(args.output + ".sha256", "w", encoding="ascii") as fh:
        fh.write(f"{info['sha256']}  {os.path.basename(args.output)}\n")
    if args.info:
        with open(args.info, "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=2, sort_keys=True)
            fh.write("\n")
    print(f"pc5: wrote {args.output} ({info['iso_bytes']} bytes, "
          f"{info['iso_sectors']} sectors)")
    print(f"pc5: sha256 {info['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

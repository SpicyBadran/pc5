#!/usr/bin/env python3
"""Independent ISO9660 / El Torito verifier for PC5 images.

This parses the image from scratch (it shares no code with tools/mkiso.py) and
checks the things that make the difference between "a file with .iso on the
end" and a medium a firmware will boot:

  * ISO9660 primary volume descriptor, block size and volume size
  * the boot record volume descriptor and the El Torito boot catalog,
    including the validation-entry checksum
  * both El Torito sections: platform 0x00 (BIOS) and, when present, the
    platform 0xEF (UEFI) section with its FAT image
  * the boot image entry (load segment, virtual sector count, media type)
  * the UEFI boot image: FAT12/16 boot sector, the ESP directory tree, and a
    PE32+ application at \EFI\BOOT\BOOTX64.EFI with machine x86-64 and
    subsystem 10 (EFI application)
  * the PC5 boot descriptor inside the boot image, including its CRC32
  * that the descriptor's kernel geometry matches the KERNEL.BIN directory
    record, that the kernel signature is present at its extent, and that the
    bytes match the recorded SHA-256

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib

SECTOR = 2048


def u32le(b, off):
    return struct.unpack_from("<I", b, off)[0]


def u16le(b, off):
    return struct.unpack_from("<H", b, off)[0]


class Report:
    def __init__(self):
        self.checks = []
        self.data = {}

    def check(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return ok

    @property
    def ok(self):
        return all(c["ok"] for c in self.checks)

    @property
    def failures(self):
        return [c for c in self.checks if not c["ok"]]


def _fat_geometry(fat):
    """Parse a FAT12/FAT16 boot sector (512-byte sectors only)."""
    if len(fat) < 512 or fat[510:512] != b"\x55\xaa":
        return None
    geo = {
        "bytes_per_sector": u16le(fat, 11),
        "sectors_per_cluster": fat[13],
        "reserved": u16le(fat, 14),
        "num_fats": fat[16],
        "root_entries": u16le(fat, 17),
        "total": u16le(fat, 19) or u32le(fat, 32),
        "fat_sectors": u16le(fat, 22),
    }
    if geo["bytes_per_sector"] != 512 or geo["sectors_per_cluster"] == 0:
        return None
    geo["root_dir_sectors"] = (geo["root_entries"] * 32 + 511) // 512
    geo["first_data"] = (geo["reserved"] + geo["num_fats"] * geo["fat_sectors"]
                         + geo["root_dir_sectors"])
    if geo["first_data"] * 512 > len(fat):
        return None
    return geo


def _fat_entries(blob):
    out = []
    for off in range(0, len(blob) - 31, 32):
        raw = blob[off : off + 32]
        if raw[0] == 0x00:
            break
        out.append({
            "name": bytes(raw[0:8]).decode("latin-1").rstrip(),
            "ext": bytes(raw[8:11]).decode("latin-1").rstrip(),
            "attr": raw[11],
            "cluster": u16le(raw, 26),
            "size": u32le(raw, 28),
        })
    return out


def _fat_read(fat, geo, cluster, size):
    """Follow a FAT12/FAT16 cluster chain and return `size` bytes.

    `size` of 0 means "the whole chain", which is how directories are read.
    """
    per = geo["sectors_per_cluster"] * 512
    fat_start = geo["reserved"] * 512
    out = bytearray()
    seen = set()
    while cluster >= 2 and cluster not in seen:
        seen.add(cluster)
        start = (geo["first_data"] + (cluster - 2) * geo["sectors_per_cluster"]) * 512
        out += fat[start : start + per]
        entry_off = cluster + cluster // 2
        if entry_off + 2 > geo["fat_sectors"] * 512:
            return None
        value = u16le(fat, fat_start + entry_off)
        value = (value >> 4) if cluster & 1 else (value & 0xFFF)
        cluster = 0 if value >= 0xFF8 else value
    if size == 0:
        return bytes(out)
    if len(out) < size:
        return None
    return bytes(out[:size])


def verify_esp(rep, fat):
    """Check the El Torito UEFI image the way firmware would mount it."""
    geo = _fat_geometry(fat)
    if not rep.check("UEFI image has a valid FAT boot sector", geo is not None):
        return
    cluster_bytes = geo["sectors_per_cluster"] * 512
    clusters = (geo["total"] - geo["first_data"]) // geo["sectors_per_cluster"]
    bits = 12 if clusters + 2 < 4085 else 16
    rep.check("UEFI image is FAT12 or FAT16 (El Torito bootable form)",
              bits in (12, 16), f"{clusters} clusters -> FAT{bits}")
    rep.data["uefi_fat"] = {"fat_bits": bits, "clusters": clusters,
                            "cluster_bytes": cluster_bytes,
                            "sectors_per_cluster": geo["sectors_per_cluster"]}

    root_off = (geo["reserved"] + geo["num_fats"] * geo["fat_sectors"]) * 512
    root_blob = fat[root_off : root_off + geo["root_dir_sectors"] * 512]
    root_entries = _fat_entries(root_blob)
    rep.data["uefi_root"] = [e["name"] + ("." + e["ext"] if e["ext"] else "")
                             for e in root_entries if e["attr"] != 0x08]
    efi = next((e for e in root_entries if e["name"] == "EFI" and e["attr"] & 0x10), None)
    if not rep.check("ESP root directory contains EFI/", efi is not None):
        return

    boot = None
    current = efi
    for want in ("BOOT", "BOOTX64"):
        if current is None:
            break
        blob = _fat_read(fat, geo, current["cluster"], 0)
        if blob is None:
            rep.check(f"ESP directory {want} is readable", False)
            return
        entries = _fat_entries(blob)
        match = next((e for e in entries if e["name"] == want), None)
        if want == "BOOT":
            if not rep.check("ESP contains EFI/BOOT", match is not None and match["attr"] & 0x10):
                return
            current = match
        else:
            if not rep.check("ESP contains EFI/BOOT/BOOTX64.EFI",
                             match is not None and not (match["attr"] & 0x10)):
                return
            boot = match

    data = _fat_read(fat, geo, boot["cluster"], boot["size"])
    if not rep.check("BOOTX64.EFI content is readable through the FAT chain",
                     data is not None and len(data) == boot["size"],
                     f"{boot['size']} bytes"):
        return
    rep.data["uefi_app"] = {"bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()}
    rep.check("BOOTX64.EFI starts with the DOS 'MZ' signature", data[0:2] == b"MZ",
              data[0:2].hex())
    pe_off = u32le(data, 0x3C)
    rep.check("BOOTX64.EFI has a PE header inside the file",
              0x40 <= pe_off < len(data) - 24, hex(pe_off))
    if not (0x40 <= pe_off < len(data) - 24):
        return
    rep.check("BOOTX64.EFI PE signature", data[pe_off : pe_off + 4] == b"PE\0\0",
              data[pe_off : pe_off + 4].hex())
    machine = u16le(data, pe_off + 4)
    subsys = u16le(data, pe_off + 24 + 68)
    magic = u16le(data, pe_off + 24)
    rep.check("BOOTX64.EFI machine is x86-64", machine == 0x8664, hex(machine))
    rep.check("BOOTX64.EFI is PE32+", magic == 0x20B, hex(magic))
    rep.check("BOOTX64.EFI subsystem is EFI application", subsys == 10, str(subsys))


def read_dir_records(image, lba, size):
    raw = image[lba * SECTOR : lba * SECTOR + size]
    out = []
    i = 0
    while i < len(raw) and raw[i]:
        length = raw[i]
        if length < 33 or i + length > len(raw):
            break
        rec = raw[i : i + length]
        extent = u32le(rec, 2)
        data_len = u32le(rec, 10)
        flags = rec[25]
        name_len = rec[32]
        name = rec[33 : 33 + name_len]
        out.append({"name": name, "lba": extent, "size": data_len, "dir": bool(flags & 2)})
        i += length
    return out


def verify(path, info_path=None):
    rep = Report()
    with open(path, "rb") as fh:
        image = fh.read()

    rep.data["file"] = path
    rep.data["bytes"] = len(image)
    rep.data["sha256"] = hashlib.sha256(image).hexdigest()

    if not rep.check("image is a whole number of 2048-byte blocks", len(image) % SECTOR == 0,
                     f"{len(image)} bytes"):
        return rep

    # ---------------- primary volume descriptor ----------------
    pvd = image[16 * SECTOR : 17 * SECTOR]
    rep.check("volume descriptor signature at LBA 16", pvd[1:6] == b"CD001", pvd[1:6].decode("latin-1"))
    rep.check("primary volume descriptor type", pvd[0] == 1, f"type {pvd[0]}")
    volume_id = pvd[40:72].decode("ascii", "replace").rstrip()
    block_size = u16le(pvd, 128)
    volume_blocks = u32le(pvd, 80)
    rep.data["volume_id"] = volume_id
    rep.data["block_size"] = block_size
    rep.data["volume_blocks"] = volume_blocks
    rep.check("logical block size is 2048", block_size == SECTOR, str(block_size))
    rep.check("volume size matches the file", volume_blocks * SECTOR == len(image),
              f"{volume_blocks} blocks")

    root_rec = pvd[156:190]
    root_lba = u32le(root_rec, 2)
    root_size = u32le(root_rec, 10)
    rep.check("root directory extent is present", root_lba * SECTOR < len(image), f"LBA {root_lba}")
    entries = read_dir_records(image, root_lba, root_size)
    files = {e["name"].decode("ascii", "replace"): e for e in entries if not e["dir"]}
    rep.data["root_files"] = sorted(files)
    rep.check("volume contains a kernel file", any(n.startswith("KERNEL") for n in files),
              ",".join(sorted(files)))

    # ---------------- boot record + catalog ----------------
    brvd = image[17 * SECTOR : 18 * SECTOR]
    rep.check("boot record volume descriptor type", brvd[0] == 0, f"type {brvd[0]}")
    rep.check("El Torito system identifier",
              brvd[7 : 7 + 23] == b"EL TORITO SPECIFICATION",
              brvd[7:31].rstrip(b"\x00 ").decode("latin-1"))
    catalog_lba = u32le(brvd, 71)
    rep.check("boot catalog pointer is inside the image", 0 < catalog_lba * SECTOR < len(image),
              f"LBA {catalog_lba}")
    catalog = image[catalog_lba * SECTOR : (catalog_lba + 1) * SECTOR]

    rep.check("catalog validation header id", catalog[0] == 0x01, hex(catalog[0]))
    rep.check("catalog validation signature 55AA", catalog[30:32] == b"\x55\xaa",
              catalog[30:32].hex())
    words = struct.unpack("<16H", catalog[0:32])
    rep.check("catalog validation checksum sums to zero", sum(words) % 0x10000 == 0,
              hex(sum(words) % 0x10000))

    # ---------------- catalog sections ----------------
    # The catalog starts with the initial/default entry at offset 32, which
    # is what a BIOS reads first.  Any further platform entries live in
    # sections that start with a 0x90/0x91 header; the last section's header
    # carries 0x91.  A section of n entries occupies 32 + 32*n bytes.
    sections = [{
        "offset": 32,
        "header": None,
        "first": True,
        # the initial entry's platform comes from the validation entry
        "platform": catalog[1],
        "entries": 1,
        "bootable": catalog[32],
        "media_type": catalog[33],
        "load_segment": u16le(catalog, 34),
        "virtual_sectors": u16le(catalog, 38),
        "image_lba": u32le(catalog, 40),
    }]
    offset = 64
    while offset + 64 <= SECTOR and catalog[offset] in (0x90, 0x91):
        header = catalog[offset]
        platform = catalog[offset + 1]
        entries = u16le(catalog, offset + 2)
        if entries < 1:
            break
        entry = catalog[offset + 32 : offset + 64]
        sections.append({
            "offset": offset,
            "header": header,
            "first": False,
            "platform": platform,
            "entries": entries,
            "bootable": entry[0],
            "media_type": entry[1],
            "load_segment": u16le(entry, 2),
            "virtual_sectors": u16le(entry, 6),
            "image_lba": u32le(entry, 8),
        })
        if header == 0x91:      # 0x91 means "this is the last section"
            break
        offset += 32 + 32 * entries
    rep.data["sections"] = sections
    rep.check("catalog has an initial entry", bool(sections))
    if sections:
        rep.check("initial entry is the 80x86 BIOS default",
                  sections[0]["platform"] == 0x00, hex(sections[0]["platform"]))
        rep.check("every section advertises at least one entry",
                  all(sec["entries"] >= 1 for sec in sections),
                  ",".join(str(sec["entries"]) for sec in sections))
        rep.check("the last section header is 0x91 (no further sections)",
                  len(sections) == 1 or sections[-1]["header"] == 0x91,
                  str(sections[-1]["header"]))
        duplicates = {}
        for sec in sections:
            duplicates[sec["platform"]] = duplicates.get(sec["platform"], 0) + 1
        rep.check("no duplicate platform sections",
                  all(count == 1 for count in duplicates.values()), str(duplicates))

    entry = catalog[32:64]
    bootable = entry[0]
    media = entry[1]
    load_seg = u16le(entry, 2)
    vsectors = u16le(entry, 6)
    image_lba = u32le(entry, 8)
    rep.data["boot"] = {
        "bootable": bootable,
        "media_type": media,
        "load_segment": load_seg,
        "virtual_sectors": vsectors,
        "image_lba": image_lba,
    }
    rep.check("default entry is bootable", bootable == 0x88, hex(bootable))
    rep.check("default entry is no-emulation", media == 0, str(media))
    rep.check("boot image load segment is 0x7C0", load_seg == 0x07C0, hex(load_seg))
    rep.check("boot image lies inside the image", image_lba * SECTOR < len(image),
              f"LBA {image_lba}")
    rep.check("boot image advertises at least one sector", vsectors >= 1, str(vsectors))

    boot_bytes = image[image_lba * SECTOR : image_lba * SECTOR + vsectors * 512]
    rep.data["boot_image_bytes"] = len(boot_bytes)

    # ---------------- UEFI section, if the medium has one ----------------
    uefi = next((sec for sec in sections if sec["platform"] == 0xEF), None)
    rep.data["has_uefi"] = uefi is not None
    if uefi is not None:
        rep.check("UEFI section entry is bootable", uefi["bootable"] == 0x88,
                  hex(uefi["bootable"]))
        rep.check("UEFI section entry is no-emulation", uefi["media_type"] == 0,
                  str(uefi["media_type"]))
        rep.check("UEFI entry loads at segment 0",
                  uefi["load_segment"] == 0, hex(uefi["load_segment"]))
        uefi_start = uefi["image_lba"] * SECTOR
        uefi_end = uefi_start + uefi["virtual_sectors"] * 512
        rep.check("UEFI image lies inside the ISO",
                  uefi["image_lba"] > 0 and uefi_end <= len(image),
                  f"LBA {uefi['image_lba']} +{uefi['virtual_sectors']} sectors")
        fat = image[uefi_start:uefi_end]
        rep.data["uefi"] = {"lba": uefi["image_lba"],
                            "bytes": len(fat),
                            "sha256": hashlib.sha256(fat).hexdigest()}
        verify_esp(rep, fat)

    # ---------------- PC5 boot descriptor ----------------
    desc = None
    for off in range(0, max(0, len(boot_bytes) - 64)):
        if boot_bytes[off : off + 8] == b"PC5BOOT1":
            desc = boot_bytes[off : off + 64]
            rep.data["descriptor_offset"] = off
            break
    if not rep.check("PC5 boot descriptor found in the boot image", desc is not None):
        return rep
    crc = u32le(desc, 60)
    stored = desc[60:64]
    computed = zlib.crc32(desc[0:60]) & 0xFFFFFFFF
    rep.check("boot descriptor CRC32 is valid", crc == computed,
              f"stored {crc:08x} computed {computed:08x}")
    kernel_lba = u32le(desc, 8)
    kernel_bytes = u32le(desc, 12)
    desc_volume = desc[36:60].split(b"\0")[0].decode("ascii", "replace")
    rep.data["descriptor"] = {"kernel_lba": kernel_lba, "kernel_bytes": kernel_bytes,
                              "volume_id": desc_volume}
    rep.check("descriptor volume id matches the volume descriptor", desc_volume == volume_id,
              f"{desc_volume!r} vs {volume_id!r}")

    kernel_entry = next((e for n, e in files.items() if n.startswith("KERNEL")), None)
    if kernel_entry is not None:
        rep.check("descriptor kernel LBA matches the directory record",
                  kernel_entry["lba"] == kernel_lba,
                  f"{kernel_lba} vs {kernel_entry['lba']}")
        rep.check("descriptor kernel size matches the directory record",
                  kernel_entry["size"] == kernel_bytes,
                  f"{kernel_bytes} vs {kernel_entry['size']}")
        kernel = image[kernel_lba * SECTOR : kernel_lba * SECTOR + kernel_bytes]
        rep.data["kernel"] = {"lba": kernel_lba, "bytes": kernel_bytes,
                              "sha256": hashlib.sha256(kernel).hexdigest()}
        rep.check("kernel image carries the PC5K signature",
                  len(kernel) > 6 and kernel[2:6] == b"PC5K", kernel[:8].hex())
        rep.check("kernel image is not empty", kernel_bytes > 1024, str(kernel_bytes))

    # ---------------- build-info cross check ----------------
    if info_path:
        try:
            with open(info_path, "r", encoding="utf-8") as fh:
                info = json.load(fh)
        except OSError as exc:
            rep.check("build info readable", False, str(exc))
            return rep
        rep.check("image SHA-256 matches build info", info.get("sha256") == rep.data["sha256"],
                  info.get("sha256", "")[:16])
        for f in info.get("files", []):
            ent = files.get(f["identifier"])
            if not rep.check(f"file {f['identifier']} is present", ent is not None):
                continue
            data = image[ent["lba"] * SECTOR : ent["lba"] * SECTOR + ent["size"]]
            digest = hashlib.sha256(data).hexdigest()
            rep.check(f"file {f['identifier']} content matches build info", digest == f["sha256"],
                      digest[:16])
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify a PC5 ISO image")
    ap.add_argument("image")
    ap.add_argument("--info", help="build-info.json to cross-check")
    ap.add_argument("--json-out")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    rep = verify(args.image, args.info)
    if not args.quiet:
        for c in rep.checks:
            print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['name']}"
                  + (f"  ({c['detail']})" if c["detail"] else ""))
        print()
        print(f"{'VALID' if rep.ok else 'INVALID'}: {args.image}  sha256={rep.data['sha256']}")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"ok": rep.ok, "checks": rep.checks, "data": rep.data}, fh, indent=2)
            fh.write("\n")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())

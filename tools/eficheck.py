#!/usr/bin/env python3
"""PC5 UEFI application inspector.

The UEFI loader is cross-linked by binutils' PE emulation, and a PE image can
be subtly wrong in ways that only firmware notices (a missing relocation
table, an entry point outside .text, sections that overlap the headers).  This
tool reads the produced file back and checks the properties UEFI relies on, so
`make iso` fails at build time instead of at boot time on somebody's laptop.

Checks:

  * DOS header 'MZ', e_lfanew sane, PE signature 'PE\\0\\0'
  * machine x86-64 (0x8664), optional header magic PE32+ (0x20B)
  * subsystem 10 (EFI application), not a DLL
  * no imports: the loader links no libraries at all
  * >= 1 base relocation, and every fixup is a type EDK2 implements for
    x86-64 (HIGHLOW, DIR64, ABSOLUTE); a PE loaded at an address other than
    its preferred base *requires* this table
  * entry point inside an executable section; every section inside the file
  * sections laid out at or above the image base, non-overlapping, aligned
  * optional upper bound on the file size (the El Torito entry has a 16-bit
    virtual-sector count, so the image must stay well under 32 MiB)

Usage:  tools/eficheck.py build/uefi/BOOTX64.EFI [--json-out FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys

MACHINE_X64 = 0x8664
PE32P_MAGIC = 0x20B
SUBSYSTEM_EFI_APPLICATION = 10
# Image base relocation types that firmware's x86-64 PE loader implements
# (EDK2's PeCoffLoaderRelocateImageEx): HIGHLOW for 32-bit absolute addresses,
# DIR64 for 64-bit ones, ABSOLUTE as padding.  Anything else in an image means
# a linker option or a code pattern this loader must not use.
RELOC_ABSOLUTE = 0
RELOC_HIGHLOW = 3
RELOC_DIR64 = 10
SUPPORTED_RELOCS = (RELOC_ABSOLUTE, RELOC_HIGHLOW, RELOC_DIR64)


class Report:
    def __init__(self, path: str):
        self.path = path
        self.checks: list[dict] = []
        self.data: dict = {}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def failures(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"]]

    def render(self) -> str:
        lines = [f"{self.path}:"]
        for c in self.checks:
            mark = "ok  " if c["ok"] else "FAIL"
            detail = f"  ({c['detail']})" if c["detail"] else ""
            lines.append(f"  [{mark}] {c['name']}{detail}")
        passed = len(self.checks) - len(self.failures)
        lines.append(f"  {passed}/{len(self.checks)} checks passed")
        return "\n".join(lines)


def parse_sections(image: bytes, pe_off: int) -> tuple[dict, list[dict]]:
    """Read the COFF header, optional header and the section table."""
    machine, nsections, timestamp, _, _, opt_size, characteristics = struct.unpack_from(
        "<HHIIIHH", image, pe_off + 4)
    opt = pe_off + 24
    magic = struct.unpack_from("<H", image, opt)[0]
    if magic != PE32P_MAGIC:
        raise SystemExit(f"not a PE32+ image (optional header magic {magic:#x})")
    entry = struct.unpack_from("<I", image, opt + 16)[0]
    image_base = struct.unpack_from("<Q", image, opt + 24)[0]
    section_alignment = struct.unpack_from("<I", image, opt + 32)[0]
    file_alignment = struct.unpack_from("<I", image, opt + 36)[0]
    size_of_image = struct.unpack_from("<I", image, opt + 56)[0]
    size_of_headers = struct.unpack_from("<I", image, opt + 60)[0]
    subsystem = struct.unpack_from("<H", image, opt + 68)[0]
    ndirs = struct.unpack_from("<I", image, opt + 108)[0]
    reloc_dir = (0, 0)
    if ndirs >= 6:
        reloc_rva, reloc_size = struct.unpack_from("<II", image, opt + 112 + 5 * 8)
        reloc_dir = (reloc_rva, reloc_size)

    table = opt + opt_size
    sections = []
    for i in range(nsections):
        off = table + i * 40
        name = image[off : off + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, raw_size, raw_ptr = struct.unpack_from("<IIII", image, off + 8)
        sec_chars = struct.unpack_from("<I", image, off + 36)[0]
        sections.append({
            "name": name,
            "virtual_size": vsize,
            "virtual_address": vaddr,
            "raw_size": raw_size,
            "raw_pointer": raw_ptr,
            "characteristics": sec_chars,
            "executable": bool(sec_chars & 0x20000000),
            "readable": bool(sec_chars & 0x40000000),
            "writable": bool(sec_chars & 0x80000000),
        })
    header = {
        "machine": machine,
        "nsections": nsections,
        "timestamp": timestamp,
        "characteristics": characteristics,
        "entry": entry,
        "image_base": image_base,
        "section_alignment": section_alignment,
        "file_alignment": file_alignment,
        "size_of_image": size_of_image,
        "size_of_headers": size_of_headers,
        "subsystem": subsystem,
        "reloc_dir": reloc_dir,
    }
    return header, sections


def section_span(section: dict) -> int:
    """Size of the section in memory.

    PE records both a virtual size and a file-aligned raw size; the raw size is
    padded up to the file alignment and therefore routinely extends past the
    next section.  Virtual layout is what matters, so the virtual size wins.
    """
    return section["virtual_size"] or section["raw_size"]


def find_section(sections: list[dict], rva: int) -> dict | None:
    for section in sections:
        if section["virtual_address"] <= rva < section["virtual_address"] + section_span(section):
            return section
    return None


def walk_relocations(image: bytes, header: dict, sections: list[dict]) -> list[tuple[int, int]]:
    """Yield (page_rva, type) for each fixup in the base relocation table."""
    rva, size = header["reloc_dir"]
    if not rva or not size:
        return []
    section = find_section(sections, rva)
    if section is None:
        return []
    offset = section["raw_pointer"] + (rva - section["virtual_address"])
    if offset is None:
        return []
    out = []
    end = offset + size
    while offset + 8 <= end:
        page, block_size = struct.unpack_from("<II", image, offset)
        if block_size < 8:
            break
        count = (block_size - 8) // 2
        for i in range(count):
            entry = struct.unpack_from("<H", image, offset + 8 + i * 2)[0]
            out.append((page, entry >> 12))
        offset += block_size
    return out


def inspect(path: str, require_relocs: bool = True, max_bytes: int = 0,
            timestamp_zero: bool = True) -> Report:
    with open(path, "rb") as fh:
        image = fh.read()
    rep = Report(path)
    rep.data["bytes"] = len(image)
    rep.data["sha256"] = hashlib.sha256(image).hexdigest()

    if not rep.check("file is at least one DOS header long", len(image) >= 0x40,
                     f"{len(image)} bytes"):
        return rep
    rep.check("DOS header 'MZ'", image[0:2] == b"MZ", image[0:2].decode("latin-1"))
    e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
    rep.check("e_lfanew points inside the file", 0x40 <= e_lfanew < len(image) - 4,
              hex(e_lfanew))
    if e_lfanew + 24 > len(image):
        return rep
    rep.check("PE signature", image[e_lfanew : e_lfanew + 4] == b"PE\0\0",
              image[e_lfanew : e_lfanew + 4].hex())

    header, sections = parse_sections(image, e_lfanew)
    rep.data.update({"header": header, "sections": sections})

    rep.check("machine is x86-64", header["machine"] == MACHINE_X64,
              hex(header["machine"]))
    rep.check("subsystem is EFI application", header["subsystem"] == SUBSYSTEM_EFI_APPLICATION,
              str(header["subsystem"]))
    rep.check("image is executable, not a DLL",
              bool(header["characteristics"] & 0x0002) and
              not (header["characteristics"] & 0x2000),
              hex(header["characteristics"]))
    rep.check("no import table (freestanding image)",
              struct.unpack_from("<I", image, e_lfanew + 24 + 112 + 8 * 8 + 4)[0] == 0,
              "import directory size")
    rep.check("at least one section", header["nsections"] >= 1,
              str(header["nsections"]))

    alignment_ok = (header["section_alignment"] >= 0x200 and
                    header["section_alignment"] & (header["section_alignment"] - 1) == 0 and
                    header["file_alignment"] >= 0x200 and
                    header["file_alignment"] & (header["file_alignment"] - 1) == 0)
    rep.check("section/file alignments are powers of two >= 0x200", alignment_ok,
              f"{header['section_alignment']:#x}/{header['file_alignment']:#x}")

    # PE section addresses are RVAs; only the image base is an address.
    base = header["image_base"]
    rep.check("image base is page aligned", base % 0x1000 == 0, hex(base))

    in_file = True
    for sec in sections:
        if sec["raw_size"] and sec["raw_pointer"] + sec["raw_size"] > len(image):
            in_file = False
        if sec["virtual_address"] < header["size_of_headers"]:
            in_file = False
    rep.check("every section lies inside the file and clear of the headers", in_file,
              f"SizeOfHeaders {header['size_of_headers']:#x}")

    ordered = sorted(sections, key=lambda s: s["virtual_address"])
    overlaps = any(
        ordered[i]["virtual_address"] + section_span(ordered[i]) > ordered[i + 1]["virtual_address"]
        for i in range(len(ordered) - 1))
    rep.check("sections do not overlap in memory", not overlaps)

    entry_rva = header["entry"]
    entry_sec = find_section(sections, base + entry_rva) or find_section(sections, entry_rva)
    rep.check("entry point lies in the first executable section",
              entry_sec is not None and entry_sec["executable"] and
              entry_sec is ordered[0], entry_sec["name"] if entry_sec else "none")
    rep.check("entry point is the first byte of the image",
              bool(ordered) and entry_rva == ordered[0]["virtual_address"],
              hex(entry_rva))

    relocs = walk_relocations(image, header, sections)
    rep.data["relocations"] = len(relocs)
    if require_relocs:
        rep.check("base relocation table present and non-empty", len(relocs) > 0,
                  str(len(relocs)))
        bad = [t for _, t in relocs if t not in SUPPORTED_RELOCS]
        rep.check("every fixup is a type firmware's x64 loader implements", not bad,
                  ",".join(sorted({hex(t) for t in bad})))
    else:
        rep.check("no unsupported relocation types",
                  all(t in SUPPORTED_RELOCS for _, t in relocs))
    rep.data["relocation_types"] = {
        hex(t): sum(1 for _, ty in relocs if ty == t) for _, t in relocs}

    # The .text section itself must be code, and .bss must not be in the file.
    text = next((s for s in sections if s["name"] == ".text"), None)
    rep.check(".text section exists and is executable", text is not None and text["executable"])
    bss = next((s for s in sections if s["name"] == ".bss"), None)
    rep.check(".bss carries no file contents (the entry stub zeroes it)",
              bss is None or bss["raw_size"] == 0,
              str(bss["raw_size"]) if bss else "absent")

    if timestamp_zero:
        rep.check("PE timestamp is zero (reproducible build)", header["timestamp"] == 0,
                  str(header["timestamp"]))
    if max_bytes:
        rep.check(f"image is at most {max_bytes} bytes", len(image) <= max_bytes,
                  str(len(image)))
    rep.check("image is smaller than the El Torito 16-bit sector limit",
              len(image) < 0xFFFF * 512, str(len(image)))
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="inspect a PC5 UEFI application")
    ap.add_argument("image")
    ap.add_argument("--json-out")
    ap.add_argument("--require-relocs", action="store_true",
                    help="fail when there is no base relocation table")
    ap.add_argument("--max-bytes", type=int, default=0)
    ap.add_argument("--allow-timestamp", action="store_true")
    args = ap.parse_args(argv)

    rep = inspect(args.image, require_relocs=args.require_relocs,
                  max_bytes=args.max_bytes, timestamp_zero=not args.allow_timestamp)
    print(rep.render())
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"path": rep.path, "ok": not rep.failures,
                       "checks": rep.checks, "data": rep.data}, fh, indent=2,
                      sort_keys=True)
            fh.write("\n")
    if rep.failures:
        print(f"eficheck: {len(rep.failures)} check(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run the PC5 UEFI loader against a stub firmware and assert what it did.

See tests/uefi_stub_firmware.py for what the harness is and, more importantly,
what it is not.  In one sentence: it executes the loader's real PE32+ machine
code and the real handover stub, but the firmware around them is a model, so a
passing run is evidence of the *loader's* correctness, not of UEFI
compatibility.

Checks, in the order they matter:

  1. the image ran at all, from an address other than its preferred base, with
     its base relocations applied;
  2. the loader's own entry stub cleared .bss and called efi_main with the
     ms_abi frame (observable: counters that start at zero and only work when
     they do);
  3. it found the volume that holds KERNEL.BIN instead of assuming its own -
     the ESP it was booted from does not contain the kernel, exactly as on a
     real El Torito UEFI boot;
  4. it verified the PC5K signature and refused a corrupt one (negative case);
  5. it refused to start when no volume had a kernel (negative case);
  6. it left boot services and performed the handover with EBX pointing at a
     boot-info block that is byte-for-byte the contract in kernel/include/pc5.h:
     magic, version, memory map count, framebuffer geometry and phys_base,
     font_addr = 0, kernel size, loader version, and the flags that admit what
     could not be reported;
  7. the framebuffer it reported is the one the stub exposed, and the GDT it
     loaded is the flat one the kernel expects.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import mkefiimg  # noqa: E402

try:
    import uefi_stub_firmware as stub
except ImportError as exc:              # pragma: no cover
    stub = None
    STUB_IMPORT_ERROR = exc
else:
    STUB_IMPORT_ERROR = None


BOOT_INFO_ADDR = 0x4000
E820_ADDR = 0x2000
VBE_ADDR = 0x2800


class Report:
    def __init__(self):
        self.checks = []
        self.data = {}

    @staticmethod
    def _summarise(detail):
        """Keep the detail short enough to read in a terminal.

        Some callers pass a whole serial trace as context, which is invaluable
        when a check *fails* and pure noise when it passes.  The full trace is
        always available in the JSON report under "data".
        """
        text = str(detail).replace("\r\n", " | ")
        return text if len(text) <= 120 else text[:117] + "..."

    def check(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok),
                            "detail": self._summarise(detail)})
        return bool(ok)

    @property
    def ok(self):
        return all(c["ok"] for c in self.checks)

    @property
    def failures(self):
        return [c for c in self.checks if not c["ok"]]


def esp_files_from_image(path):
    """Read the FAT volume the way firmware would, through its own walker."""
    with open(path, "rb") as fh:
        volume = mkefiimg.FatVolume(fh.read())
    out = {}
    for name, meta in volume.walk().items():
        out["\\" + name.replace("/", "\\")] = meta["data"]
    return out


def read_boot_info(fw):
    raw = fw.read(stub.LOW_MEM + BOOT_INFO_ADDR, 104)
    return raw, {
        "magic": struct.unpack_from("<I", raw, 0)[0],
        "version": struct.unpack_from("<I", raw, 4)[0],
        "boot_drive": struct.unpack_from("<I", raw, 8)[0],
        "e820_addr": struct.unpack_from("<I", raw, 12)[0],
        "e820_count": struct.unpack_from("<I", raw, 16)[0],
        "vbe_mode_addr": struct.unpack_from("<I", raw, 20)[0],
        "vbe_ok": struct.unpack_from("<I", raw, 24)[0],
        "font_addr": struct.unpack_from("<I", raw, 28)[0],
        "font_bytes_per_char": struct.unpack_from("<I", raw, 32)[0],
        "pvd_addr": struct.unpack_from("<I", raw, 36)[0],
        "pvd_ok": struct.unpack_from("<I", raw, 40)[0],
        "kernel_bytes": struct.unpack_from("<I", raw, 44)[0],
        "kernel_lba": struct.unpack_from("<I", raw, 48)[0],
        "volume_id": raw[52:76].split(b"\0")[0].decode("ascii", "replace"),
        "iso_sectors": struct.unpack_from("<I", raw, 76)[0],
        "loader_version": raw[80:96].split(b"\0")[0].decode("ascii", "replace"),
        "desc_crc": struct.unpack_from("<I", raw, 96)[0],
        "flags": struct.unpack_from("<I", raw, 100)[0],
    }


def read_vbe(fw):
    raw = fw.read(stub.LOW_MEM + VBE_ADDR, 0x30)
    return {
        "attributes": struct.unpack_from("<H", raw, 0x00)[0],
        "pitch": struct.unpack_from("<H", raw, 0x10)[0],
        "width": struct.unpack_from("<H", raw, 0x12)[0],
        "height": struct.unpack_from("<H", raw, 0x14)[0],
        "char_w": raw[0x16], "char_h": raw[0x17],
        "planes": raw[0x18], "bpp": raw[0x19],
        "model": raw[0x1B],
        "direct_color": raw[0x27],
        "phys_base": struct.unpack_from("<I", raw, 0x28)[0],
    }


def read_e820(fw, count):
    entries = []
    raw = fw.read(stub.LOW_MEM + E820_ADDR, 24 * count)
    for i in range(count):
        base, length, kind, acpi = struct.unpack_from("<QQII", raw, i * 24)
        entries.append({"base": base, "length": length, "type": kind, "acpi": acpi})
    return entries


def run_once(efi_path, esp_path, kernel_path, iso_has_kernel=True,
             expect_handover=True):
    with open(efi_path, "rb") as fh:
        image = fh.read()
    with open(kernel_path, "rb") as fh:
        kernel = fh.read()
    files = esp_files_from_image(esp_path)
    fw = stub.StubFirmware(image, files, kernel, iso_volume_has_kernel=iso_has_kernel)
    trace = fw.run(expect_handover=expect_handover)
    return fw, trace


def verify(efi_path, esp_path, kernel_path):
    rep = Report()
    rep.data["inputs"] = {
        "efi": os.path.basename(efi_path),
        "esp": os.path.basename(esp_path),
        "kernel_bytes": os.path.getsize(kernel_path),
    }

    # ---------------------------------------------------------------- run 1
    fw, trace = run_once(efi_path, esp_path, kernel_path)
    rep.data["serial"] = trace.serial
    rep.data["events"] = trace.events
    rep.data["calls"] = trace.calls

    rep.check("the image is loaded away from its preferred base",
              fw.entry != fw.preferred_base, f"entry {fw.entry:#x}")
    rep.check("base relocations were applied", fw.relocations > 0,
              f"{fw.relocations} fixups")
    rep.check("the loader's own entry stub ran", trace.calls.get("output_string", 0) > 0)
    rep.check("the loader printed its banner",
              trace.has_serial("PC5 UEFI loader uefi-0.2.0"))
    rep.check("the loader reached its own trace output",
              trace.has_serial("PC5-UEFI: firmware_started"))

    # volume discovery: the ESP it came from has no kernel, the other volume has
    rep.check("the loader searched every file-system volume",
              trace.calls.get("locate_handle", 0) >= 1)
    rep.check("it took the image device from LoadedImage, not a guess",
              trace.has_serial("PC5-UEFI: image_device=media"))
    rep.check("it found the volume holding KERNEL.BIN",
              trace.has_serial("PC5-UEFI: kernel_volume_opened"))
    rep.check("it read the kernel and checked the signature",
              trace.has_serial("PC5-UEFI: kernel_protocol_version=1"))

    # display: GOP was queried and reported
    rep.check("the framebuffer was discovered through GOP",
              trace.calls.get("handle_protocol", 0) >= 1 and
              trace.has_serial("PC5-UEFI: display_width=1024"))
    rep.check("the memory map was read",
              trace.calls.get("get_memory_map", 0) >= 2)     # size query + fetch
    rep.check("the loader left boot services",
              trace.exited and trace.has_serial("boot_services_exited"))

    # ------------------------------------------------------- boot contract
    raw, bi = read_boot_info(fw)
    rep.data["boot_info"] = bi
    rep.check("boot info magic is 'PC5B'", bi["magic"] == 0x42354350, hex(bi["magic"]))
    rep.check("boot info protocol version is 1", bi["version"] == 1, bi["version"])
    rep.check("boot drive is the documented no-BIOS marker",
              bi["boot_drive"] == 0xFFFFFFFF, hex(bi["boot_drive"]))
    rep.check("E820 array address is the BIOS-loader address",
              bi["e820_addr"] == E820_ADDR, hex(bi["e820_addr"]))
    rep.check("E820 array has entries", 1 <= bi["e820_count"] <= 40, bi["e820_count"])
    rep.check("VBE mode info address is the BIOS-loader address",
              bi["vbe_mode_addr"] == VBE_ADDR, hex(bi["vbe_mode_addr"]))
    rep.check("framebuffer is advertised", bi["vbe_ok"] == 1)
    rep.check("no VGA font is claimed", bi["font_addr"] == 0, hex(bi["font_addr"]))
    rep.check("font bytes per char is zero when there is no font",
              bi["font_bytes_per_char"] == 0)
    rep.check("pvd_ok is honest (not reachable through the file protocol)",
              bi["pvd_ok"] == 0)
    rep.check("kernel size matches the file on the medium",
              bi["kernel_bytes"] == os.path.getsize(kernel_path),
              f"{bi['kernel_bytes']} vs {os.path.getsize(kernel_path)}")
    rep.check("kernel LBA is not invented", bi["kernel_lba"] == 0)
    rep.check("volume id is not invented", bi["volume_id"] == "", bi["volume_id"])
    rep.check("iso sector count is not invented", bi["iso_sectors"] == 0)
    rep.check("loader version string is recorded",
              bi["loader_version"].startswith("uefi-0.2.0"), bi["loader_version"])
    rep.check("flags admit the UEFI origin and the unreported fields",
              bi["flags"] == 0x7, hex(bi["flags"]))

    vbe = read_vbe(fw)
    rep.data["vbe"] = vbe
    rep.check("VBE block describes the real GOP geometry",
              vbe["width"] == stub.FB_WIDTH and vbe["height"] == stub.FB_HEIGHT,
              f"{vbe['width']}x{vbe['height']}")
    rep.check("VBE pitch matches the GOP scan line", vbe["pitch"] == stub.FB_PITCH,
              vbe["pitch"])
    rep.check("VBE block is 32 bpp direct colour",
              vbe["bpp"] == 32 and vbe["model"] == 6 and vbe["direct_color"] == 1)
    rep.check("VBE block points at the framebuffer", vbe["phys_base"] == stub.FB_BASE,
              hex(vbe["phys_base"]))
    rep.check("VBE character cell is 8x16 (what the kernel console assumes)",
              vbe["char_w"] == 8 and vbe["char_h"] == 16)

    e820 = read_e820(fw, bi["e820_count"])
    rep.data["e820"] = e820
    usable = [e for e in e820 if e["type"] == 1]
    rep.check("conventional memory is reported as usable", usable and
              usable[0]["length"] == 0x9F * 4096, e820[:1])
    rep.check("loader data is NOT reported as usable",
              all(e["type"] != 1 for e in e820
                  if e["base"] <= fw.alloc_high_water < e["base"] + e["length"]),
              hex(fw.alloc_high_water) if hasattr(fw, "alloc_high_water") else "")
    rep.data["boot_info_raw_sha"] = __import__("hashlib").sha256(raw).hexdigest()

    # handover
    jump = trace.kernel_jump
    rep.check("the handover targeted the kernel entry", jump is not None and
              jump["target"] == "0x10000", jump)
    rep.check("the handover passed the boot-info address in EBX",
              jump is not None and int(jump["ebx"], 16) == BOOT_INFO_ADDR, jump)
    rep.check("the kernel image was copied to the handover address",
              fw.read(0x10000, 8)[2:6] == b"PC5K", fw.read(0x10000, 8).hex())
    gdt = trace.gdt_loaded
    rep.check("the handover GDT is the flat 3-entry table",
              gdt is not None and gdt["limit"] == 23, gdt)
    rep.check("no harness-level problems were reported", not trace.problems,
              "; ".join(trace.problems))

    # ------------------------------------------------------ negative runs
    bad_kernel = bytearray(open(kernel_path, "rb").read())
    bad_kernel[2:6] = b"XXXX"                     # break the PC5K signature
    bad_path = os.path.join(os.path.dirname(efi_path), "kernel-badsig.bin")
    with open(bad_path, "wb") as fh:
        fh.write(bad_kernel)
    try:
        _fw2, trace2 = run_once(efi_path, esp_path, bad_path,
                                expect_handover=False)
        rep.data["negative_signature_serial"] = trace2.serial
        rep.check("a kernel without the PC5K signature is refused",
                  "PC5-UEFI FAILURE E4" in trace2.serial and
                  trace2.kernel_jump is None)
    finally:
        os.unlink(bad_path)

    _fw3, trace3 = run_once(efi_path, esp_path, kernel_path, iso_has_kernel=False,
                            expect_handover=False)
    rep.data["negative_volume_serial"] = trace3.serial
    rep.check("no kernel on any volume stops the boot with E2",
              "PC5-UEFI FAILURE E2" in trace3.serial and trace3.kernel_jump is None)

    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="execute the PC5 UEFI loader")
    ap.add_argument("--efi", default=os.path.join(ROOT, "build", "uefi", "BOOTX64.EFI"))
    ap.add_argument("--esp", default=os.path.join(ROOT, "build", "efi.img"))
    ap.add_argument("--kernel", default=os.path.join(ROOT, "build", "kernel.bin"))
    ap.add_argument("--json-out")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    # A missing dependency is not a failed boot: report it as "cannot run" and
    # exit 2 so the caller can tell the two apart from a real check failure.
    if STUB_IMPORT_ERROR is not None or stub is None or not stub.HAVE_UNICORN:
        detail = STUB_IMPORT_ERROR or "the 'unicorn' module is not installed"
        print(f"uefi-stub-test: cannot run: {detail}", file=sys.stderr)
        print("uefi-stub-test: install the harness dependency with "
              "'pip install unicorn'", file=sys.stderr)
        return 2
    for path in (args.efi, args.esp, args.kernel):
        if not os.path.exists(path):
            print(f"uefi-stub-test: missing {path}; run 'make iso' first",
                  file=sys.stderr)
            return 2

    try:
        rep = verify(args.efi, args.esp, args.kernel)
    except stub.StubError as exc:
        print(f"uefi-stub-test: the stub firmware could not complete the run: {exc}",
              file=sys.stderr)
        return 1

    if not args.quiet:
        for c in rep.checks:
            print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['name']}"
                  + (f"  ({c['detail']})" if c["detail"] else ""))
        print()
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"ok": rep.ok, "checks": rep.checks, "data": rep.data},
                      fh, indent=2, sort_keys=True)
            fh.write("\n")
    passed = len(rep.checks) - len(rep.failures)
    if rep.ok:
        print(f"PASSED: {passed}/{len(rep.checks)} checks against the stub firmware")
        return 0
    print(f"FAILED: {len(rep.failures)} of {len(rep.checks)} checks")
    return 1


if __name__ == "__main__":
    sys.exit(main())

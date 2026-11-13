"""Host tests for the UEFI boot path.

These run on the build machine with no firmware and no emulator, and they
cover everything about the UEFI handover that can be checked that way:

  * tools/mkefiimg.py writes a FAT12/FAT16 image whose directory tree and
    cluster chains read back identically through an independent walk;
  * tools/eficheck.py accepts a real PE32+ EFI application and rejects the
    specific defects that make firmware refuse one (wrong machine, missing
    relocations, a DLL, an entry point outside .text);
  * tools/mkiso.py emits two El Torito sections (BIOS and UEFI), and
    tools/verify_iso.py, which shares no code with the writer, finds the ESP,
    walks its FAT chains and confirms a PE32+ EFI application sits at
    \\EFI\\BOOT\\BOOTX64.EFI;
  * every stub used here is built inside the test, so the tests describe the
    contract rather than depending on whatever ./build happens to contain.
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import eficheck  # noqa: E402
import mkefiimg  # noqa: E402
import mkiso  # noqa: E402
import verify_iso  # noqa: E402

EFI_PAYLOAD = b"MZ" + bytes(0x3A) + struct.pack("<I", 0x80) + b"PE\0\0" + bytes(4096)


# ---------------------------------------------------------------------------
# FAT image builder
# ---------------------------------------------------------------------------
class FatImageTests(unittest.TestCase):
    def build(self, files=None, size_kb=1440):
        builder = mkefiimg.EfiImageBuilder(size_kb=size_kb)
        for path, data in (files or {
            "EFI/BOOT/BOOTX64.EFI": EFI_PAYLOAD,
        }).items():
            builder.add_file(path, data)
        return builder.build()

    def test_image_is_floppy_sized_with_a_valid_boot_sector(self):
        image, info = self.build()
        self.assertEqual(len(image), 1440 * 1024)
        self.assertEqual(image[510:512], b"\x55\xaa")
        self.assertEqual(info["fat_type"], "FAT12")
        geo = mkefiimg.FatVolume(image)
        self.assertEqual(geo.total_sectors, 2880)
        self.assertEqual(geo.fat_bits, 12)
        self.assertEqual(geo.num_fats, 2)
        self.assertEqual(geo.root_entries, 224)

    def test_both_fat_copies_are_identical(self):
        image, info = self.build()
        layout = info["layout"]
        start = layout["reserved_sectors"] * 512
        first = image[start:start + layout["fat_sectors"] * 512]
        second = image[start + layout["fat_sectors"] * 512:
                       start + 2 * layout["fat_sectors"] * 512]
        self.assertEqual(first, second)
        # the media descriptor marker must be present in the first FAT byte
        self.assertEqual(first[0], mkefiimg.MEDIA_DESCRIPTOR)

    def test_directory_tree_round_trips(self):
        payload = bytes(range(256)) * 5          # 1280 bytes -> 3 clusters
        image, _ = self.build({
            "EFI/BOOT/BOOTX64.EFI": EFI_PAYLOAD,
            "EFI/PC5.TXT": payload,
        })
        volume = mkefiimg.FatVolume(image)
        files = volume.walk()
        self.assertEqual(sorted(files), ["EFI/BOOT/BOOTX64.EFI", "EFI/PC5.TXT"])
        self.assertEqual(files["EFI/BOOT/BOOTX64.EFI"]["data"], EFI_PAYLOAD)
        self.assertEqual(files["EFI/PC5.TXT"]["data"], payload)

    def test_subdirectory_has_dot_entries_pointing_at_itself_and_parent(self):
        image, _ = self.build()
        volume = mkefiimg.FatVolume(image)
        root = volume.parse_entries(volume.root_dir_bytes())
        efi = next(e for e in root if e["name"] == "EFI")
        self.assertTrue(efi["dir"])
        entries = {e["name"]: e for e in volume.parse_entries(volume.dir_bytes(efi["cluster"]))}
        self.assertEqual(entries["."]["cluster"], efi["cluster"])
        # the parent of a FAT12/FAT16 root is the reserved value 0
        self.assertEqual(entries[".."]["cluster"], 0)

    def test_volume_label_entry_is_present_and_first(self):
        image, _ = self.build()
        volume = mkefiimg.FatVolume(image)
        root = volume.parse_entries(volume.root_dir_bytes())
        self.assertEqual(root[0]["name"], "PC5EFI")
        self.assertEqual(root[0]["attributes"], mkefiimg.ATTR_VOLUME_ID)

    def test_build_is_deterministic(self):
        a, info_a = self.build()
        b, info_b = self.build()
        self.assertEqual(info_a["sha256"], info_b["sha256"])
        self.assertEqual(a, b)

    def test_source_date_epoch_pins_directory_timestamps(self):
        files = {"EFI/BOOT/BOOTX64.EFI": EFI_PAYLOAD}
        old = os.environ.get("SOURCE_DATE_EPOCH")
        try:
            os.environ["SOURCE_DATE_EPOCH"] = "1600000000"
            first, _ = self.build(files)
            os.environ["SOURCE_DATE_EPOCH"] = "1700000000"
            second, _ = self.build(files)
        finally:
            if old is None:
                os.environ.pop("SOURCE_DATE_EPOCH", None)
            else:
                os.environ["SOURCE_DATE_EPOCH"] = old
        self.assertNotEqual(first, second)

    def test_seventeen_megabyte_image_becomes_fat16(self):
        image, info = self.build({"EFI/BOOT/BOOTX64.EFI": EFI_PAYLOAD}, size_kb=32768)
        self.assertEqual(info["fat_type"], "FAT16")
        volume = mkefiimg.FatVolume(image)
        self.assertEqual(volume.fat_bits, 16)
        self.assertEqual(sorted(volume.walk()), ["EFI/BOOT/BOOTX64.EFI"])

    def test_rejects_names_that_are_not_8_3(self):
        builder = mkefiimg.EfiImageBuilder()
        with self.assertRaises(SystemExit):
            builder.add_file("EFI/BOOT/BOOTX64.EFI", EFI_PAYLOAD)
            builder.add_file("EFI/BOOT/TOOLONGNAME.EFI", EFI_PAYLOAD)
            builder.build()

    def test_rejects_an_image_too_small_for_its_files(self):
        builder = mkefiimg.EfiImageBuilder(size_kb=64)
        builder.add_file("BIG.BIN", bytes(200 * 1024))
        with self.assertRaises(SystemExit):
            builder.build()

    def test_command_line_writes_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "BOOTX64.EFI")
            with open(source, "wb") as fh:
                fh.write(EFI_PAYLOAD)
            out = os.path.join(tmp, "efi.img")
            info_path = os.path.join(tmp, "efi-info.json")
            subprocess.run(
                [sys.executable, os.path.join(ROOT, "tools", "mkefiimg.py"),
                 "--file", f"{source}=EFI/BOOT/BOOTX64.EFI",
                 "--output", out, "--info", info_path],
                check=True, capture_output=True)
            with open(info_path, encoding="utf-8") as fh:
                info = json.load(fh)
            self.assertEqual(info["files"][0]["path"], "EFI/BOOT/BOOTX64.EFI")
            self.assertEqual(info["files"][0]["bytes"], len(EFI_PAYLOAD))
            listing = subprocess.run(
                [sys.executable, os.path.join(ROOT, "tools", "mkefiimg.py"),
                 "--list", out], check=True, capture_output=True, text=True)
            self.assertIn("EFI/BOOT/BOOTX64.EFI", listing.stdout)


# ---------------------------------------------------------------------------
# PE32+ inspection
# ---------------------------------------------------------------------------
def synthetic_pe(machine=0x8664, subsystem=10, magic=0x20B, entry=0x1000,
                 image_base=0x10000000, relocs=True, characteristics=0x0226):
    """Build a minimal PE32+ header block; sections/relocs are added after."""
    dos = bytearray(0x80)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, magic)
    struct.pack_into("<I", opt, 16, entry)
    struct.pack_into("<Q", opt, 24, image_base)
    struct.pack_into("<I", opt, 32, 0x1000)      # section alignment
    struct.pack_into("<I", opt, 36, 0x200)       # file alignment
    struct.pack_into("<I", opt, 56, 0x3000)      # size of image
    struct.pack_into("<I", opt, 60, 0x400)       # size of headers
    struct.pack_into("<H", opt, 68, subsystem)
    struct.pack_into("<I", opt, 108, 16)         # number of directories
    if relocs:
        # the relocation block lives at .text+0x80 (file offset 0x480)
        struct.pack_into("<II", opt, 112 + 5 * 8, 0x1080, 12)
    coff = struct.pack("<HHIIIHH", machine, 2, 0, 0, 0, len(opt), characteristics)
    text = struct.pack("<8sIIIIIIHHI", b".text", 0x100, 0x1000, 0x200, 0x400, 0, 0, 0, 0, 0x60000020)
    bss = struct.pack("<8sIIIIIIHHI", b".bss", 0x100, 0x2000, 0, 0, 0, 0, 0, 0, 0xC0000080)
    image = bytearray(0x800)
    image[0:0x80] = dos
    image[0x80:0x80 + 24] = b"PE\0\0" + coff
    image[0x80 + 24:0x80 + 24 + len(opt)] = opt
    table = 0x80 + 24 + len(opt)
    image[table:table + 40] = text
    image[table + 40:table + 80] = bss
    if relocs:
        # one 4 KB page block holding a single HIGHLOW fixup at .text+0x10
        struct.pack_into("<II", image, 0x480, 0x1000, 12)
        struct.pack_into("<H", image, 0x488, (3 << 12) | 0x10)
        struct.pack_into("<H", image, 0x48A, 0)
    return bytes(image)


class EfiCheckTests(unittest.TestCase):
    def check(self, image, require_relocs=True):
        with tempfile.NamedTemporaryFile(suffix=".efi", delete=False) as fh:
            fh.write(image)
            path = fh.name
        try:
            return eficheck.inspect(path, require_relocs=require_relocs, max_bytes=0)
        finally:
            os.unlink(path)

    def failures(self, rep):
        return [c["name"] for c in rep.failures]

    def test_accepts_a_well_formed_efi_application(self):
        rep = self.check(synthetic_pe())
        self.assertEqual(self.failures(rep), [])

    def test_rejects_the_wrong_machine(self):
        rep = self.check(synthetic_pe(machine=0x014C))
        self.assertIn("machine is x86-64", self.failures(rep))

    def test_rejects_a_console_application_subsystem(self):
        rep = self.check(synthetic_pe(subsystem=3))
        self.assertIn("subsystem is EFI application", self.failures(rep))

    def test_rejects_a_dll(self):
        rep = self.check(synthetic_pe(characteristics=0x2226))
        self.assertIn("image is executable, not a DLL", self.failures(rep))

    def test_rejects_a_32_bit_optional_header(self):
        with self.assertRaises(SystemExit):
            self.check(synthetic_pe(magic=0x10B))

    def test_rejects_a_missing_relocation_table(self):
        rep = self.check(synthetic_pe(relocs=False), require_relocs=True)
        self.assertIn("base relocation table present and non-empty", self.failures(rep))

    def test_reports_the_number_of_fixups(self):
        rep = self.check(synthetic_pe())
        self.assertGreaterEqual(rep.data["relocations"], 1)

    def test_rejects_an_entry_point_outside_the_first_section(self):
        rep = self.check(synthetic_pe(entry=0x2500))
        self.assertIn("entry point lies in the first executable section",
                      self.failures(rep))

    def test_rejects_a_non_zero_timestamp(self):
        image = bytearray(synthetic_pe())
        struct.pack_into("<I", image, 0x80 + 8, 0x5F5E1000)
        rep = self.check(bytes(image))
        self.assertIn("PE timestamp is zero (reproducible build)", self.failures(rep))

    def test_max_bytes_is_enforced(self):
        with tempfile.NamedTemporaryFile(suffix=".efi", delete=False) as fh:
            fh.write(synthetic_pe())
            path = fh.name
        try:
            rep = eficheck.inspect(path, require_relocs=True, max_bytes=16)
            self.assertTrue(any("at most 16 bytes" in c["name"] for c in rep.failures))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# ISO layout with a UEFI section
# ---------------------------------------------------------------------------
class UefiIsoTests(unittest.TestCase):
    def make_boot_image(self):
        image = bytearray(4096)
        image[0:3] = b"\xfa\xeb\xfe"
        image[0xE00:0xE08] = b"PC5BOOT1"
        return bytes(image)

    def build(self, with_uefi=True):
        builder = mkiso.IsoBuilder(volume_id="PC5TEST")
        builder.set_bios_boot_image(self.make_boot_image(), desc_offset=0xE00)
        if with_uefi:
            esp = mkefiimg.EfiImageBuilder()
            esp.add_file("EFI/BOOT/BOOTX64.EFI", synthetic_pe())
            image, _ = esp.build()
            builder.set_uefi_image(image)
        builder.add_file("KERNEL.BIN", b"\xeb\x05PC5K\x01" + bytes(2048))
        return builder.build()

    def verify(self, image):
        with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as fh:
            fh.write(image)
            path = fh.name
        try:
            return verify_iso.verify(path)
        finally:
            os.unlink(path)

    def catalog(self, image, info):
        lba = info["layout"]["boot_catalog_lba"]
        return image[lba * 2048:(lba + 1) * 2048]

    def test_bios_only_image_has_the_default_entry_at_32(self):
        image, info = self.build(with_uefi=False)
        cat = self.catalog(image, info)
        # a BIOS reads offset 32 as the initial entry; there must be no
        # section header in front of it
        self.assertEqual(cat[32], 0x88, "initial entry must be bootable")
        self.assertEqual(cat[33], 0x00, "initial entry must be no-emulation")
        self.assertEqual(cat[64], 0x00, "no UEFI section header in a BIOS image")
        self.assertEqual(info["layout"]["uefi_image_lba"], 0)
        self.assertEqual(info["layout"]["uefi_section_header_offset"], None)

    def test_uefi_section_follows_the_bios_default_entry(self):
        image, info = self.build()
        cat = self.catalog(image, info)
        self.assertEqual(cat[32], 0x88, "BIOS default entry stays at offset 32")
        self.assertEqual(cat[33], 0x00, "no-emulation media type")
        self.assertEqual(cat[64], 0x91, "one final section header at 64")
        self.assertEqual(cat[65], 0xEF, "platform: UEFI")
        self.assertEqual(struct.unpack_from("<H", cat, 66)[0], 1)
        # the UEFI entry follows its header at 96
        self.assertEqual(cat[96], 0x88)
        self.assertEqual(cat[97], 0x00, "no-emulation media type")
        self.assertEqual(struct.unpack_from("<H", cat, 96 + 2)[0], 0)
        self.assertEqual(info["layout"]["uefi_section_header_offset"], 64)
        self.assertEqual(info["layout"]["uefi_entry_offset"], 96)

    def test_uefi_entry_points_at_the_fat_image(self):
        image, info = self.build()
        cat = self.catalog(image, info)
        lba = struct.unpack_from("<I", cat, 96 + 8)[0]
        sectors = struct.unpack_from("<H", cat, 96 + 6)[0]
        self.assertEqual(lba, info["layout"]["uefi_image_lba"])
        self.assertEqual(sectors, 2880)
        self.assertEqual(sectors * 512, info["layout"]["uefi_image_bytes"])
        start = lba * 2048
        self.assertEqual(image[start:start + 2], b"\xeb\x3c")

    def test_verifier_finds_the_esp_and_the_efi_application(self):
        image, _ = self.build()
        rep = self.verify(image)
        self.assertTrue(rep.ok, [c for c in rep.checks if not c["ok"]])
        section_platforms = [sec["platform"] for sec in rep.data["sections"]]
        self.assertEqual(section_platforms, [0x00, 0xEF])
        self.assertEqual(rep.data["uefi_fat"]["fat_bits"], 12)
        self.assertEqual(rep.data["uefi_app"]["bytes"], len(synthetic_pe()))

    def test_verifier_rejects_a_truncated_esp(self):
        image, info = self.build()
        start = info["layout"]["uefi_image_lba"] * 2048
        broken = bytearray(image)
        # wipe the ESP boot sector signature
        broken[start + 510:start + 512] = b"\0\0"
        with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as fh:
            fh.write(bytes(broken))
            path = fh.name
        try:
            rep = verify_iso.verify(path)
        finally:
            os.unlink(path)
        self.assertFalse(rep.ok)
        self.assertIn("UEFI image has a valid FAT boot sector",
                      [c["name"] for c in rep.failures])

    def test_verifier_rejects_a_non_pe_boot_application(self):
        builder = mkiso.IsoBuilder(volume_id="PC5TEST")
        builder.set_bios_boot_image(self.make_boot_image(), desc_offset=0xE00)
        esp = mkefiimg.EfiImageBuilder()
        esp.add_file("EFI/BOOT/BOOTX64.EFI", b"not a pe image" * 100)
        image, _ = esp.build()
        builder.set_uefi_image(image)
        builder.add_file("KERNEL.BIN", b"\xeb\x05PC5K\x01" + bytes(2048))
        iso, _ = builder.build()
        rep = self.verify(iso)
        self.assertFalse(rep.ok)
        self.assertIn("BOOTX64.EFI starts with the DOS 'MZ' signature",
                      [c["name"] for c in rep.failures])

    def test_uefi_layout_is_deterministic(self):
        _, info_a = self.build()
        _, info_b = self.build()
        self.assertEqual(info_a["sha256"], info_b["sha256"])


class UefiSourceContractTests(unittest.TestCase):
    """The loader must not drift away from the kernel's boot contract."""

    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def test_loader_includes_the_kernel_boot_contract(self):
        source = self.read("boot", "uefi", "uefi_main.c")
        self.assertIn('#include "pc5.h"', source)
        self.assertIn("sizeof(struct pc5_boot_info) == 104", source)

    def test_loader_pins_every_offset_the_kernel_reads(self):
        source = self.read("boot", "uefi", "uefi_main.c")
        for field in ("e820_addr", "e820_count", "vbe_mode_addr", "vbe_ok",
                      "font_addr", "pvd_addr", "kernel_bytes", "kernel_lba",
                      "volume_id", "iso_sectors", "loader_version", "flags"):
            self.assertIn(f"offsetof(struct pc5_boot_info, {field})", source,
                          f"{field} offset is not pinned")

    def test_entry_point_geometry_matches_the_bios_loader(self):
        uefi = self.read("boot", "uefi", "uefi_main.c")
        bios = " ".join(self.read("boot", "loader.S").split())
        self.assertIn("#define KERNEL_ADDR 0x10000u", uefi)
        # both loaders must hand the kernel the same low-memory addresses
        for constant in (".set BOOT_INFO, 0x4000", ".set E820_BUF, 0x2000",
                         ".set VBE_MODE, 0x2800", ".set PVD_BUF, 0x3A00",
                         ".set KERNEL_ADDR, 0x10000"):
            self.assertIn(constant, bios)

    def test_loader_reports_no_font_and_no_iso_descriptor(self):
        source = self.read("boot", "uefi", "uefi_main.c")
        self.assertIn("bi->font_addr = 0;", source)
        self.assertIn("bi->pvd_ok = 0;", source)

    def test_entry_stub_uses_the_ms_abi_slot_registers(self):
        stub = self.read("boot", "uefi", "bootx64.S")
        self.assertIn("movq %rcx, %r8", stub)
        self.assertIn("call efi_main", stub)
        self.assertIn("lretq", stub)
        self.assertIn("andl $0x7FFFFFFF, %eax", stub, "paging must be cleared")

    def test_makefile_builds_and_embeds_the_uefi_image(self):
        make = self.read("Makefile")
        self.assertIn("--enable-reloc-section", make)
        self.assertIn("tools/mkefiimg.py", make)
        self.assertIn("--uefi-image $(BUILD)/efi.img", make)
        self.assertIn("tools/eficheck.py", make)


if __name__ == "__main__":
    unittest.main()

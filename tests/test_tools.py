"""Unit tests for the PC5 host tools (no emulator required)."""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import firmware  # noqa: E402
import mkiso  # noqa: E402
import verify_iso  # noqa: E402


class MkIsoTests(unittest.TestCase):
    def make_boot_image(self):
        image = bytearray(4096)
        image[0:3] = b"\xfa\xeb\xfe"
        image[0xE00:0xE08] = b"PC5BOOT1"
        return bytes(image)

    def build(self, files=None):
        builder = mkiso.IsoBuilder(volume_id="PC5TEST")
        builder.set_bios_boot_image(self.make_boot_image(), desc_offset=0xE00)
        for name, data in (files or {"KERNEL.BIN": b"\xeb\x05PC5K\x01" + bytes(2048)}).items():
            builder.add_file(name, data)
        return builder.build()

    def test_layout_is_deterministic(self):
        a, info_a = self.build()
        b, info_b = self.build()
        self.assertEqual(info_a["sha256"], info_b["sha256"])
        self.assertEqual(len(a) % 2048, 0)

    def test_volume_descriptors(self):
        image, info = self.build()
        pvd = image[16 * 2048:17 * 2048]
        self.assertEqual(pvd[0], 1)
        self.assertEqual(pvd[1:6], b"CD001")
        self.assertEqual(pvd[40:72].rstrip(), b"PC5TEST")
        self.assertEqual(struct.unpack_from("<H", pvd, 128)[0], 2048)
        self.assertEqual(struct.unpack_from("<I", pvd, 80)[0], len(image) // 2048)
        brvd = image[17 * 2048:18 * 2048]
        self.assertEqual(brvd[0], 0)
        self.assertEqual(brvd[7:30], b"EL TORITO SPECIFICATION")

    def test_boot_catalog_checksum(self):
        image, info = self.build()
        lba = info["layout"]["boot_catalog_lba"]
        cat = image[lba * 2048:(lba + 1) * 2048]
        self.assertEqual(cat[0], 0x01)
        self.assertEqual(cat[30:32], b"\x55\xaa")
        self.assertEqual(sum(struct.unpack("<16H", cat[0:32])) % 0x10000, 0)
        # the virtual sector count must be in 512-byte units
        self.assertEqual(struct.unpack_from("<H", cat, 38)[0], 8)

    def test_boot_descriptor_is_patched(self):
        image, info = self.build()
        lba = info["layout"]["bios_boot_image_lba"]
        desc = image[lba * 2048 + 0xE00: lba * 2048 + 0xE00 + 64]
        self.assertEqual(desc[0:8], b"PC5BOOT1")
        self.assertEqual(struct.unpack_from("<I", desc, 8)[0], info["kernel"]["lba"])
        self.assertEqual(struct.unpack_from("<I", desc, 12)[0], info["kernel"]["bytes"])
        self.assertEqual(struct.unpack_from("<I", desc, 60)[0], zlib.crc32(desc[0:60]) & 0xFFFFFFFF)

    def test_verifier_accepts_good_image(self):
        image, info = self.build()
        with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as img:
            img.write(image)
            path = img.name
        try:
            rep = verify_iso.verify(path)
            self.assertTrue(rep.ok, [c for c in rep.checks if not c["ok"]])
        finally:
            os.unlink(path)

    def test_verifier_rejects_broken_catalog(self):
        image, info = self.build()
        image = bytearray(image)
        lba = info["layout"]["boot_catalog_lba"]
        image[lba * 2048 + 30] ^= 0xFF  # corrupt the 55AA signature
        with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as img:
            img.write(image)
            path = img.name
        try:
            rep = verify_iso.verify(path)
            self.assertFalse(rep.ok)
        finally:
            os.unlink(path)


class FirmwareToolTests(unittest.TestCase):
    def analyze_bytes(self, data):
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(data)
            path = fh.name
        try:
            return firmware.analyze(path)
        finally:
            os.unlink(path)

    def test_identifies_slb2_container(self):
        data = b"SLB2" + bytes(60) + b"\x00PS5UPDATE1.PUP\x00" + bytes(4096)
        report = self.analyze_bytes(data)
        self.assertIn("SLB2", report["kind"])
        self.assertTrue(any("PS5UPDATE1.PUP" in f["detail"] for f in report["findings"]))
        self.assertEqual(len(report["sha256"]), 64)

    def test_identifies_finalised_package(self):
        data = bytearray(0x2000)
        data[0:4] = b"\x7fFIH"
        struct.pack_into("<Q", data, 0x10, 0x10000)
        report = self.analyze_bytes(bytes(data))
        self.assertIn("FIH", report["kind"])
        self.assertTrue(any("PFS image offset" == f["probe"] for f in report["findings"]))

    def test_unidentified_is_reported_honestly(self):
        report = self.analyze_bytes(b"not a firmware at all" * 100)
        self.assertEqual(report["kind"], "unidentified")
        self.assertTrue(report["notes"])

    def test_manifest_round_trip(self):
        data = b"SLB2" + bytes(4096)
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(data)
            fw_path = fh.name
        manifest_path = tempfile.mktemp(suffix=".json")
        c_path = tempfile.mktemp(suffix=".c")
        try:
            report = firmware.analyze(fw_path)
            firmware.write_manifest(report, manifest_path)
            with open(manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
            self.assertEqual(manifest["schema"], "pc5.firmware-manifest/1")
            firmware.manifest_to_c(manifest, c_path)
            with open(c_path, encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("pc5_fw_manifest", src)
            self.assertIn(report["sha256"][:16], src)
        finally:
            for p in (fw_path, manifest_path, c_path):
                if os.path.exists(p):
                    os.unlink(p)


class KernelUnitTests(unittest.TestCase):
    def test_kernel_unit_binary(self):
        out = os.path.join(tempfile.gettempdir(), "pc5-kunit")
        cc = os.environ.get("CC", "gcc")
        cmd = [cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter",
               "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-DPC5_HOST_TEST",
               "-I", os.path.join(ROOT, "kernel", "include"), "-o", out,
               os.path.join(ROOT, "tests", "kernel_unit.c"),
               os.path.join(ROOT, "kernel", "lib.c"),
               os.path.join(ROOT, "kernel", "mem.c"),
               os.path.join(ROOT, "kernel", "chain.c")]
        build = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stderr[-2000:])
        run = subprocess.run([out], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class BuiltImageTests(unittest.TestCase):
    """Only runs when build/pc5.iso exists."""

    def test_built_iso_verifies(self):
        iso = os.path.join(ROOT, "build", "pc5.iso")
        info = os.path.join(ROOT, "build", "build-info.json")
        if not os.path.exists(iso):
            self.skipTest("build/pc5.iso not built")
        rep = verify_iso.verify(iso, info if os.path.exists(info) else None)
        self.assertTrue(rep.ok, [c for c in rep.checks if not c["ok"]])
        with open(info, encoding="utf-8") as fh:
            build_info = json.load(fh)
        self.assertEqual(build_info["sha256"], rep.data["sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

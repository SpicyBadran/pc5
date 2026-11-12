#!/usr/bin/env python3
"""PC5 emulated boot test.

Boots the built ISO in the v86 x86 emulator (SeaBIOS firmware, emulated CD-ROM
with El Torito) and asserts what the machine actually did:

  * the loader ran, read the ISO volume descriptor and verified the kernel
  * the 32-bit kernel started and completed its boot log
  * every interface page renders (asserted from the console shadow buffer,
    dumped over the serial console, so the check covers the rendered UI)
  * the compatibility chain reports the genuine-PS5 stages as not started

This proves the image boots on an emulated PC.  It does not prove physical
hardware support: see docs/TESTING_STRATEGY.md for the evidence levels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "tests", "v86_runner.mjs")

V86_CANDIDATES = [
    os.environ.get("V86_ASSETS"),
    os.path.join(ROOT, "node_modules", "v86-system", "assets"),
    "/home/user/work/v86/node_modules/v86-system/assets",
]


def find_v86():
    for path in V86_CANDIDATES:
        if path and os.path.exists(os.path.join(path, "libv86.mjs")):
            return path
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Result:
    def __init__(self):
        self.checks = []

    def check(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        return ok

    @property
    def ok(self):
        return all(c["ok"] for c in self.checks)


def run_vm(iso, seconds, serial_out, screen_out=None, keys=None):
    cmd = ["node", RUNNER, "--cdrom", iso, "--seconds", str(seconds),
           "--serial-out", serial_out, "--mem", "128M"]
    if screen_out:
        cmd += ["--screen-out", screen_out]
    if keys:
        cmd += ["--keys", keys]
    env = dict(os.environ)
    assets = find_v86()
    if assets:
        env["V86_ASSETS"] = assets
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=seconds + 60)
    return proc


def screen_dump(serial_text):
    """Extract the last complete screen dump from a serial log."""
    begin = "pc5 screen dump begin"
    end = "pc5 screen dump end"
    blocks = []
    pos = 0
    while True:
        i = serial_text.find(begin, pos)
        if i < 0:
            break
        j = serial_text.find(end, i)
        if j < 0:
            break
        block = serial_text[i + len(begin):j].replace("\r", "")
        blocks.append(block.lstrip("\n"))
        pos = j + len(end)
    return blocks


def main(argv=None):
    ap = argparse.ArgumentParser(description="PC5 emulated boot test")
    ap.add_argument("--iso", default=os.path.join(ROOT, "build", "pc5.iso"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "build", "test"))
    ap.add_argument("--seconds", type=int, default=14)
    ap.add_argument("--json-out", default=os.path.join(ROOT, "build", "test", "boot-evidence.json"))
    args = ap.parse_args(argv)

    res = Result()
    if not os.path.exists(args.iso):
        print(f"missing image: {args.iso} (run 'make iso')")
        return 2
    if not shutil.which("node") or not find_v86():
        print("SKIP: node or the v86 emulator assets are not available")
        print("      install with: npm install v86-system")
        return 77
    os.makedirs(args.out_dir, exist_ok=True)

    image_sha = sha256(args.iso)
    serial_path = os.path.join(args.out_dir, "serial.log")
    proc = run_vm(args.iso, args.seconds, serial_path)
    with open(serial_path, "r", errors="replace") as fh:
        serial = fh.read()

    res.check("emulator produced a serial log", len(serial) > 0, f"{len(serial)} bytes")
    for marker, label in [
        ("PC5 loader", "loader banner on serial"),
        ("pc5: medium is ISO9660", "loader read the ISO9660 volume descriptor"),
        ("pc5: kernel image verified", "loader loaded and verified the kernel image"),
        ("pc5: entering 32-bit kernel", "protected-mode handoff"),
        ("PC5 KERNEL", "32-bit kernel started"),
        ("PC5-BOOT-OK", "kernel reached the end of its boot log"),
    ]:
        res.check(label, marker in serial, marker)

    res.check("genuine PS5 software is not claimed as running",
              "genuine_ps5_execution=no" in serial)
    res.check("kernel mounted the ISO9660 volume through its own block driver",
              "PC5-LOG storage_mounted volume=PC5" in serial)
    res.check("kernel read a file back from the medium with a valid signature",
              "signature=ok" in serial)
    res.check("chain reports a blocked stage with evidence",
              "chain_blocked_at=" in serial and "chain_blocked_evidence=" in serial)

    # ---- interface pages, dumped from the console shadow buffer ----
    keys = ",".join([
        "serial:screen\\r", "wait:1",
        "serial:page 2\\r", "wait:1", "serial:screen\\r", "wait:1",
        "serial:page 3\\r", "wait:1", "serial:screen\\r", "wait:1",
        "serial:page 4\\r", "wait:1", "serial:screen\\r", "wait:1",
        "serial:page 5\\r", "wait:1", "serial:screen\\r", "wait:1",
        "serial:page 6\\r", "wait:1", "serial:screen\\r", "wait:1",
    ])
    ui_serial = os.path.join(args.out_dir, "serial-ui.log")
    run_vm(args.iso, max(args.seconds, 18), ui_serial, keys=keys)
    with open(ui_serial, "r", errors="replace") as fh:
        ui_log = fh.read()
    dumps = screen_dump(ui_log)
    res.check("console shadow buffer dumped over serial", len(dumps) >= 4,
              f"{len(dumps)} dumps")
    joined = "\n".join(dumps)
    with open(os.path.join(args.out_dir, "screens.txt"), "w", encoding="utf-8") as fh:
        for i, dump in enumerate(dumps):
            fh.write(f"===== screen {i} =====\n{dump}\n")

    for needle, label in [
        ("PS5 COMPATIBILITY CHAIN", "status page renders the compatibility chain"),
        ("PC5 boot environment executing", "status page lists stage 1"),
        ("Genuine PS5 home screen", "status page lists the genuine home-screen stage"),
        ("NOT-STARTED", "status page shows not-started stages"),
        ("HARDWARE INVENTORY", "hardware page renders"),
        ("PCI", "hardware page reports PCI inventory"),
        ("PS5 FIRMWARE STATUS", "firmware page renders"),
        ("not executing", "firmware page states the truth about execution"),
        ("SELF-TESTS", "diagnostics page renders"),
        ("ISO9660 mounted in kernel", "diagnostics page reports the kernel storage self-test"),
        ("volume 'PC5'", "storage stage evidence names the mounted volume"),
        ("BOOT LOG", "log page renders"),
        ("POWER AND RECOVERY", "power page renders"),
    ]:
        res.check(label, needle in joined, needle)

    evidence = {
        "image": os.path.abspath(args.iso),
        "image_sha256": image_sha,
        "emulator": "v86 (SeaBIOS, emulated CD-ROM, El Torito no-emulation)",
        "checks": res.checks,
        "serial_log": serial_path,
        "screens_dump": os.path.join(args.out_dir, "screens.txt"),
        "levels_proven": [
            "ISO generated",
            "ISO integrity verified by tools/verify_iso.py (run 'make verify')",
            "ISO boots in an emulated x86 PC",
            "PC5 boot environment runs and reports the compatibility chain",
        ],
        "levels_not_proven": [
            "physical hardware boot",
            "controller, network and audio on physical hardware",
            "genuine PS5 system software execution",
            "actual PS5 game execution",
        ],
    }
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2)
        fh.write("\n")

    print()
    print(f"{'PASSED' if res.ok else 'FAILED'}: boot evidence written to {args.json_out}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""pc5ctl — the PC5 command line.

  pc5ctl info   [--iso build/pc5.iso]        build and image summary
  pc5ctl verify [--iso build/pc5.iso]        structural verification
  pc5ctl boot   [--iso build/pc5.iso]        run the emulator boot test
  pc5ctl chain  --log FILE                   compatibility chain from a boot log
  pc5ctl fw     analyze --input IMAGE        firmware analysis (no decryption)
  pc5ctl usb    --device /dev/sdX --iso ...  write the image to a USB stick

`usb` refuses to touch a device without --yes, refuses the device that holds
the running root filesystem, and re-verifies the image checksum first.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ISO = os.path.join(ROOT, "build", "pc5.iso")
DEFAULT_INFO = os.path.join(ROOT, "build", "build-info.json")


def load_info(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError:
        return {}


def cmd_info(args):
    info = load_info(args.info)
    if not info:
        print("no build info: run 'make iso' first")
        return 1
    print(f"image        {info['iso_bytes']} bytes ({info['iso_sectors']} blocks)")
    print(f"sha256       {info['sha256']}")
    print(f"volume id    {info['volume_id']}")
    layout = info["layout"]
    print(f"boot image   LBA {layout['bios_boot_image_lba']} "
          f"({layout['bios_boot_image_bytes']} bytes, "
          f"{layout['bios_boot_virtual_sectors']} virtual sectors)")
    print(f"kernel       LBA {info['kernel']['lba']} ({info['kernel']['bytes']} bytes)")
    for f in info["files"]:
        print(f"file         {f['identifier']} LBA {f['lba']} {f['bytes']} bytes")
    return 0


def cmd_verify(args):
    cmd = [sys.executable, os.path.join(ROOT, "tools", "verify_iso.py"), args.iso]
    if os.path.exists(args.info):
        cmd += ["--info", args.info]
    return subprocess.call(cmd)


def cmd_boot(args):
    cmd = [sys.executable, os.path.join(ROOT, "tests", "boot_test.py"), "--iso", args.iso]
    return subprocess.call(cmd)


def cmd_chain(args):
    try:
        with open(args.log, "r", encoding="utf-8", errors="replace") as fh:
            log = fh.read()
    except OSError as exc:
        print(f"cannot read log: {exc}")
        return 1
    stages = []
    for line in log.replace("\r", "\n").split("\n"):
        line = line.strip()
        if line.startswith("chain "):
            parts = line.split(None, 3)
            if len(parts) >= 4:
                stages.append((parts[1], parts[2], parts[3]))
    if not stages:
        print("no chain lines in this log (boot the PC5 ISO first)")
        return 1
    print(f"{'#':>3}  {'STATE':<12} STAGE")
    for num, state, name in stages:
        print(f"{num:>3}  {state:<12} {name}")
    blocked = [s for s in stages if s[1] == "BLOCKED"]
    if blocked:
        print(f"\nfirst blocked stage: {blocked[0][0]} ({blocked[0][2]})")
    print("\nPS5 system software execution: NOT RUNNING (see chain above)")
    return 0


def cmd_fw(args):
    cmd = [sys.executable, os.path.join(ROOT, "tools", "firmware.py")] + args.rest
    return subprocess.call(cmd)


def find_root_device():
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) > 1 and parts[1] == "/":
                    return parts[0]
    except OSError:
        pass
    return ""


def cmd_usb(args):
    iso = args.iso
    if not os.path.exists(iso):
        print(f"no image at {iso}")
        return 1
    sha_file = iso + ".sha256"
    expected = None
    if os.path.exists(sha_file):
        with open(sha_file, "r", encoding="ascii") as fh:
            expected = fh.read().split()[0]
    import hashlib
    h = hashlib.sha256()
    with open(iso, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    actual = h.hexdigest()
    print(f"image    {iso}")
    print(f"sha256   {actual}")
    if expected and actual != expected:
        print("checksum mismatch against the .sha256 file: refusing to write")
        return 1
    device = args.device
    if not device.startswith("/dev/"):
        print("device must be a block device path such as /dev/sdX")
        return 1
    if not os.path.exists(device):
        print(f"device {device} does not exist")
        return 1
    root = find_root_device()
    if root and os.path.realpath(device) == os.path.realpath(root.rstrip("0123456789")):
        print(f"refusing to overwrite {device}: it holds the running root filesystem")
        return 1
    print(f"target   {device}")
    print("\nTHIS ERASES EVERYTHING ON THE TARGET DEVICE.")
    if not args.yes:
        print("re-run with --yes to confirm after checking the device path")
        return 2
    dd = shutil.which("dd")
    if not dd:
        print("dd not found")
        return 1
    return subprocess.call([dd, f"if={iso}", f"of={device}", "bs=4M", "status=progress", "conv=fsync"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pc5ctl", description="PC5 control tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info")
    p.add_argument("--info", default=DEFAULT_INFO)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("verify")
    p.add_argument("--iso", default=DEFAULT_ISO)
    p.add_argument("--info", default=DEFAULT_INFO)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("boot")
    p.add_argument("--iso", default=DEFAULT_ISO)
    p.set_defaults(func=cmd_boot)

    p = sub.add_parser("chain")
    p.add_argument("--log", required=True)
    p.set_defaults(func=cmd_chain)

    p = sub.add_parser("fw")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_fw)

    p = sub.add_parser("usb")
    p.add_argument("--iso", default=DEFAULT_ISO)
    p.add_argument("--device", required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_usb)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

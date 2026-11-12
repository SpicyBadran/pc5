#!/usr/bin/env python3
"""PC5 firmware analysis tool.

What this does
--------------
PC5 never bundles Sony firmware.  The owner of an image runs this tool on it
locally; the tool produces *evidence* — container identification, structural
probes, hashes and an entropy profile — and a manifest that the PC5 build can
embed so the boot environment can report which image was analysed.

What this does not do
---------------------
It does not decrypt firmware, extract keys, patch signatures, or bypass any
authentication or DRM.  Structurally identifying a container is legitimate
interoperability research; circumventing its protection is not, and the tool
refuses to pretend it did something it cannot.

Container signatures implemented here are the ones that are documented in
public research (see docs/FIRMWARE_ANALYSIS.md for citations):

    SLB2   outer PlayStation update container ("SLB2" at offset 0)
    FIH    finalised package image     (0x7F 'F' 'I' 'H', little endian)
    CNT    package metadata container  (0x7F 'C' 'N' 'T', big endian)
    ELF    ELF executable / shared object
    SELF   signed ELF container used by PlayStation systems
    PKG    generic PlayStation package

Anything the tool cannot identify is reported as unidentified.  That is a
result, not a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys

TOOL_VERSION = "0.1.0"


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def entropy(data):
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    total = len(data)
    e = 0.0
    for c in counts:
        if c:
            p = c / total
            e -= p * math.log2(p)
    return round(e, 3)


def printable_strings(data, minimum=6, limit=24):
    out = []
    current = bytearray()
    for b in data:
        if 32 <= b < 127:
            current.append(b)
        else:
            if len(current) >= minimum:
                out.append(current.decode("ascii"))
                if len(out) >= limit:
                    return out
            current.clear()
    if len(current) >= minimum and len(out) < limit:
        out.append(current.decode("ascii"))
    return out


def identify(header: bytes, data_prefix: bytes):
    """Identify the container from its documented signature."""
    if header.startswith(b"SLB2"):
        return "ps5-update-container (SLB2)", "Outer PlayStation update container."
    if len(header) >= 4 and header[0] == 0x7F and header[1:4] == b"FIH":
        return "ps5-pkg-finalised (FIH)", "Finalised PS5 package image; PFS image at 0x10000."
    if len(header) >= 4 and header[0] == 0x7F and header[1:4] == b"CNT":
        return "ps5-pkg-metadata (CNT)", "PS5 package metadata container."
    if header.startswith(b"\x7fELF"):
        return "elf", "ELF image (unencrypted)."
    if header.startswith(b"NPXS") or header[4:8] == b"NPXS":
        return "self (signed elf)", "Signed ELF container; segments are encrypted in retail images."
    if header.startswith(b"PKG"):
        return "pkg", "Package container."
    if header.startswith(b"PK\x03\x04"):
        return "zip", "ZIP archive (not a PlayStation container)."
    if len(data_prefix) > 0x60 and data_prefix[0:4] == b"PS5U":
        return "ps5update", "File names itself as a PS5 update."
    return "unidentified", "No documented signature matched."


def analyze(path):
    result = {
        "tool": f"pc5-firmware {TOOL_VERSION}",
        "path": os.path.abspath(path),
        "size_bytes": os.path.getsize(path),
        "sha256": sha256_file(path),
        "findings": [],
        "notes": [],
    }
    with open(path, "rb") as fh:
        head = fh.read(0x2000)
        fh.seek(0)
        size = result["size_bytes"]
        # entropy profile in 1 MiB windows, capped to 64 windows
        windows = []
        limit = min(size, 64 << 20)
        read = 0
        while read < limit:
            block = fh.read(1 << 20)
            if not block:
                break
            windows.append(entropy(block))
            read += len(block)
    kind, explanation = identify(head[:8], head)
    result["kind"] = kind
    result["kind_note"] = explanation
    result["header_hex"] = head[:64].hex()
    result["entropy_windows"] = windows
    result["entropy_mean"] = round(sum(windows) / len(windows), 3) if windows else 0.0
    result["strings"] = printable_strings(head, minimum=6, limit=16)

    # structural probes -------------------------------------------------
    if kind.startswith("ps5-update-container"):
        result["findings"].append({
            "probe": "SLB2 container",
            "detail": "Outer update container. Public research reports a plaintext "
                      "header followed by signed/encrypted entries; entry layout is "
                      "version specific and is not asserted here.",
            "confidence": "confirmed-signature",
        })
        for name in result["strings"]:
            if name.upper().endswith(".PUP"):
                result["findings"].append({
                    "probe": "embedded entry name",
                    "detail": name,
                    "confidence": "confirmed-string",
                })
    if kind.startswith("ps5-pkg"):
        if len(head) >= 0x20:
            pfs_offset = struct.unpack_from("<Q", head, 0x10)[0] if head[1:4] == b"FIH" else None
            if pfs_offset is not None:
                result["findings"].append({
                    "probe": "PFS image offset",
                    "detail": f"0x{pfs_offset:x}",
                    "confidence": "public-research",
                })
        result["notes"].append(
            "The PFS image is AES-XTS encrypted; PC5 does not decrypt it."
        )
    if kind == "unidentified":
        result["notes"].append(
            "Unidentified container. This is a legitimate outcome: record the hash and "
            "the first bytes, then investigate rather than guess."
        )
    result["encrypted_likely"] = result["entropy_mean"] > 7.5
    if result["encrypted_likely"]:
        result["notes"].append(
            "Mean entropy above 7.5 bits/byte: the payload looks compressed or encrypted, "
            "so structural parsing without keys is not possible."
        )
    return result


def write_manifest(report, path):
    manifest = {
        "schema": "pc5.firmware-manifest/1",
        "tool": report["tool"],
        "image": {
            "sha256": report["sha256"],
            "size_bytes": report["size_bytes"],
            "kind": report["kind"],
        },
        "entropy_mean": report["entropy_mean"],
        "findings": report["findings"],
        "analysed_utc": os.environ.get("SOURCE_DATE_EPOCH", "unstamped"),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


def manifest_to_c(manifest, out_path):
    """Embed a short summary in the kernel, never the firmware itself."""
    image = manifest.get("image", {})
    summary = (
        f"analysed image sha256={image.get('sha256', '?')[:16]} "
        f"size={image.get('size_bytes', 0)} kind={image.get('kind', '?')}; "
        f"payload is not distributed with PC5 and is not executable by this build"
    )
    summary = summary.replace('"', "'")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("/* generated by tools/firmware.py - do not edit */\n")
        fh.write('#include "pc5.h"\n\n')
        fh.write(f'const char *pc5_fw_manifest = "{summary}";\n')
        fh.write(f'const int pc5_fw_manifest_size = {len(summary)};\n')
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="PC5 firmware analysis (no decryption)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="identify and hash a firmware image")
    a.add_argument("--input", required=True)
    a.add_argument("--json-out")
    a.add_argument("--manifest-out")

    m = sub.add_parser("manifest", help="render a manifest as a kernel C source")
    m.add_argument("--input", required=True)
    m.add_argument("--c-output", required=True)

    sub.add_parser("plan", help="print the user-supplied firmware workflow")

    args = ap.parse_args(argv)

    if args.cmd == "analyze":
        report = analyze(args.input)
        print(f"image      {report['path']}")
        print(f"size       {report['size_bytes']} bytes")
        print(f"sha256     {report['sha256']}")
        print(f"kind       {report['kind']} - {report['kind_note']}")
        print(f"entropy    mean {report['entropy_mean']} over {len(report['entropy_windows'])} MiB windows")
        for f in report["findings"]:
            print(f"finding    {f['probe']}: {f['detail']} [{f['confidence']}]")
        for n in report["notes"]:
            print(f"note       {n}")
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
                fh.write("\n")
        if args.manifest_out:
            write_manifest(report, args.manifest_out)
            print(f"manifest   {args.manifest_out}")
        return 0

    if args.cmd == "manifest":
        with open(args.input, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("schema") != "pc5.firmware-manifest/1":
            data = {"image": data.get("image", {}), "findings": data.get("findings", [])}
        summary = manifest_to_c(data, args.c_output)
        print(f"pc5: embedded manifest: {summary}")
        return 0

    if args.cmd == "plan":
        print(
            "PC5 does not ship PlayStation firmware. To use your own image:\n"
            "  1. keep the original file outside this repository (it is not redistributable)\n"
            "  2. python3 tools/firmware.py analyze --input /path/PS5UPDATE.PUP \\\n"
            "         --json-out /tmp/fw-report.json --manifest-out firmware/manifest.json\n"
            "  3. firmware/manifest.json is embedded into the next build and shown on the\n"
            "     Firmware page of the boot environment\n"
            "  4. the firmware itself is never copied into build/ or the ISO\n"
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

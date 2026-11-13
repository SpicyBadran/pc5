#!/usr/bin/env python3
"""Attach build provenance to a PC5 build record.

`tools/mkiso.py` writes the structural record of an image (layout, per-file
hashes, image hash).  This tool appends a `build` object describing *how* that
image was produced and *what was verified*, without touching the image itself:

    python3 tools/buildmeta.py --iso build/pc5.iso --info build/build-info.json \
        --version 0.2.0 --commit "$GITHUB_SHA" --build-id "$GITHUB_SHA" \
        --source-date-epoch 1700000000 --verify-report build/verify-report.json \
        --boot-evidence build/test/boot-evidence.json \
        --unit-log build/logs/unit.log --host-log build/logs/host.log \
        --ci-provider github --ci-workflow build.yml --ci-run-id 123 --ci-run-url <url>

Design rules
------------
* Nothing is invented: every field is either measured here, read from a file
  produced by a build step, or passed in by the caller.  Unavailable values are
  written as null (or omitted) rather than guessed.
* The tool never modifies the ISO, so provenance never affects reproducibility.
* Existing top-level keys written by mkiso.py are preserved (verify_iso.py
  cross-checks them), the new information goes under "build".

Exit codes: 0 on success, 2 on bad input, 3 when a report says verification
failed (so a pipeline cannot publish a failing build by accident).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys

SCHEMA = "pc5.build-metadata/1"

UNIT_RE = re.compile(r"(PASSED|FAILED):\s*(\d+)\s+checks,\s*(\d+)\s+failures")
HOST_RE = re.compile(r"Ran\s+(\d+)\s+tests?")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def first_line(args: list[str]) -> str | None:
    """First line of a command's stdout, or None when it is not installed."""
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip()
    return text.splitlines()[0].strip() if text else None


def toolchain() -> dict:
    uname = platform.uname()
    return {
        "cc": first_line(["gcc", "--version"]),
        "ld": first_line(["ld", "--version"]),
        "as": first_line(["as", "--version"]),
        "make": first_line(["make", "--version"]),
        "python": sys.version.split()[0],
        "node": first_line(["node", "--version"]),
        "os": f"{uname.system} {uname.release} {uname.machine}",
    }


def read_json(path: str | None) -> dict | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def summarise_checks(name: str, checks: list, source: str | None) -> dict:
    failures = [c for c in checks if not c.get("ok")]
    return {
        "name": name,
        "checks": len(checks),
        "failures": len(failures),
        "failed": [c.get("name") for c in failures][:20],
        "source": os.path.basename(source) if source else None,
    }


def summarise_log(name: str, path: str | None, regex: re.Pattern) -> dict | None:
    if not path or not os.path.exists(path):
        return None
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    m = regex.search(text)
    entry: dict = {"name": name, "source": os.path.basename(path), "sha256": sha256_file(path)}
    if name == "kernel_unit":
        entry.update(
            {
                "checks": int(m.group(2)) if m else None,
                "failures": int(m.group(3)) if m else None,
                "verdict": (m.group(1).lower() if m else "unknown"),
            }
        )
    else:
        entry.update(
            {
                "tests": int(m.group(1)) if m else None,
                "verdict": "ok" if re.search(r"^OK\b", text, re.M) else "unknown",
            }
        )
    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="add build provenance to build-info.json")
    ap.add_argument("--info", required=True, help="build-info.json written by mkiso.py")
    ap.add_argument("--iso", help="the image the record describes (hash is re-checked)")
    ap.add_argument("--out", help="write here instead of updating --info in place")
    ap.add_argument("--version", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--commit", default=None)
    ap.add_argument("--build-id", default=None)
    ap.add_argument("--source-date-epoch", default=None)
    ap.add_argument("--build-date", default=None)
    ap.add_argument("--verify-report", help="JSON from verify_iso.py --json-out")
    ap.add_argument("--boot-evidence", help="JSON from tests/boot_test.py")
    ap.add_argument("--unit-log", help="captured output of `make unit`")
    ap.add_argument("--host-log", help="captured output of the python test suite")
    ap.add_argument("--ci-provider", default=os.environ.get("PC5_CI_PROVIDER"))
    ap.add_argument("--ci-workflow", default=os.environ.get("PC5_CI_WORKFLOW"))
    ap.add_argument("--ci-run-id", default=os.environ.get("PC5_CI_RUN_ID"))
    ap.add_argument("--ci-run-url", default=os.environ.get("PC5_CI_RUN_URL"))
    args = ap.parse_args(argv)

    try:
        info = read_json(args.info)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"buildmeta: cannot read {args.info}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(info, dict) or "sha256" not in info:
        print(f"buildmeta: {args.info} is not a PC5 build record", file=sys.stderr)
        return 2

    artifact = {
        "name": os.path.basename(args.iso) if args.iso else "pc5.iso",
        "bytes": info.get("iso_bytes"),
        "sectors": info.get("iso_sectors"),
        "sha256": info.get("sha256"),
        "sha256_rechecked": None,
    }
    if args.iso:
        if not os.path.exists(args.iso):
            print(f"buildmeta: image not found: {args.iso}", file=sys.stderr)
            return 2
        actual = sha256_file(args.iso)
        artifact["sha256_rechecked"] = actual
        if actual != info.get("sha256"):
            print(
                f"buildmeta: image sha256 {actual} does not match the build record "
                f"{info.get('sha256')}",
                file=sys.stderr,
            )
            return 3
        artifact["bytes"] = os.path.getsize(args.iso)

    verification = []
    verify_report = None
    try:
        verify_report = read_json(args.verify_report)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"buildmeta: cannot read verify report: {exc}", file=sys.stderr)
        return 2
    if verify_report and isinstance(verify_report.get("checks"), list):
        verification.append(
            summarise_checks("iso_structure", verify_report["checks"], args.verify_report)
        )

    try:
        boot = read_json(args.boot_evidence)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"buildmeta: cannot read boot evidence: {exc}", file=sys.stderr)
        return 2
    if boot and isinstance(boot.get("checks"), list):
        verification.append(
            summarise_checks("emulated_boot", boot["checks"], args.boot_evidence)
        )

    for entry in (
        summarise_log("kernel_unit", args.unit_log, UNIT_RE),
        summarise_log("host_tests", args.host_log, HOST_RE),
    ):
        if entry:
            verification.append(entry)

    failed = [v for v in verification if (v.get("failures") or 0) > 0]
    metadata = {
        "schema": SCHEMA,
        "product": "PC5",
        "version": args.version,
        "tag": args.tag,
        "commit": args.commit,
        "build_id": args.build_id,
        "source_date_epoch": int(args.source_date_epoch)
        if args.source_date_epoch and args.source_date_epoch.isdigit()
        else None,
        "build_date": args.build_date,
        "architecture": {
            "kernel": "i386 (32-bit protected mode, freestanding)",
            "host": platform.machine(),
        },
        "toolchain": toolchain(),
        "artifact": artifact,
        "verification": {
            "checks": verification,
            "failed": len(failed),
            "verdict": "PASS" if verification and not failed else ("FAIL" if failed else "NOT RUN"),
        },
        "ci": {
            "provider": args.ci_provider,
            "workflow": args.ci_workflow,
            "run_id": args.ci_run_id,
            "run_url": args.ci_run_url,
        },
    }

    info["build"] = metadata
    target = args.out or args.info
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(
        f"buildmeta: {target}: version={args.version} tag={args.tag} "
        f"sha256={info['sha256'][:16]}… checks={len(verification)} "
        f"verdict={metadata['verification']['verdict']}"
    )
    if metadata["verification"]["verdict"] == "FAIL":
        for v in failed:
            print(
                f"buildmeta: FAILED {v['name']}: {v.get('failures')} failure(s) "
                f"{(v.get('failed') or '')[:5]}",
                file=sys.stderr,
            )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

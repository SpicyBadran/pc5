#!/usr/bin/env python3
"""Render the GitHub release notes for a PC5 build record.

Input: `build-info.json` (schema pc5.build-metadata/1, written by
`make release-assets`).  Output: markdown on stdout.

Everything printed here is read from the record, so the notes cannot claim a
test that did not run: a missing report prints "not run" instead of a number.
"""

from __future__ import annotations

import argparse
import json
import sys


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def counts(build: dict) -> dict:
    verification = build.get("verification", {})
    return {c.get("name"): c for c in verification.get("checks", [])}


def render(info: dict) -> str:
    build = info.get("build", {})
    artifact = build.get("artifact", {})
    checks = counts(build)
    version = build.get("version") or "unknown"
    lines: list[str] = []

    def n(name: str, key: str = "checks") -> str:
        entry = checks.get(name)
        if not entry:
            return "not run"
        value = entry.get(key)
        failures = entry.get("failures")
        if value is None:
            return "not run"
        if failures:
            return f"{value} ({failures} failed)"
        return f"{value} (0 failures)"

    lines.append(f"PC5 {version} — boot environment, built and tested by CI.")
    lines.append("")
    lines.append(
        "Every asset below comes from the pipeline run that built this tag "
        f"from commit `{build.get('commit')}`."
    )
    lines.append("")
    lines.append(f"- image: `{artifact.get('name', 'pc5.iso')}` — "
                 f"{artifact.get('bytes')} bytes, {artifact.get('sectors')} sectors")
    lines.append(f"- sha256: `{artifact.get('sha256')}`")
    epoch = build.get("source_date_epoch")
    lines.append(
        f"- build id `{build.get('build_id')}`, SOURCE_DATE_EPOCH `{epoch}` "
        "(the commit timestamp), so the image is byte-reproducible"
    )
    toolchain = build.get("toolchain", {})
    if toolchain.get("cc"):
        lines.append(f"- toolchain: {toolchain.get('cc')}; {toolchain.get('os')}")
    lines.append("")
    lines.append("**What CI executed for this build**")
    lines.append("")
    lines.append(f"- ISO structure and checksums: {n('iso_structure')} checks")
    lines.append(f"- emulated boot (v86/SeaBIOS): {n('emulated_boot')} checks")
    lines.append(f"- kernel unit tests: {n('kernel_unit')} checks")
    lines.append(f"- host tool tests: {n('host_tests', 'tests')} tests")
    verdict = build.get("verification", {}).get("verdict", "NOT RUN")
    lines.append(f"- verification verdict recorded in `build-info.json`: **{verdict}**")
    lines.append("")
    lines.append("**What this image does not do**")
    lines.append("")
    lines.append(
        "It does not run genuine PS5 system software, does not run PS5 games, and "
        "has no UEFI boot path, USB, network, audio or installer yet. The 13-stage "
        "compatibility chain inside the image names the current blocker; "
        "`docs/PS5_COMPATIBILITY_STATUS.md` records the evidence."
    )
    lines.append("")
    lines.append("**Verify it yourself**")
    lines.append("")
    lines.append("```sh")
    lines.append("sha256sum -c pc5.iso.sha256")
    lines.append("python3 tools/verify_iso.py pc5.iso --info build-info.json")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="render release notes from build-info.json")
    ap.add_argument("--info", required=True)
    ap.add_argument("--out", help="write to this path instead of stdout")
    args = ap.parse_args(argv)
    try:
        text = render(load(args.info))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"release-notes: cannot read {args.info}: {exc}", file=sys.stderr)
        return 2
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"release-notes: wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

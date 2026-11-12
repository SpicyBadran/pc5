# Security

## 1. Position

PC5 is an interoperability project. It does not break copy protection, does not
distribute Sony firmware or keys, and does not implement mechanisms to bypass
authentication, signature checks, DRM or secure boot. Where a capability cannot
be built legitimately, PC5 records the limitation instead of working around it.

Concretely, PC5 will not:

* include, embed or redistribute Sony firmware images, decryption keys, or
  derived binaries,
* patch signature checks in firmware, packages or executables,
* spoof a console identity to reach PlayStation Network or any other Sony
  service,
* claim a compatibility level it has not measured.

`tools/firmware.py` identifies containers and computes hashes. It contains no
decryption code and refuses to describe encrypted payloads as parsed.

## 2. Trust boundaries in the current build

| Component | Runs as | Trust |
|---|---|---|
| `boot/loader.S` | firmware-loaded real-mode code | trusted; 4 KiB, single file, auditable |
| kernel | ring 0, no paging, no user mode | trusted; no external input except keyboard/serial |
| serial console | operator | unauthenticated by design — physical access is required |
| host tools | user's account | `pc5ctl usb` re-verifies the checksum and refuses `/` |
| ISO contents | read-only medium | verified structurally by `make verify` |

There is no network stack, no user mode and no persistent storage yet, so the
attack surface is the firmware handoff, the serial console and the build tools.

## 3. Boot integrity

* The loader verifies a kernel signature (`PC5K`) before jumping.
* The boot descriptor carries a CRC32 over its own fields; the kernel reports it
  on the Diagnostics page and the verifier recomputes it from the image.
* `build-info.json` records SHA-256 per file; `make verify` re-checks the bytes.

These detect corruption and mistakes. They are **not** a signature chain: there
is no signing key and no Secure Boot integration yet, and the CRC32 is not a
security primitive.

## 4. Firmware handling policy

1. Firmware is never committed (`.gitignore` excludes `firmware/`).
2. A user's image is analysed locally; only a short summary string is compiled
   into a build.
3. Logs never contain firmware bytes, only hashes and container identifiers.
4. The public repository and its releases contain no restricted material, so
   the ISO is redistributable.

## 5. USB writing safety

`pc5ctl usb` requires: an existing block device path, a matching checksum, an
explicit `--yes`, and refuses the device that backs `/`. It prints the target
before writing. `dd` is invoked with `conv=fsync`.

## 6. Planned security work

| Item | Status |
|---|---|
| Signed PC5 updates (Ed25519 manifest + signature) | RESEARCH REQUIRED |
| Signing key management and offline signing | RESEARCH REQUIRED |
| Secure Boot shim / enrolment instructions | RESEARCH REQUIRED |
| Cryptographic boot chain (loader → kernel) | RESEARCH REQUIRED |
| Service isolation (needs user mode and a real kernel) | BLOCKED on ADR-003 exit |
| Audit logging of privileged actions | IN PROGRESS (boot log exists) |

## 7. Reporting a security issue

Open a private security advisory on the repository rather than a public issue.
Do not attach firmware images, keys or dumps of proprietary code.

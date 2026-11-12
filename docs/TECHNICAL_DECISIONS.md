# Technical decisions

Each record states the problem, the alternatives that were considered, the
evidence, the choice, and what would reverse it.

## ADR-001 — Write the ISO9660/El Torito writer in-tree

* **Problem**: the deliverable must be a reproducible `build/pc5.iso`.
* **Alternatives**: `xorriso`, `genisoimage`, `mkisofs` (all absent and not
  installable here); downloading a prebuilt boot toolchain (release assets are
  unreachable from this environment).
* **Evidence**: `which xorriso genisoimage mkisofs` → not found; GitHub release
  downloads resolve to a host that is blocked, while `codeload` (source
  archives) works.
* **Decision**: implement ISO9660 + El Torito in `tools/mkiso.py`, and verify it
  with a *separate* parser (`tools/verify_iso.py`) so a bug cannot validate
  itself.
* **Reversal**: if a build host has `xorriso`, the writer can be swapped for it
  behind the same `make iso` target; the boot descriptor patching would move to
  a post-processing step.

## ADR-002 — BIOS path first, UEFI second

* **Problem**: modern machines boot UEFI; the reference laptop can do both.
* **Alternatives**: UEFI-first (PE32+ application + FAT ESP inside the ISO) or
  BIOS-first (El Torito no-emulation image).
* **Evidence**: the only executable test vehicle available is v86 with SeaBIOS,
  which implements BIOS/El Torito and *not* UEFI. Writing a UEFI application
  here would produce code that could not be executed once.
* **Decision**: build and prove the BIOS path now (it is fully tested), keep
  `tools/mkiso.py` capable of emitting a second El Torito entry for the UEFI
  platform (already implemented in the writer), and treat the UEFI loader as
  the next milestone with an explicit test requirement.
* **Consequence**: a UEFI-only machine cannot boot PC5 yet. This is stated in
  `docs/KNOWN_LIMITATIONS.md` and on the project README.

## ADR-003 — A dedicated 32-bit kernel instead of a Linux distribution

* **Problem**: the boot environment needs a console, hardware inventory and a
  diagnostics shell.
* **Alternatives**: (a) boot a Linux kernel + initramfs, (b) boot a
  microkernel/POSIX layer, (c) write a small freestanding kernel.
* **Evidence**: no Linux kernel source or binary was obtainable in this
  environment (no apt, no kernel.org, no release assets); no 32-bit libc headers
  either. A freestanding kernel needs only `gcc` and `binutils`.
* **Decision**: (c) for the bring-up environment. It is not a substitute for the
  final runtime: a Linux foundation remains the plan for the *compatibility*
  stage because it brings drivers (NVMe, USB, Wi-Fi, GPU) that cannot reasonably
  be rewritten. The bring-up kernel and the future Linux runtime share the boot
  contract and the chain reporting.
* **Reversal**: as soon as a build host can install `linux-image-*` and
  `debootstrap`, PC5 gains a Linux runtime path; the loader already reads
  multi-megabyte images (limit 572 KiB today, raised by switching the loader to
  unreal-mode high loads).

## ADR-004 — Separate the firmware-boot path from the execution path

* **Problem**: there are two very different ways to run PS5 software: booting
  Sony's system software, or executing PS5 binaries natively after relinking
  (the AnyPS5 approach).
* **Alternatives**: pretend they are the same problem; pick one and ignore the
  other.
* **Evidence**: AnyPS5's own architecture document shows it is a static
  relinker that never runs firmware; public research shows PS5 system software
  is signed and bound to the SoC. No public path exists from generic x86
  hardware to genuine PS5 system-software execution.
* **Decision**: model both explicitly. The compatibility chain (13 stages) is
  the firmware path; `docs/GAMING_COMPATIBILITY.md` requires PS5 titles to be
  executed through a documented mechanism and tested, never inferred from a
  library listing. Neither path may be reported as the other.
* **Consequence**: the project can make real progress on the execution path
  (relinking, PRX shims) without ever claiming the firmware stage.

## ADR-005 — Report the chain from measurements, not from a status file

* **Problem**: it is easy to write "PS5 compatible" in a README and impossible
  to disprove from the outside.
* **Decision**: the chain is computed at boot from the machine in front of you
  (`chain_evaluate()`), each stage carries an evidence string that names the
  measurement, and the UI refuses to colour a stage green without it. The
  serial log prints the same lines (`PC5-LOG chain_blocked_at=…`) so a log file
  is enough to audit a boot.
* **Test**: `tests/kernel_unit.c` asserts that the firmware-execution stages are
  never `OK` even when a firmware *manifest* is present.

## ADR-006 — Emulated boot tests are necessary but not sufficient

* **Problem**: no physical hardware is attached to this build environment.
* **Decision**: v86 boot tests prove "the ISO boots on an x86 PC with SeaBIOS".
  They do not prove driver behaviour on real chipsets, real USB controllers,
  real UEFI firmware or real timing. `docs/TESTING_STRATEGY.md` therefore keeps
  sixteen separate evidence levels and `docs/TEST_RESULTS.md` records which
  ones are currently proven.

## ADR-007 — No Sony firmware, keys or firmware-derived binaries in the repository

* **Problem**: firmware is a central research input, but redistribution is not
  permitted and the repository is public.
* **Decision**: the repository carries a *workflow* (`tools/firmware.py`) and a
  manifest, never the image. `.gitignore` excludes `firmware/`. The kernel only
  ever receives a short text summary of the analysis.
* **Test**: `tests/test_tools.py` checks the manifest round-trip and that only a
  summary string is emitted into C.

## ADR-008 — Keep the boot image under 600 KiB (load window)

* **Problem**: a real-mode loader can only read into conventional memory
  without unreal-mode tricks.
* **Decision**: kernel + assets must stay under `0x8F000 - 0x10000` (572 KiB);
  the Makefile fails the build if it grows past that, and the loader fails with
  a diagnostic code if the image would cross the limit. Measured today: 31 KB.
* **Reversal**: implement unreal-mode high loading (already scoped in
  `docs/ROADMAP.md`) when a Linux payload needs it.

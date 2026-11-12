# Project audit — what existed before any work started

Date of audit: 2026-11-12. Branch: `arena/2290edbd-pc5`, base commit `9576ad7`.

## 1. The repository as received

`git log --oneline` at the base commit contained exactly one commit
("Add files via upload") and one file:

```
AnyPS5-main (1).zip     19,749,977 bytes
```

There was no build system, no source tree, no documentation, no ISO, no tests,
no firmware image and no CI. Anything described elsewhere in this repository as
working today was built during this work; nothing was inherited except the
AnyPS5 source archive, which is an *input* to the audit, not a PC5 component.

Checks performed:

| Check | Result |
|---|---|
| `git log` | 1 commit, no history to build on |
| tracked files | 1 (zip) |
| build system | none |
| tests | none |
| ISO/boot artifacts | none |
| Sony firmware in repository | **absent** (only the AnyPS5 zip was supplied) |
| third-party binaries in repository | none |

Consequence: the firmware workstream that Part 3 of the project directive
describes cannot start from a supplied image. The firmware pathway is therefore
implemented as a *user-supplied* workflow (`tools/firmware.py`) and the boot
environment reports "no firmware image supplied" instead of pretending.
See `docs/FIRMWARE_ANALYSIS.md`.

## 2. Development environment actually available

The work was carried out on a sandboxed Debian 12 x86-64 host. What that meant
for the design:

| Resource | State | Effect on the project |
|---|---|---|
| `gcc` 12.2.0, `binutils` 2.40 (x86-64 + i386 + PE emulations), `make`, `python3` 3, `node` 22 | available | native toolchain for the kernel, loader and host tools |
| 32-bit libc headers | **absent** | kernel is fully freestanding; host unit tests build 64-bit with `PC5_HOST_TEST` |
| `xorriso`, `genisoimage`, `mtools`, `mkfs.vfat` | **absent** | `tools/mkiso.py` implements ISO9660 + El Torito directly |
| `qemu-system-x86_64`, OVMF, KVM | **absent** (`/dev/kvm` missing) | boot tests run on the v86 emulator instead; UEFI boot cannot be executed here |
| `apt` repositories | unreachable (only `github.com`, `codeload.github.com`, `api.github.com`, npm and PyPI are reachable) | no Linux kernel or distro packages could be installed |
| release-asset downloads from GitHub (`objects.githubusercontent.com`) | blocked | no prebuilt bootloader (limine/GRUB) could be fetched; hence the hand-written loader |
| Internet | partial | used only to study public documentation, cited in the research log |

Verified with:

```
$ which qemu-system-x86_64 xorriso mformat mkfs.vfat debootstrap
(none found)
$ ls /dev/kvm
ls: cannot access '/dev/kvm': No such file or directory
```

This is why the first bootable artifact is a BIOS-path image with a
hand-written loader and a hand-written ISO writer, rather than a bootable Linux
distribution. It is a constraint of the environment, not a design preference;
`docs/TECHNICAL_DECISIONS.md` records the decision and the exit condition.

## 3. AnyPS5 inspection (the supplied archive)

Source: <https://github.com/boykopovar/AnyPS5>, archive supplied as
`AnyPS5-main (1).zip` in the repository root. Licence: **GPL-2.0-only**
(`LICENSE` is the GPLv2 text). Not affiliated with Sony.

### What it actually implements

AnyPS5 is a **static relinker**, not an emulator and not a firmware loader. Its
own `docs/dev/ARCHITECTURE.md` states it plainly: "How a PS5 executable becomes
a native Linux or Windows program. Nothing is emulated: the converted
executable runs as a normal process and calls native implementations of the
system libraries."

Pipeline, as implemented in `core/relinker`:

1. read a PS5 ELF executable and its bundled `sce_module/*` modules,
2. resolve imports by NID (the numeric symbol id PlayStation binaries use),
3. lower AMD-only instructions for Intel hosts (`--to-intel` codegen),
4. build a SysV/PE dynamic section and patch the image (`LinuxElfPatcher`,
   `WindowsPePatcher`), renaming exports to their NIDs (`nid_patcher`),
5. link against `core/libs/prx/*` — independently written implementations of the
   system PRX libraries.

### Measured size and completeness

Measurements taken from the supplied archive:

| Metric | Value |
|---|---|
| C/C++ lines under `core/` | 478,791 |
| PRX library projects in `core/libs/prx/` | 411 |
| `APS5_EXPORT("…")` NID declarations | 5,167 |
| files under `core/libs/prx` containing a bare `return 0;` stub | 1,686 |
| `TODO` / `UNIMPLEMENTED` / `not implemented` markers under `core/` | 857 |
| build system | CMake ≥ 3.20, C++ with MinGW/GCC/Clang; `3rdparty/` are git submodules |
| buildable here | **no** — no `cmake`/`ninja` in the sandbox, and the submodules are not vendored |

Its own `docs/dev/TechnicalDebt.md` documents silent stubs per library,
"unknown signature" exports and untested paths, which matches the stub counts
above. The project publishes per-title bring-up threads rather than a
compatibility list, and it does not claim complete game compatibility.

### What it requires

* a *decrypted, unpacked* PS5 executable (SELF containers must be unwrapped
  first; the tool refuses containers whose segments look encrypted),
* the title's own `sce_module/` modules,
* a host with the project's built `libs/*.prx`,
* a game the project's library set already covers.

### Can PC5 reuse it?

Yes, under the GPL, and it is the most credible *execution* route that exists
for PS5 game binaries. But note what it is not: it cannot boot PS5 system
software and does not attempt to. Executing a PS5 *game* through AnyPS5 means
running a relinked user-space program on a host OS — which is why the PC5
architecture keeps two separate paths (see decision ADR-004). The supplied
archive is studied rather than vendored: `tools/fetch_anyps5.sh` obtains the
sources reproducibly when a host has the build prerequisites.

### Limitations that block the PC5 objective

1. No firmware execution path at all: PS5 system software never runs.
2. Requires decrypted binaries — the SYSCON/secure-loader chain is not touched.
3. GPU work is limited to shader recompilation; there is no full GPU command
   translation for PS5 titles.
4. Cannot be built in this environment, so it cannot be tested here either.

## 4. Other projects and sources consulted

* psdevwiki PS5 pages (package/file formats) — <https://www.psdevwiki.com/ps5/>
* LibProsperoPKG package-format notes — <https://github.com/SvenGDK/LibProsperoPKG>
* Sony's own system-software update instructions (PUP naming and USB layout) —
  <https://www.playstation.com/en-us/support/hardware/ps5/system-software/>
* v86 (x86 emulator used for boot tests) — <https://github.com/copy/v86>

## 5. Audit conclusions that shaped the build

1. Nothing existed; the first deliverable had to be a real bootable artifact.
2. No firmware was supplied, and none may be redistributed → the firmware
   workstream is a documented, user-driven analysis path, and the boot
   environment must state the truth on screen.
3. No virtual machine or UEFI firmware was available → build the bootloader and
   ISO writer in-tree; test on the only emulator that is reachable (v86).
4. AnyPS5 is an execution-layer asset for game binaries, not a boot solution →
   PC5 keeps a firmware/software-boot path and an execution-layer path separate,
   and reports them separately in the compatibility chain.

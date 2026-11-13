# Test results

Recorded on 2026-11-13. Build under test: PC5 `0.2.0`, source commit `719432c`
plus the uncommitted UEFI milestone work (branch `arena/42c51afe-pc5`).
Sections 1–6 describe the BIOS-only medium as of `5ab7c48`; section 7 covers the
UEFI boot path added on top of it and is the only section that mentions it.
Host: Debian 12 x86-64, gcc 12.2.0, binutils 2.40, make 4.3, python 3.11.2,
node 22.22.3, v86 (npm `v86-system` 0.5.0) for the emulated boot test.

Every number below was produced by the command quoted next to it, in this
session, on this source tree.

## 1. Artifact

```
$ export BUILD_ID=$(git rev-parse HEAD)
$ export SOURCE_DATE_EPOCH=$(git log -1 --format=%ct HEAD)
$ make clean && make iso
pc5: loader image 4096 bytes
pc5: kernel image 36508 bytes (limit 585728)
pc5: wrote build/pc5.iso (96256 bytes, 47 sectors)
pc5: sha256 0644cf66faf77cba1034123ac22a6451de340c1ba2bffc0b484bcc6a05e7837f
```

| Property | Value |
|---|---|
| path | `build/pc5.iso` |
| size | 96,256 bytes (47 × 2048) |
| SHA-256 | `0644cf66faf77cba1034123ac22a6451de340c1ba2bffc0b484bcc6a05e7837f` |
| inputs | `BUILD_ID=5ab7c48…`, `SOURCE_DATE_EPOCH=1794561088` (commit time) |
| loader image | 4,096 bytes (8 El Torito virtual sectors) |
| kernel image | 36,508 bytes, `PC5K` signature, loaded at `0x10000` |
| volume id | `PC5` |
| side files | `build/pc5.iso.sha256`, `build/build-info.json`, `build/verify-report.json` |

The digest embeds the commit id and the build timestamp, so a rebuild from a
different commit is a different — equally valid — image. Pin both inputs
(`docs/BUILDING.md`) to reproduce this exact file.

## 2. Structural verification — `make verify`

```
$ make verify
VALID: build/pc5.iso  sha256=0644cf66faf77cba1034123ac22a6451de340c1ba2bffc0b484bcc6a05e7837f
```

32 checks, 0 failures, written to `build/verify-report.json` as well. Selected
lines:

```
[PASS] image is a whole number of 2048-byte blocks  (96256 bytes)
[PASS] volume descriptor signature at LBA 16  (CD001)
[PASS] logical block size is 2048  (2048)
[PASS] volume size matches the file  (47 blocks)
[PASS] El Torito system identifier  (EL TORITO SPECIFICATION)
[PASS] catalog validation checksum sums to zero  (0x0)
[PASS] default entry is bootable  (0x88)
[PASS] default entry is no-emulation  (0)
[PASS] boot image load segment is 0x7C0  (0x7c0)
[PASS] boot image advertises at least one sector  (8)
[PASS] boot descriptor CRC32 is valid
[PASS] descriptor kernel size matches the directory record  (36508 vs 36508)
[PASS] image SHA-256 matches build info
```

## 3. Unit tests — `make check`

```
$ make unit
PASSED: 35 checks, 0 failures

$ python3 -m unittest discover -s tests -p 'test_*.py'
Ran 32 tests in 1.721s
OK
```

The host suite grew from 13 to 32 tests in this milestone:

| Class | Tests | What it covers |
|---|---|---|
| `MkIsoTests` | 10 | extent layout, volume descriptors, catalog checksum, descriptor patching, `SOURCE_DATE_EPOCH` determinism |
| `FirmwareToolTests` | 4 | container identification, honest "unidentified", manifest → C |
| `KernelUnitTests` | 1 | builds and runs the kernel unit binary |
| `BuiltImageTests` | 1 | the real `build/pc5.iso` verifies and matches its record |
| `BuildMetaTests` | 3 | provenance written, hash re-checked, refusal on mismatch or failing report |
| `WorkflowTests` | 7 | actions pinned to SHAs, no `pull_request_target`, one write job, tag-only publishing, delegated publish script, no secrets, reproducibility gate |
| `ReleaseNotesTests` | 2 | release notes state measured numbers, never invent one |
| `PublishScriptTests` | 4 | publish script against a stub `gh`: three assets, idempotent re-run, verdict gate, checksum gate |
| `CiLayoutTests` | 2 | the pipeline file exists and the activation note explains where it lives |

Bugs these tests caught during development:

| Bug | Caught by | Fix |
|---|---|---|
| ATAPI IDENTIFY result discarded because a packet device answers with ERR set | serial log showed `storage drives=0` although the CD was present | wait for BSY only; treat ERR + signature as "ATAPI present" |
| ATA data register accessed as two byte reads/writes | PVD read back as garbage (`storage_mounted=no error=-2`) | added `inw`/`outw`; the data port is 16-bit |
| Loader advanced the sector address by bytes instead of disk units | first kernel image over 32 KiB hung the boot | `read_lba` advances in disk units |
| ISO volume/directory timestamps came from the wall clock | two `SOURCE_DATE_EPOCH` builds had different digests | stamps come from `SOURCE_DATE_EPOCH`; test added |
| Workflow test asserted on a literal that also appeared in a comment | test failed on the workflow itself | assert on parsed permission lines |

## 4. Emulated boot — `make boot-test`

```
$ make boot-test
PASSED: boot evidence written to build/test/boot-evidence.json
```

25 checks, 0 failures (list in `build/test/boot-evidence.json`), covering the
loader markers, the protected-mode handoff, `PC5-BOOT-OK`, the honest chain
report, the kernel's own ATAPI/ISO9660 read-back, and the six rendered pages
dumped from the console shadow buffer.

Serial excerpt (SeaBIOS, 128 MiB, emulated CD-ROM):

```
PC5 loader 0.2.0
pc5: framebuffer 1600x0900
pc5: medium is ISO9660, disk unit bytes 0800
pc5: kernel image verified
pc5: medium volume PC5
pc5: entering 32-bit kernel

PC5 KERNEL 0.2.0 (build …)
PC5-LOG storage drives=1 selected=0 atapi=1 model=v86 ATAPI CD-ROM
PC5-LOG storage_mounted volume=PC5 blocks=47 file=KERNEL.BIN bytes=36508 signature=ok
PC5-LOG chain_blocked_at=5 stage=PS5 firmware image supplied
PC5-LOG genuine_ps5_execution=no
PC5-BOOT-OK
```

## 5. Reproducibility

```
$ export BUILD_ID=$(git rev-parse HEAD) SOURCE_DATE_EPOCH=$(git log -1 --format=%ct HEAD)
$ make clean && make iso && sha256sum build/pc5.iso
0644cf66faf77cba1034123ac22a6451de340c1ba2bffc0b484bcc6a05e7837f  build/pc5.iso
$ make clean && make iso && sha256sum build/pc5.iso
0644cf66faf77cba1034123ac22a6451de340c1ba2bffc0b484bcc6a05e7837f  build/pc5.iso
```

Identical. The CI pipeline repeats this check and fails the job if the two
digests differ.

## 6. Release pipeline

| Level | State |
|---|---|
| Workflow YAML parses and every `run:` step passes `bash -n` | VERIFIED locally (13 steps, 2 embedded python blocks compile) |
| Pipeline steps executed locally in order | VERIFIED — two identical images, all suites green, assets staged |
| Publish script logic (checksum gate, verdict gate, create-then-update, `--clobber`, asset assertion) | VERIFIED against a stub `gh` (`tests/test_release.py`) |
| Workflow executed by GitHub Actions | **NOT VERIFIED** — the file cannot be pushed: the GitHub App token lacks the *workflows* permission |
| Release created by CI, three assets uploaded | **NOT VERIFIED** |
| Assets downloaded and checksum verified | **NOT VERIFIED** |

Stage assets locally with:

```
$ make release-assets TAG=v0.2.0
pc5: release assets staged in build/release
0644cf66…  pc5.iso   pc5.iso.sha256   build-info.json
```

`build-info.json` then carries the `build` object (schema
`pc5.build-metadata/1`): version `0.2.0`, tag, commit, build id,
`SOURCE_DATE_EPOCH`, toolchain, the artifact hash re-computed from the file, and
each test result with the SHA-256 of the log it came from.

## 7. UEFI boot path — IMPLEMENTED, UNTESTED

Added on branch `arena/42c51afe-pc5` (base `main` `719432c`). Everything below
was produced by the command quoted next to it on this tree.

```
$ export BUILD_ID=719432cea7d1ebe7c748efefcac1cdfa6962439e
$ export SOURCE_DATE_EPOCH=1794561355
$ make clean && make iso
pc5: kernel image 36636 bytes (limit 585728)
22/22 checks passed                       <- tools/eficheck.py on BOOTX64.EFI
pc5: wrote build/efi.img (FAT12, 1474560 bytes, 22/2847 clusters used)
pc5: wrote build/pc5.iso (1570816 bytes, 767 sectors)
pc5: sha256 b66296c99abf30470a4fc2eb39777daeac174c2931e486e82aa8631965c10143

$ sha256sum build/uefi/BOOTX64.EFI build/efi.img build/pc5.iso
d941abdbb475e008c7706a6bb3c056985685ad00700a01d43054bf61e43e6b1c  build/uefi/BOOTX64.EFI
01e3004b1a5317e93a54d256da21a0dea9d52f63002ef289f20377b40734aaf5  build/efi.img
b66296c99abf30470a4fc2eb39777daeac174c2931e486e82aa8631965c10143  build/pc5.iso
```

Both builds were repeated from `make clean` with the same inputs and all three
digests were identical, so the UEFI path is as reproducible as the BIOS path.

| Artifact | Size | Checks |
|---|---|---|
| `build/uefi/BOOTX64.EFI` | 9,771 bytes | 22/22 (`tools/eficheck.py --require-relocs --max-bytes 196608`) |
| `build/efi.img` | 1,474,560 bytes (FAT12, 2,880 sectors) | read back with `tools/mkefiimg.py --list` |
| `build/pc5.iso` | 1,570,816 bytes (767 sectors) | 53/53 (`make verify`) |

The ISO grew from 96,256 to 1,570,816 bytes because it now carries the 1.44 MB
ESP. Selected verifier lines that only exist because of this milestone:

```
[PASS] catalog has an initial entry
[PASS] initial entry is the 80x86 BIOS default  (0x0)
[PASS] the last section header is 0x91 (no further sections)  (145)
[PASS] no duplicate platform sections  ({0: 1, 239: 1})
[PASS] UEFI section entry is bootable  (0x88)
[PASS] UEFI section entry is no-emulation  (0)
[PASS] UEFI entry loads at segment 0  (0x0)
[PASS] UEFI image lies inside the ISO  (LBA 26 +2880 sectors)
[PASS] UEFI image has a valid FAT boot sector
[PASS] UEFI image is FAT12 or FAT16 (El Torito bootable form)  (2847 clusters -> FAT12)
[PASS] ESP root directory contains EFI/
[PASS] ESP contains EFI/BOOT
[PASS] ESP contains EFI/BOOT/BOOTX64.EFI
[PASS] BOOTX64.EFI content is readable through the FAT chain  (9771 bytes)
[PASS] BOOTX64.EFI machine is x86-64  (0x8664)
[PASS] BOOTX64.EFI is PE32+  (0x20b)
[PASS] BOOTX64.EFI subsystem is EFI application  (10)
```

Host suite: `python3 -m unittest discover -s tests -p 'test_*.py'` → **Ran 66
tests, OK** (was 32). The new `tests/test_uefi.py` holds the 34 new tests:
`FatImageTests` (12), `EfiCheckTests` (10), `UefiIsoTests` (7) and
`UefiSourceContractTests` (5). Kernel unit tests are unchanged at 35 checks, and
`make boot-test` still passes **25/25** on the BIOS path with the UEFI-capable
ISO, which is the regression test that matters here.

Bug this milestone started with, caught by the emulator rather than by review:

| Bug | Caught by | Fix |
|---|---|---|
| A 0x90 section header written in front of the BIOS default entry | `make boot-test` produced a 0-byte serial log: SeaBIOS reads catalog offset 32 as an entry, saw 0x90, and refused the medium | default entry back at +32, UEFI section header at +64, entry at +96; the verifier and tests now pin that layout |

**What is not established:** the UEFI loader has never executed. No OVMF image,
no QEMU and no UEFI-capable virtual machine were obtainable in this environment
(`command -v qemu-system-x86_64` → not found; no `/usr/share/OVMF`), so the
loader is built, inspected field by field, and structurally verified inside the
finished ISO — nothing more. The label is therefore **IMPLEMENTED — UNTESTED**,
and it stays that way until a boot in real or emulated UEFI firmware is recorded
here with its serial log.

## 7. What these results do and do not establish

Established: the image is a valid, reproducible ISO9660/El Torito medium; it
boots on an emulated PC; the kernel runs, inventories the machine, mounts its own
medium through its own ATAPI + ISO9660 code and reads a file back; six pages
render; the serial console works; provenance is generated from measurements and
refuses to describe a failing build as passing.

Not established: physical hardware boot, any driver on real silicon, UEFI
booting (built and verified as a medium, never executed — §7),
controller/network/audio support, genuine PS5 firmware execution, PS5 game
execution, a CI run, or a CI-published release. `docs/TESTING_STRATEGY.md`
defines the levels; `docs/PS5_COMPATIBILITY_STATUS.md` records what the machine
itself reports.

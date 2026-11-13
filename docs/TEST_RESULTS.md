# Test results

Recorded on 2026-11-13 (sections 1–6 and 7.7: milestone A, base `719432c`;
section 7: milestone B2, branch `arena/2f423f3b-pc5`, base `main` `4a7e2a7`;
section 6 activation attempts: milestone B3, bases `main` `237725d` and
`a266936`). Earlier revisions of this file dated the B3 work 2026-11-12; the
merges they describe are timestamped 2026-11-13, which is the date used now.
Build under test: PC5 `0.2.0`. Sections 1–6 describe the BIOS-only medium as of
`5ab7c48`; section 7 covers the UEFI boot path added on top of it and is the only
section that mentions it.
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

The activation push has now been attempted twice, on 2026-11-13, and rejected
both times with the same cause.

Against `main` `237725d`:

```
 ! [remote rejected] arena/0e2b454e-pc5 -> arena/0e2b454e-pc5 (refusing to allow a GitHub App to create or update workflow `.github/workflows/build.yml` without `workflows` permission)
```

Against `main` `a266936` (retry 2, after the permission was re-tested and found
unchanged; one decisive push, a pure rename with 0 insertions and 0 deletions):

```
 ! [remote rejected] arena/79f9165d-pc5 -> arena/79f9165d-pc5 (refusing to allow a GitHub App to create or update workflow `.github/workflows/build.yml` without `workflows` permission)
error: failed to push some refs to 'https://github.com/SpicyBadran/pc5.git'
```

Neither attempt reached the remote; the local commits were reverted and no
`.github/` directory exists on any remote branch. `gh api
repos/SpicyBadran/pc5/actions/workflows` reports `total_count: 0`, `gh run list`
is empty, and the `pc5-0.1.0` release carries **zero assets** — so no workflow
has ever been registered, no run has ever executed, and no release asset has
ever been published by CI.

The token is a GitHub App installation token (no OAuth scopes;
`X-Accepted-Github-Permissions: actions=read`). It holds `admin`/`push`, but the
installation lacks **Workflows: Read and write**; `/installation/repositories`
and `/actions/permissions` both return `403 Resource not accessible by
integration`.

**Nothing in this section may be upgraded until a real run exists.** See
`ci/README.md` for the owner action that unblocks it.

### 6.1 Workflow rehearsal, 2026-11-13 — a defect the pipeline would have hit

The workflow has never run on GitHub, so its steps were rehearsed locally in the
order the `build` job runs them, from a clean clone of `b97e302`. One step was
broken:

```
$ python3 -m pip install --disable-pip-version-check "unicorn==2.1.4"
error: externally-managed-environment
× This environment is externally managed
rc=1
```

The runner image marks its Python as externally managed (PEP 668), and the step
runs under `set -eu`, so this aborted the **whole build job** before a single
test ran — `make stubtest` was never reached. The workflow also uses no
`setup-python` action, so it inherits exactly that interpreter.

Fixed by installing into a virtual environment and putting it first on `PATH`,
which is what makes the Makefile's hard-coded `python3` resolve to it:

```
$ python3 -m venv .venv
$ .venv/bin/pip install --disable-pip-version-check "unicorn==2.1.4"
$ export PATH="$PWD/.venv/bin:$PATH"
$ python3 -c "import unicorn; print('unicorn', unicorn.__version__)"
unicorn 2.1.4
$ make stubtest
PASSED: 42/42 checks against the stub firmware
```

`.venv/` is now in `.gitignore`, next to the existing `node_modules/` entry, so
the rehearsal does not leave untracked files. The rest of the job was rehearsed
unchanged and behaves correctly: ISO build, `make verify` **VALID**,
`make unit` **35/0**, host suite **OK**, `make boot-test` **25/25**, two clean
builds byte-identical (`97c56ec5…016775`), and `release-assets` producing a
`build-info.json` whose verdict is `PASS` with artifact and record hashes equal.

This is a **local rehearsal, not a CI run**. It does not change the verdicts in
the table above: the workflow has still never been registered or executed by
GitHub, and no release asset exists.

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

## 7. UEFI boot path — IMPLEMENTED — EXECUTED AGAINST STUB FIRMWARE (not OVMF)

Recorded on branch `arena/2f423f3b-pc5` (base `main` `4a7e2a7`). The label
changed in this milestone for one reason: the loader's own machine code now runs
to completion. It still has **not** run under real UEFI firmware, and nothing
below should be read as saying it has.

### 7.1 What was missing, and what closed it

Milestone A (previous section) proved the medium is structurally correct and
left the code "built but never run". No OVMF image, no QEMU, no UEFI-capable
VM, no KVM and no package manager exist in this environment, so firmware could
not be obtained. Floating-point-free workaround, used honestly:

`tests/uefi_stub_firmware.py` executes the real `build/uefi/BOOTX64.EFI` on the
Unicorn CPU emulator (2.1.4) with a firmware **model** around it:

* the PE32+ image is loaded the way firmware loads it — sections at their
  virtual addresses, every base relocation applied — at `0x400000`, deliberately
  **not** its `0x10000000` preferred base, so a missing relocation is fatal;
* Simple Text Output, Graphics Output, Boot Services, Loaded Image, Device Path
  and Simple File System are served at the byte offsets the specification
  assigns (`handle_protocol` 152, `locate_handle` 176, `get_memory_map` 56,
  `exit_boot_services` 232, …), each reached through a real x86-64 `ret` stub
  that the harness services from the **ms_abi** registers;
* the file system is two volumes: the FAT ESP parsed out of `build/efi.img`, and
  a second volume carrying `KERNEL.BIN`. That is the shape of a real El Torito
  UEFI boot, and it is why the loader must search for the volume instead of
  assuming its own — the search is exercised, not bypassed;
* execution starts at the image's own `_start` and follows the handover stub to
  the far jump into the kernel.

`tests/uefi_stubtest.py` asserts 42 properties of that run, and takes two
negative runs: a kernel with a corrupted signature must stop with `E4`, and a
machine with no kernel on any volume must stop with `E2`.

### 7.2 Recorded output

```
$ python3 -m venv /tmp/ucv && /tmp/ucv/bin/pip install "unicorn==2.1.4"
$ make stubtest
[PASS] the image is loaded away from its preferred base  (entry 0x401000)
[PASS] base relocations were applied  (93 fixups)
[PASS] the loader's own entry stub ran
[PASS] the loader printed its banner
[PASS] the loader reached its own trace output
[PASS] the loader searched every file-system volume
[PASS] it took the image device from LoadedImage, not a guess
[PASS] it found the volume holding KERNEL.BIN
[PASS] it read the kernel and checked the signature
[PASS] the framebuffer was discovered through GOP
[PASS] the memory map was read
[PASS] the loader left boot services
[PASS] boot info magic is 'PC5B'  (0x42354350)
[PASS] boot info protocol version is 1  (1)
[PASS] boot drive is the documented no-BIOS marker  (0xffffffff)
[PASS] E820 array address is the BIOS-loader address  (0x2000)
[PASS] E820 array has entries  (7)
[PASS] VBE mode info address is the BIOS-loader address  (0x2800)
[PASS] framebuffer is advertised
[PASS] no VGA font is claimed  (0x0)
[PASS] font bytes per char is zero when there is no font
[PASS] pvd_ok is honest (not reachable through the file protocol)
[PASS] kernel size matches the file on the medium  (36636 vs 36636)
[PASS] kernel LBA is not invented
[PASS] volume id is not invented
[PASS] iso sector count is not invented
[PASS] loader version string is recorded  (uefi-0.2.0)
[PASS] flags admit the UEFI origin and the unreported fields  (0x7)
[PASS] VBE block describes the real GOP geometry  (1024x768)
[PASS] VBE pitch matches the GOP scan line  (4096)
[PASS] VBE block is 32 bpp direct colour
[PASS] VBE block points at the framebuffer  (0x4000000)
[PASS] VBE character cell is 8x16 (what the kernel console assumes)
[PASS] conventional memory is reported as usable  ([{'base': 0, 'length': 651264, 'type': 1, 'acpi': 0}])
[PASS] loader data is NOT reported as usable  (0x20098b0)
[PASS] the handover targeted the kernel entry  ({'target': '0x10000', 'ebx': '0x4000', 'esp': '0x9f000'})
[PASS] the handover passed the boot-info address in EBX  ({'target': '0x10000', 'ebx': '0x4000', 'esp': '0x9f000'})
[PASS] the kernel image was copied to the handover address  (eb055043354b01fa)
[PASS] the handover GDT is the flat 3-entry table  ({'base': '0x402310', 'limit': 23})
[PASS] no harness-level problems were reported
[PASS] a kernel without the PC5K signature is refused
[PASS] no kernel on any volume stops the boot with E2

PASSED: 42/42 checks against the stub firmware
```

`make stubtest` exits 2 with an explanation when `unicorn` is not installed, so
a missing dependency reads as *cannot run* rather than as a failed or passing
boot. The machine-readable form of the same run is
`build/stubtest-report.json`.

### 7.3 The serial trace the loader itself produced

Captured from port `0x3F8`, i.e. written by the loader's own `outb`, not by the
harness:

```
PC5 UEFI loader uefi-0.2.0
PC5-UEFI: firmware_started
PC5-UEFI: firmware=PC5 stub firmware
PC5-UEFI: firmware_revision=131072
PC5-UEFI: display_width=1024
PC5-UEFI: display_height=768
PC5-UEFI: display_pitch=4096
PC5-UEFI: display_pixel_format=1
PC5-UEFI: image_device=media
PC5-UEFI: filesystem_volumes=2
PC5-UEFI: kernel_volume_opened
PC5-UEFI: medium_readme_unreadable
PC5-UEFI: kernel_bytes_read=36636
PC5-UEFI: kernel_protocol_version=1
PC5-UEFI: memory_map_entries=7
PC5-UEFI: memory_conventional_mib=2
PC5-UEFI: boot_info_ready
PC5-UEFI: kernel_loaded_at=0x00010000
PC5-UEFI: boot_services_exited
```

The `boot_info` block the kernel receives, as read back out of memory at
`0x4000` after the handover (`build/stubtest-report.json` → `data.boot_info`):

| Field | Value | Checked against |
|---|---|---|
| `magic`, `version` | `0x42354350`, `1` | `kernel/include/pc5.h` |
| `boot_drive` | `0xFFFFFFFF` | the documented no-BIOS marker |
| `e820_addr`, `e820_count` | `0x2000`, `7` | the BIOS loader's addresses |
| `vbe_mode_addr`, `vbe_ok` | `0x2800`, `1` | GOP mode reported by the stub |
| `font_addr`, `font_bytes_per_char` | `0`, `0` | no VGA font is claimed |
| `kernel_bytes` | `36636` | the size of `build/kernel.bin` on the medium |
| `kernel_lba`, `volume_id`, `iso_sectors`, `pvd_ok` | `0`, empty, `0`, `0` | not invented: the file protocol does not expose them |
| `flags` | `0x7` | bit 0 = UEFI origin, bits 1–2 = the two unreported fields |

The handover itself: target `0x10000` (decoded from the `EA imm32 imm16`
instruction, not assumed), `EBX = 0x4000`, the flat 3-entry GDT with limit 23
found by decoding the loader's own `lgdt`, and the kernel image copied to
`0x10000` with its `PC5K` header intact.

### 7.4 Two real loader bugs this found

Both were invisible to the structural tests and to review, and both would have
broken a real boot:

| Bug | Symptom in the harness | Fix |
|---|---|---|
| `find_kernel_volume()` tested the status of the *last probe*, so a volume without `\KERNEL.BIN` ended the search even when a later volume had it | a healthy two-volume machine stopped with `E2` | the loop is driven by the chosen root (`for (…; i < count && !chosen; i++)`), each volume is closed before moving on, and the chosen one is reopened for the caller |
| the kernel signature was compared at offset 0 | every real kernel was rejected with `E4` | `PC5_KERNEL_SIG_OFFSET = 2` in `kernel/include/pc5.h`, used by the loader; the file starts with the kernel's own short jump, then `PC5K`, then the protocol version |

Both are pinned by `LoaderRegressionTests` in `tests/test_uefi.py`, which fail
against the previous revision of `uefi_main.c` and pass now.

### 7.5 Reproducibility and the rest of the suite

```
$ export BUILD_ID=4a7e2a71d216d288830bdaa6cb8ebf7c9761eb2f
$ export SOURCE_DATE_EPOCH=1794562897
$ make clean && make iso
pc5: wrote build/pc5.iso (1570816 bytes, 767 sectors)
pc5: sha256 e00a2a0220a7553b8990bfd23f6b7b3c1a78b025931ad3e47713d962d1b329ae

$ sha256sum build/uefi/BOOTX64.EFI build/efi.img build/pc5.iso
c9b864a008bef1be4e65e55785697d5a19383488d732c39e90f36aa7e96783b6  build/uefi/BOOTX64.EFI
4c9c9f37bdace05d410f70c71f1189f013d751a6b9d30cccb4369e4f35356a39  build/efi.img
e00a2a0220a7553b8990bfd23f6b7b3c1a78b025931ad3e47713d962d1b329ae  build/pc5.iso
```

Run twice from `make clean` with those inputs: all three digests identical.

| Suite | Result |
|---|---|
| `make stubtest` (stub firmware, this milestone) | **42/42**, two negative runs included |
| `make verify` (structural ISO, unchanged) | **VALID**, sha256 `e00a2a02…b329ae` |
| `make unit` (kernel logic) | **35 checks, 0 failures** |
| host suite `python3 -m unittest discover -s tests` | **73 tests, OK** (was 66) |
| `make boot-test` (BIOS path, v86/SeaBIOS) | **25/25** |
| `tools/eficheck.py --require-relocs` | 22/22 |

### 7.6 What this does and does not establish

Established: the loader's own code executes from `_start` through the handover,
takes its protocols from the specification's slots, applies its relocations,
finds the kernel volume by searching rather than assuming, reads the kernel,
converts the memory map, fills the boot contract, leaves boot services and
performs the far jump into the kernel — and refuses a corrupt kernel or a
missing one with the documented codes.

Not established: that the image boots under real firmware. The stub has no
ACPI, no PCI, no interrupts, no timer and no NVRAM, does not enforce Secure
Boot, does not perform a real `ExitBootServices` memory-map transition, and
**emulates `lgdt`, the segment loads and the `lretq` itself** because the CPU
emulator does not implement them (the descriptor contents are checked, but the
CPU does not perform the switch). The kernel is stopped at its entry point: the
rest of it wants devices the harness does not provide. This is evidence about
the *loader*, not a UEFI compatibility result.

Closing the gap needs one recorded boot under OVMF or on hardware:

```
qemu-system-x86_64 -m 512 -serial stdio \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
  -drive if=pflash,format=raw,file=copy-of-OVMF_VARS.fd \
  -cdrom build/pc5.iso -boot d
```

Until that exists, the label is IMPLEMENTED — EXECUTED AGAINST STUB FIRMWARE
(not OVMF), and the BIOS path remains the only verified boot path.

### 7.7 History — milestone A: the loader is built and structurally verified

Recorded on branch `arena/42c51afe-pc5` (base `main` `719432c`). Everything below
was produced by the command quoted next to it on that tree; the digests differ
now because the loader changed. This section is kept as the record of what that
milestone established — a medium that is structurally correct.

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

Both builds were repeated from `make clean` with those inputs and all three
digests were identical, so the UEFI path is as reproducible as the BIOS path.
The build id is compiled into the kernel, so a build at the tip of this branch
has a different (equally valid) ISO digest; rebuilt with
`BUILD_ID=0cd396b…` and the same `SOURCE_DATE_EPOCH` it is
`b562caf35ba2da97cd529c967be46d3a85b6542d7f6721760332f732f9bbc275`, with the
same `efi.img` and `BOOTX64.EFI` digests above.

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

## 8. What these results do and do not establish

Established: the image is a valid, reproducible ISO9660/El Torito medium; it
boots on an emulated PC; the kernel runs, inventories the machine, mounts its own
medium through its own ATAPI + ISO9660 code and reads a file back; six pages
render; the serial console works; provenance is generated from measurements and
refuses to describe a failing build as passing.

Not established: physical hardware boot, any driver on real silicon, UEFI
booting under real firmware (the loader now executes against a stub — §7 — but
has never run under OVMF or on hardware),
controller/network/audio support, genuine PS5 firmware execution, PS5 game
execution, a CI run, or a CI-published release. `docs/TESTING_STRATEGY.md`
defines the levels; `docs/PS5_COMPATIBILITY_STATUS.md` records what the machine
itself reports.

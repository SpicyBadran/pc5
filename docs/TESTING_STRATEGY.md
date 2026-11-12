# Testing strategy

## 1. Sixteen evidence levels

A level is only claimed when its own evidence exists. The table is the contract
used across this repository.

| # | Level | How it is proven | Current status |
|---|---|---|---|
| 1 | Code compiles | `make` | PROVEN |
| 2 | Build succeeds | `make iso` writes `build/pc5.iso` + `build-info.json` | PROVEN |
| 3 | ISO is generated | file exists with recorded SHA-256 | PROVEN |
| 4 | ISO integrity verified | `make verify` (independent parser, 32 checks) | PROVEN |
| 5 | ISO boots in a virtual machine | `make boot-test` (v86 + SeaBIOS) | PROVEN |
| 6 | Installer works | installer does not exist | NOT APPLICABLE YET |
| 7 | Installation succeeds | depends on 6 | NOT APPLICABLE YET |
| 8 | Installed system boots | depends on 6 | NOT APPLICABLE YET |
| 9 | Physical hardware boots | requires a physical machine | NOT PROVEN |
| 10 | Controller works | DualSense over USB/BT | NOT PROVEN (no USB stack) |
| 11 | Internet connectivity works | wired/Wi-Fi from the booted system | NOT PROVEN |
| 12 | Genuine PS5 firmware executes | instrumented boot of Sony system software | NOT PROVEN |
| 13 | Genuine PS5 home screen operates | observation on hardware | NOT PROVEN |
| 14 | Actual PS5 game installs | package installation from media | NOT PROVEN |
| 15 | Actual PS5 game launches | title execution trace | NOT PROVEN |
| 16 | Actual PS5 game playable | sustained gameplay measurements | NOT PROVEN |

Levels 1–5 are machine-checked in this repository. Levels 6–16 are not claimed
anywhere, in any document, on any screen.

## 2. Test layers

### 2.1 Host unit tests — `make check`

* `tests/test_tools.py`
  * ISO writer: determinism, volume descriptors, catalog checksum, virtual
    sector count, descriptor patching (LBA/size/CRC32).
  * Verifier: accepts a good image, rejects a corrupted catalog signature.
  * Firmware tool: SLB2 identification, FIH/PFS offset, honest "unidentified"
    result, manifest → C embedding.
  * Kernel unit binary: built and executed.
  * Built image: verifies the real `build/pc5.iso` when present.
* `tests/kernel_unit.c` — 32 assertions over the kernel's pure logic:
  formatter (`%s`, `%-4s`, `%08x`, `%llu`, `%%`), number conversion, E820
  accounting, chain state machine (including "a firmware manifest never turns
  execution into OK").

These run in milliseconds and catch the class of bug that otherwise only shows
up on screen — the formatter bugs found this way are recorded in
`docs/TEST_RESULTS.md`.

### 2.2 Structural image test — `make verify`

A second, independent ISO9660/El Torito parser checks:
volume descriptor, block size, volume size vs file size, root directory walk,
boot record volume descriptor, catalog validation checksum, bootable
no-emulation entry, load segment `0x7C0`, virtual sector count in 512-byte
units, boot descriptor CRC32, descriptor↔directory agreement for the kernel
extent, `PC5K` kernel signature, and per-file SHA-256 against the build record.

### 2.3 Emulated boot test — `make boot-test`

`tests/v86_runner.mjs` boots the image in v86 (SeaBIOS, emulated CD-ROM,
El Torito no-emulation) and records serial output, the VGA text screen and
scripted input. `tests/boot_test.py` then asserts:

* loader banner, ISO9660 descriptor read, kernel verification, protected-mode
  handoff, kernel start, `PC5-BOOT-OK`;
* `genuine_ps5_execution=no` and a blocked chain stage with evidence in the log;
* the kernel mounted its own medium through its ATAPI/ISO9660 code and read a
  file back with a valid signature (`storage_mounted volume=PC5 … signature=ok`);
* all six interface pages by dumping the console's shadow character grid over
  the serial console (`page N` + `screen`), so the assertions cover the
  *rendered* interface rather than a separate reporting path.

Evidence is written to `build/test/boot-evidence.json`, `serial.log`,
`serial-ui.log` and `screens.txt`.

### 2.4 What the emulator cannot prove

v86 is an x86 PC emulator, not a PC. It proves the boot chain and the interface
logic. It does **not** prove: real firmware behaviour (VBE vs GOP quirks), real
chipset/PCI topology, real disk controllers, USB, audio, network, timing or
thermal behaviour. No claim of physical compatibility is made from it.

## 3. Physical hardware plan (not yet executed)

For the reference Dell Inspiron 15 7577 and any other machine:

1. flash the ISO, boot with CSM enabled, capture the serial log on another host
   with a USB-serial adapter or via the same stick's log file if a storage
   driver exists (it does not yet — record the screen instead),
2. record `PC5-LOG` lines: display mode, CPUID, E820, PCI list, ACPI tables,
   SMBIOS strings,
3. compare against `docs/HARDWARE_COMPATIBILITY.md` and file the result,
4. repeat with a DualSense attached on the USB path once the USB stack exists.

## 4. Regression policy

* every bug fixed on screen becomes an assertion in `tests/boot_test.py` or
  `tests/kernel_unit.c`,
* `make check` must pass before a commit that touches `kernel/` or `tools/`,
* `make verify` must pass before any release.

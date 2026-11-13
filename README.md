# PC5

[![build](https://github.com/SpicyBadran/pc5/actions/workflows/build.yml/badge.svg)](https://github.com/SpicyBadran/pc5/actions/workflows/build.yml)

PC5 is an engineering project whose objective is to make compatible PC
hardware operate as a PlayStation 5: boot the machine, reach genuine PS5 system
software, and run real PS5 games.

This repository contains the parts of that objective that are actually built
and tested today: a bootable PC5 image, a 32-bit boot environment that
inventories the machine, and the compatibility-chain framework that reports —
honestly and per stage — how far the project has got.

## Read this first

**Genuine PS5 system software is not running on PC5 today.** If you boot the
image you will see the PC5 boot environment, which says so on screen. PC5 does
not ship Sony firmware, does not decrypt it, and does not claim compatibility
it has not measured. The current state of every stage is in
[`docs/PS5_COMPATIBILITY_STATUS.md`](docs/PS5_COMPATIBILITY_STATUS.md).

What *does* work today, verified in this repository:

| Capability | Status | Evidence |
|---|---|---|
| Reproducible ISO build (`build/pc5.iso`) | COMPLETE AND VERIFIED | `make iso`, [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md) |
| ISO structure (ISO9660 + El Torito + boot descriptor) | COMPLETE AND VERIFIED | `make verify` → 32/32 checks |
| Boots on an emulated x86 PC (SeaBIOS, CD-ROM) | COMPLETE AND VERIFIED | `make boot-test` → 25/25 checks |
| Kernel reads its own medium (ATAPI + ISO9660, no firmware calls) | COMPLETE AND VERIFIED (emulated) | `storage_mounted volume=PC5` in the boot log |
| Hardware inventory (CPUID, E820, PCI, ACPI, SMBIOS) | IMPLEMENTED — TESTING REQUIRED | hardware page + serial log |
| Framebuffer console with VGA text fallback | COMPLETE AND VERIFIED (emulated) | boot log, framebuffer self-test |
| PS/2 keyboard navigation | IMPLEMENTED — TESTING REQUIRED | 8042 driver, emulator input |
| Serial recovery console | COMPLETE AND VERIFIED | `pc5>` commands |
| UEFI boot path | NOT STARTED (BIOS path only) | [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) |
| DualSense controller support | NOT STARTED (needs a USB stack) | chain stage 3 |
| Genuine PS5 firmware execution | BLOCKED — no verified path exists | [`docs/FIRMWARE_ANALYSIS.md`](docs/FIRMWARE_ANALYSIS.md) |
| Actual PS5 game execution | NOT STARTED | [`docs/GAME_TEST_RESULTS.md`](docs/PS5_GAME_TEST_RESULTS.md) |

## Quick start

Download a verified build (every release is built and tested by CI and carries
`pc5.iso`, `pc5.iso.sha256` and `build-info.json`):

```sh
gh release download --repo SpicyBadran/pc5 && sha256sum -c pc5.iso.sha256
```

Build it yourself (needs `gcc`, `binutils`, `make`, `python3`; nothing else):

```sh
make            # writes build/pc5.iso + build/pc5.iso.sha256 + build/build-info.json
make verify     # independent structural verification of the image
make check      # host unit tests + kernel unit tests
make boot-test  # boots the ISO in the emulator and asserts the interface
make release-assets TAG=v0.2.0   # verify + metadata + the three release files
```

Try the image without leaving the build host:

```sh
npm install v86-system          # emulator used by the boot test
make boot-test
```

Write it to a USB stick and boot a real machine: [`docs/INSTALLATION.md`](docs/INSTALLATION.md).

## What the boot environment gives you

* a hardware inventory taken from firmware tables and CPUID, not from a database,
* a storage stack of its own: ATAPI PIO driver + ISO9660 reader, used at boot to
  mount the CD and read the kernel file back as a self-test,
* a 13-stage compatibility chain with the evidence behind every stage,
* self-tests for the graphics mode, font, serial port, PCI, ACPI, SMBIOS,
  ISO9660 descriptor and boot-descriptor integrity,
* a serial console on COM1 at 115200 8N1 (`status`, `chain`, `hw`, `fw`,
  `diag`, `log`, `screen`, `page N`, `reboot`, `halt`) so a machine with no
  display can still be diagnosed.

## Documentation

| Document | Contents |
|---|---|
| [`docs/PROJECT_AUDIT.md`](docs/PROJECT_AUDIT.md) | what the repository contained, what was inspected, environment limits |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | boot chain, kernel modules, host tools |
| [`docs/TECHNICAL_DECISIONS.md`](docs/TECHNICAL_DECISIONS.md) | decision records with rejected alternatives |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | milestones M0–M9 and their real status |
| [`docs/BUILDING.md`](docs/BUILDING.md) | toolchain, reproducibility, targets |
| [`docs/INSTALLATION.md`](docs/INSTALLATION.md) | flashing, booting, troubleshooting |
| [`docs/TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md) | the sixteen evidence levels and how each is proven |
| [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md) | results of the current build, with commands |
| [`docs/HARDWARE_COMPATIBILITY.md`](docs/HARDWARE_COMPATIBILITY.md) | reference machine, detection, matrix |
| [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) | everything that does not work yet |
| [`docs/SECURITY.md`](docs/SECURITY.md) | threat model, firmware handling, what PC5 refuses to do |
| [`docs/UPDATE_SYSTEM.md`](docs/UPDATE_SYSTEM.md) | PC5 update design vs Sony firmware updates |
| [`docs/RECOVERY.md`](docs/RECOVERY.md) | recovery console and re-flashing |
| [`docs/FIRMWARE_ANALYSIS.md`](docs/FIRMWARE_ANALYSIS.md) | what firmware research can and cannot do |
| [`docs/PS5_COMPATIBILITY_ARCHITECTURE.md`](docs/PS5_COMPATIBILITY_ARCHITECTURE.md) | the 18 compatibility subsystems |
| [`docs/PS5_COMPATIBILITY_STATUS.md`](docs/PS5_COMPATIBILITY_STATUS.md) | per-level status with evidence |
| [`docs/GAMING_COMPATIBILITY.md`](docs/GAMING_COMPATIBILITY.md) | PC games vs PS5 games, kept separate |
| [`docs/PS5_GAME_TEST_RESULTS.md`](docs/PS5_GAME_TEST_RESULTS.md) | per-title test records (empty so far, honestly) |
| [`docs/playstation/`](docs/playstation/) | firmware versions, feature parity, research log |

## Legal

PC5 is an independent interoperability and preservation project. It is not
affiliated with, endorsed by, or authorised by Sony Interactive Entertainment.
"PlayStation" and "PS5" are trademarks of Sony Interactive Entertainment Inc.

PC5 contains no Sony firmware, keys or proprietary libraries, and will not
redistribute them. See [`docs/SECURITY.md`](docs/SECURITY.md) and
[`docs/FIRMWARE_ANALYSIS.md`](docs/FIRMWARE_ANALYSIS.md).

PC5 is licensed under the GNU General Public License version 2 only, matching
the AnyPS5 sources it studies and intends to interoperate with.

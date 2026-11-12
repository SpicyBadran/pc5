# PC5 architecture

## 1. Boot chain as implemented today

```
 firmware (BIOS/SeaBIOS)
   │  El Torito no-emulation entry written by tools/mkiso.py
   ▼
 boot/loader.S         real mode, 4096 bytes, loaded at 07C0:0000
   ├─ COM1 serial console (115200 8N1) + failure codes
   ├─ INT 15h E820 memory map            → 0x2000
   ├─ INT 10h 1130h firmware 8x16 font   → 0x2900
   ├─ VBE 4F00/4F01/4F02 linear mode     → 0x2800  (text mode fallback)
   ├─ INT 13h read of ISO9660 sector 16  → 0x3A00  (proves the medium reads,
   │                                                and detects 2048 vs 512
   │                                                byte disk units)
   ├─ INT 13h read of the kernel image   → 0x10000 (signature "PC5K" checked)
   ├─ struct pc5_boot_info               → 0x4000
   └─ GDT + CR0.PE, 32-bit far jump      → 0x10000 with EBX = 0x4000
   ▼
 kernel/start.S        identity flat 32-bit entry, .bss cleared, IDT installed
   ▼
 kernel/main.c         console → timer → CPUID → E820 → PCI → SMBIOS → ACPI
                       → firmware probe → storage (ATAPI + ISO9660 self-test)
                       → keyboard → chain → interface
```

Fixed low-memory contract (both `boot/loader.S` and `kernel/include/pc5.h`):

| Address | Contents |
|---|---|
| `0x2000` | E820 entries (up to 40 × 24 bytes) |
| `0x2500` | VBE controller information |
| `0x2600` | copied VBE mode list |
| `0x2800` | VBE mode information block (framebuffer address/geometry) |
| `0x2900` | 256-glyph 8×16 font copied from the video BIOS |
| `0x3A00` | ISO9660 primary volume descriptor |
| `0x4000` | `struct pc5_boot_info` |
| `0x4400` | disk address packet |
| `0x10000` | kernel image (limit `0x8F000`) |
| `0x9F000` | stack top |

`_Static_assert`s in `kernel/include/pc5.h` pin the struct offsets so the
kernel and the loader cannot drift apart silently.

## 2. Kernel modules

| File | Responsibility |
|---|---|
| `kernel/start.S` | entry stub, `.bss` clear, protected-mode continuation, IDT with 32 real exception gates |
| `kernel/main.c` | boot order, evidence log, chain evaluation, hand-off to the UI |
| `kernel/console.c` | linear-framebuffer console (firmware font), VGA text fallback, shadow character grid, framebuffer read-back self-test, panic |
| `kernel/serial.c` | 16550 polling driver on COM1 |
| `kernel/lib.c` | freestanding string/memory/formatting (`pc5_snprintf` is the only formatter in the tree) |
| `kernel/cpu.c` | CPUID: vendor, brand, family/model, logical CPUs, feature bits, long-mode |
| `kernel/mem.c` | E820 accounting (usable, addressable, top of memory) |
| `kernel/pci.c` | configuration mechanism #1 enumeration and classification |
| `kernel/acpi.c` | RSDP discovery (EBDA + BIOS area), RSDT walk, table signatures |
| `kernel/smbios.c` | `_SM_`/`_SM3_` anchor, structure walk (BIOS, system, board, CPU, DIMMs) |
| `kernel/ata.c` | legacy ATA/ATAPI PIO block driver (LBA28 reads, packet reads on 2048-byte blocks) |
| `kernel/iso9660.c` | ECMA-119 volume mount, root directory walk, file read on top of `ata.c` |
| `kernel/kbd.c` | 8042 PS/2 keyboard, polled, scan-code set 1 translation, E0 handling |
| `kernel/timer.c` | PIT calibration against the TSC; millisecond timeouts and uptime |
| `kernel/chain.c` | the 13-stage PS5 compatibility chain and its evidence strings |
| `kernel/fw.c` | firmware probe (manifest presence), never a claim of execution |
| `kernel/ui.c` | six pages, controller/keyboard navigation, serial recovery console, audit log |

The kernel is deliberately small (≈31 KB) and freestanding: no libc, no
allocator, no paging, no interrupts beyond the IDT gates. Everything is
polled, which keeps the boot deterministic and makes failures reproducible.

## 3. Host tooling

| Tool | Purpose |
|---|---|
| `tools/mkiso.py` | ISO9660 (ECMA-119) + El Torito writer, byte-exact control of the boot descriptor, deterministic layout |
| `tools/verify_iso.py` | independent verifier: volume descriptors, catalog checksum, boot entry, descriptor CRC, kernel signature, per-file SHA-256 |
| `tools/firmware.py` | firmware container identification, entropy profile, manifest generation — no decryption |
| `tools/pc5ctl.py` | operator CLI: `info`, `verify`, `boot`, `chain`, `fw`, `usb` |
| `tests/v86_runner.mjs` | boots an image in v86, captures serial and the VGA text screen, injects serial/PS2 input |
| `tests/boot_test.py` | asserts boot markers and the rendered interface, writes `build/test/boot-evidence.json` |
| `tests/kernel_unit.c` | host-side unit tests for the kernel's pure logic |
| `tests/test_tools.py` | unit tests for the ISO writer, verifier and firmware tool |

## 4. Interfaces that the next stages plug into

* **Display**: `console_init()` accepts any boot info with a VBE mode block;
  a GOP-based mode can be supplied by a future UEFI loader without touching the
  console.
* **Input**: `kbd_read()` is the only input source in the UI; a USB HID or
  DualSense translator is a second source behind the same interface.
* **Storage**: `ata_read_blocks()` is the only block interface; AHCI, NVMe and
  USB storage plug in behind it. `iso_read_file()` is what a package reader will
  call once a PS5 container parser exists (chain stage 4).
* **Firmware**: `fw_probe()` consumes a manifest compiled into the kernel; the
  manifest is produced by `tools/firmware.py` from a user-supplied image.
* **Compatibility chain**: `chain_evaluate()` takes one argument per subsystem,
  so a new subsystem adds a stage without rewriting the reporting.

## 5. Why the UEFI path and a Linux foundation are not in this build

Both are required for the final objective and both are blocked by the *build
environment*, not by design:

* no UEFI firmware image (OVMF) and no virtual machine capable of UEFI were
  obtainable, so a UEFI loader could be written but not executed;
* no Linux kernel source or binary was obtainable (apt and kernel.org are
  unreachable, no release assets can be downloaded), so a Linux-based PC5
  runtime could not be built or tested.

The BIOS path was therefore built first: it is fully testable here, it produces
the required `build/pc5.iso`, and it establishes the hardware-inventory and
reporting layer that both future paths reuse. See `docs/KNOWN_LIMITATIONS.md`
and `docs/ROADMAP.md`.

# UEFI boot path

The PC5 medium is a dual-firmware ISO: one El Torito catalog carries both a
legacy BIOS entry and a UEFI entry, so the same file boots either way.

```
build/pc5.iso
├── El Torito catalog
│   ├── +32  default entry, platform 0x00 (80x86)  -> build/loader.bin   (BIOS)
│   └── +64  section header 0x91, platform 0xEF    -> build/efi.img      (UEFI)
│         +96  boot entry -> \EFI\BOOT\BOOTX64.EFI inside that FAT image
└── ISO9660 root: KERNEL.BIN, README.TXT, BUILDINFO.TXT
```

## Status

**IMPLEMENTED — EXECUTED AGAINST STUB FIRMWARE (not OVMF).**

The loader now *runs*: `tests/uefi_stub_firmware.py` loads the real
`build/uefi/BOOTX64.EFI` the way firmware does, applies its base relocations at
an address other than its preferred base, serves the protocols it calls at the
slots the specification assigns, and follows the code from `_start` through
`efi_main` and the handover into 32-bit protected mode.
`tests/uefi_stubtest.py` asserts 42 properties of that run, including two
negative runs (a corrupt kernel signature, no kernel on any volume).

What that does **not** establish: that the image boots under real UEFI
firmware. There is no ACPI, PCI, interrupt or timer model, no NVRAM, no
Secure Boot, no real `ExitBootServices` memory-map transition, and `lgdt`,
segment loads and the far return are emulated by the harness because the CPU
emulator does not implement them. A passing run means the loader's own code ran
and did the right thing against a stub; it is not a compatibility result. The
gap closes only with a recorded boot under OVMF or on hardware — the command is
at the end of this file.

Two real loader defects were found by running it and are fixed here:

* `find_kernel_volume()` tested the status of the last probe, so a volume
  without the kernel ended the search even when a later volume had it (E2 on a
  healthy medium);
* the kernel signature was read at offset 0, but the kernel file starts with its
  own jump instruction and `PC5K` sits at offset 2 — every kernel the BIOS path
  boots would have been rejected (E4).

Both are pinned by regression tests in `tests/test_uefi.py`. See §7 of
`../docs/TEST_RESULTS.md` for the recorded output.

## What is in this directory

| File | Purpose |
|---|---|
| `bootx64.S` | entry stub (ms_abi frame, `.bss` clearing, return to firmware) and the 64→32-bit handover trampoline |
| `uefi_main.c` | the loader: console trace, GOP, memory map, ESP read, kernel load, `ExitBootServices`, handover |
| `efi.h` | the slice of the UEFI specification this loader uses, with field offsets pinned by `_Static_assert` |
| `bootx64.ld` | PE32+ link map (section at `ImageBase + 0x1000`, `.bss` NOLOAD, `.reloc` present) |

It includes `kernel/include/pc5.h` and asserts every offset the kernel reads, so
the loader cannot drift away from the boot contract without a compile error.

## Build

```
make uefi     # build/uefi/BOOTX64.EFI + build/efi.img, checked by tools/eficheck.py
make iso      # build/pc5.iso with both boot entries
make verify   # walks the ESP out of the ISO and confirms the PE32+ image
```

No EDK2 and no cross compiler: `ld -m i386pep` (binutils' PE32+ emulation) links
gcc objects built with `-m64 -ffreestanding -fno-pic -mno-red-zone`, and
`--enable-reloc-section` derives the base relocation table from the absolute
addresses `.data` initialisers produce. `--no-insert-timestamp` keeps the image
reproducible.

## Handover contract

Identical to `boot/loader.S`: the kernel is entered in 32-bit protected mode
with a flat GDT, paging off, interrupts off, `EBX` = `0x4000` pointing at
`struct pc5_boot_info`, and the kernel image already copied to `0x10000`.

The order in `pc5_uefi_bridge` matters: in 64-bit mode `CR0.PG` cannot be
cleared, so a far return moves the CPU into a 32-bit compatibility segment
first, and paging is switched off only after that.

## What differs from the BIOS path

| Field | UEFI value | Why |
|---|---|---|
| `boot_drive` | `0xFFFFFFFF` | there is no BIOS drive number on this path |
| `font_addr` | `0` | firmware hands over no VGA font, so the kernel uses text mode |
| `pvd_ok`, `volume_id`, `kernel_lba`, `iso_sectors` | `0`, empty, `0`, `0` | the file protocol does not expose the ISO9660 descriptor or a file's LBA |
| `flags` | `0x7` | bit 0 = booted by the UEFI loader, bit 1 = no ISO LBA, bit 2 = no volume id |
| `e820_*` | UEFI memory map | conventional memory → type 1, everything else → type 2 (loader data is *not* called usable) |
| `vbe_*` | synthetic VBE block for the GOP mode | GOP format 0 (RGB) matches; format 1 (BGR) is reported honestly and the kernel's colours swap |

## Failure codes

The loader prints `PC5-UEFI FAILURE E<n>` with a status word and then halts;
the same code goes to COM1 when a serial port probes successfully.

| Code | Meaning |
|---|---|
| E1 | no file system on the volume we were loaded from |
| E2 | no volume on this machine holds `\KERNEL.BIN` |
| E3 | `\KERNEL.BIN` could not be read |
| E4 | kernel image has no `PC5K` signature |
| E5 | kernel boot protocol version mismatch |
| E6 | kernel larger than the load window |
| E8–E12 | memory map query, allocation or descriptor size failed |
| E13 | `ExitBootServices` was refused |
| E14 | handover address is not the protocol address |

## Testing it

Structural checks, with no firmware and no emulator (`tests/test_uefi.py`):

```
python3 -m unittest tests.test_uefi -v
python3 tools/eficheck.py build/uefi/BOOTX64.EFI --require-relocs
python3 tools/mkefiimg.py --list build/efi.img
```

Execution of the loader itself, against the stub firmware:

```
pip install "unicorn==2.1.4"   # the harness dependency
make stubtest              # exits 2 with an explanation if unicorn is absent
```

`make stubtest` prints one line per check and writes
`build/stubtest-report.json`. It is wired into `make test`, and a missing
`unicorn` is reported as *cannot run* (exit 2) rather than as a failed boot, so
the dependency can never be mistaken for a passing or a failing boot.

To close the gap, boot `build/pc5.iso` in QEMU with OVMF:

```
qemu-system-x86_64 -m 512 -serial stdio \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
  -drive if=pflash,format=raw,file=copy-of-OVMF_VARS.fd \
  -cdrom build/pc5.iso -boot d
```

Expected on the serial port, in order: `PC5 UEFI LOADER uefi-0.2.0`,
`firmware_started`, `volume_opened`, `medium_readme_bytes=…`,
`kernel_bytes_read=…`, `kernel_protocol_version=1`, `memory_map_entries=…`,
`boot_info_ready`, `boot_services_exited`, `entering 32-bit kernel`, then the
kernel's own `PC5 KERNEL 0.2.0` banner and `PC5-BOOT-OK`.

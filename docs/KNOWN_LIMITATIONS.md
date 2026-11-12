# Known limitations

Everything below is true of the current build. None of it is a placeholder for
work that has secretly been done.

## Boot

1. **No UEFI boot path.** The image is an El Torito BIOS image. A UEFI machine
   without CSM/legacy support cannot boot it. (The ISO writer already supports a
   second UEFI entry; the loader does not exist yet.)
2. **Not isohybrid.** There is no MBR, so firmware that treats a USB stick
   strictly as a hard disk will not boot it.
3. **No Secure Boot support.** No signed shim, no enrolled keys.
4. **No installer.** PC5 runs from the medium; nothing is written to disk.
   Partitioning, data-loss confirmation and installed-system boot do not exist.

## Environment

5. **Storage is read-only and legacy-only.** The kernel drives ATAPI and ATA PIO
   on the two legacy channels and reads ISO9660. There is no AHCI, no NVMe, no
   USB storage, no partition table parser, no writable filesystem and no way to
   write anything to a disk.
6. **No USB stack.** No USB host controller driver exists, therefore no
   DualSense, no USB storage, no USB Ethernet.
7. **No network stack.** PCI network adapters are enumerated, but no driver,
   DHCP or DNS exists.
8. **No audio.** The audio class is counted in the inventory; there is no
   driver.
9. **Input is PS/2 keyboard only.** USB HID and Bluetooth are not implemented;
   controller support is chain stage 3 and is reported as PARTIAL for exactly
   this reason.
10. **No real-time clock and no interrupt timers.** Timing is PIT-calibrated
    TSC deltas; the clock shown is uptime, not wall time.
11. **No power-off.** ACPI PM1 control is not driven. The Power page says so
    instead of showing a button that does nothing.
12. **No ACPI AML interpreter.** Only table signatures are read.
13. **Framebuffer console only at 16/24/32 bpp VBE modes ≤ 1600×1200.** If
    firmware offers no such mode, the environment falls back to 80×25 VGA text.
14. **32-bit kernel, no paging.** Physical memory above 4 GiB is reported but
    not used; long mode is not entered.

## PS5 compatibility

15. **Genuine PS5 system software does not run and no path to run it is
    implemented.** Stages 5–13 of the compatibility chain are BLOCKED or
    NOT-STARTED by measurement.
16. **No PS5 package parsing.** The `FIH`/`CNT` structures are identified by
    signature in the host tool only; nothing in the kernel understands them.
17. **No PS5 executable execution.** No SELF/ELF loader, no PRX shim, no
    graphics translation for titles.
18. **No PSN or any Sony service access**, authorised or otherwise.
19. **No game compatibility claims.** `docs/PS5_GAME_TEST_RESULTS.md` is empty
    because no title has been executed.

## Engineering process

20. **Physical hardware is untested.** Nothing in this repository has run on the
    reference Dell Inspiron 15 7577; the sandbox has no hardware access and no
    KVM. Emulated boot is the highest evidence level reached.
21. **UEFI firmware was not available to test with**, so even the structural
    UEFI work that the ISO writer supports is unexercised.

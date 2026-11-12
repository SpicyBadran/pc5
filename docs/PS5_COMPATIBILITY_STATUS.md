# PS5 compatibility status

Build: PC5 0.1.0 (`9576ad7`). Every line below is what the boot environment
prints on this build; nothing is aspirational.

## 1. The twelve project levels

| Level | State | Evidence |
|---|---|---|
| Firmware analysed | **NO** | no image supplied; `tools/firmware.py` ready, nothing to run it on |
| Firmware loading pathway implemented | **NO** | `kernel/chain.c` stage 7 is BLOCKED by design |
| Firmware initialisation attempted | **NO** | stage 8 NOT-STARTED |
| Firmware executing | **NO** | stage 9 NOT-STARTED |
| PS5 system services operating | **NO** | stage 10 NOT-STARTED |
| Genuine PS5 home screen operating | **NO** | stage 11 NOT-STARTED |
| Controller navigation operating | **NO** (PC5 environment only) | PS/2 keyboard works in the PC5 UI; no controller driver |
| Network connectivity operating | **NO** | PCI enumeration only; no driver, no stack |
| Authorised PlayStation services operating | **NO** | nothing implemented, nothing attempted |
| Actual PS5 game installation operating | **NO** | no package parser in the kernel, no storage driver |
| Actual PS5 game execution operating | **NO** | no executable loader, no PRX shims |
| Actual PS5 gameplay verified | **NO** | no title has been run |

## 2. The thirteen-stage chain, as the machine reports it

Captured from the emulated boot (`build/test/screens.txt`):

```
 >  1. PC5 boot environment executing          OK
    2. Host hardware inventoried               OK
    3. Controller / input path                 PARTIAL
    4. Storage stack for game installation     PARTIAL
    5. PS5 firmware image supplied             BLOCKED
    6. Firmware format analysed                BLOCKED
    7. Firmware loading pathway implemented    BLOCKED
    8. Firmware initialisation attempted       NOT-STARTED
    9. Firmware executing                      NOT-STARTED
   10. PS5 system services operating           NOT-STARTED
   11. Genuine PS5 home screen                 NOT-STARTED
   12. PS5 game installation                   NOT-STARTED
   13. PS5 game execution                      NOT-STARTED
```

Why each non-OK stage has that state:

| Stage | Reason |
|---|---|
| 1 OK | the kernel is executing and says which CPU it is on |
| 2 OK | CPUID, E820 and PCI produced values on this machine |
| 3 PARTIAL | an 8042 keyboard driver exists; DualSense needs the USB stack that does not |
| 4 PARTIAL | the kernel mounts the ISO through its own ATAPI PIO + ISO9660 code and reads `KERNEL.BIN` back; there is still no writable target, no partition table support and no package installation |
| 5 BLOCKED | no firmware image in the build, and PC5 does not redistribute one |
| 6 BLOCKED | depends on 5; host-side analysis exists but has had nothing to analyse |
| 7 BLOCKED | no verified pathway exists to load Sony-signed system software on a PC |
| 8–13 | nothing has been attempted, so nothing can be claimed |

## 3. What is genuinely working on the PC5 side

| Feature | Status | Evidence |
|---|---|---|
| Bootable ISO (BIOS/El Torito) | COMPLETE AND VERIFIED | `make verify` 32/32, `make boot-test` 21/21 |
| Loader (A20, E820, VBE, font, ISO probe, kernel load, PM handoff) | COMPLETE AND VERIFIED (emulated) | serial log |
| Framebuffer console + text fallback + read-back self-test | COMPLETE AND VERIFIED (emulated) | Diagnostics page |
| CPUID / E820 / PCI / ACPI / SMBIOS inventory | IMPLEMENTED — TESTING REQUIRED | hardware page; needs physical runs |
| PS/2 keyboard navigation | IMPLEMENTED — TESTING REQUIRED | 8042 driver; emulator input only |
| Serial console with 11 commands | COMPLETE AND VERIFIED | boot test drives it |
| Compatibility chain + evidence reporting | COMPLETE AND VERIFIED | unit tests + boot test |
| ISO writer + independent verifier | COMPLETE AND VERIFIED | 12 host unit tests |
| Firmware analysis tool (no decryption) | COMPLETE AND VERIFIED | unit tests on synthetic containers |
| Kernel ATAPI PIO driver + ISO9660 reader | COMPLETE AND VERIFIED (emulated) | `storage_mounted volume=PC5 … signature=ok` |
| UEFI boot path | NOT STARTED | — |
| Writable storage (partitions, filesystem, installer) | NOT STARTED | stage 4 is PARTIAL for this reason |
| AHCI / NVMe | NOT STARTED | legacy ATA channels only |
| USB stack / DualSense | NOT STARTED | — |
| Network stack | NOT STARTED | — |
| Audio | NOT STARTED | — |
| Installer / updater | NOT STARTED | — |

## 4. Honest summary

PC5 today is a real, reproducible, bootable PC environment with working
diagnostics and an honest compatibility model. It is **not** a PlayStation 5:
no Sony code runs, no PS5 game runs, and no stage of the genuine-PS5 chain has
been reached. The next real engineering step is the one that unblocks the most
downstream work: a kernel storage driver, followed by the UEFI boot path.

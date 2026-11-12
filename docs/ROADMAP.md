# Roadmap

Milestones from the project directive, with what is actually true today. A
milestone is not "done" because its documentation exists.

## M0 — Repository and technical audit · **COMPLETE**

Repository inspected (one file: the AnyPS5 archive), environment characterised,
AnyPS5 audited with measured metrics, firmware availability established (none
supplied), licences checked. Evidence: `docs/PROJECT_AUDIT.md`.

## M1 — Working bootable PC5 ISO · **COMPLETE (emulated)**

* `make iso` → `build/pc5.iso` (96,256 bytes, reproducible).
* `make verify` → 32/32 structural checks.
* `make boot-test` → 25/25 checks on the v86/SeaBIOS emulated PC, including the
  kernel mounting its own volume through its ATAPI/ISO9660 driver.

Not done here: UEFI boot, isohybrid USB, physical hardware (M2).

## M2 — Physical boot and safe installation · **IN PROGRESS**

* Physical boot: **not attempted** (no hardware access in this environment).
  Instructions and the troubleshooting matrix exist; the evidence does not.
* Installer: **not started**. Blocked on a storage driver, because an installer
  without disk access would be a menu of buttons that do nothing.
* USB writing: implemented and safe (`pc5ctl usb`), but the image is not yet
  isohybrid.

## M3 — Hardware and core services · **PARTIAL**

| Service | State |
|---|---|
| boot/service management | minimal (no service model; single address space) |
| hardware detection | implemented (CPUID, E820, PCI, ACPI, SMBIOS) |
| storage management | read-only: ATA/ATAPI PIO + ISO9660 in the kernel |
| networking | not started |
| audio | not started |
| graphics | framebuffer console only |
| controller input | PS/2 keyboard only |
| logging | boot log + serial mirror |
| notifications | n/a (no services) |
| updates / recovery | serial recovery console only |

## M4 — PS5 firmware execution research and prototype · **BLOCKED**

No firmware image supplied; no verified pathway exists to load Sony-signed
system software on generic x86 hardware. Work that *can* proceed and has:
container identification (`tools/firmware.py`), the manifest workflow, and the
chain reporting that will name the blocker on screen.

## M5 — Genuine PS5 system-software compatibility · **NOT STARTED**

Depends on M4.

## M6 — Controller and network operation · **NOT STARTED**

Prerequisites: xHCI/USB stack, HID parser, DualSense report parsing, network
driver + IP stack. None exist. Chain stage 3 is PARTIAL for exactly this reason.

## M7 — Actual PS5 game compatibility · **NOT STARTED**

Two prerequisites, both absent: package/executable intake (storage driver) and
an execution layer (relinking + PRX shims, per AnyPS5). Per-title testing
methodology is written; no title has been attempted.

## M8 — Performance, reliability and expanded hardware · **NOT STARTED**

No driver exists to measure. There is no performance claim in this repository.

## M9 — Release-quality PC5 · **NOT STARTED**

A release process exists in outline (`docs/UPDATE_SYSTEM.md`) and the artifact
is reproducible; that is not a release-quality product.

---

## The next twelve engineering tasks, in dependency order

1. **AHCI/NVMe and write support** — the legacy PIO path and the ISO9660 reader
   are done; partitions, a writable filesystem (and therefore an installer)
   are next.
2. **Package intake from the medium** — the kernel can already read a file from
   its own volume; the missing piece is a container parser behind that call.
3. **UEFI loader** — PE32+ application filling the same `struct pc5_boot_info`,
   plus the FAT ESP the ISO writer already supports.
4. **isohybrid MBR** — so a stick boots on firmware that insists on HDD mode.
5. **GOP graphics path** — framebuffer from `EFI_GRAPHICS_OUTPUT_PROTOCOL` for
   machines with no VBE.
6. **USB stack (xHCI + HID)** — then a DualSense driver behind
   `controller_read()`; chain stage 3 becomes measurable.
7. **Network driver + IPv4/DHCP/DNS** — start with the emulator's RTL8139, then
   real chipsets.
8. **ACPI PM1 driver** — real power-off and reset.
9. **Installer** — drive identification, explicit confirmation, verification.
10. **Signed update manifest** — Ed25519, channels, rollback.
11. **Linux runtime decision point** — if a build host can install a kernel and
    `debootstrap`, add the compatibility runtime and keep the bring-up kernel as
    the recovery environment.
12. **Execution-layer prototype** — build AnyPS5 on a capable host, run one
    legally distributable PS5 ELF, record the first game-test row.

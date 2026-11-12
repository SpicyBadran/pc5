# Hardware compatibility

## 1. Seven levels per machine

PC5 distinguishes these outcomes; they are never collapsed into "supported":

| Level | Meaning |
|---|---|
| L1 | PC5 boots (firmware accepts the medium) |
| L2 | PC5 can install (no installer yet — not reachable) |
| L3 | the operating environment works (display, input, services) |
| L4 | genuine PS5 firmware executes |
| L5 | the genuine PS5 interface works |
| L6 | actual PS5 games execute |
| L7 | actual PS5 games are playable |

No machine is at L4 or above, because no path exists yet.

## 2. Reference hardware (unverified)

The previously identified reference machine is:

* Dell Inspiron 15 7577
* Intel Core i7-7700HQ (Kaby Lake, 4C/8T)
* 16 GB RAM
* NVIDIA GTX 1060 Max-Q 6 GB + Intel HD Graphics 630
* 128 GB SSD, 1 TB HDD

**This has not been verified.** The build sandbox has no access to that machine
and no KVM; nothing in this repository has run on it. Its firmware, its GPU
switching mode (Optimus vs discrete-only), its USB controller generation and its
Wi-Fi chip are all unknown until someone boots and records the log.

What the boot environment will report for it, once run:
`PC5-LOG cpu=…`, `PC5-LOG memory_mib=16384 …`, `PC5-LOG pci=…`, `PC5-LOG gpu=…`,
`PC5-LOG net=…`, `PC5-LOG smbios=present …`. Those lines are the compatibility
record; nothing else is accepted.

## 3. Detection implemented today

| Subsystem | Mechanism | Reported fields |
|---|---|---|
| CPU | `CPUID` leaves 0, 1, 0x80000000–0x80000008 | vendor, brand, family/model/stepping, logical CPUs, SSE/AVX/RDRAND, long mode |
| Memory | `INT 15h E820` | addressable size, usable size, entry count, top of memory |
| PCI | configuration mechanism #1 | bus/slot/func, vendor:device, class, subsystem ids |
| Firmware tables | `ACPI` RSDP → RSDT, `SMBIOS` `_SM_`/`_SM3_` | BIOS vendor/version/date, system vendor/product, board, CPU record, DIMM count/size, ACPI revision and table signatures |
| Display | `VBE` mode list | framebuffer address, geometry, pitch, bpp |
| Input | 8042 controller | presence/initialisation status |

## 4. Compatibility matrix template

Every tested machine gets a row. Copy this block into a pull request:

```
machine            <vendor> <model> (<year>)
firmware           <UEFI version> / CSM on|off / Secure Boot on|off
cpu                <from PC5-LOG cpu=>        long_mode=<yes|no>
memory_mb          <from PC5-LOG memory_mib=>
gpu                <from PC5-LOG gpu=>
network            <from PC5-LOG net=>
storage controller <from PCI list class 0x01>
display mode       <from PC5-LOG display=>     fallback=<yes|no>
input              <PS/2 ok|error>
result             L1 <pass|fail>, L2 n/a, L3 <pass|fail>
notes              <anything the log does not show>
log                <attached serial log>
```

## 5. Known interoperability risks on real machines

| Risk | Why it matters | Mitigation planned |
|---|---|---|
| UEFI-only firmware | the image has no UEFI loader yet | UEFI milestone (`docs/ROADMAP.md`) |
| Secure Boot enforced | unsigned bootloader | signed shim, or documented CSM requirement |
| USB sticks presented as HDD | no MBR in the image | isohybrid MBR |
| Firmware with no linear-framebuffer VBE mode | text fallback only | GOP path in the UEFI loader |
| Optimus/hybrid graphics | which GPU owns the framebuffer | report both from PCI; no driver yet |
| Firmware quirks in VBE mode info | wrong pitch or bpp | framebuffer write/read-back self-test on the Diagnostics page |

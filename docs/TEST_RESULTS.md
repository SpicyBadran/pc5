# Test results

Build under test: PC5 `0.1.0`, build id `9576ad7`, branch `arena/2290edbd-pc5`.
Host: Debian 12 x86-64, gcc 12.2.0, binutils 2.40, node 22, v86 (npm
`v86-system` 0.5.0).

## 1. Artifact

```
$ make iso
pc5: wrote build/pc5.iso (92160 bytes, 45 sectors)
pc5: sha256 f44d3c62a0aa3b4614934a3d1aea6a2b262e6d25dfcffb8ed6dd00d387c12df6
```

| Property | Value |
|---|---|
| path | `build/pc5.iso` |
| size | 96,256 bytes (47 × 2048) |
| SHA-256 | `26d8fc8101b60c5a16d7ce618e4e008dc9b405f7c332f6701c6cf4e6ef6ce12d` |
| loader image | 4,096 bytes (8 El Torito virtual sectors) |
| kernel image | 36,508 bytes, `PC5K` signature, loaded at `0x10000` |
| volume id | `PC5` |

## 2. Structural verification — `make verify`

32 checks, all pass. Selected lines:

```
[PASS] image is a whole number of 2048-byte blocks  (92160 bytes)
[PASS] volume descriptor signature at LBA 16  (CD001)
[PASS] logical block size is 2048  (2048)
[PASS] volume size matches the file  (47 blocks)
[PASS] volume contains a kernel file  (BUILDINF.TXT;1,KERNEL.BIN;1,README.TXT;1)
[PASS] El Torito system identifier  (EL TORITO SPECIFICATION)
[PASS] catalog validation checksum sums to zero  (0x0)
[PASS] default entry is bootable  (0x88)
[PASS] default entry is no-emulation  (0)
[PASS] boot image load segment is 0x7C0  (0x7c0)
[PASS] boot image advertises at least one sector  (8)
[PASS] PC5 boot descriptor found in the boot image
[PASS] boot descriptor CRC32 is valid  (stored 0b9d0682 computed 0b9d0682)
[PASS] descriptor kernel LBA matches the directory record  (27 vs 27)
[PASS] descriptor kernel size matches the directory record  (36508 vs 36508)
[PASS] kernel image carries the PC5K signature  (eb055043354b01fa)
[PASS] image SHA-256 matches build info
[PASS] file KERNEL.BIN;1 content matches build info
VALID: build/pc5.iso
```

## 3. Unit tests — `make check`

```
$ make unit
PASSED: 35 checks, 0 failures

$ python3 -m unittest discover -s tests -p 'test_*.py'
Ran 12 tests in 0.150s
OK
```

Bugs these tests actually caught during development (kept here as evidence that
the tests have teeth):

| Bug | Caught by | Fix |
|---|---|---|
| ATAPI IDENTIFY result discarded because a packet device answers with ERR set | serial log showed `storage drives=0` although the CD was present | wait for BSY only; treat ERR+signature as "ATAPI present" |
| ATA data register accessed as two byte reads/writes (`inb(0x1f0)`, `inb(0x1f1)`) | `storage_mounted=no error=-2`: the PVD read back as garbage | added `inw`/`outw`; the data port is a 16-bit register |
| Loader advanced the sector address by bytes instead of disk units, so any multi-chunk kernel load read from a wild LBA | the first kernel image larger than 32 KiB hung the boot | `read_lba` advances in disk units, `read_dest` in bytes |
| `%x` printed 8 zero-padded digits without a width | kernel unit test `pci id` | minimal digits unless a width is given |
| `%llu` emitted a stray `u` | kernel unit test `u64` | consume the second `l` |
| El Torito entry advertised 2048-byte units (2 instead of 8 virtual sectors) → firmware loaded the first 1024 bytes only | boot test (loader read a zeroed boot descriptor) | count virtual 512-byte sectors |
| El Torito validation checksum computed with CRC32 instead of a 16-bit word sum | SeaBIOS refused to boot (`code 0008`) | correct word-sum checksum |
| PVD field offsets shifted by one field | firmware rejected the volume | ECMA-119 offsets corrected |
| Boot descriptor `desc_crc` at +100 vs the struct's +96 | diagnostics page showed `crc32 00000000` | offsets pinned with `_Static_assert` |

## 4. Emulated boot — `make boot-test`

```
[PASS] emulator produced a serial log  (2563 bytes)
[PASS] loader banner on serial
[PASS] loader read the ISO9660 volume descriptor
[PASS] loader loaded and verified the kernel image
[PASS] protected-mode handoff
[PASS] 32-bit kernel started
[PASS] kernel reached the end of its boot log
[PASS] genuine PS5 software is not claimed as running
[PASS] kernel mounted the ISO9660 volume through its own block driver
[PASS] kernel read a file back from the medium with a valid signature
[PASS] chain reports a blocked stage with evidence
[PASS] console shadow buffer dumped over serial  (6 dumps)
[PASS] status page renders the compatibility chain
[PASS] status page lists stage 1
[PASS] status page lists the genuine home-screen stage
[PASS] status page shows not-started stages
[PASS] hardware page renders
[PASS] hardware page reports PCI inventory
[PASS] firmware page renders
[PASS] firmware page states the truth about execution
[PASS] diagnostics page renders
[PASS] log page renders
[PASS] diagnostics page reports the kernel storage self-test
[PASS] storage stage evidence names the mounted volume
[PASS] power page renders
PASSED (24 checks)
```

Serial excerpt from the emulated machine (SeaBIOS, 128 MiB, emulated CD-ROM):

```
PC5 loader 0.1.0
pc5: framebuffer 1600x0900
pc5: medium is ISO9660, disk unit bytes 0800
pc5: kernel image verified
pc5: medium volume PC5
pc5: entering 32-bit kernel

PC5 KERNEL 0.1.0 (build 9576ad7, …)
PC5-LOG kernel_entry eip=0x10000
PC5-LOG protocol=1 magic=ok
PC5-LOG display=framebuffer 1600x900 pitch=3200 font=firmware-8x16
PC5-LOG cpu=GenuineIntel family=15 model=6 logical=1 long=0 avx=0
PC5-LOG memory_mib=128 entries=5 top_mib=127
PC5-LOG pci=5 display=1 network=1 storage=1 audio=0 usb=0
PC5-LOG smbios=absent version=0.0
PC5-LOG acpi=absent
PC5-LOG medium_volume=PC5 sectors=47 kernel_lba=27 pvd=ok
PC5-LOG firmware supplied=no note=no firmware image or manifest in this build
PC5-LOG input keyboard=8042-ok
PC5-LOG storage drives=1 selected=0 atapi=1 model=v86 ATAPI CD-ROM
PC5-LOG storage_mounted volume=PC5 blocks=47 file=KERNEL.BIN bytes=36508 signature=ok
PC5-LOG chain_blocked_at=5 stage=PS5 firmware image supplied
PC5-LOG genuine_ps5_execution=no
PC5-BOOT-OK
```

(The emulated CPU reports `family=15 model=6` and no long mode — that is v86's
CPUID, not a real processor. On hardware these fields come from the host.)

## 5. What these results do and do not establish

Established: the image is a valid ISO9660/El Torito medium, its boot descriptor
and kernel extent are consistent and CRC-protected, it boots on an emulated PC,
the kernel runs, inventories the machine, mounts its own medium through its own
ATAPI + ISO9660 code and reads a file back, renders six pages, answers on the
serial console, and reports the PS5 compatibility chain honestly.

Not established: physical hardware boot, any driver on real silicon, UEFI
booting, controller/network/audio support, genuine PS5 firmware execution, PS5
game installation or execution. See `docs/TESTING_STRATEGY.md` for the level
definitions.

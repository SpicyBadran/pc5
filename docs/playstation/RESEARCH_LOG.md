# Research log

Dated entries, newest first. Facts are marked as reported or verified.

## 2026-11-12 — Project start

**Environment verification (verified here).**
Debian 12 x86-64, gcc 12.2.0, binutils 2.40 (emulations `elf_x86_64`,
`elf_i386`, `i386pep`), node 22.22, python 3.11. Absent: `xorriso`,
`genisoimage`, `mtools`, `mkfs.vfat`, `nasm`, `cmake`, `ninja`, `qemu`,
`/dev/kvm`, 32-bit libc headers. Network: `github.com`, `codeload.github.com`,
`api.github.com`, npm and PyPI reachable; `deb.debian.org`, `cdn.kernel.org`,
`archive.ubuntu.com`, `raw.githubusercontent.com` and GitHub release-asset hosts
are not.

Consequences: ISO writer, bootloader and kernel must be written in-tree; boot
testing must use an emulator from npm (`v86-system`); UEFI cannot be executed.

**AnyPS5 (reported by its own sources; metrics verified here).**
Static relinker, GPL-2.0-only, "nothing is emulated" — converts PS5 ELF
executables to native Linux/Windows programs and supplies independent PRX
library implementations. Measured in the supplied archive: 478,791 C/C++ lines,
411 PRX libraries, 5,167 `APS5_EXPORT` NID declarations, 1,686 files with bare
`return 0;` stubs, 857 TODO/UNIMPLEMENTED markers. Cannot be built here (no
CMake, submodules absent). Source: <https://github.com/boykopovar/AnyPS5>.

**PS5 hardware (public documentation).** Custom AMD Zen 2, 8 cores/16 threads up
to 3.5 GHz; custom RDNA 2 GPU, 36 CUs, up to 2.23 GHz (~10.28 TFLOPS); 16 GB
GDDR6 at 448 GB/s; custom 825 GB NVMe SSD with ~5.5 GB/s raw throughput;
Wi-Fi 6, Bluetooth 5.1, Gigabit Ethernet; Tempest 3D audio.
Sources: <https://www.psdevwiki.com/ps5/>, Sony's published specifications,
secondary summaries.

**PS5 package format (reported).** Finalised images use the magic `\x7fFIH`
(little endian) with the PFS image at 0x10000; metadata container magic
`\x7fCNT` (big endian, shared with PS4); PFS is AES-XTS over 0x1000-byte
sectors with a Merkle tree for integrity.
Sources: <https://github.com/SvenGDK/LibProsperoPKG/blob/main/docs/ps5-pkg-format.md>,
<https://www.psdevwiki.com/ps5/Package_Files>.

**PS5 firmware update container (reported).** Sony documents the USB layout
`PS5/UPDATE/PS5UPDATE.PUP` and the ~1.1 GB update / ~1.2 GB+ reinstall sizes.
Community analysis reports an outer container beginning with `SLB2`, containing
`PS5UPDATE1.PUP` / `PS5UPDATE2.PUP`, with a plaintext header and signed or
encrypted entries whose layout is version specific; one thread explicitly notes
that a modified PUP must still pass authentication.
Sources: <https://www.playstation.com/en-us/support/hardware/ps5/system-software/>,
<https://gbatemp.net/threads/built-a-pc-based-pup-decrypt-tool-one-key-away-from-decrypting-any-firmware-forever-need-someone-on-13-60-to-run-an-extraction-payload.685380/>,
<https://github.com/ZigZagBoi1/PS5-14.10-Research/issues/73>.

**Conclusion recorded.** No public, verified path exists from generic x86
hardware to genuine PS5 system-software execution; the console security
processor roots that trust. PC5 therefore separates a firmware path (BLOCKED,
documented) from an execution path for PS5 binaries (researchable, legitimate
inputs) and never reports one as the other.

## Open questions

1. Exact `SLB2` entry-table layout per firmware version (needs a supplied image;
   currently unverified).
2. Which PS5 system services are reachable from user space without console
   hardware (unknown; no authorised interface documented publicly).
3. Whether the relinking approach scales to retail titles: depends on PRX
   coverage and GPU translation, both unmeasured by PC5.
4. DualSense input report layout for adaptive triggers and haptics beyond the
   documented HID descriptors (HID reports are public; effect semantics need
   hardware testing).

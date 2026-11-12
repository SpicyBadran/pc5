# Building PC5

## Requirements

| Component | Version used | Notes |
|---|---|---|
| `gcc` | 12.2.0 | must support `-m32` code generation (no 32-bit libc needed) |
| `binutils` | 2.40 | `as` with `.code16/.code32`, `ld` with `elf_i386` and `--oformat binary` |
| `make` | GNU make | top-level `Makefile` |
| `python3` | 3.11 | ISO writer, verifier, firmware tool, tests |
| `node` + `v86-system` | node 22 | only for `make boot-test` (`npm install v86-system`) |

No other dependency is required: the build does not use a cross compiler, a
distribution tool, or network access.

## Targets

```sh
make info        # version, build id, timestamp, source list
make             # build/pc5.iso, build/pc5.iso.sha256, build/build-info.json
make unit        # host-side kernel unit tests (32 checks)
make check       # unit tests + python test suite
make verify      # independent ISO verification
make boot-test   # boot the ISO in the emulator and assert the interface
make clean
```

## Reproducibility

The build is deterministic except for the timestamp, which is taken from
`SOURCE_DATE_EPOCH` when set:

```sh
SOURCE_DATE_EPOCH=1700000000 make clean iso
sha256sum build/pc5.iso
```

The ISO writer allocates every extent by a fixed rule, so nothing depends on
file system order. `build/build-info.json` records the volume layout, the
per-file SHA-256 values and the image SHA-256 that `make verify` re-checks.

To confirm byte-identical output:

```sh
SOURCE_DATE_EPOCH=1700000000 make clean iso && sha256sum build/pc5.iso
SOURCE_DATE_EPOCH=1700000000 make clean iso && sha256sum build/pc5.iso
```

(Two builds with the same epoch produce the same digest; the boot descriptor
contains no timestamp.)

## Layout

```
boot/loader.S        stage-1 loader (real mode, 4096 bytes, descriptor at 0xE00)
kernel/              freestanding 32-bit kernel (see docs/ARCHITECTURE.md)
tools/               ISO writer, verifier, firmware analysis, operator CLI
tests/               emulator harness, boot assertions, host + kernel unit tests
docs/                engineering documentation
build/               generated; not committed
```

## Adding a file to the ISO

`make iso` passes `--file NAME=PATH` to `tools/mkiso.py`. File names are
normalised to ISO9660 level 1 (`NAME.EXT;1`) and must fit one 2048-byte root
directory sector — the writer fails the build rather than writing a broken
volume.

## Build guard rails

* loader must be exactly 4096 bytes (the boot descriptor offset is compiled in),
* kernel must be ≤ 585,728 bytes (real-mode load window),
* `tools/mkiso.py` refuses to write past the end of the image and asserts the
  final size,
* `make verify` re-parses the finished image from scratch.

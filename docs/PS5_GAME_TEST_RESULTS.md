# PS5 game test results

## Method

Every row requires: the title, the executable's SHA-256, the mechanism used to
execute it, the host configuration, the observed behaviour, the log, and the
status from the vocabulary in `docs/GAMING_COMPATIBILITY.md`.

A title is only added once it has actually been attempted. No title has been
attempted, so the table is empty.

## Results

| Title | Title ID | Mechanism | Host | Status | Notes / evidence |
|---|---|---|---|---|---|
| — | — | — | — | *no tests performed* | no PS5 executable has been executed by PC5 |

## Why the table is empty

1. No PS5 game package or executable was supplied to this project.
2. PC5 has no package parser in the kernel and no storage driver, so it cannot
   read a package from a medium yet.
3. The execution route (relinking PS5 binaries) requires the AnyPS5 toolchain,
   which cannot be built in this environment (no CMake, submodules not
   vendored), and requires a decrypted executable the owner must provide
   lawfully.

Recording anything here before those are true would be fabrication. The
Diagnostics and Status pages exist precisely so that the state of the machine is
visible instead.

## What will appear first, and when

The first realistic entry is a PS5 **homebrew** ELF (a legally distributable
test binary), executed through the relinking path on a Linux host, with:

* `Mechanism` = "AnyPS5 relinker + host PRX libraries, PC5 test host",
* `Status` = BOOTS or REACHES GAMEPLAY,
* `Notes` = the exact relinker version, the host kernel/GPU, and the log.

Retail titles come later and are marked per the same vocabulary.

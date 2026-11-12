# Recovery

## 1. Nothing is written, so nothing breaks

PC5 currently boots and runs entirely from the medium. It does not partition,
format, or write to any disk. "Recovery" therefore means getting back to a
working image, not restoring data.

## 2. Recovering a machine that will not boot PC5

1. Power off, remove the medium.
2. Boot the machine normally. If the firmware boot order was changed, reset it
   (or use the firmware's one-time boot menu).
3. Re-flash the medium: `python3 tools/pc5ctl.py usb --iso build/pc5.iso
   --device /dev/sdX --yes` — the tool re-verifies the checksum first.
4. If the machine offers CSM/legacy boot, make sure it is enabled; the current
   image is BIOS-only.

`docs/INSTALLATION.md` has the full flashing and troubleshooting matrix,
including the meaning of each loader failure code.

## 3. Recovery console (in the boot environment)

The serial port is a first-class console: COM1, 115200 8N1, 8 data bits, no
parity, 1 stop bit. It mirrors the boot log (every line beginning `PC5-LOG`) and
accepts commands at the `pc5>` prompt:

| Command | Effect |
|---|---|
| `status` | version, display, keyboard, CPU, RAM, PCI count |
| `chain` | all 13 compatibility stages with state and the blocked-stage evidence |
| `hw` | CPU, memory, PCI classes, GPU/NIC descriptors, SMBIOS system identity |
| `fw` | firmware probe result and an explicit `genuine_ps5_execution=running=no` line |
| `storage` | drives found on the legacy ATA channels, mounted volume, read-back result |
| `diag` | the self-test summary as one line |
| `log` | the in-memory boot log |
| `screen` | dump of the rendered character grid, so a headless machine can be inspected |
| `page N` | switch the on-screen page |
| `reboot` | 8042 reset line |
| `halt` | stop the CPU (safe to power off) |

This exists because a machine with a broken display, a wrong framebuffer mode or
a firmware quirk is exactly when you need the log.

## 4. Recovery of the build environment

```sh
make clean && make && make verify && make check
```

If `make boot-test` cannot find the emulator: `npm install v86-system` (or set
`V86_ASSETS`). If a boot test fails, `build/test/serial.log` and
`build/test/screens.txt` contain what the machine actually did.

## 5. Planned recovery environment

A dedicated recovery entry (separate boot option, minimal kernel, disk tools,
update rollback) is on the roadmap once the installer exists. It cannot be
built before there is storage support, because recovery without disk access
would be a menu of buttons that do nothing.

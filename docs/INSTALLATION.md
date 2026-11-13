# Installing and booting PC5

## 1. Get the image

```sh
gh release download --repo SpicyBadran/pc5       # or build it: see docs/BUILDING.md
ls                     # pc5.iso  pc5.iso.sha256  build-info.json
sha256sum -c pc5.iso.sha256
```

Release assets are produced by the CI pipeline from the tagged commit, never
uploaded by hand. `build-info.json` records the layout, per-file hashes and the
build provenance (commit, toolchain, and the result of each test that ran);
`python3 tools/verify_iso.py pc5.iso --info build-info.json` re-checks the image
independently.

## 2. Write it to a USB stick

Safety rules enforced by `pc5ctl usb`:

* the checksum is re-verified before writing,
* the target must be a `/dev/` block device that exists,
* the device holding `/` is refused,
* nothing is written without `--yes`.

```sh
python3 tools/pc5ctl.py usb --iso build/pc5.iso --device /dev/sdX
# check the device path twice, then:
python3 tools/pc5ctl.py usb --iso build/pc5.iso --device /dev/sdX --yes
```

Or use a graphical imager (balenaEtcher, Rufus in DD mode, `dd` directly).

**Important, and honest:** the current image carries a *BIOS/El Torito* boot
path only. It boots from CD/DVD and from USB media that the firmware presents
as a CD-ROM class device. It is **not** isohybrid — there is no MBR for
firmware that insists on booting a USB stick as a hard disk. If your machine
only offers UEFI, or boots USB sticks strictly as HDDs, the image will not
start yet; see `docs/KNOWN_LIMITATIONS.md`. Writing the ISO to a stick is safe
(the image is read-only in this respect), but it may not boot.

## 3. Boot the machine

1. Enter the firmware setup, enable legacy/CSM boot (needed for the current
   BIOS path), and disable Secure Boot (PC5 has no signed shim yet).
2. Select the USB device or CD/DVD drive as the boot device.
3. The PC5 boot environment starts on the Status page.

Expected boot log on COM1 (115200 8N1):

```
PC5 loader 0.1.0
pc5: framebuffer 1024x0768
pc5: medium is ISO9660, disk unit bytes 0800
pc5: kernel image verified
pc5: medium volume PC5
pc5: entering 32-bit kernel
PC5 KERNEL 0.1.0 …
PC5-LOG …
PC5-BOOT-OK
```

## 4. Using the environment

| Input | Action |
|---|---|
| ↑ / ↓ | move through the compatibility chain |
| 1 – 6 | switch page (Status, Hardware, Firmware, Diagnostics, Log, Power) |
| R / H | reboot / halt (Power page) |
| serial `help` | list console commands |

The serial console accepts: `status`, `chain`, `hw`, `fw`, `diag`, `log`,
`screen`, `page N`, `reboot`, `halt`.

## 5. Troubleshooting

| Symptom | Meaning | What to do |
|---|---|---|
| `Boot failed: Could not read from CDROM` | firmware rejected the El Torito catalog | verify the image with `make verify`; re-flash |
| `pc5: fatal: A20 gate did not open` | firmware/CPU issue | report the host; try another machine |
| `pc5: fatal: kernel load failed` followed by numbers | disk read error (`LBA sectors AH dest first-dword`) | the medium is unreadable at the kernel extent; re-flash |
| `pc5: VBE unavailable, using text mode` | no linear-framebuffer mode was offered | not fatal: the VGA text UI is used |
| Screen blank but serial log complete | framebuffer address wrong on this firmware | report with the `PC5-LOG display=` line |
| Nothing at all | machine booted UEFI only | legacy/CSM is required today |

## 6. Removing PC5

There is no installer yet: PC5 runs entirely from the medium and writes nothing
to the host. Remove the USB stick, or restore the firmware boot order.

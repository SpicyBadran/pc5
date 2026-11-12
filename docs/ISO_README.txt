PC5 — PlayStation 5 compatibility project
=========================================

This medium contains the PC5 boot environment.

What it is
----------
A bootable PC environment that initialises the machine, inventories its
hardware, and reports exactly how far PC5 has got towards executing genuine
PlayStation 5 system software.  It is the honest diagnostic and development
front end of the project.

What it is NOT
--------------
This image does not contain, and cannot execute, Sony PlayStation 5 system
software.  PC5 does not redistribute Sony firmware.  If the machine boots and
you see the PC5 boot environment, genuine PS5 software is NOT running — the
Status page says so explicitly, with the measured reason.

Boot it
-------
1. Verify the image:  sha256sum -c pc5.iso.sha256
2. Write it to a USB stick:  sudo dd if=pc5.iso of=/dev/sdX bs=4M status=progress
   (or use balenaEtcher / Rufus / Ventoy in ISO mode)
3. Boot the machine from the USB stick in UEFI or legacy/BIOS mode.
4. The environment starts on the Status page.  Arrow keys or 1-6 switch pages.
5. The serial console (COM1, 115200 8N1) carries the same boot log and accepts
   commands: status, chain, hw, fw, diag, log, reboot, halt.

Full documentation: https://github.com/SpicyBadran/pc5

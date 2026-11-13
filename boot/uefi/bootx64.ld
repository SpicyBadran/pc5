/*
 * PC5 UEFI loader link map.
 *
 * The output is a PE32+ EFI application (binutils emulation i386pep), which is
 * what firmware's LoadImage expects for x86-64.  Three details matter:
 *
 *   - `.text` must start at ImageBase + section alignment.  The PE emulation
 *     in binutils places the first section at `__image_base__ + .` where `.`
 *     is the current location counter; writing the expression below is the
 *     documented way to get a normal, non-overlapping image.
 *   - `.reloc` must exist, because firmware relocates the image to wherever
 *     it decides to load it.  `--enable-reloc-section` fills it in from the
 *     32-bit absolute relocations the compiler emits with -fno-pic.
 *   - `.bss` is NOLOAD: the file does not carry it, so the entry stub zeroes
 *     it.  Firmware does not.
 *
 * Nothing here is 16-bit: the application is pure 64-bit code until the
 * handover stub switches to 32-bit protected mode for the kernel.
 */
OUTPUT_FORMAT(pei-x86-64)
ENTRY(_start)

SECTIONS
{
    . = SIZEOF_HEADERS;
    . = ALIGN(0x1000);

    .text __image_base__ + 0x1000 : {
        *(.text)
        *(.text.*)
    }

    .data : {
        *(.data)
        *(.data.*)
    }

    .rdata : {
        *(.rdata)
        *(.rdata.*)
        *(.rodata)
        *(.rodata.*)
    }

    .bss : {
        __bss_start = .;
        *(.bss)
        *(.bss.*)
        *(COMMON)
        __bss_end = .;
    }

    .reloc : {
        *(.reloc)
    }

    /DISCARD/ : {
        *(.comment)
        *(.note*)
        *(.eh_frame*)
        *(.pdata)
        *(.xdata)
        *(.idata)
    }
}

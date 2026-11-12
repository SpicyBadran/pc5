/* PC5 kernel link map: a flat image loaded at 1 MiB - 960 KiB = 0x10000.
 * The loader reads the file straight to 0x10000, so the first byte of the
 * image must be the entry stub (see start.S, which also carries the "PC5K"
 * signature the loader verifies). */
OUTPUT_FORMAT(bINARY)
ENTRY(_start)
SECTIONS
{
    . = 0x10000;
    .text : {
        *(.text.start)
        *(.text*)
    }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    __bss_start = .;
    .bss : {
        *(.bss*)
        *(COMMON)
    }
    __bss_end = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.note.gnu.property) }
}

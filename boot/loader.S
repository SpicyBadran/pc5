/*
 * PC5 stage-1 loader (x86 real mode, BIOS).
 *
 * Booted by the firmware through the El Torito no-emulation entry written by
 * tools/mkiso.py, so the *whole* image is already loaded contiguously at
 * 07C0:0000 before the first instruction runs.  The loader therefore needs no
 * disk reads for its own code; it uses the BIOS for the things only firmware
 * can do on this path, then hands a fully described machine to the 32-bit PC5
 * kernel:
 *
 *   1. serial console (COM1), so the boot log survives a blank screen
 *   2. A20 gate
 *   3. INT 15h E820 memory map
 *   4. the video BIOS 8x16 character font (needed by the framebuffer console)
 *   5. a VBE linear-framebuffer mode, with a text-mode fallback
 *   6. ISO9660 primary volume descriptor (proof that the medium is readable)
 *   7. the kernel image, read with INT 13h extensions
 *   8. protected mode and a jump to the kernel, passing a boot-info pointer
 *
 * Every failure is reported on serial and on screen with a distinct code;
 * the loader never pretends a stage succeeded.
 *
 * Memory use in the low 1 MiB (fixed contract with the kernel, see
 * kernel/include/pc5.h):
 *   0x2000  E820 entries        (up to 40 x 24 bytes)
 *   0x2500  VBE controller info
 *   0x2600  copied VBE mode list
 *   0x2800  VBE mode info block
 *   0x2900  8x16 font, 256 chars
 *   0x3A00  ISO9660 primary volume descriptor
 *   0x4000  struct pc5_boot_info
 *   0x4400  disk address packet
 *   0x10000 kernel image (up to 0x8F000 = 572 KiB)
 *   0x9F000 loader stack top
 */

    .set BOOT_INFO,     0x4000
    .set E820_BUF,      0x2000
    .set E820_MAX,      40
    .set VBE_CTRL,      0x2500
    .set VBE_MODES,     0x2600
    .set VBE_MODE,      0x2800
    .set FONT_BUF,      0x2900
    .set PVD_BUF,       0x3A00
    .set DAP,           0x4400
    .set KERNEL_ADDR,   0x10000
    .set KERNEL_LIMIT,  0x8F000

    .set DESC_MAGIC,    0x314f4f425043ULL /* not used; kept for reference */

    .code16
    .section .text
    .globl _start
_start:
    cli
    xorw %ax, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %ss
    movw %ax, %fs
    movw %ax, %gs
    movw $0x9F00, %sp
    sti
    cld
    movb %dl, boot_drive

    call serial_init
    movw $s_banner, %si
    call puts

    /* ---------------------------------------------------------- A20 ---- */
    call a20_enable
    testw %ax, %ax
    jz err_a20

    /* ------------------------------------------- firmware font first --- */
    call copy_font

    /* --------------------------------------------------------- E820 ---- */
    call e820_scan

    /* ---------------------------------------------------------- VBE ---- */
    call vbe_setup

    /* --------------------------------- ISO9660 volume descriptor ------ */
    call read_pvd

    /* ------------------------------------------------- kernel image ---- */
    call load_kernel

    /* --------------------------------------------- boot info block ----- */
    call build_boot_info

    /* ------------------------------------------- last words, then PM -- */
    movw $s_volume, %si
    call puts
    movw $BOOT_INFO+52, %si
    call puts_tail
    movw $s_enter, %si
    call puts
    jmp enter_pmode

/* ==================================================================== */
/* serial                                                               */
/* ==================================================================== */
serial_init:
    pushw %ax
    pushw %dx
    movw $0x3f9, %dx
    xorb %al, %al
    outb %al, %dx           /* IER = 0 */
    movw $0x3fb, %dx
    movb $0x80, %al
    outb %al, %dx           /* DLAB on */
    movw $0x3f8, %dx
    movb $0x01, %al
    outb %al, %dx           /* divisor low: 115200 */
    movw $0x3f9, %dx
    xorb %al, %al
    outb %al, %dx           /* divisor high */
    movw $0x3fb, %dx
    movb $0x03, %al
    outb %al, %dx           /* 8N1, DLAB off */
    movw $0x3fa, %dx
    movb $0xc7, %al
    outb %al, %dx           /* FIFO enable+clear */
    movw $0x3fc, %dx
    movb $0x03, %al
    outb %al, %dx           /* DTR + RTS */
    popw %dx
    popw %ax
    ret

putc_serial:
    pushw %ax
    pushw %dx
    pushw %bx
    movw %ax, %bx
1:  movw $0x3fd, %dx
    inb %dx, %al
    testb $0x20, %al
    jz 1b
    movw %bx, %ax
    movw $0x3f8, %dx
    outb %al, %dx
    popw %bx
    popw %dx
    popw %ax
    ret

/* SI = NUL terminated string */
puts:
    pushw %ax
    pushw %si
1:  lodsb
    testb %al, %al
    jz 2f
    call putc_serial
    jmp 1b
2:  popw %si
    popw %ax
    ret

/* SI = fixed 24 byte, NUL padded field */
puts_tail:
    pushw %cx
    pushw %si
    movw $24, %cx
1:  lodsb
    testb %al, %al
    jz 2f
    call putc_serial
    loop 1b
2:  popw %si
    popw %cx
    ret

/* AL = byte to print as two hex digits */
phex8:
    pushw %ax
    movb %al, %bl
    shrb $4, %al
    call phex_nib
    movb %bl, %al
    andb $0x0f, %al
    call phex_nib
    popw %ax
    ret
phex_nib:
    cmpb $10, %al
    jb 1f
    addb $('a'-10), %al
    jmp 2f
1:  addb $'0', %al
2:  call putc_serial
    ret

/* AH = fatal code; SI = message.  Switch to text mode and stop. */
fatal:
    movw %si, %si
    call puts
    movw $s_halt, %si
    call puts
    /* text mode so the message is visible on a physical screen */
    movw $0x0003, %ax
    int $0x10
    movw $0xb800, %ax
    movw %ax, %es
    xorw %di, %di
    movw $s_fatal_prefix, %si
1:  lodsb
    testb %al, %al
    jz 2f
    movb $0x4f, %ah
    stosw
    jmp 1b
2:  movw $s_halt, %si
3:  lodsb
    testb %al, %al
    jz 4f
    movb $0x4f, %ah
    stosw
    jmp 3b
4:  cli
5:  hlt
    jmp 5b

err_a20:
    movw $s_e_a20, %si
    jmp fatal

/* ==================================================================== */
/* A20                                                                  */
/* ==================================================================== */
a20_test:
    pushw %ds
    pushw %es
    pushw %si
    pushw %di
    pushw %bx
    xorw %ax, %ax
    movw %ax, %ds
    movw %ax, %es
    movw 0x0500, %bx        /* saved value */
    movw $0x1234, 0x0500
    movw $0xffff, %ax
    movw %ax, %es
    movw $0x0510, %di       /* physical 0x100500 */
    movw %es:(%di), %ax
    movw %bx, 0x0500
    cmpw $0x1234, %ax
    je 1f                   /* still reads back: A20 is off */
    movw $1, %ax
    jmp 2f
1:  xorw %ax, %ax
2:  popw %bx
    popw %di
    popw %si
    popw %es
    popw %ds
    ret

a20_enable:
    pushw %bx
    movw $0x2401, %ax
    int $0x15
    call a20_test
    testw %ax, %ax
    jnz 9f
    /* fast A20 */
    inb $0x92, %al
    testb $0x02, %al
    jnz 1f                  /* already set, avoid clearing bit 0 */
    orb $0x02, %al
    outb %al, $0x92
1:  call a20_test
9:  popw %bx
    ret

/* ==================================================================== */
/* firmware 8x16 font                                                   */
/* ==================================================================== */
copy_font:
    movw $0, %ax
    movw %ax, %es
    movw $0x1130, %ax
    movw $0x0600, %bx       /* BH=6 -> 8x16 font, BL=0 -> int 1Fh */
    int $0x10
    testw %bp, %bp
    jz 9f                   /* no font: kernel falls back to text mode */
    movw %cx, font_bpc
    movw %bp, %si
    pushw %ds
    movw %es, %ax
    movw %ax, %ds           /* DS:SI = font in ROM */
    xorw %ax, %ax
    movw %ax, %es
    movw $FONT_BUF, %di
    movw %cx, %ax
    shlw $8, %ax            /* 256 characters */
    movw %ax, %cx
    rep movsb
    popw %ds
9:  ret

/* ==================================================================== */
/* E820                                                                 */
/* ==================================================================== */
e820_scan:
    pushw %es
    pushw %di
    pushw %bx
    pushw %bp
    xorw %ax, %ax
    movw %ax, %es
    movw $E820_BUF, %di
    xorl %ebx, %ebx
    xorl %ebp, %ebp
1:  movl $0xE820, %eax
    movl $0x534d4150, %edx
    movl $24, %ecx
    int $0x15
    jc 2f
    cmpl $0x534d4150, %eax
    jne 2f
    testl %ecx, %ecx
    jz 2f
    incl %ebp
    addw $24, %di
    testl %ebx, %ebx
    jz 2f
    cmpw $E820_MAX, %bp
    jb 1b
2:  movw %bp, e820_count
    popw %bp
    popw %bx
    popw %di
    popw %es
    ret

/* ==================================================================== */
/* VBE                                                                  */
/* ==================================================================== */
vbe_setup:
    movw $0, %ax
    movw %ax, %es
    movw $VBE_CTRL, %di
    movl $0x32454256, %es:(%di)      /* 'VBE2': request VBE 2.0+ fields */
    movw $0x4f00, %ax
    int $0x10
    movw %ax, vbe_err
    cmpw $0x004f, %ax
    jne vbe_fallback
    cmpl $0x41534556, VBE_CTRL       /* 'VESA' signature present? */
    jne vbe_fallback

    /* copy the mode list out of firmware memory into our own buffer; both
       halves of the far pointer must be read before DS is repointed */
    movw VBE_CTRL+0x0e, %si          /* mode list offset  */
    movw VBE_CTRL+0x10, %dx          /* mode list segment */
    xorw %ax, %ax
    movw %ax, %es
    movw $VBE_MODES, %di
    pushw %ds
    movw %dx, %ds
    movw $256, %cx
1:  lodsw
    stosw
    cmpw $0xffff, %ax
    je 2f
    loop 1b
    movw $0xffff, %es:-2(%di)
2:  popw %ds
    xorw %ax, %ax
    movw %ax, %ds

    movw $0xffff, best_mode
    movl $0, best_score
    movw $0, modes_seen
    movw $0, modes_lfb
    movw $VBE_MODES, %si
1:  movw (%si), %cx
    cmpw $0xffff, %cx
    je 3f
    incw modes_seen
    addw $2, %si
    movw %si, mode_cursor
    movw $VBE_MODE, %di
    movw $0x4f01, %ax
    int $0x10
    movw mode_cursor, %si
    cmpw $0x004f, %ax
    jne 1b
    /* linear framebuffer available? */
    movw VBE_MODE+0x00, %ax
    testw $0x0010, %ax
    jz 1b
    incw modes_lfb
    /* only direct colour modes we can render into */
    movb VBE_MODE+0x1b, %al           /* memory model: 4 packed, 6 direct */
    cmpb $4, %al
    je 7f
    cmpb $6, %al
    jne 1b
7:
    movb VBE_MODE+0x19, %al           /* bits per pixel */
    cmpb $32, %al
    je 4f
    cmpb $24, %al
    je 4f
    cmpb $16, %al
    jne 1b
4:  movw VBE_MODE+0x12, %ax           /* width */
    cmpw $800, %ax
    jb 1b
    cmpw $1600, %ax
    ja 1b
    movw VBE_MODE+0x14, %dx           /* height */
    cmpw $600, %dx
    jb 1b
    cmpw $1200, %dx
    ja 1b
    /* score = width*height, with a bonus for 32bpp */
    pushw %dx
    movzwl %ax, %eax
    movzwl %dx, %edx
    imull %edx, %eax
    movb VBE_MODE+0x19, %dl
    cmpb $32, %dl
    jne 5f
    shll $1, %eax                     /* prefer 32bpp at equal area */
5:  cmpl best_score, %eax
    jbe 6f
    movl %eax, best_score
    movw (%si), %ax
    movw %ax, best_mode
6:  popw %dx
    jmp 1b

3:  movw best_mode, %cx
    cmpw $0xffff, %cx
    je vbe_fallback
    orw $0x4000, %cx                  /* use the linear framebuffer */
    movw $0x4f02, %ax
    int $0x10
    cmpw $0x004f, %ax
    jne vbe_fallback
    /* re-read the mode info: firmwares disagree about pre-set fields */
    movw best_mode, %cx
    movw $VBE_MODE, %di
    movw $0x4f01, %ax
    int $0x10
    movw $1, vbe_ok
    movw $s_vbe_ok, %si
    call puts
    movw VBE_MODE+0x12, %ax
    call phex16
    movw $'x', %ax
    call putc_serial
    movw VBE_MODE+0x14, %ax
    call phex16
    movw $s_nl, %si
    call puts
    ret

vbe_fallback:
    movw $s_vbe_modes, %si
    call puts
    movzwl modes_seen, %eax
    call phex16
    movw $s_sp, %si
    call puts
    movzwl modes_lfb, %eax
    call phex16
    movw $s_sp, %si
    call puts
    movzwl best_mode, %eax
    call phex16
    movw $s_nl, %si
    call puts
    movw $0, vbe_ok
    movw $0x0003, %ax
    int $0x10
    movw $s_vbe_fail, %si
    call puts
    movw vbe_err, %ax
    call phex16
    movw $s_nl, %si
    call puts
    ret

phex32:
    pushl %eax
    shrl $16, %eax
    call phex16
    popl %eax
    pushl %eax
    andl $0xffff, %eax
    call phex16
    popl %eax
    ret

phex16:
    pushw %ax
    movb %ah, %al
    call phex8
    popw %ax
    pushw %ax
    call phex8
    popw %ax
    ret

/* ==================================================================== */
/* disk access (INT 13h extensions)                                     */
/* ==================================================================== */
/*
 * Disk reads through INT 13h extensions.
 *
 * A CD-ROM is addressed in 2048-byte units and a hard disk (including a USB
 * stick flashed with this image) in 512-byte units, and firmware gives no
 * reliable way to ask which one we booted from.  The loader therefore probes:
 * it reads the ISO9660 volume descriptor both ways and keeps the unit size
 * that produced a valid "CD001" signature.  Every later read uses the probe
 * result, so the same loader works from a CD and from a USB stick.
 */

/* EAX = LBA in units, CX = unit count, EBX = destination physical address.
   Returns with CF set on failure. */
disk_read_chunk:
    pushw %ax
    pushw %bx
    pushw %cx
    pushl %edx
    pushl %ebx
    pushl %eax

    movw %cx, DAP+2
    movl %ebx, %edx
    shrl $4, %edx
    movw %dx, DAP+6          /* segment */
    movl %ebx, %edx
    andl $0x0f, %edx
    movw %dx, DAP+4          /* offset  */
    movzwl %ax, %edx
    movl %edx, DAP+8         /* LBA low 32 bits */
    shrl $16, %eax
    movl %eax, DAP+12        /* LBA high 16 bits */

    movw $3, retries
1:  movw $DAP, %si
    movb boot_drive, %dl
    movw $0x4200, %ax
    int $0x13
    jnc 3f
    pushw %ax
    call disk_reset
    popw %ax
    decw retries
    jnz 1b
    movb %ah, disk_err
    stc
    jmp 4f
3:  clc
4:  popl %eax
    popl %ebx
    popl %edx
    popw %cx
    popw %bx
    popw %ax
    ret

disk_reset:
    pushw %ax
    pushw %dx
    movb boot_drive, %dl
    xorb %ah, %ah
    int $0x13
    popw %dx
    popw %ax
    ret

/* read the ISO9660 primary volume descriptor and lock in the unit size */
read_pvd:
    movl $16, %eax           /* LBA 16 in 2048-byte units */
    movw $1, %cx
    movl $PVD_BUF, %ebx
    call disk_read_chunk
    jc 1f
    cmpl $0x30304443, PVD_BUF+1     /* 'CD001' */
    jne 1f
    movl $2048, unit_bytes
    jmp 2f
1:  movl $64, %eax           /* LBA 16 * 4 in 512-byte units */
    movw $4, %cx
    movl $PVD_BUF, %ebx
    call disk_read_chunk
    jc 3f
    cmpl $0x30304443, PVD_BUF+1
    jne 3f
    movl $512, unit_bytes
2:  movw $1, pvd_ok
    movw $s_pvd_ok, %si
    call puts
    movl unit_bytes, %eax
    call phex16
    movw $s_nl, %si
    call puts
    ret
3:  movw $0, pvd_ok
    movw $s_pvd_fail, %si
    call puts
    ret

/* ==================================================================== */
/* kernel image                                                         */
/* ==================================================================== */
load_kernel:
    /* logical block address of the kernel file, converted to disk units */
    movl boot_desc+8, %eax
    cmpl $2048, unit_bytes
    je 1f
    shll $2, %eax            /* 2048 -> 512 byte units */
1:  movl %eax, read_lba
    movl boot_desc+12, %eax  /* size in bytes */
    movl %eax, kernel_bytes

    /* number of disk units to read */
    movl unit_bytes, %ecx
    addl %ecx, %eax
    decl %eax
    xorl %edx, %edx
    divl %ecx
    movl %eax, read_sectors
    movl $KERNEL_ADDR, %eax
    movl %eax, read_dest

    /* maximum units per BIOS call: 32 KiB */
    movl $32768, %eax
    xorl %edx, %edx
    divl %ecx
    movl %eax, max_chunk

1:  movl read_sectors, %eax
    testl %eax, %eax
    jz 5f
    cmpl max_chunk, %eax
    jbe 2f
    movl max_chunk, %eax
2:  movl %eax, this_chunk
    movl read_lba, %eax
    movl this_chunk, %ecx
    movl read_dest, %ebx
    call disk_read_chunk
    jc err_kernel
    /* advance by this_chunk * unit_bytes */
    /* read_lba is already in disk units; read_dest advances in bytes.
     * (Multi-chunk loads only happen above 16 disk units, which is why this
     * went unnoticed until the kernel image grew past 32 KiB.) */
    movl this_chunk, %eax
    addl %eax, read_lba
    mull unit_bytes
    addl %eax, read_dest
    movl this_chunk, %eax
    subl %eax, read_sectors
    cmpl $KERNEL_LIMIT, read_dest
    ja err_kernel
    jmp 1b

5:  /* verify the kernel image signature */
    movl $KERNEL_ADDR, %ebx
    cmpb $'P', 2(%ebx)
    jne err_kernel
    cmpb $'C', 3(%ebx)
    jne err_kernel
    cmpb $'5', 4(%ebx)
    jne err_kernel
    cmpb $'K', 5(%ebx)
    jne err_kernel
    movw $s_kernel_ok, %si
    call puts
    ret

err_kernel:
    movw $s_e_kernel, %si
    call puts
    movl read_lba, %eax
    call phex16
    movw $s_sp, %si
    call puts
    movl read_sectors, %eax
    call phex16
    movw $s_sp, %si
    call puts
    movl read_dest, %eax
    call phex16
    movw $s_sp, %si
    call puts
    movzwl disk_err, %eax
    call phex16
    movw $s_sp, %si
    call puts
    movl $KERNEL_ADDR, %ebx
    movl (%ebx), %eax
    call phex32
    movw $s_nl, %si
    call puts
    jmp fatal

/* ==================================================================== */
/* boot info                                                            */
/* ==================================================================== */
build_boot_info:
    movl $0x42354350, BOOT_INFO+0        /* 'PC5B' */
    movl $1, BOOT_INFO+4                 /* protocol version */
    movzwl boot_drive, %eax
    movl %eax, BOOT_INFO+8
    movl $E820_BUF, BOOT_INFO+12
    movzwl e820_count, %eax
    movl %eax, BOOT_INFO+16
    movl $VBE_MODE, BOOT_INFO+20
    movzwl vbe_ok, %eax
    movl %eax, BOOT_INFO+24
    movl $FONT_BUF, BOOT_INFO+28
    movzwl font_bpc, %eax
    movl %eax, BOOT_INFO+32
    movl $PVD_BUF, BOOT_INFO+36
    movzwl pvd_ok, %eax
    movl %eax, BOOT_INFO+40
    movl kernel_bytes, %eax
    movl %eax, BOOT_INFO+44
    movl boot_desc+8, %eax
    movl %eax, BOOT_INFO+48

    /* descriptor integrity: copy the basic fields for the kernel and
       record whether the descriptor CRC matches what mkiso wrote */
    movl boot_desc+60, %eax
    movl %eax, BOOT_INFO+96
    movl $0, BOOT_INFO+100

    /* copy the 24 byte volume id + iso sector count from the descriptor */
    movw $boot_desc+36, %si
    movw $BOOT_INFO+52, %di
    movw $12, %cx
    rep movsw
    movl boot_desc+24, %eax
    movl %eax, BOOT_INFO+76

    /* loader version string */
    movw $loader_version, %si
    movw $BOOT_INFO+80, %di
    movw $8, %cx
    rep movsw
    ret

/* ==================================================================== */
/* protected mode                                                       */
/* ==================================================================== */
enter_pmode:
    cli
    lgdt gdt_ptr
    movl %cr0, %eax
    orl $0x00000001, %eax
    movl %eax, %cr0
    /* 32-bit far jump, encoded by hand: the operand-size prefix makes the
       CPU read a 32-bit offset, which GAS will not emit from a 16-bit ljmp */
    .byte 0x66, 0xea
    .long pm_entry
    .word 0x08

    .code32
pm_entry:
    movw $0x10, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %fs
    movw %ax, %gs
    movw %ax, %ss
    movl $0x9f000, %esp
    movl $BOOT_INFO, %ebx
    ljmp $0x08, $KERNEL_ADDR

/* ==================================================================== */
/* data                                                                 */
/* ==================================================================== */
    .code16
    .balign 4
gdt_start:
    .quad 0
    .quad 0x00cf9a000000ffff        /* code: base 0, limit 4 GiB, 32-bit */
    .quad 0x00cf92000000ffff        /* data: base 0, limit 4 GiB */
gdt_end:
gdt_ptr:
    .word gdt_end - gdt_start - 1
    .long gdt_start

boot_drive:     .byte 0
e820_count:     .word 0
vbe_ok:         .word 0
pvd_ok:         .word 0
best_mode:      .word 0xffff
best_score:     .long 0
vbe_err:        .word 0
mode_cursor:    .word 0
modes_seen:     .word 0
modes_lfb:      .word 0
retries:        .word 0
font_bpc:       .word 16
kernel_bytes:   .long 0
read_lba:       .long 0
read_sectors:   .long 0
read_dest:      .long 0
unit_bytes:     .long 512
disk_err:       .byte 0
s_sp:           .asciz " "
max_chunk:      .long 16
this_chunk:     .long 0

s_banner:       .asciz "\r\nPC5 loader 0.1.0\r\n"
s_vbe_ok:       .asciz "pc5: framebuffer "
s_vbe_fail:     .asciz "pc5: VBE unavailable, using text mode\r\n"
s_vbe_modes:    .asciz "pc5: vbe modes_seen/lfb/best "
s_pvd_ok:       .asciz "pc5: medium is ISO9660, disk unit bytes "
s_pvd_fail:     .asciz "pc5: warning: ISO9660 descriptor unreadable\r\n"
s_kernel_ok:    .asciz "pc5: kernel image verified\r\n"
s_volume:       .asciz "pc5: medium volume "
s_enter:        .asciz "\r\npc5: entering 32-bit kernel\r\n"
s_halt:         .asciz "\r\npc5: halted\r\n"
s_fatal_prefix: .asciz "PC5 LOADER FAILURE: "
s_e_a20:        .asciz "pc5: fatal: A20 gate did not open\r\n"
s_e_kernel:     .asciz "pc5: fatal: kernel load failed\r\n"
s_nl:           .asciz "\r\n"

loader_version: .ascii "0.1.0"
                .space 11, 0

/*
 * The boot descriptor is patched in place by tools/mkiso.py at the offset
 * given to the builder (0xE00 below).  Keep the size and field order in sync
 * with make_boot_descriptor() there.
 */
    .org 0xE00
boot_desc:
    .ascii "PC5BOOT1"               /* +0  magic                      */
    .long 0                         /* +8  kernel LBA                 */
    .long 0                         /* +12 kernel bytes               */
    .long 0                         /* +16 boot image LBA             */
    .long 0                         /* +20 volume descriptor LBA      */
    .long 0                         /* +24 ISO sector count           */
    .long 0                         /* +28 reserved                   */
    .long 0                         /* +32 flags                      */
    .asciz "PC5"
    .space 23, 0                    /* +36 volume id, 24 bytes        */
    .long 0                         /* +60 descriptor CRC32           */
    .space 0, 0
    .org 0x1000                     /* boot image is exactly 4096 bytes */

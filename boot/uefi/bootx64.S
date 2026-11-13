/*
 * PC5 UEFI entry stub and 64->32-bit handover trampoline.
 *
 * PE32+/EFI images have no CRT and no startup code: firmware loads the
 * sections, applies the base relocations, and calls the entry point with the
 * Microsoft x64 calling convention (ImageHandle in RCX, SystemTable in RDX).
 * That is the whole runtime contract, and GAS has no "EFI ABI" mode, so this
 * file provides it by hand:
 *
 *   1. keep the caller's RSP so the return to firmware is exact, and keep the
 *      two arguments in registers the .bss clearing loop cannot clobber;
 *   2. zero .bss, because a PE section records only its size: no loader ever
 *      zeroes it for us;
 *   3. build an ms_abi call frame (32 bytes of shadow space, stack aligned to
 *      16 at the call) around `call efi_main`, whose prototype in efimain.c is
 *      __attribute__((ms_abi)).
 *
 * The second half of the file is the handover into the 32-bit kernel.  The
 * ordering there is not cosmetic: in 64-bit mode CR0.PG cannot be cleared, so
 * the CPU must first be moved to 32-bit compatibility mode with a far return,
 * and only then may paging be switched off.
 */
    .set KERNEL_ADDR,   0x10000
    .set KERNEL_STACK,  0x9F000
    .set CODE32_SEL,    0x08
    .set DATA_SEL,      0x10

    .section .text
    .code64
    .globl _start
_start:
    /* RCX = ImageHandle, RDX = SystemTable. */
    movq %rsp, saved_rsp(%rip)     /* RIP-relative: needs no relocation     */
    movq %rcx, %r8                 /* ImageHandle                           */
    movq %rdx, %r9                 /* SystemTable                           */

    /* Zero .bss (RAX, RCX, RDI are clobbered here, hence R8/R9 above). */
    leaq __bss_start(%rip), %rdi
    leaq __bss_end(%rip), %rcx
    subq %rdi, %rcx
    addq $7, %rcx
    shrq $3, %rcx
    xorl %eax, %eax
    rep stosq

    /* ms_abi frame: 32 bytes of shadow space, RSP aligned to 16 at the call,
     * so efi_main sees RSP % 16 == 8 on entry, as the ABI requires. */
    andq $-16, %rsp
    subq $32, %rsp
    movq %r8, %rcx
    movq %r9, %rdx
    call efi_main

    /* Back to firmware with its own stack pointer; RAX is the EFI_STATUS. */
    movq saved_rsp(%rip), %rsp
    ret

/* ------------------------------------------------------------------ */
/*                               pc5_uefi_bridge(entry, boot_info)     */
/* ------------------------------------------------------------------ */
/* Called from C, so the arguments arrive in the SysV registers:
 *     RDI = kernel entry address (must be KERNEL_ADDR for protocol 1)
 *     RSI = physical address of struct pc5_boot_info
 *
 * The kernel is entered with EBX = boot info and a flat 32-bit address space
 * with paging off, exactly as boot/loader.S leaves it.  This routine does not
 * return. */
    .globl pc5_uefi_bridge
pc5_uefi_bridge:
    cli
    movq %rsi, %rbx                /* boot info, preserved across the mode switch */
    /* RDI (entry point) is not used: the kernel is linked at KERNEL_ADDR and
     * the caller has already checked that it passed exactly that address. */

    /* Flat 32-bit GDT.  Loading it does not disturb the cached CS descriptor,
     * so the following instructions still execute as 64-bit code. */
    lgdt pc5_gdt_desc(%rip)
    movw $DATA_SEL, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %fs
    movw %ax, %gs
    movw %ax, %ss

    /* Far return into 32-bit compatibility mode: pops RIP then CS, and
     * CODE32_SEL is a 32-bit code segment, so the CPU leaves 64-bit mode
     * while paging is still on (which compatibility mode requires). */
    leaq compat32(%rip), %rax
    pushq $CODE32_SEL
    pushq %rax
    lretq

    .code32
compat32:
    /* Now in 32-bit compatibility mode.  Only here may paging be disabled;
     * clearing CR0.PG also clears LMA and drops the CPU into plain protected
     * mode with the identity map gone but the physical addresses unchanged. */
    movl %cr0, %eax
    andl $0x7FFFFFFF, %eax
    movl %eax, %cr0

    /* Re-load the segments after the mode change (the cached bases are the
     * flat ones, but reloading is what the architecture asks for). */
    movw $DATA_SEL, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %fs
    movw %ax, %gs
    movw %ax, %ss
    movl $KERNEL_STACK, %esp

    ljmp $CODE32_SEL, $KERNEL_ADDR

/* ------------------------------------------------------------------ */
/*                                    pc5_uefi_halt(status)           */
/* ------------------------------------------------------------------ */
/* Park the CPU after an error so the trace on screen stays readable and the
 * firmware never resumes with a half-initialised machine. */
    .code64
    .globl pc5_uefi_halt
pc5_uefi_halt:
    cli
1:  hlt
    jmp 1b

/* ------------------------------------------------------------------ */
/* Flat GDT used for the 32-bit handover.                             */
/* ------------------------------------------------------------------ */
    .section .data
    .balign 8
saved_rsp:
    .quad 0

    .balign 16
    .globl pc5_gdt
pc5_gdt:
    .quad 0
    .quad 0x00cf9a000000ffff     /* 0x08 code: base 0, limit 4 GiB, 32-bit */
    .quad 0x00cf92000000ffff     /* 0x10 data: base 0, limit 4 GiB        */
    .globl pc5_gdt_end
pc5_gdt_end:
    .globl pc5_gdt_desc
pc5_gdt_desc:
    .word pc5_gdt_end - pc5_gdt - 1
    .quad pc5_gdt

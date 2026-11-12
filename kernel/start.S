/*
 * PC5 kernel entry (32-bit, flat, no paging identity map).
 *
 * The loader jumps here with EBX = physical address of struct pc5_boot_info.
 * Interrupts are still disabled and the GDT set up by the loader is flat, so
 * everything below is straightforward 32-bit code.
 *
 * Exception handling is deliberately minimal but real: every CPU exception
 * gets its own entry in a real IDT and reports the vector, so a kernel bug
 * produces a diagnostic instead of a silent triple fault.
 */
    .set KERNEL_CODE_SEL, 0x08

    .section .text.start
    .code32
    .globl _start
_start:
    jmp start_real
    .ascii "PC5K"           /* verified by the loader */
    .byte 1                 /* boot protocol version   */
start_real:
    cli
    cld
    movl %ebx, %esi         /* keep the boot-info pointer */

    /* clear .bss: the loader copies the file image only */
    movl $__bss_start, %edi
    movl $__bss_end, %ecx
    subl %edi, %ecx
    xorl %eax, %eax
    movl %ecx, %edx
    shrl $2, %ecx
    rep stosl
    movl %edx, %ecx
    andl $3, %ecx
    rep stosb

    movl $0x9f000, %esp
    movl %esp, %ebp

    call idt_install
    pushl %esi
    call kmain
1:  cli
    hlt
    jmp 1b

/* ------------------------------------------------------------- IDT ---- */
    .section .text
    .code32
idt_install:
    pushal
    xorl %ecx, %ecx
1:  movl $exc_table, %eax
    movl (%eax,%ecx,4), %eax
    movl %ecx, %edi
    shll $3, %edi
    movw %ax, idt(%edi)
    shrl $16, %eax
    movw %ax, idt+6(%edi)
    movw $KERNEL_CODE_SEL, idt+2(%edi)
    movb $0, idt+4(%edi)
    movb $0x8e, idt+5(%edi) /* present, DPL0, 32-bit interrupt gate */
    incl %ecx
    cmpl $32, %ecx
    jb 1b
    lidt idt_ptr
    popal
    ret

exc_0:
    pushl $0
    jmp exc_common
exc_1:
    pushl $1
    jmp exc_common
exc_2:
    pushl $2
    jmp exc_common
exc_3:
    pushl $3
    jmp exc_common
exc_4:
    pushl $4
    jmp exc_common
exc_5:
    pushl $5
    jmp exc_common
exc_6:
    pushl $6
    jmp exc_common
exc_7:
    pushl $7
    jmp exc_common
exc_8:
    pushl $8
    jmp exc_common
exc_9:
    pushl $9
    jmp exc_common
exc_10:
    pushl $10
    jmp exc_common
exc_11:
    pushl $11
    jmp exc_common
exc_12:
    pushl $12
    jmp exc_common
exc_13:
    pushl $13
    jmp exc_common
exc_14:
    pushl $14
    jmp exc_common
exc_15:
    pushl $15
    jmp exc_common
exc_16:
    pushl $16
    jmp exc_common
exc_17:
    pushl $17
    jmp exc_common
exc_18:
    pushl $18
    jmp exc_common
exc_19:
    pushl $19
    jmp exc_common
exc_20:
    pushl $20
    jmp exc_common
exc_21:
    pushl $21
    jmp exc_common
exc_22:
    pushl $22
    jmp exc_common
exc_23:
    pushl $23
    jmp exc_common
exc_24:
    pushl $24
    jmp exc_common
exc_25:
    pushl $25
    jmp exc_common
exc_26:
    pushl $26
    jmp exc_common
exc_27:
    pushl $27
    jmp exc_common
exc_28:
    pushl $28
    jmp exc_common
exc_29:
    pushl $29
    jmp exc_common
exc_30:
    pushl $30
    jmp exc_common
exc_31:
    pushl $31
    jmp exc_common

exc_common:
    pushal
    pushl %esp
    call exception_report
    cli
1:  hlt
    jmp 1b

    .section .rodata
    .balign 4
exc_table:
    .long exc_0
    .long exc_1
    .long exc_2
    .long exc_3
    .long exc_4
    .long exc_5
    .long exc_6
    .long exc_7
    .long exc_8
    .long exc_9
    .long exc_10
    .long exc_11
    .long exc_12
    .long exc_13
    .long exc_14
    .long exc_15
    .long exc_16
    .long exc_17
    .long exc_18
    .long exc_19
    .long exc_20
    .long exc_21
    .long exc_22
    .long exc_23
    .long exc_24
    .long exc_25
    .long exc_26
    .long exc_27
    .long exc_28
    .long exc_29
    .long exc_30
    .long exc_31

    .section .data
    .balign 8
idt:
    .space 256, 0
idt_ptr:
    .word 255
    .long idt

/* PC5 kernel: polled 16550-compatible serial port on COM1 (0x3F8). */
#include "pc5.h"

#define COM1 0x3f8

void serial_init(void)
{
    outb(COM1 + 1, 0x00); /* disable interrupts            */
    outb(COM1 + 3, 0x80); /* enable divisor latch          */
    outb(COM1 + 0, 0x01); /* 115200 baud                   */
    outb(COM1 + 1, 0x00);
    outb(COM1 + 3, 0x03); /* 8N1                           */
    outb(COM1 + 2, 0xc7); /* FIFO on, cleared              */
    outb(COM1 + 4, 0x03); /* DTR + RTS                     */
}

void serial_putc(char c)
{
    static int last_was_cr;
    if (c == '\n' && !last_was_cr)
        serial_putc('\r');
    last_was_cr = (c == '\r');
    for (u32 spin = 0; spin < 100000; spin++)
        if (inb(COM1 + 5) & 0x20)
            break;
    outb(COM1, (u8)c);
}

void serial_puts(const char *s)
{
    while (*s)
        serial_putc(*s++);
}

char serial_getc_nonblock(void)
{
    if (inb(COM1 + 5) & 0x01)
        return (char)inb(COM1);
    return 0;
}

/*
 * PC5 kernel: 8042 PS/2 keyboard driver (polled).
 *
 * The boot environment does not enable interrupts, so the controller is used
 * in polled mode: scanning is enabled, translation to scan-code set 1 is on,
 * and kbd_read() returns one scan code at a time with an "extended" flag for
 * the E0-prefixed arrows and keypad keys.  This is real hardware input, not
 * synthetic input: on a physical machine these bytes come from the i8042.
 */
#include "pc5.h"

static int extended_pending;

static int wait_input_empty(void)
{
    for (u32 i = 0; i < 100000; i++)
        if (!(inb(0x64) & 0x02))
            return 0;
    return -1;
}

static int wait_output_full(void)
{
    for (u32 i = 0; i < 100000; i++)
        if (inb(0x64) & 0x01)
            return 0;
    return -1;
}

static int send_cmd(u8 cmd)
{
    if (wait_input_empty())
        return -1;
    outb(0x64, cmd);
    return 0;
}

static int send_data(u8 data)
{
    if (wait_input_empty())
        return -1;
    outb(0x60, data);
    return 0;
}

int kbd_init(void)
{
    /* drain anything the firmware left behind */
    for (int i = 0; i < 16 && (inb(0x64) & 0x01); i++)
        (void)inb(0x60);

    if (send_cmd(0xae))          /* enable first PS/2 port            */
        return -1;
    if (send_cmd(0x20))          /* read controller configuration     */
        return -2;
    u8 cfg = inb(0x60);
    cfg |= 0x01;                 /* enable IRQ1 (harmless when polled) */
    cfg |= 0x40;                 /* translate to scan-code set 1      */
    cfg &= (u8)~0x10;            /* enable the first clock line       */
    if (send_cmd(0x60))
        return -3;
    if (send_data(cfg))
        return -4;
    (void)send_data(0xf4);       /* enable scanning                   */
    return 0;
}

int kbd_read(u8 *code, int *extended)
{
    if (!(inb(0x64) & 0x01))
        return 0;
    u8 data = inb(0x60);
    if (data == 0xe0) {
        extended_pending = 1;
        return 0;
    }
    if (data == 0xe1) {          /* pause/break sequence: swallow 5 bytes */
        for (int i = 0; i < 5; i++)
            if (!wait_output_full())
                (void)inb(0x60);
        return 0;
    }
    *code = data;
    *extended = extended_pending;
    extended_pending = 0;
    return 1;
}

int kbd_wait(u32 timeout_ms, u8 *code, int *extended)
{
    u32 start = pit_ticks();
    for (;;) {
        int ext = 0;
        if (kbd_read(code, &ext)) {
            *extended = ext;
            return 1;
        }
        if (pc5_ms_since(start) > timeout_ms)
            return 0;
    }
}

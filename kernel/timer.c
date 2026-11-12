/*
 * PC5 kernel timing.
 *
 * There is no interrupt-driven timer yet: scheduling is not needed by the boot
 * environment, but timeouts and an uptime display are.  The PIT is calibrated
 * once against the TSC (channel 2, polled through port 0x61), and every later
 * measurement is a TSC delta, which is accurate enough for keyboard timeouts
 * and for reporting how long a boot stage took.
 */
#include "pc5.h"

static u32 cycles_per_ms;
static u32 boot_tsc;

static void pit_wait_1ms(void)
{
    /* channel 2, mode 0, divisor 1193 = 1 ms at 1.193182 MHz */
    u8 gate = inb(0x61);
    outb(0x61, (u8)((gate | 0x01) & ~0x02)); /* gate on, speaker off */
    outb(0x43, 0xb0);
    outb(0x42, 1193 & 0xff);
    outb(0x42, (1193 >> 8) & 0xff);
    for (u32 spin = 0; spin < 2000000; spin++)
        if (inb(0x61) & 0x20)
            break;
}

static inline u64 rdtsc(void)
{
    u32 lo, hi;
    __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));
    return ((u64)hi << 32) | lo;
}

u32 rdtsc_low(void) { return (u32)rdtsc(); }

void pit_init(void)
{
    u32 t0 = rdtsc_low();
    for (int i = 0; i < 20; i++)
        pit_wait_1ms();
    u32 t1 = rdtsc_low();
    cycles_per_ms = (t1 - t0) / 20;
    if (!cycles_per_ms)
        cycles_per_ms = 1000000; /* 1 GHz assumption as a last resort */
    boot_tsc = rdtsc_low();
}

u32 pit_ticks(void)
{
    /* milliseconds since pit_init() */
    if (!cycles_per_ms)
        return 0;
    return (rdtsc_low() - boot_tsc) / cycles_per_ms;
}

u32 pc5_ms_since(u32 start) { return pit_ticks() - start; }

/*
 * PC5 kernel console: a linear-framebuffer text console rendered with the
 * firmware's own 8x16 font, a VGA text-mode fallback for firmware that cannot
 * give us a linear framebuffer, and a serial mirror so every byte the boot
 * environment shows is also available on COM1 (used by the boot tests and by
 * headless recovery sessions).
 */
#include <stdarg.h>

#include "pc5.h"

struct console con;

static const u32 palette[16] = {
    0x000000, 0x0000aa, 0x00aa00, 0x00aaaa, 0xaa0000, 0xaa00aa, 0xaa5500, 0xaaaaaa,
    0x555555, 0x5555ff, 0x55ff55, 0x55ffff, 0xff5555, 0xff55ff, 0xffff55, 0xffffff,
};

static u16 *text_mem(void) { return (u16 *)0xb8000; }

/* Shadow copy of the character grid.
 *
 * The framebuffer has no readable text representation, so the console keeps
 * one as it draws.  It is what the serial "screen" command returns and what the
 * boot tests assert against, which means the tests check the *rendered* UI and
 * not a separate code path. */
#define SHADOW_ROWS 64
#define SHADOW_COLS 200
static char shadow[SHADOW_ROWS][SHADOW_COLS];

static void shadow_put(int x, int y, char c)
{
    if (x >= 0 && x < SHADOW_COLS && y >= 0 && y < SHADOW_ROWS)
        shadow[y][x] = c;
}

void con_snapshot(char *buf, u32 max, int *rows_out, int *cols_out)
{
    u32 out = 0;
    int last = -1; u32 maxw = 0;
    for (int y = 0; y < con.rows && y < SHADOW_ROWS; y++) {
        u32 w = 0;
        for (int x = 0; x < con.cols && x < SHADOW_COLS; x++)
            if (shadow[y][x] && shadow[y][x] != ' ')
                w = (u32)x + 1;
        if (w)
            last = y;
        if (w > maxw)
            maxw = w;
    }
    for (int y = 0; y <= last; y++) {
        for (int x = 0; x < con.cols && out + 2 < max; x++) {
            char c = shadow[y][x] ? shadow[y][x] : ' ';
            buf[out++] = c;
        }
        while (out > 0 && buf[out - 1] == ' ')
            out--;
        if (out + 1 < max)
            buf[out++] = '\n';
    }
    if (max)
        buf[out < max ? out : max - 1] = 0;
    if (rows_out)
        *rows_out = last + 1;
    if (cols_out)
        *cols_out = (int)maxw;
}

/* Prove that the framebuffer is writable and readable at the address the
 * firmware reported: write a pattern, read it back, restore the original. */
int con_framebuffer_selftest(void)
{
    if (!con.fb || !con.phys)
        return 0;
    volatile u8 *p = (volatile u8 *)(u32)(con.phys + 8 * con.pitch + 32);
    u8 saved[4];
    u32 bytes = con.bpp / 8;
    if (bytes < 3)
        bytes = 2;
    for (u32 i = 0; i < bytes; i++)
        saved[i] = p[i];
    for (u32 i = 0; i < bytes; i++)
        p[i] = (u8)(0x5a + i);
    int ok = 1;
    for (u32 i = 0; i < bytes; i++)
        if (p[i] != (u8)(0x5a + i))
            ok = 0;
    for (u32 i = 0; i < bytes; i++)
        p[i] = saved[i];
    return ok;
}

/* ------------------------------------------------------------------ fb */
static void put_pixel(int x, int y, u32 rgb)
{
    if (x < 0 || y < 0 || (u32)x >= con.width || (u32)y >= con.height)
        return;
    u8 *p = (u8 *)(u32)(con.phys + (u32)y * con.pitch + (u32)x * (con.bpp / 8));
    if (con.bpp == 32) {
        *(u32 *)p = rgb;
    } else if (con.bpp == 24) {
        p[0] = (u8)(rgb & 0xff);
        p[1] = (u8)((rgb >> 8) & 0xff);
        p[2] = (u8)((rgb >> 16) & 0xff);
    } else if (con.bpp == 16) {
        *(u16 *)p = (u16)(((rgb >> 19) << 11) | (((rgb >> 10) & 0x3f) << 5) | ((rgb >> 3) & 0x1f));
    }
}

static void fill_rect(int x, int y, int w, int h, u8 colour)
{
    if (w <= 0 || h <= 0)
        return;
    for (int row = 0; row < h; row++)
        for (int col = 0; col < w; col++)
            shadow_put(x + col, y + row, ' ');
    if (!con.fb) {
        for (int row = 0; row < h; row++) {
            if (y + row < 0 || (u32)(y + row) >= (u32)con.rows)
                continue;
            for (int col = 0; col < w; col++) {
                if (x + col < 0 || (u32)(x + col) >= (u32)con.cols)
                    continue;
                text_mem()[(y + row) * con.cols + x + col] = (u16)(' ' | ((u16)((colour << 4) | colour) << 8));
            }
        }
        return;
    }
    u32 rgb = palette[colour & 15];
    for (int row = 0; row < h; row++)
        for (int col = 0; col < w; col++)
            put_pixel(x * 8 + col, y * 16 + row, rgb);
}

static void draw_glyph(int cx, int cy, u8 ch, u8 fg, u8 bg)
{
    shadow_put(cx, cy, (char)(ch ? ch : ' '));
    if (!con.fb) {
        if (cy < 0 || (u32)cy >= (u32)con.rows || cx < 0 || (u32)cx >= (u32)con.cols)
            return;
        text_mem()[cy * con.cols + cx] = (u16)(u8)ch | ((u16)((bg << 4) | (fg & 15)) << 8);
        return;
    }
    if (!con.font)
        return;
    const u8 *glyph = con.font + (u32)ch * con.font_bpc;
    u32 fgrgb = palette[fg & 15], bgrgb = palette[bg & 15];
    for (int row = 0; row < 16; row++) {
        u8 bits = row < (int)con.font_bpc ? glyph[row] : 0;
        for (int col = 0; col < 8; col++)
            put_pixel(cx * 8 + col, cy * 16 + row, (bits & (0x80 >> col)) ? fgrgb : bgrgb);
    }
}

/* --------------------------------------------------------------- init */
void console_init(const struct pc5_boot_info *bi)
{
    memset(&con, 0, sizeof(con));
    con.fg = COL_LGREY;
    con.bg = COL_BLACK;
    con.serial_mirror = 1;
    con.wrap = 1;
    con.font = (u8 *)(u32)bi->font_addr;
    con.font_bpc = bi->font_bytes_per_char ? bi->font_bytes_per_char : 16;

    if (bi->vbe_ok && bi->vbe_mode_addr) {
        const struct vbe_mode_info *mi = (const struct vbe_mode_info *)(u32)bi->vbe_mode_addr;
        if (mi->phys_base && mi->width && mi->height && mi->bpp >= 16) {
            con.fb = 1;
            con.phys = mi->phys_base;
            con.width = mi->width;
            con.height = mi->height;
            con.pitch = mi->pitch;
            con.bpp = mi->bpp;
        }
    }
    if (!con.fb) {
        con.width = 80 * 8;
        con.height = 25 * 16;
        con.pitch = 80 * 2;
        con.bpp = 0;
    }
    con.cols = (int)(con.width / 8);
    con.rows = (int)(con.height / 16);
    con.x = con.y = 0;
    con_clear();
}

void con_clear(void)
{
    for (int y = 0; y < SHADOW_ROWS; y++)
        for (int x = 0; x < SHADOW_COLS; x++)
            shadow[y][x] = ' ';
    if (!con.fb) {
        for (int i = 0; i < con.cols * con.rows; i++)
            text_mem()[i] = (u16)(' ' | ((u16)((con.bg << 4) | con.fg) << 8));
    } else {
        fill_rect(0, 0, con.cols, con.rows, con.bg);
    }
    con.x = con.y = 0;
}

static void scroll(void)
{
    if (!con.fb) {
        for (int i = 0; i < (con.rows - 1) * con.cols; i++)
            text_mem()[i] = text_mem()[i + con.cols];
        for (int i = 0; i < con.cols; i++)
            text_mem()[(con.rows - 1) * con.cols + i] =
                (u16)(' ' | ((u16)((con.bg << 4) | con.fg) << 8));
        return;
    }
    u32 row_bytes = (u32)con.cols * 8 * (con.bpp / 8);
    u8 *base = (u8 *)(u32)con.phys;
    for (u32 y = 0; y + 16 < con.height; y++)
        memcpy(base + y * con.pitch, base + (y + 16) * con.pitch, row_bytes);
    fill_rect(0, con.rows - 1, con.cols, 1, con.bg);
}

void con_putc(char c)
{
    if (con.serial_mirror)
        serial_putc(c);
    if (c == '\n') {
        con.x = 0;
        con.y++;
    } else if (c == '\r') {
        con.x = 0;
    } else if (c == '\t') {
        con.x = (con.x + 8) & ~7;
    } else if (c == '\b') {
        if (con.x > 0)
            con.x--;
        draw_glyph(con.x, con.y, ' ', con.fg, con.bg);
    } else {
        if (!con.wrap && con.x >= con.cols)
            return;
        draw_glyph(con.x, con.y, (u8)c, con.fg, con.bg);
        con.x++;
    }
    if (con.x >= con.cols) {
        con.x = 0;
        con.y++;
    }
    if (con.y >= con.rows) {
        scroll();
        con.y = con.rows - 1;
    }
}

void con_puts(const char *s)
{
    while (*s)
        con_putc(*s++);
}

void con_attr(u8 fg, u8 bg)
{
    con.fg = fg & 15;
    con.bg = bg & 15;
}

void con_wrap(int enable) { con.wrap = enable ? 1 : 0; }

void con_gotoxy(int x, int y)
{
    if (x >= 0 && x < con.cols)
        con.x = x;
    if (y >= 0 && y < con.rows)
        con.y = y;
}

void con_fill(int x, int y, int w, int h, u8 colour)
{
    fill_rect(x, y, w, h, colour);
}

/* write a row of text with a background, padded to the full width */
void con_hline(int x, int y, int w, u8 colour, const char *text)
{
    con_attr(con.fg, colour);
    fill_rect(x, y, w, 1, colour);
    con_gotoxy(x, y);
    con_puts(text);
}

static void emit_uint(u32 v, int base, char pad)
{
    char buf[36];
    u32_to_str(v, buf, base);
    if (pad) {
        u32 len = strlen(buf);
        u32 width = (u32)pad - '0';
        while (len < width) {
            con_putc(base == 10 ? ' ' : '0');
            len++;
        }
    }
    con_puts(buf);
}

void con_printf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    while (*fmt) {
        if (*fmt != '%') {
            con_putc(*fmt++);
            continue;
        }
        fmt++;
        char pad = 0;
        if (*fmt >= '0' && *fmt <= '9')
            pad = *fmt++;
        switch (*fmt) {
        case 's': {
            const char *s = va_arg(ap, const char *);
            con_puts(s ? s : "(nullal)");
            break;
        }
        case 'c':
            con_putc((char)va_arg(ap, int));
            break;
        case 'd':
        case 'u': {
            u32 v = va_arg(ap, u32);
            if (*fmt == 'd' && (s32)v < 0) {
                con_putc('-');
                v = (u32)(-(s32)v);
            }
            emit_uint(v, 10, pad);
            break;
        }
        case 'x':
            emit_uint(va_arg(ap, u32), 16, pad);
            break;
        case 'l': {
            fmt++;
            u64 v = va_arg(ap, u64);
            char buf[72];
            u64_to_str(v, buf, *fmt == 'x' ? 16 : 10);
            con_puts(buf);
            break;
        }
        case '%':
            con_putc('%');
            break;
        default:
            con_putc('%');
            con_putc(*fmt);
            break;
        }
        fmt++;
    }
    va_end(ap);
}

void con_panic(const char *msg)
{
    con_attr(COL_WHITE, COL_RED);
    con_printf("\nPC5 PANIC: %s\n", msg);
    con_attr(COL_LGREY, COL_BLACK);
    for (;;)
        hlt();
}

/* called from start.S exception stub */
void exception_report(u32 *frame)
{
    /* frame: pushedal layout; the vector is pushed after it */
    u32 vector = frame[8];
    static const char *names[32] = {
        "divide error", "debug", "NMI", "breakpoint", "overflow", "bound range",
        "invalid opcode", "device not available", "double fault", "coprocessor segment",
        "invalid TSS", "segment not present", "stack fault", "general protection",
        "page fault", "reserved", "x87 error", "alignment check", "machine check",
        "SIMD error", "virtualisation", "control protection", "reserved", "reserved",
        "reserved", "reserved", "reserved", "reserved", "hypervisor injection",
        "VMM communication", "security", "reserved",
    };
    con_attr(COL_WHITE, COL_RED);
    con_printf("\nPC5 CPU EXCEPTION %u: %s\n", vector, vector < 32 ? names[vector] : "unknown");
    con_attr(COL_LGREY, COL_BLACK);
    con_printf("eip=%x cs=%x eflags=%x error=%x\n",
               frame[7], frame[6], frame[5], frame[9]);
    con_puts("system halted; capture this line for a bug report\n");
    for (;;)
        hlt();
}

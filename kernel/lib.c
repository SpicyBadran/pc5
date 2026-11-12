/* PC5 kernel: freestanding string, memory and number helpers. */
#include <stdarg.h>

#include "pc5.h"

void *memset(void *dst, int c, PC5_SIZE n)
{
    u8 *d = (u8 *)dst;
    while (n--)
        *d++ = (u8)c;
    return dst;
}

void *memcpy(void *dst, const void *src, PC5_SIZE n)
{
    u8 *d = (u8 *)dst;
    const u8 *s = (const u8 *)src;
    while (n--)
        *d++ = *s++;
    return dst;
}

int memcmp(const void *a, const void *b, PC5_SIZE n)
{
    const u8 *x = (const u8 *)a, *y = (const u8 *)b;
    for (PC5_SIZE i = 0; i < n; i++)
        if (x[i] != y[i])
            return (int)x[i] - (int)y[i];
    return 0;
}

int strcmp(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return (int)(u8)*a - (int)(u8)*b;
}

int strncmp(const char *a, const char *b, PC5_SIZE n)
{
    while (n && *a && *a == *b) {
        a++;
        b++;
        n--;
    }
    if (!n)
        return 0;
    return (int)(u8)*a - (int)(u8)*b;
}

PC5_SIZE strlen(const char *s)
{
    PC5_SIZE n = 0;
    while (s[n])
        n++;
    return n;
}

int str_contains(const char *hay, const char *needle)
{
    PC5_SIZE nl = strlen(needle);
    if (!nl)
        return 1;
    for (PC5_SIZE i = 0; hay[i]; i++) {
        PC5_SIZE j = 0;
        while (j < nl && hay[i + j] && hay[i + j] == needle[j])
            j++;
        if (j == nl)
            return 1;
    }
    return 0;
}

void str_copy(char *dst, const char *src, u32 max)
{
    PC5_SIZE i = 0;
    if (!max)
        return;
    for (; src[i] && i + 1 < max; i++)
        dst[i] = src[i];
    dst[i] = 0;
}

void str_append(char *dst, const char *src, u32 max)
{
    PC5_SIZE len = strlen(dst);
    if (len + 1 >= max)
        return;
    str_copy(dst + len, src, max - len);
}

void u32_to_str(u32 value, char *out, int base)
{
    char tmp[33];
    int i = 0;
    if (base < 2 || base > 16) {
        out[0] = 0;
        return;
    }
    if (!value) {
        out[0] = '0';
        out[1] = 0;
        return;
    }
    while (value) {
        u32 d = value % (u32)base;
        tmp[i++] = (char)(d < 10 ? '0' + d : 'a' + (d - 10));
        value /= (u32)base;
    }
    int k = 0;
    while (i)
        out[k++] = tmp[--i];
    out[k] = 0;
}

void u64_to_str(u64 value, char *out, u32 base)
{
    /* 32-bit kernel: implement without 64-bit division helpers */
    char tmp[65];
    int i = 0;
    if (!value) {
        out[0] = '0';
        out[1] = 0;
        return;
    }
    while (value) {
        /* divide by base using shift/subtract (base is 10 or 16 here) */
        u64 q = 0;
        u32 rem = 0;
        for (int bit = 63; bit >= 0; bit--) {
            rem = (rem << 1) | (u32)((value >> bit) & 1u);
            if (rem >= base) {
                rem -= base;
                q |= (u64)1 << bit;
            }
        }
        tmp[i++] = (char)(rem < 10 ? '0' + rem : 'a' + (rem - 10));
        value = q;
    }
    int k = 0;
    while (i)
        out[k++] = tmp[--i];
    out[k] = 0;
}

void u32_to_hex(u32 value, char *out, int digits)
{
    static const char hex[] = "0123456789abcdef";
    for (int i = digits - 1; i >= 0; i--) {
        out[i] = hex[value & 0xf];
        value >>= 4;
    }
    out[digits] = 0;
}

/* ------------------------------------------------------------------ fmt */
struct fmt_sink {
    char *buf;
    u32 max;
    u32 len;
};

static void sink_putc(struct fmt_sink *s, char c)
{
    if (s->buf && s->len + 1 < s->max)
        s->buf[s->len] = c;
    s->len++;
}

int pc5_vsnprintf(char *buf, u32 max, const char *fmt, va_list ap)
{
    struct fmt_sink s = {buf, max, 0};
    char tmp[72];
    struct fmt_sink *sp = &s;

    while (*fmt) {
        if (*fmt != '%') {
            sink_putc(sp, *fmt++);
            continue;
        }
        fmt++;
        int left = 0;
        if (*fmt == '-') {
            left = 1;
            fmt++;
        }
        char zero = 0;
        if (*fmt == '0') {
            zero = '0';
            fmt++;
        }
        u32 width = 0;
        while (*fmt >= '0' && *fmt <= '9') {
            width = width * 10 + (u32)(*fmt - '0');
            fmt++;
        }
        switch (*fmt) {
        case 's': {
            const char *p = va_arg(ap, const char *);
            if (!p)
                p = "(null)";
            u32 len = strlen(p);
            if (!left)
                for (u32 i = len; i < width; i++)
                    sink_putc(sp, ' ');
            while (*p)
                sink_putc(sp, *p++);
            if (left)
                for (u32 i = len; i < width; i++)
                    sink_putc(sp, ' ');
            break;
        }
        case 'c':
            sink_putc(sp, (char)va_arg(ap, int));
            break;
        case 'd':
        case 'u': {
            u32 v = va_arg(ap, u32);
            if (*fmt == 'd' && (s32)v < 0) {
                if (!left && !zero)
                    for (u32 i = 1; i < width; i++)
                        sink_putc(sp, ' ');
                sink_putc(sp, '-');
                v = (u32)(-(s32)v);
                width = width > 1 ? width - 1 : 0;
            }
            u32_to_str(v, tmp, 10);
            u32 len = strlen(tmp);
            if (!left)
                for (u32 i = len; i < width; i++)
                    sink_putc(sp, zero ? '0' : ' ');
            for (const char *p = tmp; *p; p++)
                sink_putc(sp, *p);
            if (left)
                for (u32 i = len; i < width; i++)
                    sink_putc(sp, ' ');
            break;
        }
        case 'x': {
            u32 v = va_arg(ap, u32);
            char hx[16];
            if (width) {
                u32 digits = width > 8 ? 8 : width;
                u32_to_hex(v, hx, (int)digits);
            } else {
                u32_to_str(v, hx, 16);
            }
            for (const char *p = hx; *p; p++)
                sink_putc(sp, *p);
            break;
        }
        case 'l': {
            fmt++;
            if (*fmt == 'l')
                fmt++;
            u64 v = va_arg(ap, u64);
            u64_to_str(v, tmp, *fmt == 'x' ? 16 : 10);
            for (const char *p = tmp; *p; p++)
                sink_putc(sp, *p);
            break;
        }
        case '%':
            sink_putc(sp, '%');
            break;
        default:
            sink_putc(sp, '%');
            sink_putc(sp, *fmt);
            break;
        }
        fmt++;
    }
    if (max) {
        u32 idx = sp->len < max - 1 ? sp->len : max - 1;
        buf[idx] = 0;
    }
    return (int)sp->len;
}

int pc5_snprintf(char *buf, u32 max, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    int n = pc5_vsnprintf(buf, max, fmt, ap);
    va_end(ap);
    return n;
}

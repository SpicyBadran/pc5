/*
 * PC5 kernel: CPU identification.
 *
 * Everything here comes from CPUID; nothing is assumed about the machine.
 * This matters for the compatibility chain: the PS5 SoC is a Zen 2 part, so
 * "can this host execute the same instruction set" is a question we answer
 * from evidence (vendor, family/model, feature bits, long mode) rather than
 * from marketing names.
 */
#include "pc5.h"

static inline void cpuid(u32 leaf, u32 sub, u32 *a, u32 *b, u32 *c, u32 *d)
{
    __asm__ volatile("cpuid" : "=a"(*a), "=b"(*b), "=c"(*c), "=d"(*d) : "a"(leaf), "c"(sub));
}

void cpu_detect(struct cpu_info *out)
{
    u32 a, b, c, d;
    memset(out, 0, sizeof(*out));

    cpuid(0, 0, &a, &b, &c, &d);
    *(u32 *)&out->vendor[0] = b;
    *(u32 *)&out->vendor[4] = d;
    *(u32 *)&out->vendor[8] = c;
    out->vendor[12] = 0;

    cpuid(1, 0, &a, &b, &c, &d);
    out->stepping = a & 0xf;
    out->model = (a >> 4) & 0xf;
    out->family = (a >> 8) & 0xf;
    u32 ext_model = (a >> 16) & 0xf;
    u32 ext_family = (a >> 20) & 0xff;
    if (out->family == 0xf)
        out->family += ext_family;
    if (out->family == 0x6 || out->family == 0xf)
        out->model += ext_model << 4;
    out->logical = (b >> 16) & 0xff;
    out->features_ecx = c;
    out->features_edx = d;

    cpuid(0x80000000u, 0, &a, &b, &c, &d);
    u32 max_ext = a;
    if (max_ext >= 0x80000004u) {
        u32 *dst = (u32 *)out->brand;
        for (u32 leaf = 0x80000002u; leaf <= 0x80000004u; leaf++) {
            cpuid(leaf, 0, &a, &b, &c, &d);
            *dst++ = a;
            *dst++ = b;
            *dst++ = c;
            *dst++ = d;
        }
        out->brand[48] = 0;
        /* trim leading spaces that Intel leaves in the brand string */
        char *p = out->brand;
        while (*p == ' ')
            p++;
        if (p != out->brand) {
            char tmp[49];
            str_copy(tmp, p, sizeof(tmp));
            str_copy(out->brand, tmp, sizeof(out->brand));
        }
    } else {
        str_copy(out->brand, "unknown", sizeof(out->brand));
    }
    if (max_ext >= 0x80000001u) {
        cpuid(0x80000001u, 0, &a, &b, &c, &d);
        out->ext_edx = d;
    }
    if (max_ext >= 0x80000008u) {
        cpuid(0x80000008u, 0, &a, &b, &c, &d);
        out->phys_bits = a & 0xff;
        out->virt_bits = (a >> 8) & 0xff;
    }
}

void cpu_report(const struct cpu_info *ci, char *out, u32 max)
{
    char num[16];
    out[0] = 0;
    str_append(out, ci->vendor, max);
    str_append(out, " family ", max);
    u32_to_str(ci->family, num, 10);
    str_append(out, num, max);
    str_append(out, " model ", max);
    u32_to_str(ci->model, num, 10);
    str_append(out, num, max);
    str_append(out, " stepping ", max);
    u32_to_str(ci->stepping, num, 10);
    str_append(out, num, max);
    str_append(out, " logical ", max);
    u32_to_str(ci->logical, num, 10);
    str_append(out, num, max);
    str_append(out, (ci->ext_edx & (1u << 29)) ? " long-mode" : " no-long-mode", max);
    str_append(out, (ci->features_edx & (1u << 25)) ? " sse" : "", max);
    str_append(out, (ci->features_ecx & (1u << 28)) ? " avx" : "", max);
    str_append(out, (ci->features_ecx & (1u << 30)) ? " rdrand" : "", max);
}

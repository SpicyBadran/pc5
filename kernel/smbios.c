/*
 * PC5 kernel: SMBIOS (DMI) structure table parsing.
 *
 * Firmware describes the machine here: system vendor/product, BIOS version and
 * date, CPU socket and core count, and the installed memory modules.  PC5
 * reports exactly what firmware says and marks the fields it could not read,
 * because the hardware compatibility matrix depends on these strings.
 */
#include "pc5.h"

struct smbios_header {
    u8 type;
    u8 length;
    u16 handle;
} __attribute__((packed));

static const char *string_at(const struct smbios_header *hdr, int index)
{
    if (index <= 0)
        return "";
    const char *p = (const char *)hdr + hdr->length;
    int current = 1;
    while (*p) {
        if (current == index)
            return p;
        while (*p)
            p++;
        p++;
        current++;
    }
    return "";
}

static const u8 *next_structure(const u8 *p)
{
    const struct smbios_header *hdr = (const struct smbios_header *)p;
    const u8 *q = p + hdr->length;
    while (q[0] || q[1])
        q++;
    return q + 2;
}

static int smbios_checksum_ok(const u8 *p, u32 len)
{
    u8 sum = 0;
    for (u32 i = 0; i < len; i++)
        sum = (u8)(sum + p[i]);
    return sum == 0;
}

void smbios_scan(struct smbios_info *out)
{
    memset(out, 0, sizeof(*out));
    const u8 *table = NULL;
    u32 table_len = 0;

    for (u32 addr = 0xf0000; addr < 0x100000; addr += 16) {
        const u8 *p = (const u8 *)addr;
        if (memcmp(p, "_SM3_", 5) == 0 && smbios_checksum_ok(p, p[6])) {
            out->version_major = p[7];
            out->version_minor = p[8];
            u32 t = *(const u32 *)(p + 0x10);
            table = (const u8 *)t;
            table_len = *(const u32 *)(p + 0x0c);
            out->present = 1;
            break;
        }
        if (memcmp(p, "_SM_", 4) == 0 && smbios_checksum_ok(p, p[5])) {
            out->version_major = p[6];
            out->version_minor = p[7];
            u32 t = *(const u32 *)(p + 0x18);
            table = (const u8 *)t;
            table_len = *(const u32 *)(p + 0x16);
            out->present = 1;
            break;
        }
    }
    if (!table || table_len < 4)
        return;

    const u8 *p = table;
    const u8 *end = table + table_len;
    for (u32 guard = 0; guard < 256 && p + 4 < end; guard++) {
        const struct smbios_header *hdr = (const struct smbios_header *)p;
        if (hdr->type == 127)
            break;
        switch (hdr->type) {
        case 0:
            if (hdr->length >= 0x12) {
                str_copy(out->bios_vendor, string_at(hdr, p[0x04]), sizeof(out->bios_vendor));
                str_copy(out->bios_version, string_at(hdr, p[0x05]), sizeof(out->bios_version));
                str_copy(out->bios_date, string_at(hdr, p[0x08]), sizeof(out->bios_date));
            }
            break;
        case 1:
            if (hdr->length >= 0x08) {
                str_copy(out->sys_vendor, string_at(hdr, p[0x04]), sizeof(out->sys_vendor));
                str_copy(out->product, string_at(hdr, p[0x05]), sizeof(out->product));
            }
            break;
        case 2:
            if (hdr->length >= 0x05)
                str_copy(out->board, string_at(hdr, p[0x04]), sizeof(out->board));
            break;
        case 4:
            if (hdr->length >= 0x28) {
                str_copy(out->cpu_version, string_at(hdr, p[0x10]), sizeof(out->cpu_version));
                out->cpu_cores = p[0x23];
                out->cpu_threads = p[0x24];
            }
            break;
        case 17:
            if (hdr->length >= 0x08) {
                out->memory_devices++;
                u16 size = *(const u16 *)(p + 0x0c);
                if (size && size != 0xffff)
                    out->memory_total_mb += (size & 0x8000) ? (size & 0x7fff) / 1024 : size;
            }
            break;
        default:
            break;
        }
        p = next_structure(p);
    }
}

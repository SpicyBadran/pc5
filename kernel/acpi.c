/*
 * PC5 kernel: ACPI root table discovery.
 *
 * The RSDP is searched where the ACPI specification says it can live: the
 * first 1 KiB of the EBDA, then the 0xE0000-0xFFFFF BIOS area.  The RSDT is
 * walked (32-bit entries, safe in this kernel) and every table signature is
 * reported, which is what tells us whether firmware exposes the tables needed
 * for power management, interrupt routing and device discovery.
 */
#include "pc5.h"

static u8 acpi_checksum(const u8 *p, u32 len)
{
    u8 sum = 0;
    for (u32 i = 0; i < len; i++)
        sum = (u8)(sum + p[i]);
    return sum;
}

static const u8 *find_rsdp(void)
{
    u16 ebda_seg = *(volatile u16 *)0x40e;
    u32 ebda = (u32)ebda_seg << 4;
    if (ebda) {
        for (u32 off = 0; off < 1024; off += 16) {
            const u8 *p = (const u8 *)(ebda + off);
            if (memcmp(p, "RSD PTR ", 8) == 0 && acpi_checksum(p, 20) == 0)
                return p;
        }
    }
    for (u32 addr = 0xe0000; addr < 0x100000; addr += 16) {
        const u8 *p = (const u8 *)addr;
        if (memcmp(p, "RSD PTR ", 8) == 0) {
            u32 len = *(p + 15) >= 2 ? 36 : 20;
            if (acpi_checksum(p, len) == 0)
                return p;
        }
    }
    return NULL;
}

void acpi_scan(struct acpi_info *out)
{
    memset(out, 0, sizeof(*out));
    const u8 *rsdp = find_rsdp();
    if (!rsdp)
        return;
    out->present = 1;
    out->revision = rsdp[15];
    memcpy(out->oem_id, rsdp + 16, 6);
    out->oem_id[6] = 0;
    out->rsdt_addr = *(const u32 *)(rsdp + 16 + 4);
    /* RSDP: 9 sig, 1 checksum, 6 oem id, 1 revision, 4 rsdt addr */
    out->rsdt_addr = *(const u32 *)(rsdp + 24);
    const u8 *rsdt = (const u8 *)out->rsdt_addr;
    if (memcmp(rsdt, "RSDT", 4) != 0)
        return;
    u32 length = *(const u32 *)(rsdt + 4);
    if (length > 4096 || length < 36)
        return;
    memcpy(out->oem_table_id, rsdt + 16, 8);
    out->oem_table_id[8] = 0;
    u32 count = (length - 36) / 4;
    for (u32 i = 0; i < count && out->table_count < 16; i++) {
        u32 addr = *(const u32 *)(rsdt + 36 + i * 4);
        if (!addr)
            continue;
        const u8 *hdr = (const u8 *)addr;
        memcpy(out->table_names[out->table_count], hdr, 4);
        out->table_names[out->table_count][4] = 0;
        if (memcmp(hdr, "FACP", 4) == 0)
            out->fadt_length = (u16)(*(const u32 *)(hdr + 4) & 0xffff);
        out->table_count++;
    }
}

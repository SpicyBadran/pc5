/* PC5 kernel: physical memory map supplied by the firmware through E820. */
#include "pc5.h"

static struct mem_info g_mem;
static const struct e820_entry *g_entries;

void mem_detect(const struct pc5_boot_info *bi, struct mem_info *out)
{
    const struct e820_entry *e = (const struct e820_entry *)(u32)bi->e820_addr;
    memset(out, 0, sizeof(*out));
    out->entries = bi->e820_count;
    for (u32 i = 0; i < bi->e820_count; i++) {
        u64 end = e[i].base + e[i].length;
        if (e[i].type == 1) {
            out->usable_bytes += e[i].length;
            if (e[i].base < 0x100000ull)
                out->upper_bytes += e[i].length; /* conventional memory */
        }
        if (e[i].type != 2 && end > out->total_bytes)
            out->total_bytes = end;
        u64 top_mb = end >> 20;
        if (top_mb > out->top_address_mb && top_mb < 0x100000ull)
            out->top_address_mb = (u32)top_mb;
    }
    g_mem = *out;
    g_entries = e;
}

const struct e820_entry *mem_entries(void) { return g_entries; }

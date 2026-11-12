/*
 * PC5 kernel: ISO9660 reader on top of the ATA/ATAPI block driver.
 *
 * Scope: enough of ECMA-119 to open the volume, list the root directory and
 * read a file by name.  No Rock Ridge, no Joliet, no multi-extent files — the
 * PC5 medium does not need them, and pretending to support them would be worse
 * than not having them.
 */
#include "pc5.h"

struct iso_volume {
    int mounted;
    u32 root_lba;
    u32 root_size;
    char volume_id[33];
    u32 blocks;
};

static struct iso_volume volume;
static u8 sector_buf[2048];

static u32 rd32(const u8 *p) { return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24); }

int iso_mount(void)
{
    memset(&volume, 0, sizeof(volume));
    if (ata_read_blocks(16, 1, sector_buf))
        return -1;
    if (sector_buf[0] != 1 || memcmp(sector_buf + 1, "CD001", 5) != 0)
        return -2;
    for (int i = 0; i < 32; i++)
        volume.volume_id[i] = (char)sector_buf[40 + i];
    for (int i = 31; i >= 0 && volume.volume_id[i] == ' '; i--)
        volume.volume_id[i] = 0;
    volume.blocks = rd32(sector_buf + 80);
    volume.root_lba = rd32(sector_buf + 156 + 2);
    volume.root_size = rd32(sector_buf + 156 + 10);
    if (!volume.root_lba || !volume.root_size)
        return -3;
    volume.mounted = 1;
    return 0;
}

const char *iso_volume_id(void) { return volume.volume_id; }
u32 iso_block_count(void) { return volume.blocks; }
int iso_mounted(void) { return volume.mounted; }

/* Iterate the root directory; returns 1 and fills the record on success. */
int iso_root_find(const char *want, u32 *lba_out, u32 *size_out)
{
    if (!volume.mounted)
        return 0;
    u32 sectors = (volume.root_size + 2047) / 2048;
    for (u32 s = 0; s < sectors; s++) {
        if (ata_read_blocks(volume.root_lba + s, 1, sector_buf))
            return 0;
        u32 off = 0;
        while (off < 2048) {
            u8 len = sector_buf[off];
            if (!len) {
                off = (off / 2048 + 1) * 2048; /* rest of this block is padding */
                break;
            }
            const u8 *rec = sector_buf + off;
            u8 name_len = rec[32];
            const char *name = (const char *)(rec + 33);
            u32 lba = rd32(rec + 2);
            u32 size = rd32(rec + 10);
            if (name_len == 1 && (name[0] == 0 || name[0] == 1)) {
                /* "." and ".." */
            } else {
                /* compare ignoring the ";1" version suffix and any trailing dot */
                u32 n = 0;
                while (n < name_len && name[n] != ';')
                    n++;
                if (n == strlen(want) && strncmp(name, want, (int)n) == 0) {
                    if (lba_out)
                        *lba_out = lba;
                    if (size_out)
                        *size_out = size;
                    return 1;
                }
            }
            off += len;
        }
    }
    return 0;
}

/* Read up to max bytes of a file into buf; returns the number read. */
u32 iso_read_file(const char *name, void *buf, u32 max)
{
    u32 lba = 0, size = 0;
    if (!iso_root_find(name, &lba, &size))
        return 0;
    u32 want = size < max ? size : max;
    u32 blocks = (want + 2047) / 2048;
    u8 *out = (u8 *)buf;
    for (u32 b = 0; b < blocks; b++) {
        if (ata_read_blocks(lba + b, 1, sector_buf))
            return 0;
        u32 n = want - b * 2048;
        if (n > 2048)
            n = 2048;
        memcpy(out + b * 2048, sector_buf, n);
    }
    return want;
}

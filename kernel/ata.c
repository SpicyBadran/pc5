/*
 * PC5 kernel: ATA/ATAPI PIO block driver.
 *
 * Polled PIO is not fast, but it is the smallest correct thing that can read a
 * real optical drive or disk, and it makes the boot medium readable from the
 * kernel instead of only from firmware.  That is what turns compatibility chain
 * stage 4 from "the loader proved the firmware can read the medium" into "the
 * operating environment has a storage stack".
 *
 * Supported: ATA PIO (LBA28) for hard disks and ATAPI PACKET (READ(10)) for
 * CD/DVD, on both legacy channels, master and slave.  No DMA, no interrupts, no
 * AHCI/NVMe (see docs/ROADMAP.md).
 */
#include "pc5.h"

#define ATA_PRIMARY_IO 0x1f0
#define ATA_PRIMARY_CTL 0x3f6
#define ATA_SECONDARY_IO 0x170
#define ATA_SECONDARY_CTL 0x376

#define REG_DATA 0
#define REG_ERROR 1
#define REG_FEATURES 1
#define REG_SECTOR_COUNT 2
#define REG_LBA_LO 3
#define REG_LBA_MID 4
#define REG_LBA_HI 5
#define REG_DRIVE 6
#define REG_STATUS 7
#define REG_COMMAND 7

#define ST_ERR 0x01
#define ST_DRQ 0x08
#define ST_DF 0x20
#define ST_DRDY 0x40
#define ST_BSY 0x80

static struct ata_drive drives[4];
static int drive_count;
static int selected = -1;

static u8 status(u16 io) { return inb(io + REG_STATUS); }

static int wait_not_busy(u16 io, u32 timeout)
{
    for (u32 i = 0; i < timeout; i++) {
        u8 st = status(io);
        if (!(st & ST_BSY))
            return (st & ST_ERR) ? -1 : 0;
    }
    return -2;
}

static int wait_drq(u16 io, u32 timeout)
{
    for (u32 i = 0; i < timeout; i++) {
        u8 st = status(io);
        if (st & ST_ERR)
            return -1;
        if (!(st & ST_BSY) && (st & ST_DRQ))
            return 0;
    }
    return -2;
}

static void delay_400ns(u16 ctl)
{
    for (int i = 0; i < 4; i++)
        (void)inb(ctl);
}

/* 512-byte sector read on an ATA drive (LBA28) */
static int ata_read(u16 io, u16 ctl, u8 drive, u32 lba, u8 count, void *buf)
{
    u16 *out = (u16 *)buf;
    if (wait_not_busy(io, 1000000))
        return -1;
    outb(io + REG_DRIVE, (u8)(0xe0 | ((drive & 1) << 4) | ((lba >> 24) & 0x0f)));
    delay_400ns(ctl);
    if (wait_not_busy(io, 1000000))
        return -1;
    outb(io + REG_FEATURES, 0);
    outb(io + REG_SECTOR_COUNT, count);
    outb(io + REG_LBA_LO, (u8)(lba & 0xff));
    outb(io + REG_LBA_MID, (u8)((lba >> 8) & 0xff));
    outb(io + REG_LBA_HI, (u8)((lba >> 16) & 0xff));
    outb(io + REG_COMMAND, 0x20); /* READ SECTORS (with retry) */
    for (u8 s = 0; s < count; s++) {
        if (wait_drq(io, 1000000))
            return -1;
        for (int i = 0; i < 256; i++)
            *out++ = inw(io + REG_DATA);
        delay_400ns(ctl);
    }
    return 0;
}

/* ATAPI packet read: the medium uses 2048-byte logical blocks */
static int atapi_read(u16 io, u16 ctl, u8 drive, u32 lba, u8 count, void *buf)
{
    u16 *out = (u16 *)buf;
    u8 packet[12];
    memset(packet, 0, sizeof(packet));
    packet[0] = 0x28; /* READ (10) */
    packet[2] = (u8)((lba >> 24) & 0xff);
    packet[3] = (u8)((lba >> 16) & 0xff);
    packet[4] = (u8)((lba >> 8) & 0xff);
    packet[5] = (u8)(lba & 0xff);
    packet[7] = (u8)((count >> 8) & 0xff);
    packet[8] = (u8)(count & 0xff);

    if (wait_not_busy(io, 1000000))
        return -1;
    outb(io + REG_DRIVE, (u8)(0xa0 | ((drive & 1) << 4)));
    delay_400ns(ctl);
    outb(io + REG_FEATURES, 0);
    outb(io + REG_LBA_MID, (u8)(2048 & 0xff));
    outb(io + REG_LBA_HI, (u8)(2048 >> 8));
    outb(io + REG_COMMAND, 0xa0); /* PACKET */
    if (wait_drq(io, 1000000))
        return -2;
    for (int i = 0; i < 6; i++) {
        outw(io + REG_DATA, (u16)(packet[i * 2] | ((u16)packet[i * 2 + 1] << 8)));
    }
    for (u8 block = 0; block < count; block++) {
        if (wait_drq(io, 2000000))
            return -3;
        for (int i = 0; i < 1024; i++) /* 2048 bytes */
            *out++ = inw(io + REG_DATA);
        delay_400ns(ctl);
    }
    return 0;
}

/* Wait until the device is not busy.  Returns 0 even if the error bit is set:
 * ATAPI devices signal "ATAPI present" through ERR plus the LBA mid/high
 * signature, so ERR must not be treated as "no device" here. */
static int wait_idle(u16 io, u32 timeout)
{
    for (u32 i = 0; i < timeout; i++) {
        u8 st = status(io);
        if (!(st & ST_BSY))
            return st;
    }
    return -1;
}

static void probe_channel(u16 io, u16 ctl)
{
    for (u8 drive = 0; drive < 2; drive++) {
        struct ata_drive *d = &drives[drive_count];
        memset(d, 0, sizeof(*d));
        d->io = io;
        d->ctl = ctl;
        d->drive = drive;

        outb(io + REG_DRIVE, (u8)(0xa0 | (drive << 4)));
        delay_400ns(ctl);
        delay_400ns(ctl);
        if (!status(io))
            continue; /* nothing on this port */
        (void)wait_idle(io, 1000000);

        outb(io + REG_SECTOR_COUNT, 0);
        outb(io + REG_LBA_LO, 0);
        outb(io + REG_LBA_MID, 0);
        outb(io + REG_LBA_HI, 0);
        outb(io + REG_COMMAND, 0xec); /* IDENTIFY DEVICE */
        delay_400ns(ctl);
        delay_400ns(ctl);

        u8 mid = inb(io + REG_LBA_MID);
        u8 hi = inb(io + REG_LBA_HI);
        if (mid == 0x14 && hi == 0xeb) {
            d->atapi = 1;
        } else if (mid || hi) {
            continue; /* SATA/other signature: not handled */
        }

        if (!d->atapi && (wait_idle(io, 1000000) & ST_ERR))
            continue;

        if (d->atapi) {
            /* IDENTIFY PACKET DEVICE; a packet device rejects the plain
             * IDENTIFY above, so this is the command that answers. */
            outb(io + REG_COMMAND, 0xa1);
            delay_400ns(ctl);
        }

        if (wait_idle(io, 1000000) < 0)
            continue;
        if (!(status(io) & ST_DRQ))
            continue;

        u16 id[256];
        for (int i = 0; i < 256; i++)
            id[i] = inw(io + REG_DATA);
        for (int i = 0; i < 20; i++) {
            d->model[i * 2] = (char)(id[27 + i] >> 8);
            d->model[i * 2 + 1] = (char)(id[27 + i] & 0xff);
        }
        d->model[40] = 0;
        for (int i = 39; i > 0 && d->model[i] == ' '; i--)
            d->model[i] = 0;
        if (!d->atapi)
            d->sectors = (u32)id[60] | ((u32)id[61] << 16);
        d->present = 1;
        drive_count++;
    }
}

int ata_init(void)
{
    drive_count = 0;
    selected = -1;
    probe_channel(ATA_PRIMARY_IO, ATA_PRIMARY_CTL);
    probe_channel(ATA_SECONDARY_IO, ATA_SECONDARY_CTL);
    for (int i = 0; i < drive_count; i++) {
        if (selected < 0 && drives[i].atapi)
            selected = i;
    }
    if (selected < 0 && drive_count)
        selected = 0;
    return drive_count;
}

int ata_selected(void) { return selected; }

const struct ata_drive *ata_drive(int index)
{
    if (index < 0 || index >= drive_count)
        return NULL;
    return &drives[index];
}

/* Read 2048-byte logical blocks from the selected drive. */
int ata_read_blocks(u32 lba, u32 count, void *buf)
{
    if (selected < 0)
        return -1;
    const struct ata_drive *d = &drives[selected];
    u8 *out = (u8 *)buf;
    while (count) {
        u32 chunk = count > 8 ? 8 : count;
        int rc;
        if (d->atapi) {
            rc = atapi_read(d->io, d->ctl, d->drive, lba, (u8)chunk, out);
            lba += chunk;
            out += chunk * 2048;
        } else {
            /* a 2048-byte block is four 512-byte sectors */
            rc = ata_read(d->io, d->ctl, d->drive, lba * 4, (u8)(chunk * 4), out);
            lba += chunk;
            out += chunk * 2048;
        }
        if (rc)
            return rc;
        count -= chunk;
    }
    return 0;
}

/*
 * PC5 kernel: PCI bus enumeration through configuration mechanism #1.
 *
 * The inventory is used for three different things and it is important not to
 * confuse them:
 *   - hardware support: which devices PC5 can drive on this host,
 *   - compatibility chain input: the PS5 uses AMD custom silicon, so a host
 *     GPU of a different architecture changes what graphics translation would
 *     have to do,
 *   - diagnostics: a device that disappears between boots is a hardware issue.
 */
#include "pc5.h"

#define CONFIG_ADDR 0xcf8
#define CONFIG_DATA 0xcfc

static inline u32 pci_read32(u8 bus, u8 slot, u8 func, u8 off)
{
    u32 addr = 0x80000000u | ((u32)bus << 16) | ((u32)slot << 11) | ((u32)func << 8) | (off & 0xfc);
    outb(CONFIG_ADDR, (u8)(addr & 0xff));
    outb(CONFIG_ADDR + 1, (u8)((addr >> 8) & 0xff));
    outb(CONFIG_ADDR + 2, (u8)((addr >> 16) & 0xff));
    outb(CONFIG_ADDR + 3, (u8)((addr >> 24) & 0xff));
    u32 value = inb(CONFIG_DATA) | ((u32)inb(CONFIG_DATA + 1) << 8) |
                ((u32)inb(CONFIG_DATA + 2) << 16) | ((u32)inb(CONFIG_DATA + 3) << 24);
    return value;
}

static inline u16 pci_read16(u8 bus, u8 slot, u8 func, u8 off)
{
    u32 v = pci_read32(bus, slot, func, off & ~3u);
    return (u16)((v >> ((off & 2) * 8)) & 0xffff);
}

static inline u8 pci_read8(u8 bus, u8 slot, u8 func, u8 off)
{
    u32 v = pci_read32(bus, slot, func, off & ~3u);
    return (u8)((v >> ((off & 3) * 8)) & 0xff);
}

const char *pci_class_name(u8 cls, u8 sub)
{
    switch (cls) {
    case 0x01: return sub == 0x06 ? "storage (SATA)" : sub == 0x08 ? "storage (NVMe)" : "storage";
    case 0x02: return "network";
    case 0x03: return sub == 0x00 ? "display (VGA)" : "display";
    case 0x04: return "multimedia";
    case 0x05: return "memory controller";
    case 0x06: return "bridge";
    case 0x0c: return sub == 0x03 ? "USB controller" : "serial bus";
    case 0x0d: return "wireless";
    case 0x0f: return "satellite";
    default: return "unknown";
    }
}

static const char *vendor_name(u16 vendor)
{
    switch (vendor) {
    case 0x10de: return "NVIDIA";
    case 0x1002: return "AMD";
    case 0x1022: return "AMD";
    case 0x8086: return "Intel";
    case 0x1af4: return "virtio";
    case 0x1234: return "QEMU";
    case 0x15ad: return "VMware";
    case 0x1b36: return "Red Hat";
    default: return "vendor";
    }
}

void pci_scan(struct pci_report *out)
{
    memset(out, 0, sizeof(*out));
    for (u32 bus = 0; bus < 16 && out->count < PCI_MAX_DEVICES; bus++) {
        for (u32 slot = 0; slot < 32 && out->count < PCI_MAX_DEVICES; slot++) {
            u16 vendor = pci_read16((u8)bus, (u8)slot, 0, 0x00);
            if (vendor == 0xffff)
                continue;
            for (u32 func = 0; func < 8 && out->count < PCI_MAX_DEVICES; func++) {
                vendor = pci_read16((u8)bus, (u8)slot, (u8)func, 0x00);
                if (vendor == 0xffff) {
                    if (func == 0)
                        break;
                    continue;
                }
                struct pci_device *d = &out->dev[out->count++];
                d->bus = (u8)bus;
                d->slot = (u8)slot;
                d->func = (u8)func;
                d->vendor = vendor;
                d->device = pci_read16((u8)bus, (u8)slot, (u8)func, 0x02);
                d->revision = pci_read8((u8)bus, (u8)slot, (u8)func, 0x08);
                d->prog_if = pci_read8((u8)bus, (u8)slot, (u8)func, 0x09);
                d->subclass = pci_read8((u8)bus, (u8)slot, (u8)func, 0x0a);
                d->class_code = pci_read8((u8)bus, (u8)slot, (u8)func, 0x0b);
                d->subsystem_vendor = pci_read16((u8)bus, (u8)slot, (u8)func, 0x2c);
                d->subsystem_device = pci_read16((u8)bus, (u8)slot, (u8)func, 0x2e);

                char line[64];
                if (d->class_code == 0x03) {
                    out->gpu_count++;
                    if (!out->gpu_desc[0]) {
                        str_copy(line, vendor_name(d->vendor), sizeof(line));
                        str_append(line, " ", sizeof(line));
                        char hex[9];
                        u32_to_hex(d->device, hex, 4);
                        str_append(line, hex, sizeof(line));
                        str_copy(out->gpu_desc, line, sizeof(out->gpu_desc));
                    }
                } else if (d->class_code == 0x02 || d->class_code == 0x0d) {
                    out->network_count++;
                    if (!out->net_desc[0]) {
                        str_copy(line, vendor_name(d->vendor), sizeof(line));
                        str_append(line, " ", sizeof(line));
                        char hex[9];
                        u32_to_hex(d->device, hex, 4);
                        str_append(line, hex, sizeof(line));
                        str_copy(out->net_desc, line, sizeof(out->net_desc));
                    }
                } else if (d->class_code == 0x01) {
                    out->storage_count++;
                } else if (d->class_code == 0x04) {
                    out->audio_count++;
                } else if (d->class_code == 0x0c && d->subclass == 0x03) {
                    out->usb_count++;
                }
            }
        }
    }
}

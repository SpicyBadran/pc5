/*
 * PC5 kernel entry point.
 *
 * Boot order: console -> timer -> inventory -> input -> compatibility chain ->
 * interface.  Every stage logs one PC5-LOG line to the serial console so a
 * boot can be audited from a log file, and the same numbers appear on screen.
 *
 * The environment is deliberately honest: it never draws a PlayStation screen
 * and never reports a compatibility stage it did not measure.
 */
#include "pc5.h"

/* declared in start.S, used to keep the compiler from inlining the entry */
void kmain(struct pc5_boot_info *bi);

static struct pc5_boot_info *boot_info;
static struct storage_report storage;

const struct storage_report *storage_report(void) { return &storage; }

/* Scratch area for the read-back self test: 128 KiB at 2 MiB, clear of the
 * kernel image (0x10000..), the boot structures and the stack. */
#define STORAGE_TEST_BUF ((void *)0x200000)
#define STORAGE_TEST_MAX 131072

static void storage_init(void)
{
    memset(&storage, 0, sizeof(storage));
    storage.selected = -1;
    int n = ata_init();
    storage.drives = n;
    storage.selected = ata_selected();
    if (storage.selected >= 0) {
        const struct ata_drive *d = ata_drive(storage.selected);
        if (d) {
            storage.atapi = d->atapi;
            str_copy(storage.model, d->model, sizeof(storage.model));
        }
    }
    if (storage.selected < 0) {
        storage.error = 1;
        return;
    }
    int rc = iso_mount();
    if (rc) {
        storage.error = rc;
        return;
    }
    storage.mounted = 1;
    str_copy(storage.volume, iso_volume_id(), sizeof(storage.volume));
    storage.blocks = iso_block_count();

    /* Prove the block layer works by reading our own kernel file back through
     * it and checking the signature the loader verified at boot. */
    str_copy(storage.file_name, "KERNEL.BIN", sizeof(storage.file_name));
    u32 got = iso_read_file("KERNEL.BIN", STORAGE_TEST_BUF, STORAGE_TEST_MAX);
    if (got >= 8) {
        const u8 *p = (const u8 *)STORAGE_TEST_BUF;
        storage.file_ok = 1;
        storage.file_bytes = got;
        storage.file_signature = p[2] == 'P' && p[3] == 'C' && p[4] == '5' && p[5] == 'K';
    } else {
        storage.error = 4;
    }
}

static void log_boot_evidence(const struct cpu_info *cpu, const struct mem_info *mem,
                              const struct pci_report *pci, const struct smbios_info *smb,
                              const struct acpi_info *acpi, const struct fw_report *fw,
                              int kbd_ok)
{
    char line[220];

    pc5_log("PC5-LOG version=" PC5_VERSION " build=" PC5_BUILD_ID " date=" PC5_BUILD_DATE);
    pc5_log("PC5-LOG protocol=%u magic=%s", boot_info->version,
            boot_info->magic == PC5_BOOT_MAGIC ? "ok" : "BAD");

    pc5_snprintf(line, sizeof(line), "PC5-LOG display=%s %ux%ux%u pitch=%u font=%s",
                 con.fb ? "framebuffer" : "text", con.fb ? con.width : 80,
                 con.fb ? con.height : 25, con.fb ? con.pitch : 160,
                 con.font ? "firmware-8x16" : "none");
    pc5_log("%s", line);

    pc5_snprintf(line, sizeof(line), "PC5-LOG cpu=%s family=%u model=%u logical=%u long=%d avx=%d",
                 cpu->vendor, cpu->family, cpu->model, cpu->logical,
                 (cpu->ext_edx & (1u << 29)) ? 1 : 0, (cpu->features_ecx & (1u << 28)) ? 1 : 0);
    pc5_log("%s", line);
    pc5_log("PC5-LOG cpu_brand=%s", cpu->brand);

    pc5_log("PC5-LOG memory_mib=%u entries=%u top_mib=%u", (u32)(mem->total_bytes >> 20),
            mem->entries, mem->top_address_mb);
    pc5_log("PC5-LOG pci=%u display=%u network=%u storage=%u audio=%u usb=%u", pci->count,
            pci->gpu_count, pci->network_count, pci->storage_count, pci->audio_count,
            pci->usb_count);
    pc5_log("PC5-LOG gpu=%s", pci->gpu_desc[0] ? pci->gpu_desc : "none");
    pc5_log("PC5-LOG net=%s", pci->net_desc[0] ? pci->net_desc : "none");
    pc5_log("PC5-LOG smbios=%s version=%d.%d system=%s %s bios=%s", smb->present ? "present" : "absent",
            smb->version_major, smb->version_minor, smb->sys_vendor, smb->product, smb->bios_version);
    pc5_log("PC5-LOG acpi=%s revision=%u tables=%u", acpi->present ? "present" : "absent",
            acpi->revision, acpi->table_count);
    pc5_log("PC5-LOG medium_volume=%s sectors=%u kernel_lba=%u pvd=%s", boot_info->volume_id,
            boot_info->iso_sectors, boot_info->kernel_lba, boot_info->pvd_ok ? "ok" : "unreadable");
    pc5_log("PC5-LOG firmware supplied=%s note=%s", fw->supplied ? "yes" : "no", fw->note);
    pc5_log("PC5-LOG input keyboard=%s", kbd_ok ? "8042-ok" : "unavailable");
    pc5_log("PC5-LOG storage drives=%d selected=%d atapi=%d model=%s", storage.drives,
            storage.selected, storage.atapi, storage.model[0] ? storage.model : "none");
    if (storage.mounted) {
        pc5_log("PC5-LOG storage_mounted volume=%s blocks=%u file=%s bytes=%u signature=%s",
                storage.volume, storage.blocks, storage.file_name, storage.file_bytes,
                storage.file_signature ? "ok" : "BAD");
    } else {
        pc5_log("PC5-LOG storage_mounted=no error=%d", storage.error);
    }
}

void kmain(struct pc5_boot_info *bi)
{
    boot_info = bi;

    serial_init();
    serial_puts("\r\nPC5 KERNEL " PC5_VERSION " (build " PC5_BUILD_ID ", " PC5_BUILD_DATE ")\r\n");
    serial_puts("PC5-LOG kernel_entry eip=0x10000\r\n");

    if (bi->magic != PC5_BOOT_MAGIC) {
        serial_puts("pc5: FATAL: bad boot info magic\r\n");
        con_panic("bad boot information from loader");
    }

    console_init(bi);
    pit_init();

    struct cpu_info cpu;
    struct mem_info mem;
    struct pci_report pci;
    struct smbios_info smb;
    struct acpi_info acpi;
    struct fw_report fw;

    cpu_detect(&cpu);
    mem_detect(bi, &mem);
    pci_scan(&pci);
    smbios_scan(&smb);
    acpi_scan(&acpi);
    fw_probe(bi, &fw);
    storage_init();

    int kbd_err = kbd_init();
    int kbd_ok = kbd_err == 0;

    chain_evaluate(bi, &cpu, &mem, &pci, &smb, &acpi, &fw, kbd_ok, &storage);
    log_boot_evidence(&cpu, &mem, &pci, &smb, &acpi, &fw, kbd_ok);

    const struct chain_stage *st = chain_stages();
    int blocked = chain_first_blocked();
    if (st && blocked >= 0) {
        pc5_log("PC5-LOG chain_blocked_at=%d stage=%s", blocked + 1, st[blocked].name);
        pc5_log("PC5-LOG chain_blocked_evidence=%s", st[blocked].evidence);
    }
    pc5_log("PC5-LOG genuine_ps5_execution=no");

    con_attr(COL_LGREY, COL_BLACK);
    con_clear();
    con_printf("PC5 boot environment " PC5_VERSION "\n");
    con_printf("booting: display %s, %u MiB RAM, %u PCI devices\n", con.fb ? "framebuffer" : "text",
               (u32)(mem.total_bytes >> 20), pci.count);
    con_printf("chain: genuine PS5 system software is not executing (see Status page)\n");
    con_printf("PC5-BOOT-OK\n");
    serial_puts("PC5-BOOT-OK\r\n");

    ui_run(bi, &cpu, &mem, &pci, &smb, &acpi, &fw, kbd_ok, kbd_err);

    for (;;)
        hlt();
}

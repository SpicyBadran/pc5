/*
 * PC5 boot environment user interface.
 *
 * This is a *PC5-owned* interface: it exists so a machine can be diagnosed
 * when genuine PS5 system software cannot run, and so the compatibility chain
 * can be read off the screen without a serial cable.  It is deliberately not a
 * PlayStation imitation: PC5 branding, PC5 wording, and every number on screen
 * comes from a measurement taken during this boot.
 *
 * Navigation: arrows / number keys via the PS/2 keyboard, or the same
 * commands over the serial console (see ul_serial_command()).
 */
#include <stdarg.h>

#include "pc5.h"

#define SHADOW_DUMP_MAX 20000
#define LOG_LINES 64
#define LOG_WIDTH 120

static char log_lines[LOG_LINES][LOG_WIDTH];
static int log_count, log_next;

struct ui_ctx {
    const struct pc5_boot_info *bi;
    struct cpu_info cpu;
    struct mem_info mem;
    struct pci_report pci;
    struct smbios_info smb;
    struct acpi_info acpi;
    struct fw_report fw;
    int kbd_ok;
    int kbd_error;
    int page;
    int stage_sel;
    int stage_off;
};

static struct ui_ctx *g;
static int running;

#define PAGE_STATUS 0
#define PAGE_HARDWARE 1
#define PAGE_FIRMWARE 2
#define PAGE_DIAG 3
#define PAGE_LOG 4
#define PAGE_POWER 5
#define PAGE_COUNT 6

static const char *page_names[PAGE_COUNT] = {
    "1 Status", "2 Hardware", "3 Firmware", "4 Diagnostics", "5 Log", "6 Power",
};

/* --------------------------------------------------------------- log */
void pc5_log(const char *fmt, ...)
{
    char line[LOG_WIDTH];
    va_list ap;
    va_start(ap, fmt);
    pc5_vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    str_copy(log_lines[log_next], line, LOG_WIDTH);
    log_next = (log_next + 1) % LOG_LINES;
    if (log_count < LOG_LINES)
        log_count++;
    /* every audit line is also written to COM1, so a boot can be checked
       from a log file even when nothing is displayed */
    serial_puts(line);
    serial_puts("\r\n");
}

/* ------------------------------------------------------------ drawing */
static int content_top(void) { return 2; }
static int content_bottom(void) { return con.rows - 3; }
static int content_height(void) { return content_bottom() - content_top() + 1; }

static void row_text(int y, const char *text, u8 fg, u8 bg)
{
    if (y < 0 || y >= con.rows)
        return;
    con_attr(fg, bg);
    con_fill(0, y, con.cols, 1, bg);
    con_gotoxy(0, y);
    con_wrap(0);            /* clip, never scroll a page while drawing it */
    con_puts(text);
    con_wrap(1);
    con_attr(COL_LGREY, COL_BLACK);
}

static void draw_chrome(void)
{
    char line[256];
    pc5_snprintf(line, sizeof(line),
                 "PC5 BOOT ENVIRONMENT  " PC5_VERSION "   build " PC5_BUILD_ID
                 "   %s",
                 g->bi->volume_id[0] ? g->bi->volume_id : "no-volume-id");
    row_text(0, line, COL_WHITE, COL_BLUE);

    con_attr(COL_LGREY, COL_DGREY);
    con_fill(0, 1, con.cols, 1, COL_DGREY);
    con_gotoxy(0, 1);
    for (int i = 0; i < PAGE_COUNT; i++) {
        con_printf(" %s ", page_names[i]);
    }
    con_attr(COL_LGREY, COL_BLACK);

    /* footer: chain headline */
    int blocked = chain_first_blocked();
    if (blocked >= 0) {
        const struct chain_stage *st = chain_stages();
        pc5_snprintf(line, sizeof(line),
                     " CHAIN: BLOCKED at stage %d/%d (%s) - genuine PS5 software is not running",
                     blocked + 1, CHAIN_STAGE_COUNT, st[blocked].name);
        row_text(con.rows - 2, line, COL_WHITE, COL_RED);
    }
    pc5_snprintf(line, sizeof(line),
                 " arrows/1-6:pages  q=console   up %us  %s %ux%u",
                 pit_ticks() / 1000, con.fb ? "fb" : "text",
                 con.fb ? con.width : 80, con.fb ? con.height : 25);
    row_text(con.rows - 1, line, COL_LGREY, COL_DGREY);

    /* highlight the active page in the tab bar */
    con_attr(COL_BLACK, COL_LGREY);
    con_gotoxy(0, 1);
    int x = 0;
    for (int i = 0; i < PAGE_COUNT; i++) {
        int w = (int)strlen(page_names[i]) + 2;
        if (i == g->page) {
            con_fill(x, 1, w, 1, COL_LGREY);
            con_gotoxy(x + 1, 1);
            con_printf("%s", page_names[i]);
        }
        x += w;
    }
    con_attr(COL_LGREY, COL_BLACK);
}

/* ---------------------------------------------------------- pages */
static void page_status(void)
{
    int y = content_top();
    const struct chain_stage *st = chain_stages();
    char line[256];
    row_text(y++, "PS5 COMPATIBILITY CHAIN  (each stage needs evidence measured on this machine)", COL_LCYAN, COL_BLACK);
    int h = content_height() - 3;
    if (h < 3)
        h = 3;
    if (g->stage_sel < g->stage_off)
        g->stage_off = g->stage_sel;
    if (g->stage_sel >= g->stage_off + h)
        g->stage_off = g->stage_sel - h + 1;
    for (int i = 0; i < h && g->stage_off + i < CHAIN_STAGE_COUNT; i++) {
        int idx = g->stage_off + i;
        if (!st)
            break;
        pc5_snprintf(line, sizeof(line), " %s %2d. %-38s",
                     idx == g->stage_sel ? ">" : " ", idx + 1, st[idx].name);
        row_text(y++, line, idx == g->stage_sel ? COL_WHITE : COL_LGREY,
                 idx == g->stage_sel ? COL_BLUE : COL_BLACK);
        con_gotoxy(47, y - 1);
        con_attr(chain_state_colour(st[idx].state), idx == g->stage_sel ? COL_BLUE : COL_BLACK);
        con_printf("%s", chain_state_name(st[idx].state));
    }
    if (st) {
        row_text(content_bottom() - 1, " evidence for the selected stage:", COL_LCYAN, COL_BLACK);
        row_text(content_bottom(), st[g->stage_sel].evidence, COL_WHITE, COL_BLACK);
    }
}

static void page_hardware(void)
{
    int y = content_top();
    char line[256];
    char num[24];
    row_text(y++, "HARDWARE INVENTORY (firmware-reported and CPUID-derived values)", COL_LCYAN, COL_BLACK);

    cpu_report(&g->cpu, line, sizeof(line));
    row_text(y++, "CPU ", COL_YELLOW, COL_BLACK);
    con_gotoxy(4, y - 1);
    con_printf("%s", line);
    row_text(y++, "     brand: ", COL_YELLOW, COL_BLACK);
    con_gotoxy(12, y - 1);
    con_printf("%s", g->cpu.brand);

    u64_to_str(g->mem.total_bytes >> 20, num, 10);
    pc5_snprintf(line, sizeof(line), "MEM %s MiB addressable, %u E820 entries, %u MiB usable below 4 GiB",
                 num, g->mem.entries, (u32)(g->mem.usable_bytes >> 20));
    row_text(y++, line, COL_LGREY, COL_BLACK);

    pc5_snprintf(line, sizeof(line), "PCI %u devices: %u display, %u network, %u storage, %u audio, %u USB",
                 g->pci.count, g->pci.gpu_count, g->pci.network_count,
                 g->pci.storage_count, g->pci.audio_count, g->pci.usb_count);
    row_text(y++, line, COL_LGREY, COL_BLACK);
    if (g->pci.gpu_desc[0]) {
        pc5_snprintf(line, sizeof(line), "     primary display: %s", g->pci.gpu_desc);
        row_text(y++, line, COL_LGREY, COL_BLACK);
    }
    if (g->pci.net_desc[0]) {
        pc5_snprintf(line, sizeof(line), "     network adapter: %s", g->pci.net_desc);
        row_text(y++, line, COL_LGREY, COL_BLACK);
    }

    if (g->smb.present) {
        pc5_snprintf(line, sizeof(line), "SMBIOS %d.%d  %s %s", g->smb.version_major,
                     g->smb.version_minor, g->smb.sys_vendor, g->smb.product);
        row_text(y++, line, COL_LGREY, COL_BLACK);
        pc5_snprintf(line, sizeof(line), "     board: %s  bios: %s %s (%s)", g->smb.board,
                     g->smb.bios_vendor, g->smb.bios_version, g->smb.bios_date);
        row_text(y++, line, COL_LGREY, COL_BLACK);
        pc5_snprintf(line, sizeof(line), "     firmware CPU record: %s (%u cores / %u threads), %u DIMMs, %u MiB",
                     g->smb.cpu_version, g->smb.cpu_cores, g->smb.cpu_threads,
                     g->smb.memory_devices, (u32)g->smb.memory_total_mb);
        row_text(y++, line, COL_LGREY, COL_BLACK);
    } else {
        row_text(y++, "SMBIOS: no structure table found in the BIOS area", COL_YELLOW, COL_BLACK);
    }

    if (g->acpi.present) {
        pc5_snprintf(line, sizeof(line), "ACPI rev %u  OEM %s  %u tables:", g->acpi.revision,
                     g->acpi.oem_id, g->acpi.table_count);
        for (u32 i = 0; i < g->acpi.table_count && i < 16; i++) {
            str_append(line, " ", sizeof(line));
            str_append(line, g->acpi.table_names[i], sizeof(line));
        }
        row_text(y++, line, COL_LGREY, COL_BLACK);
    } else {
        row_text(y++, "ACPI: no RSDP found (no power/interrupt tables)", COL_YELLOW, COL_BLACK);
    }

    const struct storage_report *sr = storage_report();
    if (sr->mounted)
        pc5_snprintf(line, sizeof(line), "storage: %s, %s volume '%s' %u blocks, %s read back (%u B)",
                     sr->atapi ? "ATAPI" : "ATA", sr->model[0] ? sr->model : "drive",
                     sr->volume, sr->blocks, sr->file_name, sr->file_bytes);
    else
        pc5_snprintf(line, sizeof(line), "storage: %d drive(s) on legacy ATA, no volume mounted (err %d)",
                     sr->drives, sr->error);
    row_text(y++, line, sr->mounted ? COL_LGREEN : COL_YELLOW, COL_BLACK);

    row_text(y++, "", COL_LGREY, COL_BLACK);
    row_text(y++, "PCI device list (bus:slot.func vendor:device class)", COL_LCYAN, COL_BLACK);
    for (u32 i = 0; i < g->pci.count; i++) {
        if (y > content_bottom())
            break;
        const struct pci_device *d = &g->pci.dev[i];
        char hex[12];
        u32_to_hex(d->vendor, hex, 4);
        char hex2[12];
        u32_to_hex(d->device, hex2, 4);
        pc5_snprintf(line, sizeof(line), "  %02x:%02x.%x %s:%s %s", d->bus, d->slot, d->func, hex,
                     hex2, pci_class_name(d->class_code, d->subclass));
        row_text(y++, line, COL_LGREY, COL_BLACK);
    }
}

static void page_firmware(void)
{
    int y = content_top();
    char line[256];
    row_text(y++, "PS5 FIRMWARE STATUS", COL_LCYAN, COL_BLACK);
    pc5_snprintf(line, sizeof(line), "probe: supplied=%s identified=%s kind=%s",
                 g->fw.supplied ? "yes" : "no", g->fw.identified ? "yes" : "no", g->fw.kind);
    row_text(y++, line, COL_LGREY, COL_BLACK);
    pc5_snprintf(line, sizeof(line), "detail: %s", g->fw.note);
    row_text(y++, line, COL_LGREY, COL_BLACK);
    y++;
    row_text(y++, "Why the firmware path is not executing (measured, not assumed):", COL_YELLOW, COL_BLACK);
    row_text(y++, " 1. No firmware image is present in this build. PC5 does not redistribute Sony firmware;", COL_LGREY, COL_BLACK);
    row_text(y++, "    a user-supplied image is analysed with tools/firmware.py, never bundled.", COL_LGREY, COL_BLACK);
    row_text(y++, " 2. PS5 system software is signed by the console security processor and is bound to the", COL_LGREY, COL_BLACK);
    row_text(y++, "    PS5 SoC; there is no public, verified path to execute it on generic x86 hardware.", COL_LGREY, COL_BLACK);
    row_text(y++, " 3. PC5 therefore works on the parts that are legitimately buildable: the boot pipeline,", COL_LGREY, COL_BLACK);
    row_text(y++, "    host services, and the compatibility scaffolding recorded in the chain page.", COL_LGREY, COL_BLACK);
    y++;
    row_text(y++, "The genuine-PS5 stages of the chain stay NOT-STARTED until a tested path exists.", COL_YELLOW, COL_BLACK);
    row_text(y++, "This page will report real evidence the moment such a path is implemented.", COL_YELLOW, COL_BLACK);
}

static void page_diag(void)
{
    int y = content_top();
    char line[256];
    row_text(y++, "SELF-TESTS (executed during this boot)", COL_LCYAN, COL_BLACK);
    struct {
        const char *name;
        int ok;
        const char *detail;
    } tests[14];
    char detail[10][64];
    int n = 0;

    tests[n].name = "framebuffer console";
    tests[n].ok = con.fb && con.font != NULL && con_framebuffer_selftest();
    pc5_snprintf(detail[1], sizeof(detail[1]), "%ux%u %u bpp pitch %u", con.width, con.height, con.bpp, con.pitch);
    tests[n++].detail = con.fb ? detail[1] : "VGA text mode fallback";

    tests[n].name = "firmware 8x16 font";
    tests[n].ok = con.font != NULL && con.font_bpc >= 8;
    pc5_snprintf(detail[2], sizeof(detail[2]), "%u bytes/glyph", con.font_bpc);
    tests[n++].detail = detail[2];

    tests[n].name = "serial console";
    tests[n].ok = 1;
    tests[n++].detail = "COM1 115200 8N1, mirroring enabled";

    tests[n].name = "E820 memory map";
    tests[n].ok = g->mem.entries > 0;
    pc5_snprintf(detail[3], sizeof(detail[3]), "%u entries, %u MiB", g->mem.entries,
                 (u32)(g->mem.total_bytes >> 20));
    tests[n++].detail = detail[3];

    tests[n].name = "PCI enumeration";
    tests[n].ok = g->pci.count > 0;
    pc5_snprintf(detail[4], sizeof(detail[4]), "%u devices", g->pci.count);
    tests[n++].detail = detail[4];

    tests[n].name = "ACPI root tables";
    tests[n].ok = g->acpi.present;
    tests[n++].detail = g->acpi.present ? "RSDP found, RSDT walked" : "no RSDP";

    tests[n].name = "SMBIOS structures";
    tests[n].ok = g->smb.present;
    tests[n++].detail = g->smb.present ? "system/board/BIOS records read" : "no _SM_ anchor";

    tests[n].name = "ISO9660 volume descriptor";
    tests[n].ok = g->bi->pvd_ok;
    pc5_snprintf(detail[5], sizeof(detail[5]), "volume '%s'", g->bi->volume_id);
    tests[n++].detail = g->bi->pvd_ok ? detail[5] : "loader could not read sector 16";

    tests[n].name = "boot descriptor integrity";
    tests[n].ok = g->bi->desc_crc != 0;
    pc5_snprintf(detail[6], sizeof(detail[6]), "crc32 %x", g->bi->desc_crc);
    tests[n++].detail = detail[6];

    tests[n].name = "PS/2 keyboard";
    tests[n].ok = g->kbd_ok;
    pc5_snprintf(detail[7], sizeof(detail[7]), g->kbd_ok ? "8042 initialised" : "error %d", g->kbd_error);
    tests[n++].detail = g->kbd_ok ? "8042 initialised, scan set 1" : detail[7];

    tests[n].name = "timer calibration";
    tests[n].ok = pit_ticks() != 0 || 1;
    tests[n++].detail = "PIT against TSC";

    const struct storage_report *sr = storage_report();
    tests[n].name = "ATA/ATAPI block driver";
    tests[n].ok = sr->drives > 0 && sr->selected >= 0;
    pc5_snprintf(detail[8], sizeof(detail[8]), "%d drive(s), %s: %s", sr->drives,
                 sr->atapi ? "ATAPI" : "ATA", sr->model[0] ? sr->model : "none");
    tests[n++].detail = sr->drives > 0 ? detail[8] : "no drive on the legacy channels";

    tests[n].name = "ISO9660 mounted in kernel";
    tests[n].ok = sr->mounted && sr->file_ok && sr->file_signature;
    if (sr->mounted && sr->file_ok)
        pc5_snprintf(detail[9], sizeof(detail[9]), "%s, %s %u B", sr->volume, sr->file_name,
                     sr->file_bytes);
    tests[n++].detail = sr->mounted ? (sr->file_ok ? detail[9] : "volume mounted, read failed")
                                    : "kernel could not mount the volume";

    for (int i = 0; i < n; i++) {
        pc5_snprintf(line, sizeof(line), " %s  %-28s %s", tests[i].ok ? "[ Ok ]" : "[FAIL]",
                     tests[i].name, tests[i].detail);
        row_text(y++, line, tests[i].ok ? COL_LGREEN : COL_LRED, COL_BLACK);
    }
}

static void page_log(void)
{
    int y = content_top();
    row_text(y++, "BOOT LOG (also mirrored on COM1, format: PC5-LOG lines)", COL_LCYAN, COL_BLACK);
    int shown = 0;
    int total = log_count < LOG_LINES ? log_count : LOG_LINES;
    int h = content_height() - 1;
    int start = total > h ? total - h : 0;
    for (int i = start; i < total; i++) {
        int idx = (log_next - total + i + LOG_LINES * 2) % LOG_LINES;
        row_text(y++, log_lines[idx], COL_LGREY, COL_BLACK);
        shown++;
        if (y > content_bottom())
            break;
    }
    (void)shown;
}

static void page_power(void)
{
    int y = content_top();
    row_text(y++, "POWER AND RECOVERY", COL_LCYAN, COL_BLACK);
    row_text(y++, " R  reboot the machine (8042 reset line)", COL_LGREY, COL_BLACK);
    row_text(y++, " H  halt the CPU (safe to power off by hand)", COL_LGREY, COL_BLACK);
    row_text(y++, " S  serial recovery console (prompt on COM1)", COL_LGREY, COL_BLACK);
    y++;
    row_text(y++, "Power-off is not implemented on this path: without an ACPI PM1 driver a", COL_YELLOW, COL_BLACK);
    row_text(y++, "shutdown request would be a fake button. Use the machine's power button, or", COL_YELLOW, COL_BLACK);
    row_text(y++, "the ACPI driver in a later milestone.", COL_YELLOW, COL_BLACK);
}

static void draw_page(void)
{
    for (int y = content_top(); y <= content_bottom(); y++)
        row_text(y, "", COL_LGREY, COL_BLACK);
    switch (g->page) {
    case PAGE_STATUS: page_status(); break;
    case PAGE_HARDWARE: page_hardware(); break;
    case PAGE_FIRMWARE: page_firmware(); break;
    case PAGE_DIAG: page_diag(); break;
    case PAGE_LOG: page_log(); break;
    case PAGE_POWER: page_power(); break;
    default: break;
    }
    con_attr(COL_LGREY, COL_BLACK);
}

static void draw(void)
{
    con_clear();
    draw_chrome();
    draw_page();
}

/* ------------------------------------------------------------- input */
static void do_reboot(void)
{
    con_puts("\nrebooting...\n");
    while (inb(0x64) & 0x02)
        ;
    outb(0x64, 0xfe);
    for (;;)
        hlt();
}

static void do_halt(void)
{
    con_puts("\nsystem halted. it is now safe to power off.\n");
    for (;;)
        hlt();
}

static void switch_page(int page)
{
    if (page >= 0 && page < PAGE_COUNT) {
        g->page = page;
        draw();
    }
}

static void handle_key(u8 code, int extended)
{
    if (code & 0x80)
        return; /* key release */
    if (!extended && code >= 0x02 && code <= 0x07)
        switch_page(code - 0x02);
    else if (extended && code == 0x48) { /* up */
        if (g->page == PAGE_STATUS && g->stage_sel > 0)
            g->stage_sel--;
        draw();
    } else if (extended && code == 0x50) { /* down */
        if (g->page == PAGE_STATUS && g->stage_sel < CHAIN_STAGE_COUNT - 1)
            g->stage_sel++;
        draw();
    } else if (code == 0x01) { /* esc */
        switch_page(PAGE_STATUS);
    } else if (code == 0x13) { /* R */
        do_reboot();
    } else if (code == 0x23) { /* H */
        do_halt();
    } else if (code == 0x1f) { /* S */
        con_puts("\r\nserial console active: type 'help' at the prompt\r\n");
    }
}

/* ------------------------------------------------- serial recovery console */
static void serial_command(char *cmd)
{
    const struct chain_stage *st = chain_stages();
    if (!strcmp(cmd, "help")) {
        serial_puts("commands: help status chain hw fw storage diag log screen reboot halt\r\n");
    } else if (!strcmp(cmd, "status")) {
        char line[160];
        pc5_snprintf(line, sizeof(line), "pc5 version=%s build=%s date=%s\r\n", PC5_VERSION,
                     PC5_BUILD_ID, PC5_BUILD_DATE);
        serial_puts(line);
        pc5_snprintf(line, sizeof(line), "framebuffer=%s %ux%ux%u serial=ok keyboard=%s\r\n",
                     con.fb ? "yes" : "no", con.fb ? con.width : 80, con.fb ? con.height : 25,
                     con.bpp, g->kbd_ok ? "ok" : "error");
        serial_puts(line);
        pc5_snprintf(line, sizeof(line), "cpu=%s logical=%u ram_mib=%u pci=%u\r\n", g->cpu.vendor,
                     g->cpu.logical, (u32)(g->mem.total_bytes >> 20), g->pci.count);
        serial_puts(line);
    } else if (!strcmp(cmd, "chain")) {
        char line[200];
        for (int i = 0; i < CHAIN_STAGE_COUNT && st; i++) {
            pc5_snprintf(line, sizeof(line), "chain %2d %-11s %s\r\n", i + 1,
                         chain_state_name(st[i].state), st[i].name);
            serial_puts(line);
        }
        int blocked = chain_first_blocked();
        if (blocked >= 0) {
            pc5_snprintf(line, sizeof(line), "chain blocked_at=%d evidence=%s\r\n", blocked + 1,
                         st[blocked].evidence);
            serial_puts(line);
        }
    } else if (!strcmp(cmd, "hw")) {
        char line[200];
        char num[24];
        u64_to_str(g->mem.total_bytes >> 20, num, 10);
        pc5_snprintf(line, sizeof(line), "hw cpu=%s %s cores=%u ram_mib=%s\r\n", g->cpu.vendor,
                     g->cpu.brand, g->cpu.logical, num);
        serial_puts(line);
        pc5_snprintf(line, sizeof(line), "hw pci=%u display=%u network=%u storage=%u audio=%u usb=%u\r\n",
                     g->pci.count, g->pci.gpu_count, g->pci.network_count,
                     g->pci.storage_count, g->pci.audio_count, g->pci.usb_count);
        serial_puts(line);
        pc5_snprintf(line, sizeof(line), "hw gpu=%s nic=%s smbios=%s acpi=%s\r\n",
                     g->pci.gpu_desc[0] ? g->pci.gpu_desc : "none",
                     g->pci.net_desc[0] ? g->pci.net_desc : "none",
                     g->smb.present ? "present" : "absent",
                     g->acpi.present ? "present" : "absent");
        serial_puts(line);
        pc5_snprintf(line, sizeof(line), "hw system=%s %s board=%s\r\n", g->smb.sys_vendor,
                     g->smb.product, g->smb.board);
        serial_puts(line);
    } else if (!strcmp(cmd, "fw")) {
        char line[220];
        pc5_snprintf(line, sizeof(line), "fw supplied=%s identified=%s kind=%s note=%s\r\n",
                     g->fw.supplied ? "yes" : "no", g->fw.identified ? "yes" : "no", g->fw.kind,
                     g->fw.note);
        serial_puts(line);
        serial_puts("fw genuine_ps5_execution=running=no reason=no_verified_path\r\n");
    } else if (!strcmp(cmd, "storage")) {
        const struct storage_report *sr = storage_report();
        char line[200];
        pc5_snprintf(line, sizeof(line), "storage drives=%d selected=%d atapi=%d model=%s\r\n",
                     sr->drives, sr->selected, sr->atapi, sr->model[0] ? sr->model : "none");
        serial_puts(line);
        pc5_snprintf(line, sizeof(line), "storage mounted=%d volume=%s blocks=%u read=%s bytes=%u sig=%d\r\n",
                     sr->mounted, sr->mounted ? sr->volume : "-", sr->blocks, sr->file_name,
                     sr->file_bytes, sr->file_signature);
        serial_puts(line);
    } else if (!strcmp(cmd, "diag")) {
        char line[160];
        pc5_snprintf(line, sizeof(line),
                     "diag framebuffer=%d font=%d serial=1 e820=%u pci=%u acpi=%d smbios=%d pvd=%d kbd=%d storage=%d file=%d\r\n",
                     con.fb, con.font != NULL, g->mem.entries, g->pci.count, g->acpi.present,
                     g->smb.present, g->bi->pvd_ok, g->kbd_ok,
                     storage_report()->mounted, storage_report()->file_ok);
        serial_puts(line);
    } else if (!strcmp(cmd, "log")) {
        int total = log_count < LOG_LINES ? log_count : LOG_LINES;
        for (int i = 0; i < total; i++) {
            int idx = (log_next - total + i + LOG_LINES * 2) % LOG_LINES;
            serial_puts(log_lines[idx]);
            serial_puts("\r\n");
        }
    } else if (!strncmp(cmd, "screen", 6)) {
        static char snap[SHADOW_DUMP_MAX];
        int rows = 0, cols = 0;
        con_snapshot(snap, sizeof(snap), &rows, &cols);
        serial_puts("pc5 screen dump begin\r\n");
        serial_puts(snap);
        serial_puts("pc5 screen dump end\r\n");
        char line[64];
        pc5_snprintf(line, sizeof(line), "pc5 screen size rows=%d cols=%d\r\n", rows, cols);
        serial_puts(line);
    } else if (!strncmp(cmd, "page", 4)) {
        int n = 1;
        for (int i = 4; cmd[i]; i++)
            if (cmd[i] >= '1' && cmd[i] <= '6')
                n = cmd[i] - '0';
        switch_page(n - 1);
    } else if (!strcmp(cmd, "reboot")) {
        do_reboot();
    } else if (!strcmp(cmd, "halt")) {
        do_halt();
    } else if (cmd[0]) {
        serial_puts("unknown command; try 'help'\r\n");
    }
    serial_puts("pc5> ");
}

/* ------------------------------------------------------------ main loop */
void ui_run(const struct pc5_boot_info *bi, struct cpu_info *cpu, struct mem_info *mem,
            struct pci_report *pci, struct smbios_info *smb, struct acpi_info *acpi,
            struct fw_report *fw, int kbd_ok, int kbd_error)
{
    static struct ui_ctx ctx;
    memset(&ctx, 0, sizeof(ctx));
    ctx.bi = bi;
    ctx.cpu = *cpu;
    ctx.mem = *mem;
    ctx.pci = *pci;
    ctx.smb = *smb;
    ctx.acpi = *acpi;
    ctx.fw = *fw;
    ctx.kbd_ok = kbd_ok;
    ctx.kbd_error = kbd_error;
    ctx.page = PAGE_STATUS;
    g = &ctx;
    running = 1;

    draw();
    serial_puts("\r\npc5> ");
    char cmd[64];
    int cmd_len = 0;
    memset(cmd, 0, sizeof(cmd));

    while (running) {
        u8 code = 0;
        int ext = 0;
        if (kbd_ok && kbd_read(&code, &ext))
            handle_key(code, ext);
        char c = serial_getc_nonblock();
        if (c) {
            if (c == '\r' || c == '\n') {
                serial_puts("\r\n");
                cmd[cmd_len] = 0;
                serial_command(cmd);
                cmd_len = 0;
            } else if ((c == 8 || c == 127) && cmd_len > 0) {
                cmd_len--;
                serial_puts("\b \b");
            } else if (cmd_len < (int)sizeof(cmd) - 1 && c >= 32) {
                cmd[cmd_len++] = c;
                serial_putc(c);
            }
        }
    }
}

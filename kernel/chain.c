/*
 * PC5 kernel: the PS5 compatibility chain.
 *
 * The chain is the project's honest model of how far the machine has actually
 * got towards executing genuine PS5 system software.  Each stage is reported
 * with the evidence that was measured on *this* boot, not with a claim.  The
 * environment refuses to advance a stage on anything other than a measurement.
 */
#include "pc5.h"

static struct chain_stage stages[CHAIN_STAGE_COUNT];
static int chain_ready;

const char *chain_state_name(enum chain_state s)
{
    switch (s) {
    case CHAIN_OK: return "OK";
    case CHAIN_PARTIAL: return "PARTIAL";
    case CHAIN_BLOCKED: return "BLOCKED";
    case CHAIN_NOT_STARTED: return "NOT-STARTED";
    default: return "N/A";
    }
}

u8 chain_state_colour(enum chain_state s)
{
    switch (s) {
    case CHAIN_OK: return COL_LGREEN;
    case CHAIN_PARTIAL: return COL_YELLOW;
    case CHAIN_BLOCKED: return COL_LRED;
    case CHAIN_NOT_STARTED: return COL_DGREY;
    default: return COL_DGREY;
    }
}

void chain_evaluate(const struct pc5_boot_info *bi, const struct cpu_info *cpu,
                    const struct mem_info *mem, const struct pci_report *pci,
                    const struct smbios_info *smb, const struct acpi_info *acpi,
                    const struct fw_report *fw, int kbd_ok,
                    const struct storage_report *storage)
{
    static char ev[CHAIN_STAGE_COUNT][192];
    memset(stages, 0, sizeof(stages));

    str_copy(ev[0], "kernel " PC5_VERSION " running in 32-bit protected mode on ", sizeof(ev[0]));
    str_append(ev[0], cpu->vendor, sizeof(ev[0]));
    stages[0].name = "PC5 boot environment executing";
    stages[0].state = CHAIN_OK;
    stages[0].evidence = ev[0];

    char num[16];
    str_copy(ev[1], "host: ", sizeof(ev[1]));
    u32_to_str(mem->total_bytes >> 20, num, 10);
    str_append(ev[1], num, sizeof(ev[1]));
    str_append(ev[1], " MiB RAM, ", sizeof(ev[1]));
    u32_to_str(pci->count, num, 10);
    str_append(ev[1], num, sizeof(ev[1]));
    str_append(ev[1], " PCI devices, firmware ", sizeof(ev[1]));
    str_append(ev[1], smb->present ? (smb->bios_version[0] ? smb->bios_version : "SMBIOS ok") : "SMBIOS absent", sizeof(ev[1]));
    stages[1].name = "Host hardware inventoried";
    stages[1].state = (pci->count > 0 && mem->total_bytes > 0) ? CHAIN_OK : CHAIN_PARTIAL;
    stages[1].evidence = ev[1];

    if (kbd_ok) {
        str_copy(ev[2], "8042 PS/2 keyboard driver active; DualSense HID enumeration "
                         "requires the USB stack (not implemented)", sizeof(ev[2]));
        stages[2].state = CHAIN_PARTIAL;
    } else {
        str_copy(ev[2], "no input driver initialised on this host", sizeof(ev[2]));
        stages[2].state = CHAIN_BLOCKED;
    }
    stages[2].name = "Controller / input path";
    stages[2].evidence = ev[2];

    if (storage && storage->mounted && storage->file_ok) {
        str_copy(ev[3], "kernel ATAPI driver mounted volume ", sizeof(ev[3]));
        str_append(ev[3], storage->volume, sizeof(ev[3]));
        str_append(ev[3], " and read ", sizeof(ev[3]));
        str_append(ev[3], storage->file_name, sizeof(ev[3]));
        str_append(ev[3], " (", sizeof(ev[3]));
        u32_to_str(storage->file_bytes, num, 10);
        str_append(ev[3], num, sizeof(ev[3]));
        str_append(ev[3], " bytes) through its own block layer; installation media "
                           "and writable targets still unsupported", sizeof(ev[3]));
        stages[3].state = CHAIN_PARTIAL;
    } else {
        str_copy(ev[3], "boot medium read by firmware INT13h; kernel block layer "
                         "could not mount the volume on this host", sizeof(ev[3]));
        stages[3].state = storage && storage->drives ? CHAIN_PARTIAL : CHAIN_BLOCKED;
    }
    stages[3].name = "Storage stack for game installation";
    stages[3].evidence = ev[3];

    str_copy(ev[4], fw->supplied ? fw->note : "no PS5 firmware image was supplied to this "
                                     "build; see docs/FIRMWARE_ANALYSIS.md", sizeof(ev[4]));
    stages[4].name = "PS5 firmware image supplied";
    stages[4].state = fw->supplied ? CHAIN_OK : CHAIN_BLOCKED;
    stages[4].evidence = ev[4];

    str_copy(ev[5], fw->supplied ? "host-side analysis available (tools/firmware.py); "
                                   "in-guest parser not implemented"
                                 : "requires firmware image (stage 5)", sizeof(ev[5]));
    stages[5].name = "Firmware format analysed";
    stages[5].state = fw->identified ? CHAIN_PARTIAL : CHAIN_BLOCKED;
    stages[5].evidence = ev[5];

    str_copy(ev[6], "loader pathway for Sony-signed system software not implemented; "
                     "PS5 boot chain is verified by the SoC security processor", sizeof(ev[6]));
    stages[6].name = "Firmware loading pathway implemented";
    stages[6].state = CHAIN_BLOCKED;
    stages[6].evidence = ev[6];

    str_copy(ev[7], "no initialisation has been attempted on any hardware", sizeof(ev[7]));
    stages[7].name = "Firmware initialisation attempted";
    stages[7].state = CHAIN_NOT_STARTED;
    stages[7].evidence = ev[7];

    str_copy(ev[8], "no PS5 kernel code has executed", sizeof(ev[8]));
    stages[8].name = "Firmware executing";
    stages[8].state = CHAIN_NOT_STARTED;
    stages[8].evidence = ev[8];

    str_copy(ev[9], "no PS5 system service has executed", sizeof(ev[9]));
    stages[9].name = "PS5 system services operating";
    stages[9].state = CHAIN_NOT_STARTED;
    stages[9].evidence = ev[9];

    str_copy(ev[10], "no genuine PS5 user interface has executed", sizeof(ev[10]));
    stages[10].name = "Genuine PS5 home screen";
    stages[10].state = CHAIN_NOT_STARTED;
    stages[10].evidence = ev[10];

    str_copy(ev[11], "no PS5 package format has been parsed by PC5", sizeof(ev[11]));
    stages[11].name = "PS5 game installation";
    stages[11].state = CHAIN_NOT_STARTED;
    stages[11].evidence = ev[11];

    str_copy(ev[12], "no PS5 executable or game has been executed on this host", sizeof(ev[12]));
    stages[12].name = "PS5 game execution";
    stages[12].state = CHAIN_NOT_STARTED;
    stages[12].evidence = ev[12];

    (void)bi;
    (void)smb;
    (void)acpi;
    chain_ready = 1;
}

const struct chain_stage *chain_stages(void)
{
    if (!chain_ready)
        return NULL;
    return stages;
}

int chain_first_blocked(void)
{
    for (int i = 0; i < CHAIN_STAGE_COUNT; i++)
        if (stages[i].state == CHAIN_BLOCKED)
            return i;
    return -1;
}

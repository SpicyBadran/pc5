/*
 * PC5 UEFI loader.
 *
 * Booted by firmware as \EFI\BOOT\BOOTX64.EFI from the FAT image that
 * tools/mkiso.py places in the El Torito UEFI entry.  It does for UEFI what
 * boot/loader.S does for BIOS: describe the machine, load the kernel, and
 * enter it in 32-bit protected mode with EBX pointing at a valid
 * struct pc5_boot_info.
 *
 * What this loader does *not* do is invent hardware.  Everything it reports
 * comes from firmware and is labelled as such:
 *
 *   memory   the UEFI memory map, converted to the E820 layout the kernel
 *            already understands (conventional memory -> type 1, everything
 *            else -> type 2 reserved).  Loader data is deliberately *not*
 *            called usable: it holds this application and the kernel buffer.
 *   display  GOP.  A synthetic VBE mode-info block describes the linear
 *            framebuffer so the kernel takes its framebuffer path.  font_addr
 *            is 0 because firmware hands over no VGA font, and the kernel
 *            must not draw glyphs it does not have.
 *   medium   the boot volume is opened through EFI_SIMPLE_FILE_SYSTEM and a
 *            known file is read back as proof the medium is readable.  The
 *            ISO9660 descriptor itself is *not* reachable through the file
 *            protocol, so pvd_ok stays 0 here; the kernel reads the
 *            descriptor itself when it probes storage.  Saying otherwise
 *            would be a lie that the next stage could not back up.
 *   kernel   \KERNEL.BIN read through the file protocol, signature checked,
 *            copied to 0x10000, entered.
 *
 * Every failure is a distinct code on screen and on the serial port followed
 * by a halt: this loader never falls through pretending a step worked.
 */
#include "efi.h"

/* The boot contract is the kernel's own header: if the BIOS loader, the
 * kernel and this loader ever disagree about an offset, this file stops
 * compiling instead of corrupting a boot at run time. */
#include "pc5.h"

/* ---------------------------------------------------------------- layout */
/* The kernel is linked at 1 MiB - 960 KiB and the BIOS loader loads it to the
 * same address, so the handover address is part of the contract. */
#define KERNEL_ADDR 0x10000u
#define KERNEL_LIMIT 0x8F000u          /* below the 0x9F000 handover stack */
#define BOOT_INFO_ADDR 0x4000u         /* same address the BIOS loader uses */
#define E820_BUF_ADDR 0x2000u
#define E820_MAX 40
#define VBE_MODE_ADDR 0x2800u
#define PVD_BUF_ADDR 0x3A00u
#define MAX_FILE_BYTES (4u * 1024u * 1024u)
#define LOADER_VERSION "uefi-0.2.0"

/* Offsets that must agree with kernel/include/pc5.h and boot/loader.S. */
_Static_assert(__builtin_offsetof(struct pc5_boot_info, boot_drive) == 8, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, e820_addr) == 12, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, e820_count) == 16, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, vbe_mode_addr) == 20, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, vbe_ok) == 24, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, font_addr) == 28, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, pvd_addr) == 36, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, kernel_bytes) == 44, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, kernel_lba) == 48, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, volume_id) == 52, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, iso_sectors) == 76, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, loader_version) == 80, "abi");
_Static_assert(__builtin_offsetof(struct pc5_boot_info, flags) == 100, "abi");
_Static_assert(sizeof(struct pc5_boot_info) == 104, "abi");
_Static_assert(__builtin_offsetof(struct vbe_mode_info, pitch) == 0x10, "vbe abi");
_Static_assert(__builtin_offsetof(struct vbe_mode_info, phys_base) == 0x28, "vbe abi");

#define BOOT_INFO ((struct pc5_boot_info *)BOOT_INFO_ADDR)
#define E820 ((struct e820_entry *)E820_BUF_ADDR)
#define VBE ((struct vbe_mode_info *)VBE_MODE_ADDR)

/* provided by bootx64.S; both take ordinary SysV arguments */
void pc5_uefi_bridge(u64 entry, u64 boot_info) __attribute__((noreturn));
void pc5_uefi_halt(u64 status) __attribute__((noreturn));

/* ------------------------------------------------------- freestanding libc */
/* gcc must never reach for a hosted library, but it is allowed to turn a
 * memcpy loop into a call to memcpy, so the three symbols it can synthesise
 * are defined here.  PC5_SIZE is u32 in this build, matching pc5.h. */
void *memset(void *dst, int c, PC5_SIZE n)
{
    u8 *p = (u8 *)dst;
    while (n--)
        *p++ = (u8)c;
    return dst;
}

void *memcpy(void *dst, const void *src, PC5_SIZE n)
{
    u8 *d = (u8 *)dst;
    const u8 *s = (const u8 *)src;
    while (n--)
        *d++ = *s++;
    return dst;
}

int memcmp(const void *a, const void *b, PC5_SIZE n)
{
    const u8 *pa = (const u8 *)a, *pb = (const u8 *)b;
    while (n--) {
        if (*pa != *pb)
            return (int)*pa - (int)*pb;
        pa++;
        pb++;
    }
    return 0;
}

/* ---------------------------------------------------------------- serial */
#define COM1 0x3F8
static int serial_present;

/* A serial port is a nicety, not a requirement: probe the scratch register a
 * 16550 has and a floating port does not. */
static void uefi_serial_init(void)
{
    outb(COM1 + 1, 0x00);
    outb(COM1 + 3, 0x80);
    outb(COM1 + 0, 0x01);
    outb(COM1 + 1, 0x00);
    outb(COM1 + 3, 0x03);
    outb(COM1 + 2, 0xC7);
    outb(COM1 + 4, 0x03);
    outb(COM1 + 7, 0x5A);
    serial_present = inb(COM1 + 7) == 0x5A;
    outb(COM1 + 7, 0x00);
}

static void uefi_serial_putc(char c)
{
    int guard = 100000;
    if (!serial_present)
        return;
    while (!(inb(COM1 + 5) & 0x20) && guard--)
        ;
    outb(COM1, (u8)c);
}

static void uefi_serial_puts(const char *s)
{
    if (!serial_present)
        return;
    while (*s)
        uefi_serial_putc(*s++);
}

/* -------------------------------------------------------------- console */
static struct efi_simple_text_output *conout;

static void uefi_puts(const char *s)
{
    while (*s) {
        uefi_serial_putc(*s);
        if (conout) {
            u16 glyph[2];
            glyph[0] = (u16)(u8)*s;
            glyph[1] = 0;
            conout->output_string(conout, glyph);
        }
        s++;
    }
}

static void uefi_put_hex(u64 value, int digits)
{
    static const char hex[] = "0123456789abcdef";
    char buf[17];
    if (digits < 1 || digits > 16)
        digits = 16;
    for (int i = digits - 1; i >= 0; i--) {
        buf[i] = hex[value & 0xF];
        value >>= 4;
    }
    buf[digits] = 0;
    uefi_puts(buf);
}

static void uefi_put_dec(u64 value)
{
    char buf[21];
    int i = 20;
    buf[i] = 0;
    do {
        buf[--i] = (char)('0' + (u8)(value % 10));
        value /= 10;
    } while (value);
    uefi_puts(&buf[i]);
}

/* Every trace line is prefixed so it can be grepped in a screenshot and in
 * the serial log. */
static void trace(const char *label)
{
    uefi_puts("PC5-UEFI: ");
    uefi_puts(label);
    uefi_puts("\r\n");
}

static void trace_dec(const char *label, u64 value)
{
    uefi_puts("PC5-UEFI: ");
    uefi_puts(label);
    uefi_puts("=");
    uefi_put_dec(value);
    uefi_puts("\r\n");
}

static void trace_hex(const char *label, u64 value)
{
    uefi_puts("PC5-UEFI: ");
    uefi_puts(label);
    uefi_puts("=0x");
    uefi_put_hex(value, 8);
    uefi_puts("\r\n");
}

/* Failure: a distinct code, a sentence a human can act on, then a halt. */
static void fail(const char *code, const char *reason, u64 status)
    __attribute__((noreturn));

static void fail(const char *code, const char *reason, u64 status)
{
    uefi_puts("\r\nPC5-UEFI FAILURE ");
    uefi_puts(code);
    uefi_puts(": ");
    uefi_puts(reason);
    uefi_puts(" (status=0x");
    uefi_put_hex(status, 16);
    uefi_puts(")\r\n");
    uefi_serial_puts("PC5-UEFI-FAILURE ");
    uefi_serial_puts(code);
    uefi_serial_puts("\r\n");
    pc5_uefi_halt(status);
}

/* --------------------------------------------------------------- display */
static u32 frame_buffer;
static u32 frame_width, frame_height, frame_pitch;
static int frame_ok;

/* Only 32-bit GOP modes are accepted: a palettised mode cannot be described by
 * a VBE direct-colour block, and a 24-bit mode would need conversion the
 * kernel does not do.  GOP mode 0 (RGB) is therefore the supported path. */
static int gop_init(struct efi_system_table *st)
{
    struct efi_gop *gop = 0;
    if (EFI_ERROR(st->boot_services->handle_protocol(
            st->console_out_handle,
            (struct efi_guid *)&EFI_GRAPHICS_OUTPUT_PROTOCOL_GUID, (void **)&gop)))
        return 0;
    if (!gop || !gop->mode || !gop->mode->info)
        return 0;

    struct efi_gop_mode_info *info = gop->mode->info;
    if (info->pixel_format != 0 && info->pixel_format != 1)
        return 0;
    if (!info->horizontal_resolution || !info->vertical_resolution)
        return 0;
    if (!info->pixels_per_scan_line)
        return 0;
    if (!gop->mode->frame_buffer_base || !gop->mode->frame_buffer_size)
        return 0;
    /* the kernel addresses the framebuffer as a 32-bit physical address */
    if (gop->mode->frame_buffer_base > 0xFFFFFFFFULL)
        return 0;

    frame_buffer = (u32)gop->mode->frame_buffer_base;
    frame_width = info->horizontal_resolution;
    frame_height = info->vertical_resolution;
    frame_pitch = info->pixels_per_scan_line * 4;
    frame_ok = 1;

    /* Synthesise the VBE mode-info block the kernel console reads.  VBE has no
     * pixel-format field and the kernel always writes 0x00RRGGBB, which is
     * exactly GOP format 0.  For format 1 (BGR) the channel positions are
     * reported honestly; the kernel still draws, with red and blue swapped,
     * and that limitation is stated in the docs rather than papered over. */
    struct vbe_mode_info *vbe = VBE;
    memset(vbe, 0, sizeof(*vbe));
    vbe->attributes = 0x0081;          /* supported + linear framebuffer    */
    vbe->win_size = 64;
    vbe->pitch = (u16)(frame_pitch > 0xFFFF ? 0xFFFF : frame_pitch);
    vbe->width = (u16)(frame_width > 0xFFFF ? 0xFFFF : frame_width);
    vbe->height = (u16)(frame_height > 0xFFFF ? 0xFFFF : frame_height);
    vbe->char_w = 8;
    vbe->char_h = 16;
    vbe->planes = 1;
    vbe->bpp = 32;
    vbe->banks = 1;
    vbe->model = 6;                    /* direct colour                     */
    vbe->image_pages = 1;
    vbe->direct_color_mode = 1;
    if (info->pixel_format == 1) {
        vbe->red_mask_size = 8; vbe->red_field_pos = 16;
        vbe->green_mask_size = 8; vbe->green_field_pos = 8;
        vbe->blue_mask_size = 8; vbe->blue_field_pos = 0;
    } else {
        vbe->red_mask_size = 8; vbe->red_field_pos = 0;
        vbe->green_mask_size = 8; vbe->green_field_pos = 8;
        vbe->blue_mask_size = 8; vbe->blue_field_pos = 16;
    }
    vbe->phys_base = frame_buffer;

    trace_dec("display_width", frame_width);
    trace_dec("display_height", frame_height);
    trace_dec("display_pitch", frame_pitch);
    trace_dec("display_pixel_format", info->pixel_format);
    return 1;
}

/* ---------------------------------------------------------------- memory */
/* Firmware memory map -> E820 entries.  The mapping is stated in one place so
 * that the kernel, the tests and the docs can be checked against it. */
static u32 build_e820(u64 count, u32 desc_size, const u8 *map)
{
    u32 entries = 0;
    for (u64 i = 0; i < count && entries < E820_MAX; i++) {
        const struct efi_memory_descriptor *d =
            (const struct efi_memory_descriptor *)(map + i * desc_size);
        E820[entries].base = d->physical_start;
        E820[entries].length = d->number_of_pages * 4096u;
        E820[entries].type = (d->type == EFI_CONVENTIONAL_MEMORY) ? 1u : 2u;
        E820[entries].acpi_ext = 0;
        entries++;
    }
    return entries;
}

static u64 conventional_mib(u32 entries)
{
    u64 bytes = 0;
    for (u32 i = 0; i < entries; i++)
        if (E820[i].type == 1)
            bytes += E820[i].length;
    return bytes >> 20;
}

/* ----------------------------------------------------------------- files */
struct file_buffer {
    u8 *data;
    u64 size;
};

/* Read a whole file from the volume the application was loaded from.  The
 * buffer is EFI_LOADER_DATA, so the memory map tells the kernel it is in use;
 * it is never freed, because the kernel runs with boot services gone. */
static int read_file(struct efi_system_table *st, struct efi_file *root,
                     u16 *name, struct file_buffer *out)
{
    struct efi_file *file = 0;
    efi_status status = root->open(root, &file, name, EFI_FILE_MODE_READ, 0);
    if (EFI_ERROR(status) || !file)
        return 1;

    /* Learn the size by seeking to the end: SetPosition past EOF is allowed,
     * the position it reports back is the file size. */
    u64 size = 0;
    status = file->set_position(file, MAX_FILE_BYTES);
    if (EFI_ERROR(status)) {
        root->close(file);
        return 2;
    }
    status = file->get_position(file, &size);
    if (EFI_ERROR(status)) {
        root->close(file);
        return 3;
    }
    if (!size || size > MAX_FILE_BYTES) {
        root->close(file);
        return 4;
    }
    status = file->set_position(file, 0);
    if (EFI_ERROR(status)) {
        root->close(file);
        return 5;
    }

    void *buffer = 0;
    status = st->boot_services->allocate_pool(EFI_LOADER_DATA, size, &buffer);
    if (EFI_ERROR(status) || !buffer) {
        root->close(file);
        return 6;
    }
    u64 got = size;
    status = file->read(file, &got, buffer);
    root->close(file);
    if (EFI_ERROR(status) || got != size) {
        st->boot_services->free_pool(buffer);
        return 7;
    }
    out->data = (u8 *)buffer;
    out->size = size;
    return 0;
}

/* UTF-16 -> printable ASCII.  Anything outside ASCII becomes '?', so a stray
 * high byte can never end up in a char[] the kernel prints or compares. */
static void utf16_to_ascii(const u16 *src, char *dst, u32 max)
{
    u32 i = 0;
    while (src[i] && i + 1 < max) {
        u16 c = src[i];
        dst[i] = (char)((c >= 0x20 && c < 0x7F) ? c : '?');
        i++;
    }
    dst[i] = 0;
}

/* ------------------------------------------------------------------ main */
efi_status EFIAPI efi_main(efi_handle image_handle, struct efi_system_table *st)
{
    uefi_serial_init();
    uefi_serial_puts("\r\nPC5 UEFI LOADER " LOADER_VERSION "\r\n");

    if (!st || !st->boot_services || !st->con_out)
        return EFI_LOAD_ERROR;

    conout = st->con_out;
    uefi_puts("\r\nPC5 UEFI loader " LOADER_VERSION "\r\n");
    trace("firmware_started");

    if (st->firmware_vendor && st->firmware_vendor[0]) {
        char vendor[32];
        utf16_to_ascii(st->firmware_vendor, vendor, sizeof(vendor));
        uefi_puts("PC5-UEFI: firmware=");
        uefi_puts(vendor);
        uefi_puts("\r\n");
    }
    trace_dec("firmware_revision", st->firmware_revision);

    /* 1. display: text mode is a valid boot, so this never fails the load */
    if (!gop_init(st))
        trace("display=gop_unavailable,text_fallback");

    /* 2. the volume firmware loaded us from */
    struct efi_simple_file_system *fs = 0;
    efi_status status = st->boot_services->handle_protocol(
        image_handle, (struct efi_guid *)&EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID,
        (void **)&fs);
    if (EFI_ERROR(status) || !fs)
        fail("E1", "no file system on the volume we were loaded from", status);
    struct efi_file *root = 0;
    status = fs->open_volume(fs, &root);
    if (EFI_ERROR(status) || !root)
        fail("E2", "cannot open the root directory of the boot volume", status);
    trace("volume_opened");

    /* Proof that the medium is readable, without pretending to have read the
     * ISO9660 descriptor (the file protocol cannot expose it). */
    struct file_buffer probe;
    if (read_file(st, root, u"\\README.TXT", &probe) == 0) {
        trace_dec("medium_readme_bytes", probe.size);
        st->boot_services->free_pool(probe.data);
    } else {
        trace("medium_readme_unreadable");
    }

    /* 3. the kernel */
    struct file_buffer kernel;
    int err = read_file(st, root, u"\\KERNEL.BIN", &kernel);
    if (err)
        fail("E3", "cannot read \\KERNEL.BIN from the boot volume", (u64)err);
    trace_dec("kernel_bytes_read", kernel.size);

    if (kernel.size < 8 || memcmp(kernel.data, "PC5K", 4) != 0)
        fail("E4", "kernel image does not carry the PC5K signature", 0);
    trace_dec("kernel_protocol_version", kernel.data[4]);
    if (kernel.data[4] != PC5_PROTOCOL_VERSION)
        fail("E5", "kernel boot protocol version mismatch", kernel.data[4]);
    if (kernel.size > KERNEL_LIMIT - KERNEL_ADDR)
        fail("E6", "kernel image is larger than the load window", kernel.size);

    /* 4. the memory map */
    u64 map_size = 0, map_key = 0, desc_size = 0;
    u32 desc_version = 0;
    status = st->boot_services->get_memory_map(&map_size, 0, &map_key,
                                              &desc_size, &desc_version);
    if (status != EFI_BUFFER_TOO_SMALL || !map_size || !desc_size)
        fail("E8", "firmware did not report a memory map size", status);
    map_size += (u64)4 * desc_size;    /* the map can grow between calls */
    void *map = 0;
    status = st->boot_services->allocate_pool(EFI_LOADER_DATA, map_size, &map);
    if (EFI_ERROR(status) || !map)
        fail("E9", "cannot allocate the memory map buffer", status);
    status = st->boot_services->get_memory_map(
        &map_size, (struct efi_memory_descriptor *)map, &map_key, &desc_size,
        &desc_version);
    if (EFI_ERROR(status))
        fail("E10", "firmware memory map query failed", status);
    if (desc_size < sizeof(struct efi_memory_descriptor) || desc_size > 0x1000)
        fail("E11", "unexpected memory descriptor size", desc_size);
    /* 64-bit division would drag in libgcc; both values are small here */
    u64 count = map_size / desc_size;
    u32 e820_count = build_e820(count, (u32)desc_size, (const u8 *)map);
    if (!e820_count)
        fail("E12", "the firmware memory map was empty", 0);
    trace_dec("memory_map_entries", e820_count);
    trace_dec("memory_conventional_mib", conventional_mib(e820_count));

    /* 5. the boot contract */
    struct pc5_boot_info *bi = BOOT_INFO;
    memset(bi, 0, sizeof(*bi));
    bi->magic = PC5_BOOT_MAGIC;
    bi->version = PC5_PROTOCOL_VERSION;
    bi->boot_drive = 0xFFFFFFFFu;   /* there is no BIOS drive on this path */
    bi->e820_addr = E820_BUF_ADDR;
    bi->e820_count = e820_count;
    bi->vbe_mode_addr = VBE_MODE_ADDR;
    bi->vbe_ok = frame_ok ? 1u : 0u;
    bi->font_addr = 0;              /* firmware hands over no VGA font */
    bi->font_bytes_per_char = 0;
    bi->pvd_addr = PVD_BUF_ADDR;
    bi->pvd_ok = 0;                 /* not reachable through the file protocol */
    bi->kernel_bytes = (u32)kernel.size;
    bi->kernel_lba = 0;             /* the file protocol hides the LBA */
    bi->volume_id[0] = 0;           /* not exposed by the file protocol either */
    bi->iso_sectors = 0;
    memcpy(bi->loader_version, LOADER_VERSION, sizeof(bi->loader_version));
    bi->desc_crc = 0;
    /* bit 0: booted by the UEFI loader.  Bits 1 and 2 say what could not be
     * reported, so the kernel can print an honest medium line. */
    bi->flags = 0x1u | 0x2u /* no ISO LBA */ | 0x4u /* no volume id */;
    trace("boot_info_ready");

    /* 6. kernel image into the handover address */
    memcpy((void *)KERNEL_ADDR, kernel.data, kernel.size);
    trace_hex("kernel_loaded_at", KERNEL_ADDR);

    /* 7. leave boot services: after this the firmware is gone */
    status = st->boot_services->exit_boot_services(image_handle, map_key);
    if (EFI_ERROR(status))
        fail("E13", "ExitBootServices was refused", status);
    trace("boot_services_exited");

    /* 8. 32-bit protected mode, then the kernel never returns */
    if (KERNEL_ADDR != 0x10000u)
        fail("E14", "kernel entry address is not the protocol address", KERNEL_ADDR);
    uefi_serial_puts("PC5-UEFI: entering 32-bit kernel\r\n");
    pc5_uefi_bridge(KERNEL_ADDR, BOOT_INFO_ADDR);
}

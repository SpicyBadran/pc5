/*
 * PC5 kernel: firmware probe.
 *
 * PC5 does not ship, embed or redistribute Sony firmware.  The probe reports
 * what the current build actually has:
 *   - whether a firmware manifest was compiled in (produced on the host by
 *     tools/firmware.py from an image the user supplies), and
 *   - whether the boot medium carried a firmware payload (it never does by
 *     default, because the ISO is redistributable and firmware is not).
 *
 * Reporting "not supplied" is the correct result, not a failure of the probe.
 */
#include "pc5.h"

/* generated at build time from firmware/manifest.json, or a default */
extern const char *pc5_fw_manifest;
extern const int pc5_fw_manifest_size;

void fw_probe(const struct pc5_boot_info *bi, struct fw_report *out)
{
    memset(out, 0, sizeof(*out));
    out->supplied = 0;
    out->identified = 0;
    out->size_bytes = pc5_fw_manifest_size > 0 ? (u32)pc5_fw_manifest_size : 0;
    if (pc5_fw_manifest_size > 0) {
        out->supplied = 1;
        out->identified = 1;
        str_copy(out->kind, "manifest", sizeof(out->kind));
        str_copy(out->note, pc5_fw_manifest, sizeof(out->note));
    } else {
        str_copy(out->kind, "none", sizeof(out->kind));
        str_copy(out->note, "no firmware image or manifest in this build", sizeof(out->note));
    }
    (void)bi;
}

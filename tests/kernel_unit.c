#define PC5_HOST_TEST 1
/*
 * Host-side unit tests for the parts of the PC5 kernel that are pure logic:
 * string/number formatting, E820 accounting, SMBIOS record walking and the
 * compatibility chain state machine.  These run on the build host with the
 * host compiler, which makes formatting bugs visible without booting anything.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/mman.h>

#define PC5_HOST_TEST 1

#include "pc5.h"

static int failures;
static int checks;

static void check_str(const char *what, const char *got, const char *want)
{
    checks++;
    if (strcmp(got, want) != 0) {
        failures++;
        printf("FAIL %s: got \"%s\" want \"%s\"\n", what, got, want);
    }
}

static void check_int(const char *what, long got, long want)
{
    checks++;
    if (got != want) {
        failures++;
        printf("FAIL %s: got %ld want %ld\n", what, got, want);
    }
}

static void test_format(void)
{
    char buf[128];
    pc5_snprintf(buf, sizeof(buf), "%s", "hello");
    check_str("plain string", buf, "hello");
    pc5_snprintf(buf, sizeof(buf), "[%s]", "ab");
    check_str("bracketed", buf, "[ab]");
    pc5_snprintf(buf, sizeof(buf), "%-4s|", "ab");
    check_str("left pad", buf, "ab  |");
    pc5_snprintf(buf, sizeof(buf), "%4s|", "ab");
    check_str("right pad", buf, "  ab|");
    pc5_snprintf(buf, sizeof(buf), "%02x:%02x.%x", 0, 5, 2);
    check_str("pci id", buf, "00:05.2");
    pc5_snprintf(buf, sizeof(buf), "%u-%d-%x", 42, -7, 0xbeef);
    check_str("numbers", buf, "42--7-beef");
    pc5_snprintf(buf, sizeof(buf), "%08x", 0x1234);
    check_str("hex width", buf, "00001234");
    pc5_snprintf(buf, sizeof(buf), "100%%");
    check_str("percent", buf, "100%");
    pc5_snprintf(buf, sizeof(buf), "%u", 0);
    check_str("zero", buf, "0");
    pc5_snprintf(buf, sizeof(buf), "%llu", (u64)4294967296ull);
    check_str("u64", buf, "4294967296");
    pc5_snprintf(buf, sizeof(buf), "%s:%s", "8086", "1237");
    check_str("two strings", buf, "8086:1237");
}

static void test_numbers(void)
{
    char buf[40];
    u32_to_str(1234, buf, 10);
    check_str("u32 dec", buf, "1234");
    u32_to_str(0xdead, buf, 16);
    check_str("u32 hex", buf, "dead");
    u64_to_str(9007199254740993ull, buf, 10);
    check_str("u64 big", buf, "9007199254740993");
    u32_to_hex(0x1f, buf, 4);
    check_str("hex digits", buf, "001f");
}

static void test_strings(void)
{
    char buf[16];
    check_int("memcmp eq", memcmp("abc", "abc", 3), 0);
    check_int("memcmp ne", memcmp("abc", "abd", 3) < 0, 1);
    check_int("contains", str_contains("PC5 BOOT ENVIRONMENT", "BOOT"), 1);
    check_int("contains missing", str_contains("PC5", "BOOT"), 0);
    str_copy(buf, "truncate-me", 5);
    check_str("str_copy", buf, "trun");
    str_copy(buf, "ab", sizeof(buf));
    str_append(buf, "cd", sizeof(buf));
    check_str("append", buf, "abcd");
}

static void test_memory_map(void)
{
    /* the kernel addresses the map through a 32-bit physical address, so the
       host test allocates below 4 GiB */
    struct e820_entry *entries = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                                      MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    if (entries == MAP_FAILED) {
        printf("SKIP memory map test: no low memory available\n");
        return;
    }
    struct pc5_boot_info bi;
    struct mem_info info;
    memset(&bi, 0, sizeof(bi));
    memset(entries, 0, 4096);
    entries[0].base = 0;
    entries[0].length = 0x9fc00;
    entries[0].type = 1;
    entries[1].base = 0x9fc00;
    entries[1].length = 0x400;
    entries[1].type = 2;
    entries[2].base = 0x100000;
    entries[2].length = 0x7ee0000;
    entries[2].type = 1;
    bi.e820_addr = (u32)(unsigned long)entries;
    bi.e820_count = 3;
    mem_detect(&bi, &info);
    check_int("e820 entries", (long)info.entries, 3);
    check_int("usable MiB", (long)(info.usable_bytes >> 20), 127);
    check_int("top MiB", (long)info.top_address_mb, 127);
}

static void test_chain(void)
{
    struct pc5_boot_info bi;
    struct cpu_info cpu;
    struct mem_info mem;
    struct pci_report pci;
    struct smbios_info smb;
    struct acpi_info acpi;
    struct fw_report fw;
    memset(&bi, 0, sizeof(bi));
    memset(&cpu, 0, sizeof(cpu));
    memset(&mem, 0, sizeof(mem));
    memset(&pci, 0, sizeof(pci));
    memset(&smb, 0, sizeof(smb));
    memset(&acpi, 0, sizeof(acpi));
    memset(&fw, 0, sizeof(fw));
    str_copy(cpu.vendor, "GenuineIntel", sizeof(cpu.vendor));
    mem.total_bytes = 128ull << 20;
    pci.count = 5;
    struct storage_report sr;
    memset(&sr, 0, sizeof(sr));
    sr.selected = -1;
    chain_evaluate(&bi, &cpu, &mem, &pci, &smb, &acpi, &fw, 1, &sr);
    const struct chain_stage *st = chain_stages();
    check_int("chain ready", st != NULL, 1);
    check_int("stage 1 ok", st[0].state == CHAIN_OK, 1);
    check_int("stage 3 partial", st[2].state == CHAIN_PARTIAL, 1);
    check_int("stage 4 blocked without storage", st[3].state == CHAIN_BLOCKED, 1);
    check_int("stage 5 blocked", st[4].state == CHAIN_BLOCKED, 1);
    check_int("first blocked", chain_first_blocked(), 3);
    check_int("never claims execution", st[8].state != CHAIN_OK, 1);
    fw.supplied = 1;
    fw.identified = 1;
    sr.drives = 1;
    sr.selected = 0;
    sr.mounted = 1;
    sr.file_ok = 1;
    sr.file_signature = 1;
    sr.file_bytes = 30908;
    str_copy(sr.volume, "PC5", sizeof(sr.volume));
    str_copy(sr.file_name, "KERNEL.BIN", sizeof(sr.file_name));
    chain_evaluate(&bi, &cpu, &mem, &pci, &smb, &acpi, &fw, 1, &sr);
    st = chain_stages();
    check_int("stage 4 evidence names the volume", strstr(st[3].evidence, "PC5") != NULL, 1);
    check_int("stage 4 stays partial (no installer)", st[3].state == CHAIN_PARTIAL, 1);
    check_int("stage 5 ok with firmware", st[4].state == CHAIN_OK, 1);
    check_int("stage 7 still blocked", st[6].state == CHAIN_BLOCKED, 1);
}

int main(void)
{
    test_format();
    test_numbers();
    test_strings();
    test_memory_map();
    test_chain();
    printf("%s: %d checks, %d failures\n", failures ? "FAILED" : "PASSED", checks, failures);
    return failures ? 1 : 0;
}

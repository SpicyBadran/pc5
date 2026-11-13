# PC5 build system
#
#   make            build build/pc5.iso (the release artifact)
#   make check      unit tests for the host tools
#   make boot-test  boot the ISO in the emulator harness and assert the log
#   make verify     validate the ISO structure and every checksum
#   make clean
#
# Reproducibility: set SOURCE_DATE_EPOCH to pin the build timestamp; the
# toolchain needs only binutils, gcc (with 32-bit support), python3 and make.

VERSION      ?= 0.2.0
BUILD_ID     ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo local)
COMMIT       ?= $(shell git rev-parse HEAD 2>/dev/null || echo unknown)
TAG          ?=
STAMP_EPOCH  ?= $(shell if [ -n "$$SOURCE_DATE_EPOCH" ]; then echo $$SOURCE_DATE_EPOCH; else date -u +%s; fi)
BUILD_DATE   ?= $(shell date -u -d @$(STAMP_EPOCH) +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)

BUILD        := build
OBJ          := $(BUILD)/obj
ISO          := $(BUILD)/pc5.iso

CC           := gcc
LD           := ld
AS           := as

KERNEL_SRC   := $(filter-out kernel/manifest_default.c,$(wildcard kernel/*.c))
KERNEL_OBJ   := $(patsubst kernel/%.c,$(OBJ)/%.o,$(KERNEL_SRC))
KERNEL_OBJ   += $(OBJ)/start.o

FW_MANIFEST_SRC := kernel/manifest_default.c
FW_MANIFEST_OBJ := $(OBJ)/fwmanifest.o
ifneq ($(wildcard firmware/manifest.json),)
FW_MANIFEST_SRC := $(BUILD)/generated/manifest.c
endif

KERNEL_CFLAGS := -m32 -std=gnu11 -O2 -Wall -Wextra -Wno-unused-parameter \
                 -ffreestanding -fno-pic -fno-stack-protector -fno-builtin \
                 -fno-asynchronous-unwind-tables -fno-unwind-tables \
                 -mno-sse -mno-mmx -mno-80387 -mno-sse2 -msoft-float \
                 -fno-tree-loop-distribute-patterns \
                 -Ikernel/include \
                 -DPC5_VERSION='"$(VERSION)"' \
                 -DPC5_BUILD_ID='"$(BUILD_ID)"' \
                 -DPC5_BUILD_DATE='"$(BUILD_DATE)"'

.PHONY: all iso uefi check test boot-test stubtest verify clean distclean info unit metadata release-assets

all: iso

iso: $(ISO)

info:
	@echo "version   $(VERSION)"
	@echo "build id  $(BUILD_ID)"
	@echo "date      $(BUILD_DATE)"
	@echo "sources   $(KERNEL_SRC)"

$(OBJ):
	@mkdir -p $(OBJ)

$(BUILD)/generated:
	@mkdir -p $(BUILD)/generated

$(BUILD)/generated/manifest.c: firmware/manifest.json tools/firmware.py | $(BUILD)/generated
	python3 tools/firmware.py manifest --input firmware/manifest.json --c-output $@

$(OBJ)/%.o: kernel/%.c | $(OBJ)
	$(CC) $(KERNEL_CFLAGS) -c $< -o $@

$(OBJ)/fwmanifest.o: $(FW_MANIFEST_SRC) | $(OBJ)
	$(CC) $(KERNEL_CFLAGS) -c $(FW_MANIFEST_SRC) -o $@

$(OBJ)/start.o: kernel/start.S | $(OBJ)
	$(CC) -m32 -c $< -o $@

$(OBJ)/loader.o: boot/loader.S | $(OBJ)
	$(AS) --32 $< -o $@

$(BUILD)/kernel.bin: $(KERNEL_OBJ) $(FW_MANIFEST_OBJ) kernel/kernel.ld
	$(LD) -m elf_i386 -T kernel/kernel.ld --oformat binary -nostdlib -o $@ $(KERNEL_OBJ) $(FW_MANIFEST_OBJ)
	@size=$$(stat -c %s $@); echo "pc5: kernel image $$size bytes (limit 585728)"; \
	 if [ $$size -gt 585728 ]; then echo "pc5: kernel too large for the loader window"; exit 1; fi

$(BUILD)/loader.bin: $(OBJ)/loader.o
	$(LD) -m elf_i386 -Ttext 0x7c00 --oformat binary -e _start -o $@ $<
	@size=$$(stat -c %s $@); echo "pc5: loader image $$size bytes"; \
	 if [ $$size -ne 4096 ]; then echo "pc5: loader must be exactly 4096 bytes (descriptor at 0xE00)"; exit 1; fi

# ---------------------------------------------------------------- UEFI ----
# The UEFI boot application is an ordinary PE32+ EFI image built with the
# same binutils/gcc the rest of the tree uses: no EDK2, no mingw toolchain.
# `ld -m i386pep` is binutils' 64-bit PE emulation, and --enable-reloc-section
# derives the base relocation table from the absolute addresses the compiler
# emits with -fno-pic.
UEFI_CFLAGS := -m64 -std=gnu11 -O2 -Wall -Wextra -Wno-unused-parameter \
               -ffreestanding -fno-pic -fno-stack-protector -fno-builtin \
               -mno-red-zone -fno-asynchronous-unwind-tables -fno-unwind-tables \
               -fno-tree-loop-distribute-patterns \
               -Ikernel/include -Iboot/uefi
UEFI_LDFLAGS := -m i386pep -nostdlib -T boot/uefi/bootx64.ld \
                --image-base 0x10000000 --subsystem 10 \
                --section-alignment 0x1000 --file-alignment 0x200 \
                --major-subsystem-version 6 --minor-subsystem-version 0 \
                --minor-os-version 0 --no-insert-timestamp --enable-reloc-section

UEFI_SRC     := boot/uefi/uefi_main.c
UEFI_ASM     := boot/uefi/bootx64.S
UEFI_HDR     := boot/uefi/efi.h boot/uefi/bootx64.ld kernel/include/pc5.h

$(OBJ)/uefi_main.o: $(UEFI_SRC) $(UEFI_HDR) | $(OBJ)
	$(CC) $(UEFI_CFLAGS) -c $< -o $@

$(OBJ)/bootx64.o: $(UEFI_ASM) | $(OBJ)
	$(CC) -m64 -c $< -o $@

UEFI_OBJ := $(OBJ)/bootx64.o $(OBJ)/uefi_main.o

$(BUILD)/uefi/BOOTX64.EFI: $(UEFI_OBJ) boot/uefi/bootx64.ld
	@mkdir -p $(BUILD)/uefi
	$(LD) $(UEFI_LDFLAGS) -e _start $(UEFI_OBJ) -o $@
	@python3 tools/eficheck.py $@ --require-relocs --max-bytes 196608

$(BUILD)/efi.img: $(BUILD)/uefi/BOOTX64.EFI tools/mkefiimg.py
	python3 tools/mkefiimg.py --size-kb 1440 \
	  --file $(BUILD)/uefi/BOOTX64.EFI=EFI/BOOT/BOOTX64.EFI \
	  --output $@ --info $(BUILD)/efi-info.json

uefi: $(BUILD)/efi.img

$(BUILD)/iso/README.TXT: docs/ISO_README.txt | $(BUILD)
	@mkdir -p $(BUILD)/iso
	cp $< $@

$(BUILD)/iso/BUILDINFO.TXT: | $(BUILD)
	@mkdir -p $(BUILD)/iso
	@printf 'PC5\nversion: %s\nbuild: %s\ndate: %s\nkernel: %s\n' \
	 "$(VERSION)" "$(BUILD_ID)" "$(BUILD_DATE)" "32-bit PC5 bring-up kernel" > $@

$(BUILD):
	@mkdir -p $(BUILD)

$(ISO): $(BUILD)/loader.bin $(BUILD)/kernel.bin $(BUILD)/efi.img $(BUILD)/iso/README.TXT $(BUILD)/iso/BUILDINFO.TXT tools/mkiso.py
	python3 tools/mkiso.py \
	  --volume-id PC5 \
	  --boot-image $(BUILD)/loader.bin \
	  --desc-offset 0xE00 \
	  --uefi-image $(BUILD)/efi.img \
	  --file KERNEL.BIN=$(BUILD)/kernel.bin \
	  --file README.TXT=$(BUILD)/iso/README.TXT \
	  --file BUILDINFO.TXT=$(BUILD)/iso/BUILDINFO.TXT \
	  --output $(ISO) \
	  --info $(BUILD)/build-info.json

unit: | $(BUILD)
	$(CC) -std=gnu11 -O1 -Wall -Wextra -Wno-unused-parameter -ffreestanding \
	  -fno-builtin -fno-stack-protector -DPC5_HOST_TEST -Ikernel/include \
	  -o $(BUILD)/kernel-unit tests/kernel_unit.c kernel/lib.c kernel/mem.c kernel/chain.c
	$(BUILD)/kernel-unit

check: unit
	python3 -m unittest discover -s tests -p 'test_*.py' -v

verify: $(ISO)
	python3 tools/verify_iso.py $(ISO) --info $(BUILD)/build-info.json \
	  --json-out $(BUILD)/verify-report.json

boot-test: $(ISO)
	python3 tests/boot_test.py --iso $(ISO)

# Execute the real UEFI loader image against the stub firmware in
# tests/uefi_stub_firmware.py.  This is not OVMF and never claims to be: it runs
# the loader's own PE32+ code and the handover stub so the loader's logic is
# executed rather than inspected.  Needs the `unicorn` Python package; exits 2
# with an explanation when it is absent, so a missing dependency can never be
# mistaken for a passing boot.
stubtest: $(ISO)
	python3 tests/uefi_stubtest.py --json-out $(BUILD)/stubtest-report.json

test: check boot-test stubtest

# Provenance for a release: version, commit, toolchain and whatever the test
# logs in $(BUILD) can prove.  Reports that do not exist are simply not cited.
metadata: $(ISO)
	@mkdir -p $(BUILD)
	python3 tools/buildmeta.py --iso $(ISO) --info $(BUILD)/build-info.json \
	  --version "$(VERSION)" --tag "$(TAG)" --commit "$(COMMIT)" \
	  --build-id "$(BUILD_ID)" --source-date-epoch "$(STAMP_EPOCH)" \
	  --build-date "$(BUILD_DATE)" \
	  $$([ -f $(BUILD)/verify-report.json ] && echo --verify-report $(BUILD)/verify-report.json) \
	  $$([ -f $(BUILD)/test/boot-evidence.json ] && echo --boot-evidence $(BUILD)/test/boot-evidence.json) \
	  $$([ -f $(BUILD)/logs/unit.log ] && echo --unit-log $(BUILD)/logs/unit.log) \
	  $$([ -f $(BUILD)/logs/host.log ] && echo --host-log $(BUILD)/logs/host.log)

# Stage exactly the three release assets in one directory.
release-assets: metadata
	@mkdir -p $(BUILD)/release
	cp $(ISO) $(BUILD)/release/pc5.iso
	cp $(BUILD)/pc5.iso.sha256 $(BUILD)/release/pc5.iso.sha256
	cp $(BUILD)/build-info.json $(BUILD)/release/build-info.json
	@ls -l $(BUILD)/release
	@echo "pc5: release assets staged in $(BUILD)/release"
	@sha256sum $(BUILD)/release/*

clean:
	rm -rf $(BUILD)

distclean: clean
	rm -rf firmware/manifest.json

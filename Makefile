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

VERSION      ?= 0.1.0
BUILD_ID     ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo local)
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

.PHONY: all iso check test boot-test verify clean distclean info unit

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

$(BUILD)/iso/README.TXT: docs/ISO_README.txt | $(BUILD)
	@mkdir -p $(BUILD)/iso
	cp $< $@

$(BUILD)/iso/BUILDINFO.TXT: | $(BUILD)
	@mkdir -p $(BUILD)/iso
	@printf 'PC5\nversion: %s\nbuild: %s\ndate: %s\nkernel: %s\n' \
	 "$(VERSION)" "$(BUILD_ID)" "$(BUILD_DATE)" "32-bit PC5 bring-up kernel" > $@

$(BUILD):
	@mkdir -p $(BUILD)

$(ISO): $(BUILD)/loader.bin $(BUILD)/kernel.bin $(BUILD)/iso/README.TXT $(BUILD)/iso/BUILDINFO.TXT tools/mkiso.py
	python3 tools/mkiso.py \
	  --volume-id PC5 \
	  --boot-image $(BUILD)/loader.bin \
	  --desc-offset 0xE00 \
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
	python3 tools/verify_iso.py $(ISO) --info $(BUILD)/build-info.json

boot-test: $(ISO)
	python3 tests/boot_test.py --iso $(ISO)

test: check boot-test

clean:
	rm -rf $(BUILD)

distclean: clean
	rm -rf firmware/manifest.json

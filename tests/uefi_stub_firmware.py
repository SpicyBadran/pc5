#!/usr/bin/env python3
"""Stub UEFI firmware for the PC5 loader, on top of the Unicorn CPU emulator.

The UEFI path could not be executed in this environment: no OVMF image, no
QEMU, no bootable UEFI machine.  That left it "built but never run", which is
not a state this project is willing to dress up.  This module executes the
*real* `build/uefi/BOOTX64.EFI` that the real build produced:

  * loads the PE32+ image the way firmware does - sections at their virtual
    addresses, then every base relocation applied - at an address that is
    deliberately *not* its preferred base, so a missing relocation is fatal
    here exactly as it would be on hardware;
  * implements the boot services and protocols the loader uses (Simple Text
    Output, Graphics Output, Simple File System, Loaded Image, Device Path)
    at the specification's own slots, calling back into Python through real
    x86-64 stubs that cross the ms_abi boundary;
  * backs the file system with two volumes: the FAT ESP parsed out of
    `build/efi.img`, and one that carries `KERNEL.BIN` - which is how an
    El Torito UEFI boot actually looks, and why the loader has to search for
    the volume rather than assume its own;
  * runs the loader's own entry stub (`_start`), so the `.bss` clearing and
    the ms_abi frame are exercised, and then follows the handover into 32-bit
    protected mode until the kernel's entry point executes.

Limitations, stated plainly: this is not firmware.  There is no ACPI, no PCI,
no interrupts, no timer, and the kernel is stopped at its entry because the
rest of it wants devices the harness does not provide.  `lgdt`, segment loads
and the far return are emulated by the harness (Unicorn does not implement
them); the descriptor-table contents are still checked by the harness, so a
wrong GDT is caught, but the CPU does not perform the switch.

A passing run therefore means "the loader's own code ran and did the right
thing against a stub firmware".  It does not mean the UEFI path is verified.
"""

from __future__ import annotations

import struct

try:
    from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, \
        UC_HOOK_INSN, UC_HOOK_MEM_WRITE
    from unicorn.x86_const import (
        UC_X86_REG_RAX, UC_X86_REG_RBX, UC_X86_REG_RDI, UC_X86_REG_RSI,
        UC_X86_REG_RDX, UC_X86_REG_RCX, UC_X86_REG_R8, UC_X86_REG_R9,
        UC_X86_REG_R10, UC_X86_REG_R11, UC_X86_REG_RSP, UC_X86_REG_RBP,
        UC_X86_REG_RIP, UC_X86_REG_CS, UC_X86_REG_SS,
        UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
        UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_INS_OUT, UC_X86_INS_IN,
    )
    HAVE_UNICORN = True
    UNICORN_IMPORT_ERROR = None
except ImportError as _exc:  # reported by the caller, never hidden
    # The register constants are module-level names used by class bodies and
    # by SYSV_SLOTS.  Without the import they must still resolve to something,
    # or a *missing dependency* would surface as a NameError deep in an
    # unrelated expression instead of the "install unicorn" message.
    HAVE_UNICORN = False
    UNICORN_IMPORT_ERROR = _exc
    UC_X86_REG_RAX = UC_X86_REG_RBX = UC_X86_REG_RDI = 0
    UC_X86_REG_RSI = UC_X86_REG_RDX = UC_X86_REG_RCX = 0
    UC_X86_REG_R8 = UC_X86_REG_R9 = UC_X86_REG_R10 = UC_X86_REG_R11 = 0
    UC_X86_REG_RSP = UC_X86_REG_RBP = UC_X86_REG_RIP = 0
    UC_X86_REG_CS = UC_X86_REG_SS = 0
    UC_X86_REG_EAX = UC_X86_REG_EBX = UC_X86_REG_ECX = UC_X86_REG_EDX = 0
    UC_X86_REG_ESP = UC_X86_REG_EIP = 0
    UC_X86_INS_OUT = UC_X86_INS_IN = 0

# --------------------------------------------------------------------------
# machine layout
# --------------------------------------------------------------------------
IMAGE_LOAD = 0x00400000          # deliberately != the 0x10000000 preferred base
IMAGE_WINDOW = 0x00200000
STUB_BASE = 0x01000000           # ms_abi bridge stubs
STUB_SIZE = 0x00010000
POOL_BASE = 0x02000000           # AllocatePool carve-out
POOL_END = 0x03000000
SCRATCH = 0x03000000             # scratch/return trampolines
SCRATCH_SIZE = 0x00010000
FB_BASE = 0x04000000             # synthetic framebuffer
FB_WIDTH, FB_HEIGHT = 1024, 768
FB_PITCH = FB_WIDTH * 4
FB_SIZE = 0x00800000
FW_STACK_TOP = 0x00500000        # firmware's stack, inside the image window
LOW_MEM = 0x00000000             # kernel handover area, boot info, E820, VBE
LOW_MEM_SIZE = 0x00100000

SECTORS_PER_CLUSTER_NOTES = None

EFI_SUCCESS = 0
EFI_INVALID_PARAMETER = 0x8000000000000002
EFI_UNSUPPORTED = 0x8000000000000003
EFI_BUFFER_TOO_SMALL = 0x8000000000000005
EFI_NOT_FOUND = 0x800000000000000E
EFI_ABORTED = 0x8000000000000015

SYSV_SLOTS = (UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX,
              UC_X86_REG_RCX, UC_X86_REG_R8, UC_X86_REG_R9)

# x86-64 instructions the harness interprets itself, because Unicorn leaves
# the descriptor tables and mode switching to the caller.
OP_LGDT_RM = 0x0F0110           # lgdt [rax]
OP_IRETQ = 0xCF
OP_LJMP_PTR16 = 0xEA            # in 16/32-bit code
OP_LRETQ = 0xCB


class StubError(RuntimeError):
    pass


class Trace:
    """Observed behaviour of the run, in order."""

    def __init__(self):
        self.serial = ""
        self.events = []
        self.console = []
        self.calls = {}
        self.problems = []
        self.gdt_loaded = None
        self.kernel_jump = None
        self.kernel_ebx = None
        self.exited = False

    def put(self, text):
        self.serial += text

    def note(self, event, **data):
        self.events.append(dict(event=event, **data))

    def count(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def problem(self, text):
        self.problems.append(text)

    def has_serial(self, needle):
        return needle in self.serial


class StubFirmware:
    def __init__(self, image, esp_volume, kernel_bytes, trace=None,
                 iso_volume_has_kernel=True, fat_walker=None):
        if not HAVE_UNICORN:
            raise StubError("the 'unicorn' module is not installed "
                            "(pip install unicorn)")
        self.image = image
        self.esp_files = esp_volume          # {"\\EFI\\BOOT\\BOOTX64.EFI": data}
        self.kernel = kernel_bytes
        self.iso_has_kernel = iso_volume_has_kernel
        self.trace = trace or Trace()
        self.pool_next = POOL_BASE
        self.objects = {}                    # address -> dict for file handles
        self.file_table = {}
        self.services = []                   # [(name, callable)]
        self.gdt = None
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self._map()
        self._load_image()
        self._build_tables()
        self._install_hooks()

    # ------------------------------------------------------------ memory
    def _map(self):
        uc = self.uc
        uc.mem_map(IMAGE_LOAD, IMAGE_WINDOW)
        uc.mem_map(STUB_BASE, STUB_SIZE)
        uc.mem_map(POOL_BASE, POOL_END - POOL_BASE)
        uc.mem_map(SCRATCH, SCRATCH_SIZE)
        uc.mem_map(FB_BASE, FB_SIZE)
        uc.mem_map(LOW_MEM, LOW_MEM_SIZE)
        uc.mem_map(0x10000000, 0x00100000)     # where a stray preferred-base hit lands

    def write(self, address, data):
        self.uc.mem_write(address, bytes(data))

    def read(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    def read_u64(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0]

    def read_u32(self, address):
        return struct.unpack("<I", self.read(address, 4))[0]

    def write_u64(self, address, value):
        self.write(address, struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))

    def write_u32(self, address, value):
        self.write(address, struct.pack("<I", value & 0xFFFFFFFF))

    @property
    def alloc_high_water(self):
        """First free byte of the stub pool after every allocation so far."""
        return self.pool_next

    def alloc(self, size, align=16):
        address = (self.pool_next + align - 1) & ~(align - 1)
        if address + size > POOL_END:
            raise StubError("stub pool exhausted")
        self.pool_next = address + size
        self.write(address, bytes(size))
        return address

    def alloc_utf16(self, text):
        address = self.alloc(len(text) * 2 + 2)
        self.write(address, text.encode("utf-16-le") + b"\0\0")
        return address

    # ------------------------------------------------------------- image
    def _load_image(self):
        image = self.image
        pe = struct.unpack_from("<I", image, 0x3C)[0]
        if image[pe:pe + 4] != b"PE\0\0":
            raise StubError("not a PE image")
        nsec = struct.unpack_from("<H", image, pe + 6)[0]
        opt_size = struct.unpack_from("<H", image, pe + 20)[0]
        opt = pe + 24
        self.preferred_base = struct.unpack_from("<Q", image, opt + 24)[0]
        self.entry_rva = struct.unpack_from("<I", image, opt + 16)[0]
        size_of_headers = struct.unpack_from("<I", image, opt + 60)[0]
        reloc_rva, reloc_size = struct.unpack_from("<II", image, opt + 112 + 5 * 8)
        table = opt + opt_size
        self.sections = {}
        for i in range(nsec):
            off = table + i * 40
            name = image[off:off + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, vaddr, raw_size, raw_ptr = struct.unpack_from("<IIII", image, off + 8)
            self.sections[name] = dict(vsize=vsize, vaddr=vaddr,
                                       raw_size=raw_size, raw_ptr=raw_ptr)

        self.delta = IMAGE_LOAD - self.preferred_base
        self.write(IMAGE_LOAD, image[:size_of_headers])
        for name, sec in self.sections.items():
            if sec["raw_size"]:
                self.write(IMAGE_LOAD + sec["vaddr"],
                           image[sec["raw_ptr"]:sec["raw_ptr"] + sec["raw_size"]])
            elif sec["vsize"]:
                self.write(IMAGE_LOAD + sec["vaddr"], bytes(sec["vsize"]))

        self.relocations = 0
        offset = self._file_offset(reloc_rva)
        end = offset + reloc_size
        while offset + 8 <= end:
            page, block = struct.unpack_from("<II", image, offset)
            if block < 8:
                break
            for i in range((block - 8) // 2):
                entry = struct.unpack_from("<H", image, offset + 8 + i * 2)[0]
                kind, target = entry >> 12, page + (entry & 0xFFF)
                if kind == 0:
                    continue
                address = IMAGE_LOAD + target
                if kind == 10:
                    self.write_u64(address, self.read_u64(address) + self.delta)
                elif kind == 3:
                    self.write_u32(address, (self.read_u32(address) + self.delta) & 0xFFFFFFFF)
                else:
                    raise StubError(f"relocation type {kind} at {target:#x}")
                self.relocations += 1
            offset += block
        if not self.relocations:
            raise StubError("the image has no base relocations")

        # The loader publishes its handover descriptor as the first .data
        # object; both addresses in it are relocated, so they are valid now.
        data = self.sections.get(".data")
        if not data:
            raise StubError("no .data section")
        descriptor = self.read(IMAGE_LOAD + data["vaddr"], 24)
        if descriptor[0:8] != b"PC5HND01":
            raise StubError("handover descriptor missing from the start of .data")
        self.bridge_entry = struct.unpack_from("<Q", descriptor, 8)[0]
        self.kernel_jump = struct.unpack_from("<Q", descriptor, 16)[0]
        self.entry = IMAGE_LOAD + self.entry_rva
        self.trace.note("image_loaded", at=hex(IMAGE_LOAD),
                        preferred=hex(self.preferred_base),
                        relocations=self.relocations,
                        bridge=hex(self.bridge_entry))

    def _file_offset(self, rva):
        # PE places sections at section alignment, so the virtual span of a
        # section is its *virtual size*; the raw size is only padded up to the
        # file alignment and must not be used for address arithmetic.
        for sec in self.sections.values():
            if sec["vaddr"] <= rva < sec["vaddr"] + max(sec["vsize"], 1):
                return sec["raw_ptr"] + (rva - sec["vaddr"])
        raise StubError(f"rva {rva:#x} outside every section")

    # ------------------------------------------------------------ tables
    # Each service slot is a single `ret`; the harness handles the call in the
    # code hook *before* it executes.  Reading the arguments straight out of
    # the ms_abi registers (RCX, RDX, R8, R9) is deliberate: if the loader used
    # the SysV convention by mistake, the harness would see its arguments in
    # the wrong registers and the checks would fail.  That is the contract this
    # harness is here to test, so it is the contract it reads.
    BRIDGE_SLOT = 16
    MSABI_ARGS = (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8,
                  UC_X86_REG_R9, UC_X86_REG_RAX, UC_X86_REG_RBX)

    def add_service(self, name, function):
        index = len(self.services)
        self.services.append((name, function))
        address = STUB_BASE + index * self.BRIDGE_SLOT
        if address + self.BRIDGE_SLOT > STUB_BASE + STUB_SIZE:
            raise StubError("too many services for the bridge area")
        self.write(address, b"\xc3")          # ret, never actually executed
        return address

    def _table(self, slots):
        """Allocate a zeroed protocol table of `slots` pointers.

        The size is in bytes and `alloc` takes bytes; conflating the two makes
        every table four times too small and lets one protocol's writes land in
        the next one's memory, so the unit conversion lives here and nowhere
        else.
        """
        return self.alloc(8 * slots)

    def _build_tables(self):
        # --- Simple Text Output (11 entries; output_string at +8)
        self.con_out = self._table(11)
        self.write_u64(self.con_out + 8,
                       self.add_service("output_string", self.svc_output_string))

        # --- Graphics Output Protocol (4 entries; *Mode at +24)
        info = self.alloc(0x40)
        # EFI_GRAPHICS_PIXEL_FORMAT: 0 = RedGreenBlueReserved8BitPerColor,
        # 1 = BlueGreenRedReserved8BitPerColor.  The loader writes 0x00RRGGBB
        # and accepts either, so report the BGR layout that the framebuffer in
        # this harness is actually filled with.
        self.write(info, struct.pack("<IIII", 1, FB_WIDTH, FB_HEIGHT, 1))  # BGRx
        self.write(info + 0x10, struct.pack("<IIII", 0, 0, 0, 0))
        self.write(info + 0x20, struct.pack("<I", FB_WIDTH))
        mode = self.alloc(0x28)
        self.write(mode, struct.pack("<IIQQQQ", 1, 0, info, 0x40, FB_BASE, FB_SIZE))
        self.gop = self._table(4)
        self.write_u64(self.gop + 24, mode)

        # --- Boot Services (44 entries).  Addressed by the byte offsets the
        # specification assigns, not by slot numbers, so this table is checked
        # against the same numbers the loader's _Static_asserts pin.
        self.bs = self._table(44)
        services = {
            40: ("allocate_pages", self.svc_allocate_pages),
            48: ("free_pages", self.svc_free_pages),
            56: ("get_memory_map", self.svc_get_memory_map),
            64: ("allocate_pool", self.svc_allocate_pool),
            72: ("free_pool", self.svc_free_pool),
            152: ("handle_protocol", self.svc_handle_protocol),
            176: ("locate_handle", self.svc_locate_handle),
            232: ("exit_boot_services", self.svc_exit_boot_services),
        }
        for offset, (name, function) in services.items():
            self.write_u64(self.bs + offset, self.add_service(name, function))
        self.write(self.bs, struct.pack("<QIIII", 0x56524553544D5453, 0x00020000,
                                       0x48, 0, 0))

        # --- System Table
        self.sys_table = self.alloc(0x78)
        self.write(self.sys_table,
                   struct.pack("<QIIII", 0x5453595320494249, 0x00020000, 0x78, 0, 0))
        self.write_u64(self.sys_table + 24, self.alloc_utf16("PC5 stub firmware"))
        self.write_u32(self.sys_table + 32, 0x00020000)
        self.write_u64(self.sys_table + 56, 0xE5F0)      # console_out_handle
        self.write_u64(self.sys_table + 64, self.con_out)
        self.write_u64(self.sys_table + 96, self.bs)
        self.write_u64(self.sys_table + 104, self.alloc(0x40))   # runtime services

        # --- Volumes: the ESP the loader was booted from, and one with the kernel
        self.volumes = {
            0xE5F00000: dict(name="esp", files=self.esp_files),
            0x15000000: dict(name="iso", files={"\\KERNEL.BIN": self.kernel}
                             if self.iso_has_kernel else {"\\README.TXT": b"PC5\r\n"}),
        }
        for handle, volume in self.volumes.items():
            fs = self._table(2)
            self.write_u64(fs + 8, self.add_service(
                f"open_volume[{volume['name']}]", self._open_volume_factory(handle)))
            volume["fs"] = fs

    # ------------------------------------------------------------- hooks
    def _install_hooks(self):
        uc = self.uc
        uc.hook_add(UC_HOOK_CODE, self._hook_code)
        uc.hook_add(UC_HOOK_INSN, self._hook_out, None, 1, 0, UC_X86_INS_OUT)
        uc.hook_add(UC_HOOK_INSN, self._hook_in, None, 1, 0, UC_X86_INS_IN)
        self.in_buffer = []
        self.segment_reloads = {}
        self.image_protocol = 0

    def _hook_out(self, uc, port, size, value, userdata):
        if port == 0x3F8:
            self.trace.put(chr(value & 0xFF))
        return True

    def _hook_in(self, uc, port, size, userdata):
        # A 16550 with the transmit register always ready and a scratch
        # register that reads back what was written: that is exactly what the
        # loader's serial probe checks, so this keeps the probe honest.
        uc.reg_write(UC_X86_REG_RAX, 0x60 if port == 0x3F9 + 4 else 0x5A)
        return True

    def _hook_code(self, uc, address, size, userdata):
        # service entries
        service_entry = self.service_entries.get(address)
        if service_entry is not None:
            self._enter_service(service_entry)
            return
        # the handover trampoline, which needs the mode switch emulated
        if address == self.bridge_entry:
            self._emulate_bridge(uc)
            return
        if address == self.kernel_jump:
            self._emulate_kernel_jump(uc)
            return
        # Unicorn raises an unhandled exception on `mov Sreg, r/m16` in long
        # mode, which the 32-bit tail uses to reload the data segments after
        # the mode switch.  The GDT itself is validated in _emulate_bridge, so
        # skipping the reload loses nothing that this harness claims to test.
        if address in self.segment_reloads:
            uc.reg_write(UC_X86_REG_RIP, address + self.segment_reloads[address])
            return

    @property
    def service_entries(self):
        return {STUB_BASE + i * self.BRIDGE_SLOT: (name, fn)
                for i, (name, fn) in enumerate(self.services)}

    def _enter_service(self, entry):
        """Run one EFI service call and return to the caller as a far call."""
        name, function = entry
        self.trace.count(name)
        uc = self.uc
        args = [uc.reg_read(reg) for reg in self.MSABI_ARGS]
        # ms_abi: on entry to a callee [rsp] is the return address and the
        # caller's 32-byte shadow space sits above it.  Returning therefore
        # means "put the status in RAX, pop the return address, jump".
        rsp = uc.reg_read(UC_X86_REG_RSP)
        return_address = self.read_u64(rsp)
        if not return_address:
            raise StubError(f"service {name} called with no return address on the stack")
        # Firmware ignores extra arguments past the ones a service declares,
        # so a fixed-arity implementation is fed only the registers it can
        # take.  This is the same latitude the real x64 ABI gives callers.
        while True:
            try:
                status = function(*args)
                break
            except TypeError as exc:
                if "positional argument" not in str(exc) or len(args) == 0:
                    raise
                args = args[:-1]
        if status is None:
            status = EFI_SUCCESS
        # Return exactly as a real `ret` would: pop the return address into a
        # scratch register *first*, restore RSP, then jump.  Writing RIP before
        # RSP would leave the popped word on the stack and - worse - any write
        # to RAX after the jump would destroy the service's status, which the
        # caller is about to test.
        uc.reg_write(UC_X86_REG_R11, return_address)
        uc.reg_write(UC_X86_REG_RSP, rsp + 8)
        uc.reg_write(UC_X86_REG_RAX, status & 0xFFFFFFFFFFFFFFFF)
        uc.reg_write(UC_X86_REG_RIP, uc.reg_read(UC_X86_REG_R11))

    def _emulate_bridge(self, uc):
        """Emulate pc5_uefi_bridge: check the GDT it builds and switch to 32-bit.

        Unicorn does not implement `lgdt`, segment loads or the far return, so
        the harness validates the descriptor the loader wrote and then enters
        32-bit mode itself at the instruction after the far return.
        """
        # Decode the loader's own `lgdt` instruction rather than guessing where
        # the descriptor lives: a rebuilt image moves its data freely, and a
        # byte scan that assumes a layout fails for reasons that have nothing
        # to do with the loader.  `0f 01 /2 m16&64` is followed by a RIP
        # relative displacement to a 10-byte descriptor (limit + 64-bit base).
        descriptor = None
        for offset in range(0, 0x80):
            address = self.bridge_entry + offset
            if self.read(address, 3) == b"\x0f\x01\x15":
                disp = struct.unpack("<i", self.read(address + 3, 4))[0]
                descriptor = address + 7 + disp
                break
        if descriptor is None:
            raise StubError("could not find the loader's lgdt instruction")
        limit = struct.unpack("<H", self.read(descriptor, 2))[0]
        table = self.read_u64(descriptor + 2)
        if limit != 23:
            raise StubError(f"the loader's GDT limit is {limit}, expected 23")
        entries = self.read(table, 24)

        if entries != (bytes(8) + bytes.fromhex("ffff0000009acf00")
                       + bytes.fromhex("ffff00000092cf00")):
            raise StubError("the loader's GDT entries are not flat 32-bit "
                             f"code/data: {entries.hex()}")
        self.trace.gdt_loaded = dict(base=hex(table), limit=limit)
        # The emulation starts at the instruction *after* the far return, so
        # the instructions the bridge executes before it - and in particular
        # `movq %rsi,%rbx`, which carries the boot-info pointer across the mode
        # switch - have to be applied here, or the handover would be checked
        # against a register the loader never set.
        uc.reg_write(UC_X86_REG_RBX, uc.reg_read(UC_X86_REG_RSI))
        uc.reg_write(UC_X86_REG_CS, 0x08)
        uc.reg_write(UC_X86_REG_SS, 0x10)
        after = self._after_far_return()
        uc.reg_write(UC_X86_REG_RIP, after)
        # The reloads are `mov %ax,%ds` et al: when AX already holds 0x10, the
        # compilers emit a shorter or longer encoding depending on the register
        # they picked, so find every `8e` prefix in the tail by decoding the
        # few encodings that appear there.
        self.segment_reloads = self._segment_reloads(after)

    def _segment_reloads(self, address):
        """Map every `mov Sreg, r/m16` in the 32-bit tail to its length.

        `8e /r` takes an 8-bit ModRM; with mod=3 the instruction is two bytes
        (`8e d8`), with a memory operand it is longer.  Only the register form
        is emitted for the reloads here, but the decoder tolerates the 0xFF
        prefix used by some assemblers for `mov eax, %ds` style encodings.
        """
        found = {}
        offset = 0
        while offset < 0x40:
            at = address + offset
            if at >= self.kernel_jump:
                break
            first = self.read(at, 2)
            if first == b"\x8e":
                break
            if len(first) == 2 and first[0] == 0x8E and (first[1] & 0xC0) == 0xC0:
                found[at] = 2
                offset += 2
            else:
                offset += 1
        return found

    def _after_far_return(self):
        """Address the loader's far return lands on (`compat32`)."""
        return self.compat32

    def _emulate_kernel_jump(self, uc):
        """The final far jump: record the handover state, then stop."""
        # `ea imm32 imm16` is a 32-bit far jump: the target is an immediate in
        # the instruction, not the current EIP.  Decoding it is what proves the
        # loader jumps to the address it also copied the kernel to.
        opcode = self.read(self.kernel_jump, 7)
        if opcode[0] != 0xEA:
            raise StubError("the kernel jump is not a far jump: "
                            f"{opcode.hex()}")
        target, selector = struct.unpack("<IH", opcode[1:])
        self.trace.kernel_selector = selector
        self.trace.kernel_jump = dict(target=f"0x{target:x}",
                                      ebx=hex(uc.reg_read(UC_X86_REG_EBX)),
                                      esp=hex(uc.reg_read(UC_X86_REG_ESP)))
        self.trace.kernel_ebx = uc.reg_read(UC_X86_REG_EBX)
        uc.emu_stop()

    # ---------------------------------------------------------- services
    def svc_output_string(self, con_out, string, *_rest):
        address = string
        text = []
        for _ in range(8192):
            char = struct.unpack("<H", self.read(address, 2))[0]
            if char == 0:
                break
            text.append(chr(char))
            address += 2
        joined = "".join(text)
        self.trace.console.append(joined)
        self.trace.put(joined)
        return EFI_SUCCESS

    def svc_allocate_pages(self, alloc_type, memory_type, pages, memory_ptr, *_):
        self.write_u64(memory_ptr, self.alloc(pages * 4096, align=4096))
        return EFI_SUCCESS

    def svc_free_pages(self, *_):
        return EFI_SUCCESS

    def svc_get_memory_map(self, size_ptr, map_ptr, key_ptr, desc_ptr, ver_ptr):
        entry = 48
        descriptors = [
            (7, 0x0, 0x0, 0x9F),              # conventional, low
            (7, 0x100000, 0x0, 0x100),        # conventional
            (2, FB_BASE, 0x0, FB_SIZE // 4096),
            (2, POOL_BASE, 0x0, (POOL_END - POOL_BASE) // 4096),
            (2, IMAGE_LOAD, 0x0, IMAGE_WINDOW // 4096),
            (7, 0x100000000, 0x0, 0x100),     # above 4 GiB: must be truncated
        ]
        needed = entry * (len(descriptors) + 1)
        size = self.read_u64(size_ptr)
        # Firmware fills in the required size, the descriptor stride and the
        # map version even when it rejects the call with BUFFER_TOO_SMALL;
        # that is how a caller learns how much memory to allocate.  This
        # happens before the caller allocates anything, so the map is exactly
        # what a real firmware would report at the same point.
        self.write_u64(size_ptr, needed)
        self.write_u64(desc_ptr, entry)
        self.write_u32(ver_ptr, 1)
        if not map_ptr or size < needed:
            return EFI_BUFFER_TOO_SMALL
        for index, (kind, phys, _virt, pages) in enumerate(descriptors):
            self.write(map_ptr + index * entry,
                       struct.pack("<IIQQQQ", kind, 0, phys, 0, pages, 8))
        self.write_u64(size_ptr, needed)
        self.write_u64(key_ptr, 0xB007)
        return EFI_SUCCESS

    def svc_allocate_pool(self, pool_type, size, buffer_ptr):
        self.write_u64(buffer_ptr, self.alloc(size))
        return EFI_SUCCESS

    def svc_free_pool(self, _buffer):
        return EFI_SUCCESS

    def svc_handle_protocol(self, handle, guid_ptr, interface_ptr):
        guid = self.read(guid_ptr, 16)
        kind = self.GUIDS.get(guid)
        if kind == "gop":
            self.write_u64(interface_ptr, self.gop)
            return EFI_SUCCESS
        if kind == "fs":
            # A file-system protocol belongs to one device, so the handle has
            # to match; GOP and Loaded Image are reachable from any handle
            # firmware is willing to answer for, as on real firmware.
            volume = self.volumes.get(handle)
            if volume is None:
                return EFI_NOT_FOUND
            self.write_u64(interface_ptr, volume["fs"])
            return EFI_SUCCESS
        if kind == "loaded_image":
            # Allocated once and cached: a second ImageHandle query (which real
            # firmware answers with the same object) must not hand back a
            # different pointer each time.
            if self.image_protocol:
                self.write_u64(interface_ptr, self.image_protocol)
                return EFI_SUCCESS
            image = self.alloc(96)
            self.image_protocol = image
            self.write_u64(image + 16, self.sys_table)
            self.write_u64(image + 24, 0xE5F00000)               # device we came from
            self.write_u64(image + 32, self.alloc_file_path(r"\EFI\BOOT\BOOTX64.EFI"))
            self.write_u64(interface_ptr, image)
            return EFI_SUCCESS
        if kind == "device_path":
            node = struct.pack("<BBH", 0x04, 0x01, 42) + bytes(38)
            end = struct.pack("<BBH", 0x7F, 0xFF, 4)
            address = self.alloc(len(node) + len(end))
            self.write(address, node + end)
            self.write_u64(interface_ptr, address)
            return EFI_SUCCESS
        return EFI_UNSUPPORTED

    GUIDS = {
        # 9042a9de-23dc-4a38-96fb-7aded080516a in EFI byte order (first three
        # fields little-endian): de a9 42 90 ...
        bytes.fromhex("dea94290dc23384a96fb7aded080516a"): "gop",
        # 964e5b22-6459-11d2-8e39-00a0c969723b
        bytes.fromhex("225b4e965964d2118e3900a0c969723b"): "fs",
        # 5b1b31a1-9562-11d2-8e3f-00a0c969723b
        bytes.fromhex("a1311b5b6295d2118e3f00a0c969723b"): "loaded_image",
        # 09576e91-6d3f-11d2-8e39-00a0c969723b
        bytes.fromhex("916e57093f6dd2118e3900a0c969723b"): "device_path",
    }

    def alloc_file_path(self, text):
        address = self.alloc(16 + len(text) * 2 + 2)
        self.write(address + 16, text.encode("utf-16-le") + b"\0\0")
        return address

    def svc_locate_handle(self, size_ptr, search_type, _key, buffer):
        handles = list(self.volumes.keys())
        needed = len(handles) * 8
        size = self.read_u64(size_ptr)
        if not buffer or size < needed:
            self.write_u64(size_ptr, needed)
            return EFI_BUFFER_TOO_SMALL
        for index, handle in enumerate(handles):
            self.write_u64(buffer + index * 8, handle)
        self.write_u64(size_ptr, needed)
        return EFI_SUCCESS

    def svc_exit_boot_services(self, _image, map_key):
        self.trace.exited = True
        self.trace.note("exit_boot_services", map_key=map_key)
        return EFI_SUCCESS

    # ------------------------------------------------------ file system
    def _open_volume_factory(self, handle):
        volume = self.volumes[handle]

        def open_volume(fs, root_ptr):
            root = self._make_file(volume, None, is_dir=True)
            self.write_u64(root_ptr, root)
            return EFI_SUCCESS
        return open_volume

    def _make_file(self, volume, path, is_dir=False, data=None):
        """A file (or directory root) with a File Protocol table."""
        table = self._file_protocol_table()
        # A File Protocol object is 13 pointers wide (revision + 12 methods);
        # allocating less and copying the table into it would scribble over
        # whatever the pool allocator handed out next.
        address = self.alloc(0x80)
        self.objects[address] = dict(volume=volume, path=path, is_dir=is_dir,
                                     data=data if data is not None else b"", pos=0)
        self.write_u64(address, 0)
        for offset in range(8, 16 * 8, 8):
            self.write_u64(address + offset, self.read_u64(table + offset))
        return address

    def _file_protocol_table(self):
        if self.file_protocol:
            return self.file_protocol
        table = self._table(20)
        self.file_protocol = table
        self.write_u64(table + 8, self.add_service("file_open", self.svc_file_open))
        self.write_u64(table + 16, self.add_service("file_close", self.svc_file_close))
        self.write_u64(table + 32, self.add_service("file_read", self.svc_file_read))
        self.write_u64(table + 48, self.add_service("file_get_position", self.svc_file_get_position))
        self.write_u64(table + 56, self.add_service("file_set_position", self.svc_file_set_position))
        return table

    file_protocol = None

    def svc_file_open(self, file_ptr, new_handle_ptr, name_ptr, mode, attributes):
        entry = self.objects[file_ptr]
        files = entry["volume"]["files"]
        # Firmware accepts both "\\KERNEL.BIN" and "KERNEL.BIN" for a root
        # file; the key set is normalised to a leading backslash.
        raw = self._utf16(name_ptr).strip("\\").upper()
        wanted = "\\" + raw if raw else ""
        if entry["is_dir"]:
            key = next((k for k in files if k.upper() == wanted), None)
            if key is None:
                return EFI_NOT_FOUND
            handle = self._make_file(entry["volume"], key, data=files[key])
            self.write_u64(new_handle_ptr, handle)
            return EFI_SUCCESS
        return EFI_NOT_FOUND

    def svc_file_close(self, _file):
        return EFI_SUCCESS

    def svc_file_read(self, file_ptr, size_ptr, buffer):
        state = self.objects[file_ptr]
        data = state["data"]
        wanted = self.read_u64(size_ptr)
        chunk = data[state["pos"]:state["pos"] + wanted]
        if chunk:
            self.write(buffer, chunk)
        state["pos"] += len(chunk)
        self.write_u64(size_ptr, len(chunk))
        return EFI_SUCCESS

    def svc_file_get_position(self, file_ptr, position_ptr):
        self.write_u64(position_ptr, self.objects[file_ptr]["pos"])
        return EFI_SUCCESS

    def svc_file_set_position(self, file_ptr, position):
        state = self.objects[file_ptr]
        state["pos"] = min(position, len(state["data"]))
        return EFI_SUCCESS

    def _utf16(self, address):
        out = []
        for _ in range(520):
            char = struct.unpack("<H", self.read(address, 2))[0]
            if char == 0:
                break
            out.append(chr(char))
            address += 2
        return "".join(out)

    # -------------------------------------------------------------- run
    def run(self, max_instructions=60_000_000, expect_handover=True):
        uc = self.uc
        uc.reg_write(UC_X86_REG_CS, 0x33)
        uc.reg_write(UC_X86_REG_SS, 0x2B)
        uc.reg_write(UC_X86_REG_RSP, FW_STACK_TOP)
        uc.reg_write(UC_X86_REG_RCX, 0xE5F0)          # ImageHandle
        uc.reg_write(UC_X86_REG_RDX, self.sys_table)  # SystemTable
        # the descriptor table objects the harness emulates
        self.compat32 = self._locate_compat32()
        try:
            uc.emu_start(self.entry, 0, 0, max_instructions)
        except UcError as exc:
            raise StubError(f"emulation faulted: {exc} (eip={uc.reg_read(UC_X86_REG_RIP):#x})")
        if expect_handover and not self.trace.kernel_jump:
            raise StubError("the run ended before the kernel handover "
                            f"(eip={uc.reg_read(UC_X86_REG_RIP):#x})")
        return self.trace

    def _locate_compat32(self):
        """Find the instruction after the loader's far return (`compat32`).

        The far return is `lretq` preceded by two pushes; the code after it is
        the 32-bit tail.  Scanning .text for `lretq` inside the bridge and
        taking the following address is exact and needs no symbol.
        """
        text = self.sections[".text"]
        base = IMAGE_LOAD + text["vaddr"]
        start = self.bridge_entry
        for offset in range(0, 0x200):
            address = start + offset
            if self.read(address, 1) == b"\xcb":          # lretq
                return address + 1
        raise StubError("could not locate the 32-bit handover target")

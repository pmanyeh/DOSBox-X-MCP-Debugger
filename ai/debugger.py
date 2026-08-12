"""
FakeDOSBoxDebugger: a stateful, in-process stand-in for the real DOSBox-X
debugger. It exists only to validate the MCP tool contract before the
native DOSBox-X bridge exists (see AGENTS.md Phase 2 / Phase 3).

It maintains real registers, a real (fake) memory image, and a tiny
instruction decoder for a handful of opcodes so that step_into() /
continue_execution() / disassemble() behave like a real debugger instead
of returning hard-coded values.
"""

from protocol import DebuggerError, parse_address, format_address, linear_address

MEM_SIZE = 0x110000  # covers every real-mode SEG:OFF address (0xFFFF:0xFFFF)
MAX_READ_LENGTH = 0x10000
MAX_DISASSEMBLE_COUNT = 100
SAFETY_STEP_LIMIT = 1000

# Test program preloaded at the initial CS:EIP (see drive_c/TEST.COM):
#   MOV AX,1234h ; MOV BX,5678h ; ADD AX,BX ; MOV AH,4Ch ; INT 21h
_TEST_PROGRAM = bytes([0xB8, 0x34, 0x12, 0xBB, 0x78, 0x56, 0x01, 0xD8, 0xB4, 0x4C, 0xCD, 0x21])

_ZF = 0x40


def _decode(memory: bytearray, linear: int):
    """Decode one instruction at `linear`. Never raises; unknown bytes
    decode as a 1-byte pseudo-instruction so callers can always advance.

    Returns (length, bytes_hex, text, effect) where `effect` is a tuple
    describing the register/flag change step_into() should apply.
    """

    b0 = memory[linear] if linear < MEM_SIZE else 0x00

    if b0 == 0xB8 and linear + 2 < MEM_SIZE:  # MOV AX,imm16
        imm = memory[linear + 1] | (memory[linear + 2] << 8)
        length = 3
        text = f"MOV AX,{imm:04X}h"
        effect = ("mov_ax", imm)
    elif b0 == 0xBB and linear + 2 < MEM_SIZE:  # MOV BX,imm16
        imm = memory[linear + 1] | (memory[linear + 2] << 8)
        length = 3
        text = f"MOV BX,{imm:04X}h"
        effect = ("mov_bx", imm)
    elif b0 == 0x01 and linear + 1 < MEM_SIZE and memory[linear + 1] == 0xD8:  # ADD AX,BX
        length = 2
        text = "ADD AX,BX"
        effect = ("add_ax_bx",)
    elif b0 == 0xB4 and linear + 1 < MEM_SIZE:  # MOV AH,imm8
        imm8 = memory[linear + 1]
        length = 2
        text = f"MOV AH,{imm8:02X}h"
        effect = ("mov_ah", imm8)
    elif b0 == 0xCD and linear + 1 < MEM_SIZE:  # INT imm8
        imm8 = memory[linear + 1]
        length = 2
        text = f"INT {imm8:02X}h"
        effect = ("int", imm8)
    else:
        length = 1
        text = f"DB {b0:02X}h"
        effect = ("unknown",)

    length = min(length, MEM_SIZE - linear)
    raw = memory[linear:linear + length]
    bytes_hex = " ".join(f"{b:02X}" for b in raw)
    return length, bytes_hex, text, effect


class FakeDOSBoxDebugger:
    def __init__(self):
        self.memory = bytearray(MEM_SIZE)

        self.regs = {
            "eax": 0x00000000,
            "ebx": 0x00000000,
            "ecx": 0x00000000,
            "edx": 0x00000000,
            "esi": 0x00000000,
            "edi": 0x00000000,
            "ebp": 0x00000000,
            "esp": 0x0000FF00,
        }
        self.segs = {
            "cs": 0x1234,
            "ds": 0x2000,
            "es": 0x2000,
            "ss": 0x3000,
        }
        self.eip = 0x0100
        self.eflags = 0x00000202

        self.running = False
        self.stopped = True
        self.halted = False

        self._breakpoints: dict[int, dict] = {}
        self._next_breakpoint_id = 1

        start = linear_address(self.segs["cs"], self.eip)
        self.memory[start:start + len(_TEST_PROGRAM)] = _TEST_PROGRAM

    # -- helpers ----------------------------------------------------

    def _current_linear(self) -> int:
        return linear_address(self.segs["cs"], self.eip)

    def _decode_current(self):
        return _decode(self.memory, self._current_linear())

    def _current_address(self) -> str:
        return format_address(self.segs["cs"], self.eip)

    def _apply_effect(self, effect: tuple) -> None:
        tag = effect[0]

        if tag == "mov_ax":
            self.regs["eax"] = (self.regs["eax"] & 0xFFFF0000) | effect[1]
        elif tag == "mov_bx":
            self.regs["ebx"] = (self.regs["ebx"] & 0xFFFF0000) | effect[1]
        elif tag == "mov_ah":
            self.regs["eax"] = (self.regs["eax"] & 0xFFFF00FF) | (effect[1] << 8)
        elif tag == "add_ax_bx":
            ax = self.regs["eax"] & 0xFFFF
            bx = self.regs["ebx"] & 0xFFFF
            result = (ax + bx) & 0xFFFF
            self.regs["eax"] = (self.regs["eax"] & 0xFFFF0000) | result
            if result == 0:
                self.eflags |= _ZF
            else:
                self.eflags &= ~_ZF
        elif tag == "int":
            self.halted = True
            self.running = False
            self.stopped = True
        # "unknown" -> no register effect

    def _breakpoint_hit_here(self) -> bool:
        here = self._current_address()
        return any(bp["enabled"] and bp["address"] == here for bp in self._breakpoints.values())

    # -- CPU / instruction inspection --------------------------------

    def get_cpu_state(self) -> dict:
        return {
            "eax": f"{self.regs['eax']:08X}",
            "ebx": f"{self.regs['ebx']:08X}",
            "ecx": f"{self.regs['ecx']:08X}",
            "edx": f"{self.regs['edx']:08X}",
            "esi": f"{self.regs['esi']:08X}",
            "edi": f"{self.regs['edi']:08X}",
            "ebp": f"{self.regs['ebp']:08X}",
            "esp": f"{self.regs['esp']:08X}",
            "cs": f"{self.segs['cs']:04X}",
            "eip": f"{self.eip:04X}",
            "ds": f"{self.segs['ds']:04X}",
            "es": f"{self.segs['es']:04X}",
            "ss": f"{self.segs['ss']:04X}",
        }

    def get_current_instruction(self) -> dict:
        _length, bytes_hex, text, _effect = self._decode_current()
        return {
            "address": self._current_address(),
            "bytes": bytes_hex,
            "instruction": text,
        }

    def get_debug_status(self) -> dict:
        _length, bytes_hex, text, _effect = self._decode_current()
        cpu = self.get_cpu_state()
        return {
            "stopped": self.stopped,
            "running": self.running,
            "location": {
                "cs": cpu["cs"],
                "eip": cpu["eip"],
            },
            "instruction": {
                "bytes": bytes_hex,
                "text": text,
            },
            "registers": {
                "eax": cpu["eax"],
                "ebx": cpu["ebx"],
                "ecx": cpu["ecx"],
                "edx": cpu["edx"],
                "esi": cpu["esi"],
                "edi": cpu["edi"],
                "ebp": cpu["ebp"],
                "esp": cpu["esp"],
            },
            "segments": {
                "cs": cpu["cs"],
                "ds": cpu["ds"],
                "es": cpu["es"],
                "ss": cpu["ss"],
            },
            "flags": {
                "eflags": f"{self.eflags:08X}",
            },
        }

    # -- memory -------------------------------------------------------

    def read_memory(self, address: str, length: int) -> dict:
        if not isinstance(length, int) or length <= 0:
            raise DebuggerError("INVALID_LENGTH", f"Length must be a positive integer, got {length!r}")
        if length > MAX_READ_LENGTH:
            raise DebuggerError("INVALID_LENGTH", f"Length exceeds maximum of {MAX_READ_LENGTH}")

        segment, offset = parse_address(address)
        start = linear_address(segment, offset)
        if start + length > MEM_SIZE:
            raise DebuggerError("OUT_OF_BOUNDS", f"Read of {length} bytes at {address} exceeds emulated memory")

        raw = self.memory[start:start + length]
        return {
            "address": format_address(segment, offset),
            "length": length,
            "bytes": [f"{b:02X}" for b in raw],
        }

    def write_memory(self, address: str, data: list) -> dict:
        if not isinstance(data, list) or len(data) == 0:
            raise DebuggerError("INVALID_DATA", "data must be a non-empty list of byte values")

        parsed_bytes = []
        for item in data:
            try:
                value = int(item, 16) if isinstance(item, str) else int(item)
            except (TypeError, ValueError):
                raise DebuggerError("INVALID_DATA", f"Invalid byte value: {item!r}")
            if not (0 <= value <= 0xFF):
                raise DebuggerError("INVALID_DATA", f"Byte value out of range: {item!r}")
            parsed_bytes.append(value)

        segment, offset = parse_address(address)
        start = linear_address(segment, offset)
        length = len(parsed_bytes)
        if start + length > MEM_SIZE:
            raise DebuggerError("OUT_OF_BOUNDS", f"Write of {length} bytes at {address} exceeds emulated memory")

        self.memory[start:start + length] = bytes(parsed_bytes)
        return {
            "address": format_address(segment, offset),
            "length": length,
            "bytes": [f"{b:02X}" for b in parsed_bytes],
        }

    def disassemble(self, address: str, count: int) -> list:
        if not isinstance(count, int) or count <= 0:
            raise DebuggerError("INVALID_COUNT", f"count must be a positive integer, got {count!r}")
        if count > MAX_DISASSEMBLE_COUNT:
            raise DebuggerError("INVALID_COUNT", f"count exceeds maximum of {MAX_DISASSEMBLE_COUNT}")

        segment, offset = parse_address(address)
        result = []
        for _ in range(count):
            linear = linear_address(segment, offset)
            if linear >= MEM_SIZE:
                break
            length, bytes_hex, text, _effect = _decode(self.memory, linear)
            result.append({
                "address": format_address(segment, offset),
                "bytes": bytes_hex,
                "instruction": text,
            })
            offset = (offset + length) & 0xFFFF
        return result

    # -- breakpoints ----------------------------------------------------

    def set_breakpoint(self, address: str) -> dict:
        segment, offset = parse_address(address)
        bp_id = self._next_breakpoint_id
        self._next_breakpoint_id += 1
        breakpoint_ = {
            "id": bp_id,
            "address": format_address(segment, offset),
            "enabled": True,
        }
        self._breakpoints[bp_id] = breakpoint_
        return breakpoint_

    def delete_breakpoint(self, breakpoint_id: int) -> dict:
        if breakpoint_id not in self._breakpoints:
            raise DebuggerError("BREAKPOINT_NOT_FOUND", f"No breakpoint with id {breakpoint_id}")
        removed = self._breakpoints.pop(breakpoint_id)
        return {"id": removed["id"], "deleted": True}

    def list_breakpoints(self) -> list:
        return [self._breakpoints[bp_id] for bp_id in sorted(self._breakpoints)]

    # -- execution -----------------------------------------------------

    def step_into(self) -> dict:
        if not self.halted:
            length, _bytes_hex, _text, effect = self._decode_current()
            self._apply_effect(effect)
            if not self.halted:
                self.eip = (self.eip + length) & 0xFFFF

        self.running = False
        self.stopped = True
        return self.get_debug_status()

    def continue_execution(self) -> dict:
        self.running = True
        self.stopped = False

        steps = 0
        while steps < SAFETY_STEP_LIMIT and not self.halted:
            length, _bytes_hex, _text, effect = self._decode_current()
            self._apply_effect(effect)
            if not self.halted:
                self.eip = (self.eip + length) & 0xFFFF
            steps += 1
            if self._breakpoint_hit_here():
                break

        self.running = False
        self.stopped = True
        return self.get_debug_status()

    def pause_execution(self) -> dict:
        self.running = False
        self.stopped = True
        return self.get_debug_status()

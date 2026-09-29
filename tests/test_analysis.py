import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

import pytest

from analysis import build_control_flow_graph, get_call_stack, search_memory
from dosbox_client import DOSBoxMemoryError


class StubClient:
    """A minimal stand-in for DOSBoxClient's memory.read/cpu.get surface,
    backed by a plain Python bytearray addressed as flat linear guest
    memory (linear = segment * 16 + offset). Used to test search_memory()/
    get_call_stack()'s pure logic without a live DOSBox-X instance."""

    def __init__(self, size: int, fill: int = 0x00):
        self.memory = bytearray([fill]) * size
        self.unreadable_ranges: list[tuple[int, int]] = []
        self.cpu_state: dict = {}

    def set_bytes(self, linear_address: int, data: bytes) -> None:
        self.memory[linear_address : linear_address + len(data)] = data

    def mark_unreadable(self, linear_address: int, length: int) -> None:
        self.unreadable_ranges.append((linear_address, linear_address + length))

    def read_memory(self, address: str, length: int) -> dict:
        seg_str, off_str = address.split(":")
        linear = int(seg_str, 16) * 16 + int(off_str, 16)
        for start, end in self.unreadable_ranges:
            if linear < end and linear + length > start:
                raise DOSBoxMemoryError(f"unmapped guest memory at {address}")
        chunk = bytes(self.memory[linear : linear + length])
        return {"address": address, "length": length, "bytes": [f"{b:02X}" for b in chunk]}

    def get_cpu_state(self) -> dict:
        return self.cpu_state


class CfgStubClient:
    """A minimal stand-in for DOSBoxClient's code.disassemble surface,
    modeling one or more disjoint, physically-contiguous runs of "guest
    memory" bytes. `program` maps a linear start address to (bytes_hex,
    instruction_text); each successive linear address is derived from the
    previous entry's own length, exactly like a real disassemble() call
    decoding sequential bytes -- not a lookup keyed by "block address".
    Returned instructions are labeled using the QUERY's own segment with
    an incrementing offset, matching the real native bridge's documented
    behavior (code.disassemble mirrors debug.cpp's getcodetext() walking
    pattern: one fixed segment, advancing offset)."""

    def __init__(self, program: dict):
        self.program = dict(program)

    def disassemble(self, address: str, count: int) -> list:
        seg_str, off_str = address.split(":")
        segment = int(seg_str, 16)
        offset = int(off_str, 16)
        linear = segment * 16 + offset
        results = []
        for _ in range(count):
            if linear not in self.program:
                break
            bytes_hex, text = self.program[linear]
            results.append({"address": f"{segment:04X}:{offset:04X}", "bytes": bytes_hex, "instruction": text})
            length = len(bytes_hex.split())
            linear += length
            offset += length
        return results


def test_exact_pattern_within_one_segment():
    client = StubClient(0x10000)
    client.set_bytes(0x0100, bytes.fromhex("B8341200"))
    result = search_memory(client, "0000:0000", 0x10000, pattern=["B8", "34", "12"])
    # linear 0x0100 canonicalizes to (0x0100 >> 4, 0x0100 & 0xF) == (0x0010, 0x0000)
    assert result["matches"] == ["0010:0000"]
    assert result["scanned_bytes"] == 0x10000
    assert result["unreadable_regions"] == []
    assert result["truncated"] is False


def test_wildcard_pattern():
    client = StubClient(0x10000)
    client.set_bytes(0x0200, bytes.fromhex("B8FF1200"))
    result = search_memory(client, "0000:0000", 0x10000, pattern=["B8", "??", "12"])
    assert result["matches"] == ["0020:0000"]


def test_text_search_case_insensitive():
    client = StubClient(0x10000)
    client.set_bytes(0x0300, b"Hello, World!")
    result = search_memory(client, "0000:0000", 0x10000, text="hello", case_sensitive=False)
    assert result["matches"] == ["0030:0000"]

    result_cs = search_memory(client, "0000:0000", 0x10000, text="hello", case_sensitive=True)
    assert result_cs["matches"] == []


def test_match_spanning_a_segment_boundary():
    client = StubClient(0x20000)
    # Place "DEADBEEF" straddling the 0000:FFFF / 1000:0000 boundary --
    # linear 0xFFFE..0x10001.
    client.set_bytes(0xFFFE, bytes.fromhex("DEADBEEF"))
    result = search_memory(client, "0000:0000", 0x20000, pattern=["DE", "AD", "BE", "EF"])
    # linear 0xFFFE -> canonical (0xFFFE >> 4, 0xFFFE & 0xF) == (0x0FFF, 0x000E)
    assert result["matches"] == ["0FFF:000E"]
    assert result["scanned_bytes"] == 0x20000


def test_unreadable_region_is_skipped_not_fabricated():
    client = StubClient(0x20000)
    client.set_bytes(0x0100, bytes.fromhex("AABBCC"))
    client.mark_unreadable(0x10000, 0x10000)  # the entire second segment
    result = search_memory(client, "0000:0000", 0x20000, pattern=["AA", "BB", "CC"])
    assert result["matches"] == ["0010:0000"]
    assert result["unreadable_regions"] == [{"address": "1000:0000", "length": 0x10000}]
    assert result["scanned_bytes"] == 0x20000


def test_max_matches_truncates():
    client = StubClient(0x10000)
    for i in range(10):
        client.set_bytes(0x1000 + i * 0x100, bytes.fromhex("90"))
    result = search_memory(client, "0000:0000", 0x10000, pattern=["90"], max_matches=3)
    assert len(result["matches"]) == 3
    assert result["truncated"] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"pattern": ["90"], "text": "x"},
    ],
)
def test_exactly_one_of_pattern_or_text_required(kwargs):
    client = StubClient(0x100)
    with pytest.raises(ValueError):
        search_memory(client, "0000:0000", 0x100, **kwargs)


def test_invalid_pattern_element_type_raises():
    client = StubClient(0x100)
    with pytest.raises(TypeError):
        search_memory(client, "0000:0000", 0x100, pattern=[object()])


def test_length_must_be_positive():
    client = StubClient(0x100)
    with pytest.raises(ValueError):
        search_memory(client, "0000:0000", 0, pattern=["90"])


def test_length_cap_enforced():
    client = StubClient(0x100)
    with pytest.raises(ValueError):
        search_memory(client, "0000:0000", 0x100001, pattern=["90"])


# -- get_call_stack --


def test_get_call_stack_walks_two_frames():
    client = StubClient(0x30000)
    client.cpu_state = {"cs": "1234", "ss": "2000", "ebp": "00000100"}
    # frame 1 at SS:0100 -- saved BP 0120 (a genuine parent, > 0100), return offset 0050
    client.set_bytes(0x20000 + 0x0100, bytes.fromhex("2001") + bytes.fromhex("5000"))
    # frame 2 at SS:0120 -- saved BP 0000 (chain end), return offset 0060
    client.set_bytes(0x20000 + 0x0120, bytes.fromhex("0000") + bytes.fromhex("6000"))
    result = get_call_stack(client)
    assert result["frames"] == [
        {"bp": "2000:0100", "return_address": "1234:0050"},
        {"bp": "2000:0120", "return_address": "1234:0060"},
    ]
    assert result["truncated"] is False


def test_get_call_stack_zero_bp_is_empty():
    client = StubClient(0x30000)
    client.cpu_state = {"cs": "1234", "ss": "2000", "ebp": "00000000"}
    result = get_call_stack(client)
    assert result == {"frames": [], "truncated": False}


def test_get_call_stack_truncates():
    client = StubClient(0x30000)
    client.cpu_state = {"cs": "1234", "ss": "2000", "ebp": "00000100"}
    # a long, strictly-increasing BP chain
    for bp, next_bp in [(0x0100, 0x0120), (0x0120, 0x0140), (0x0140, 0x0160)]:
        client.set_bytes(0x20000 + bp, next_bp.to_bytes(2, "little") + b"\x00\x00")
    result = get_call_stack(client, max_frames=2)
    assert len(result["frames"]) == 2
    assert result["truncated"] is True


def test_get_call_stack_stops_on_unreadable_stack():
    client = StubClient(0x30000)
    client.cpu_state = {"cs": "1234", "ss": "2000", "ebp": "00000100"}
    client.mark_unreadable(0x20000 + 0x0100, 4)
    result = get_call_stack(client)
    assert result == {"frames": [], "truncated": False}


def test_get_call_stack_invalid_max_frames():
    client = StubClient(0x30000)
    client.cpu_state = {"cs": "1234", "ss": "2000", "ebp": "00000000"}
    with pytest.raises(ValueError):
        get_call_stack(client, max_frames=0)


# -- build_control_flow_graph --

_BRANCH_PROGRAM = {
    0x12440: ("B8 34 12", "mov ax,1234h"),
    0x12443: ("74 03", "jz 00000200"),
    0x12445: ("C3", "ret"),
    0x12640: ("B9 11 11", "mov cx,1111h"),
    0x12643: ("C3", "ret"),
}


def test_cfg_conditional_branch_produces_three_blocks():
    client = CfgStubClient(_BRANCH_PROGRAM)
    result = build_control_flow_graph(client, "1234:0100")

    assert set(result["blocks"].keys()) == {"1244:0000", "1244:0005", "1264:0000"}
    assert result["truncated"] is False

    entry = result["blocks"]["1244:0000"]
    assert [i["instruction"] for i in entry["instructions"]] == ["mov ax,1234h", "jz 00000200"]
    assert set(entry["successors"]) == {"1264:0000", "1244:0005"}
    assert entry["unresolved_transfer"] is None

    fallthrough_block = result["blocks"]["1244:0005"]
    assert [i["instruction"] for i in fallthrough_block["instructions"]] == ["ret"]
    assert fallthrough_block["successors"] == []
    assert fallthrough_block["unresolved_transfer"] == "return"

    target_block = result["blocks"]["1264:0000"]
    assert [i["instruction"] for i in target_block["instructions"]] == ["mov cx,1111h", "ret"]
    assert target_block["successors"] == []
    assert target_block["unresolved_transfer"] == "return"


def test_cfg_unconditional_jmp_has_no_fallthrough():
    program = {0x20000: ("EB 02", "jmp 00000010"), 0x20010: ("C3", "ret")}
    client = CfgStubClient(program)
    result = build_control_flow_graph(client, "2000:0000")

    assert set(result["blocks"].keys()) == {"2000:0000", "2001:0000"}
    entry = result["blocks"]["2000:0000"]
    assert entry["successors"] == ["2001:0000"]
    assert entry["unresolved_transfer"] is None


def test_cfg_indirect_call_is_unresolved():
    program = {0x30000: ("FF D3", "call bx")}
    client = CfgStubClient(program)
    result = build_control_flow_graph(client, "3000:0000")

    block = result["blocks"]["3000:0000"]
    assert block["successors"] == []
    assert block["unresolved_transfer"] == "indirect_or_far_transfer"


def test_cfg_software_interrupt_is_unresolved():
    program = {0x40000: ("CD 21", "int 21h")}
    client = CfgStubClient(program)
    result = build_control_flow_graph(client, "4000:0000")

    block = result["blocks"]["4000:0000"]
    assert block["successors"] == []
    assert block["unresolved_transfer"] == "software_interrupt"


def test_cfg_max_blocks_truncates():
    program = {
        0x50000: ("EB 02", "jmp 00000010"),
        0x50010: ("EB 02", "jmp 00000010"),
        0x50020: ("C3", "ret"),
    }
    client = CfgStubClient(program)
    result = build_control_flow_graph(client, "5000:0000", max_blocks=2)

    assert set(result["blocks"].keys()) == {"5000:0000", "5001:0000"}
    assert result["truncated"] is True


def test_cfg_invalid_max_blocks():
    client = CfgStubClient({})
    with pytest.raises(ValueError):
        build_control_flow_graph(client, "1234:0000", max_blocks=0)


def test_cfg_invalid_max_instructions_per_block():
    client = CfgStubClient({})
    with pytest.raises(ValueError):
        build_control_flow_graph(client, "1234:0000", max_instructions_per_block=0)

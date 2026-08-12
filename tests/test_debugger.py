import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

import pytest

from debugger import FakeDOSBoxDebugger
from protocol import DebuggerError


@pytest.fixture
def dbg():
    return FakeDOSBoxDebugger()


def test_initial_cpu_state(dbg):
    state = dbg.get_cpu_state()
    assert state["cs"] == "1234"
    assert state["eip"] == "0100"
    assert state["eax"] == "00000000"
    assert state["esp"] == "0000FF00"


def test_initial_debug_status(dbg):
    status = dbg.get_debug_status()
    assert status["stopped"] is True
    assert status["running"] is False
    assert status["location"] == {"cs": "1234", "eip": "0100"}
    assert status["instruction"]["text"] == "MOV AX,1234h"
    assert status["registers"]["eax"] == "00000000"
    assert status["segments"]["ss"] == "3000"
    assert "eflags" in status["flags"]


def test_instruction_retrieval(dbg):
    instr = dbg.get_current_instruction()
    assert instr["address"] == "1234:0100"
    assert instr["bytes"] == "B8 34 12"
    assert instr["instruction"] == "MOV AX,1234h"


def test_memory_read(dbg):
    result = dbg.read_memory("1234:0100", 3)
    assert result["address"] == "1234:0100"
    assert result["length"] == 3
    assert result["bytes"] == ["B8", "34", "12"]


def test_memory_write_read_round_trip(dbg):
    dbg.write_memory("2000:0000", ["DE", "AD", "BE", "EF"])
    result = dbg.read_memory("2000:0000", 4)
    assert result["bytes"] == ["DE", "AD", "BE", "EF"]


def test_memory_read_invalid_address_raises(dbg):
    with pytest.raises(DebuggerError):
        dbg.read_memory("bogus", 4)


def test_step_into_changes_eip(dbg):
    before = dbg.get_debug_status()
    assert before["location"]["eip"] == "0100"

    after = dbg.step_into()
    assert after["location"]["eip"] == "0103"
    assert after["registers"]["eax"] == "00001234"


def test_step_into_sequence_executes_program(dbg):
    dbg.step_into()  # MOV AX,1234h
    dbg.step_into()  # MOV BX,5678h
    status = dbg.step_into()  # ADD AX,BX
    assert status["registers"]["eax"] == "000068AC"
    assert status["registers"]["ebx"] == "00005678"


def test_breakpoint_creation(dbg):
    bp = dbg.set_breakpoint("1234:0103")
    assert bp["address"] == "1234:0103"
    assert bp["enabled"] is True
    assert isinstance(bp["id"], int)


def test_breakpoint_deletion(dbg):
    bp = dbg.set_breakpoint("1234:0103")
    result = dbg.delete_breakpoint(bp["id"])
    assert result["deleted"] is True
    assert dbg.list_breakpoints() == []


def test_breakpoint_deletion_missing_raises(dbg):
    with pytest.raises(DebuggerError):
        dbg.delete_breakpoint(999)


def test_breakpoint_listing(dbg):
    dbg.set_breakpoint("1234:0103")
    dbg.set_breakpoint("1234:0105")
    breakpoints = dbg.list_breakpoints()
    assert [bp["address"] for bp in breakpoints] == ["1234:0103", "1234:0105"]


def test_continue_execution_stops_at_breakpoint(dbg):
    dbg.set_breakpoint("1234:0103")
    status = dbg.continue_execution()
    assert status["location"]["eip"] == "0103"
    assert status["stopped"] is True
    assert status["running"] is False


def test_continue_execution_halts_at_program_end(dbg):
    status = dbg.continue_execution()
    assert dbg.halted is True
    assert status["stopped"] is True


def test_pause_execution(dbg):
    status = dbg.pause_execution()
    assert status["stopped"] is True
    assert status["running"] is False


def test_disassembly(dbg):
    listing = dbg.disassemble("1234:0100", 5)
    assert len(listing) == 5
    assert listing[0] == {"address": "1234:0100", "bytes": "B8 34 12", "instruction": "MOV AX,1234h"}
    assert listing[1]["instruction"] == "MOV BX,5678h"
    assert listing[2]["instruction"] == "ADD AX,BX"
    assert listing[3]["instruction"] == "MOV AH,4Ch"
    assert listing[4]["instruction"] == "INT 21h"


def test_disassemble_does_not_mutate_state(dbg):
    dbg.disassemble("1234:0100", 5)
    status = dbg.get_debug_status()
    assert status["location"]["eip"] == "0100"
    assert status["registers"]["eax"] == "00000000"

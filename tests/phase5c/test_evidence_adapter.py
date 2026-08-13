"""
Phase 5C evidence-adapter deterministic tests (ai/Phase5C4.md Part 1).

Covers tests/phase5c/evidence.py's union-schema result projection in
isolation -- no live DOSBox-X, no agent, synthetic evidence.jsonl files
only. Also proves, via the FROZEN tests/phase5b/grading.py primitives
(imported, never modified or copied), that:

  * a get_cpu_state-shaped result becomes visible to
    grade_b1_register_trace()'s _real_states() helper after the fix
    (previously invisible entirely);
  * the projection never fabricates "stopped" -- a trace containing ONLY a
    get_cpu_state observation still correctly fails the frozen grader's
    stopped check, because that evidence genuinely doesn't exist in
    get_cpu_state's raw result;
  * a trace combining a get_cpu_state observation with a get_debug_status
    confirmation at the same real location passes, since the genuine
    "stopped" evidence is then actually present in the trace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.phase5b.grading import grade_b1_register_trace
from tests.phase5c import evidence as ev


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


# -- shape recognition -----------------------------------------------------


def test_debug_status_shape_recognized_and_left_unchanged():
    result = {
        "stopped": True,
        "running": False,
        "location": {"cs": "0816", "eip": "0120"},
        "instruction": {"bytes": "CD 21", "text": "int  21"},
        "registers": {"eax": "00004C11"},
    }
    assert ev._is_debug_status_shape(result) is True
    assert ev._is_cpu_state_shape(result) is False
    assert ev._canonical_result(result) is result  # identity, not a copy


def test_cpu_state_shape_recognized_and_projected():
    result = {
        "eax": "00004C11", "ebx": "00002222", "ecx": "00003333", "edx": "00004444",
        "esi": "00005555", "edi": "00006666", "ebp": "0000091C", "esp": "0000FFFE",
        "cs": "0816", "ds": "0816", "es": "0816", "ss": "0816", "fs": "0000", "gs": "0000",
        "eip": "0120", "eflags": "00007246",
    }
    assert ev._is_debug_status_shape(result) is False
    assert ev._is_cpu_state_shape(result) is True

    projected = ev._project_cpu_state_shape(result)
    assert projected["location"] == {"cs": "0816", "eip": "0120"}
    assert projected["registers"] == {
        "eax": "00004C11", "ebx": "00002222", "ecx": "00003333", "edx": "00004444",
        "esi": "00005555", "edi": "00006666", "ebp": "0000091C", "esp": "0000FFFE",
    }
    assert projected["segments"] == {"cs": "0816", "ds": "0816", "es": "0816", "ss": "0816", "fs": "0000", "gs": "0000"}
    assert projected["flags"] == {"eflags": "00007246"}
    # Never fabricated: get_cpu_state's raw result has no such fields.
    assert "stopped" not in projected
    assert "running" not in projected
    assert "instruction" not in projected


# -- malformed / incomplete results: must pass through unchanged, never raise --


@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        [{"address": "0816:0100", "bytes": "B8 11 11", "instruction": "mov  ax,1111"}],  # disassemble's list shape
        {"ok": False, "error": {"code": "DEBUGGER_NOT_STOPPED", "message": "..."}},  # native error envelope
        {},
        {"eip": "0120"},  # cs/registers missing -- not enough to be cpu_state-shaped
        {"eip": "0120", "cs": "0816"},  # still missing all register keys
        {"eip": "0120", "cs": "0816", "eax": "00000000"},  # only one register present, not all 8
        "not even a dict",
        42,
    ],
)
def test_malformed_or_incomplete_results_pass_through_unchanged(result):
    assert ev._canonical_result(result) is result or ev._canonical_result(result) == result
    assert ev._is_cpu_state_shape(result) is False


def test_incomplete_cpu_state_missing_one_register_key_not_recognized():
    almost = {
        "eax": "0", "ebx": "0", "ecx": "0", "edx": "0", "esi": "0", "edi": "0", "ebp": "0",
        # "esp" deliberately missing
        "cs": "0816", "eip": "0120",
    }
    assert ev._is_cpu_state_shape(almost) is False
    assert ev._canonical_result(almost) == almost


# -- load_call_records(): provenance preserved, tool never renamed/fabricated --


def test_load_call_records_preserves_tool_and_args_verbatim(tmp_path: Path):
    log = tmp_path / "evidence.jsonl"
    _write_jsonl(
        log,
        [
            {
                "seq": 0, "tool": "get_cpu_state", "args": {}, "forwarded": True,
                "result": {
                    "eax": "00004C11", "ebx": "00002222", "ecx": "00003333", "edx": "00004444",
                    "esi": "00005555", "edi": "00006666", "ebp": "0000091C", "esp": "0000FFFE",
                    "cs": "0816", "eip": "0120", "eflags": "00007246",
                },
            },
            {"event": "session_finalized", "termination": "SUCCESS", "session_totals": {}},
        ],
    )
    records = ev.load_call_records(log)
    assert len(records) == 1  # the session_finalized line is skipped
    assert records[0]["tool"] == "get_cpu_state"  # never renamed to get_debug_status
    assert records[0]["args"] == {}
    assert records[0]["forwarded"] is True
    assert records[0]["result"]["location"] == {"cs": "0816", "eip": "0120"}

    # Provenance: the raw, unprojected line is still fully recoverable from
    # load_evidence_lines() / the untouched JSONL file itself.
    raw_lines = ev.load_evidence_lines(log)
    assert raw_lines[0]["tool"] == "get_cpu_state"
    assert raw_lines[0]["result"]["eax"] == "00004C11"
    assert "location" not in raw_lines[0]["result"]  # raw file genuinely untouched


# -- integration with the FROZEN grade_b1_register_trace -------------------

_EXPECTED_REGISTERS = {
    "eax": "00004C11", "ebx": "00002222", "ecx": "00003333",
    "edx": "00004444", "esi": "00005555", "edi": "00006666",
}
_INT21_EIP = "0120"


def test_grade_b1_cpu_state_only_trace_fails_on_exactly_the_stopped_check(tmp_path: Path):
    """This is the exact shape of the preserved Campaign 6 C4-B1 trace:
    one get_debug_status (initial position) followed by one get_cpu_state
    (the agent's final observation, after breakpoint+continue). Before
    this fix, _real_states() saw only the FIRST entry (get_cpu_state was
    invisible), so the grader wrongly reported "no real forward
    progression" and a wrong final position. After this fix, the
    progression check, the final-position check, AND the register-value
    check all correctly PASS (the projection carries real location and
    real registers) -- grade_b1_register_trace's SOLE remaining failure is
    the stopped check, which is correct and NOT fabricated: get_cpu_state's
    raw result genuinely never reports "stopped", so this is accurate
    absence of evidence, not a residual bug."""

    log = tmp_path / "evidence.jsonl"
    _write_jsonl(
        log,
        [
            {"seq": 0, "tool": "get_debug_status", "args": {}, "forwarded": True,
             "result": {"stopped": True, "running": False, "location": {"cs": "0816", "eip": "010C"}}},
            {"seq": 1, "tool": "get_cpu_state", "args": {}, "forwarded": True,
             "result": {
                 "eax": "00004C11", "ebx": "00002222", "ecx": "00003333", "edx": "00004444",
                 "esi": "00005555", "edi": "00006666", "ebp": "0000091C", "esp": "0000FFFE",
                 "cs": "0816", "eip": "0120", "eflags": "00007246",
             }},
        ],
    )
    records = ev.load_call_records(log)
    result = grade_b1_register_trace(records, _EXPECTED_REGISTERS, _INT21_EIP)
    assert result.passed is False
    # Exactly one reason -- not the old, misleading "no real forward
    # progression" / wrong-position / register-mismatch reasons.
    assert result.reasons == ["debugger is not stopped in the final observed real state"], result.reasons


def test_grade_b1_final_call_is_get_debug_status_unaffected_by_the_fix(tmp_path: Path):
    """Sanity check that the fix changes nothing for the ALREADY-working
    case: when the agent's final call is get_debug_status itself (which
    natively carries location + stopped + registers together), the trace
    passes exactly as it always did -- the union-schema projection is
    never invoked for a get_debug_status-shaped result."""

    log = tmp_path / "evidence.jsonl"
    _write_jsonl(
        log,
        [
            {"seq": 0, "tool": "get_debug_status", "args": {}, "forwarded": True,
             "result": {"stopped": True, "running": False, "location": {"cs": "0816", "eip": "010C"}}},
            {"seq": 1, "tool": "get_cpu_state", "args": {}, "forwarded": True,
             "result": {
                 "eax": "00004C11", "ebx": "00002222", "ecx": "00003333", "edx": "00004444",
                 "esi": "00005555", "edi": "00006666", "ebp": "0000091C", "esp": "0000FFFE",
                 "cs": "0816", "eip": "0115", "eflags": "00007246",
             }},
            {"seq": 2, "tool": "get_debug_status", "args": {}, "forwarded": True,
             "result": {
                 "stopped": True, "running": False, "location": {"cs": "0816", "eip": "0120"},
                 "registers": _EXPECTED_REGISTERS,
             }},
        ],
    )
    records = ev.load_call_records(log)
    result = grade_b1_register_trace(records, _EXPECTED_REGISTERS, _INT21_EIP)
    assert result.passed is True, result.reasons

"""
Phase 5C evidence-log reading utilities
(docs/phase5c-real-mcp-transport-design.md sections 5 and 6.3).

Reads the JSONL evidence log ai/server_phase5c.py writes -- one line per
attempted call, forwarded or rejected -- and, for grading, projects it
down to the exact CallRecord shape (`tool`/`args`/`forwarded`/`result`)
tests/phase5b/grading.py's B1-B4 graders already expect. This is the same
adapter role tests/phase5b/grading.py::to_phase5a_shape() already plays
one layer down (BoundedSession.CallRecord -> Phase 5A call-log shape);
this file plays the equivalent role one layer up (evidence JSONL ->
CallRecord shape), so the frozen B1-B4 graders can be called directly and
unmodified, per ai/Phase5C3.md requirement 6 ("Do not reuse a CLI
state-file mechanism ... add a Phase 5C adapter ... while preserving the
same grading semantics"). No new grading logic lives in this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_evidence_lines(evidence_log_path: Path) -> list[dict[str, Any]]:
    """Every line of a Phase 5C evidence JSONL file, parsed, in order --
    the full correlation record (seq / mcp_request_id / resolver counts /
    session_totals / termination / timestamp), not merely the
    CallRecord-shaped projection load_call_records() returns below."""

    path = Path(evidence_log_path)
    if not path.exists():
        return []
    lines: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))
    return lines


def _is_debug_status_shape(result: Any) -> bool:
    """get_debug_status's raw shape (ai/server.py / dosbox-src's
    debug.status): a dict with a NESTED `"location": {"cs", "eip"}`."""

    return isinstance(result, dict) and isinstance(result.get("location"), dict)


_CPU_STATE_REGISTER_KEYS = frozenset({"eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"})
_CPU_STATE_SEGMENT_KEYS = frozenset({"cs", "ds", "es", "ss", "fs", "gs"})


def _is_cpu_state_shape(result: Any) -> bool:
    """get_cpu_state's raw native-bridge shape
    (dosbox-src/src/debug/debug_ai.cpp::ExecCpuGet, verified by reading
    that function directly): a FLAT dict -- eax..esp / cs..gs / eip /
    eflags all at the top level, no nested "location" or "registers" key.
    ExecCpuGet has NO running/stopped precondition and reports live
    register values unconditionally (unlike, e.g., a step/continue call) --
    it never returns a "stopped"/"running" field in any form. This
    function only recognizes the shape; it does not (and, per that
    architectural fact, safely cannot) infer a "stopped" value for it."""

    if not isinstance(result, dict) or _is_debug_status_shape(result):
        return False
    return "eip" in result and "cs" in result and _CPU_STATE_REGISTER_KEYS.issubset(result.keys())


def _project_cpu_state_shape(result: dict) -> dict:
    """Lossless union-schema projection: re-exposes get_cpu_state's real,
    flat location/register evidence in the SAME nested shape
    tests/phase5b/grading.py's _real_states()/grade_b1_register_trace()
    (frozen, unmodified, never copied) already read from a get_debug_status
    result -- without inventing any field get_cpu_state's raw result does
    not actually contain. In particular this deliberately does NOT add a
    "stopped" or "instruction" key: get_cpu_state never reports either
    (see _is_cpu_state_shape's docstring), so
    `final.get("stopped", False)` in the frozen grader correctly still
    evaluates False for a state sourced ONLY from get_cpu_state -- that is
    accurate absence of evidence, not a gap this projection papers over."""

    projected: dict[str, Any] = {
        "location": {"cs": result["cs"], "eip": result["eip"]},
        "registers": {k: v for k, v in result.items() if k in _CPU_STATE_REGISTER_KEYS},
    }
    segments = {k: v for k, v in result.items() if k in _CPU_STATE_SEGMENT_KEYS}
    if segments:
        projected["segments"] = segments
    if "eflags" in result:
        projected["flags"] = {"eflags": result["eflags"]}
    return projected


def _canonical_result(result: Any) -> Any:
    """Union-schema entry point (ai/Phase5C4.md Part 1). Returns `result`
    completely unchanged unless it matches a specifically-recognized
    alternate real shape (currently: get_cpu_state's flat register dict) --
    malformed dicts, lists (e.g. disassemble's result), error envelopes,
    dicts missing expected keys, and the already-recognized
    get_debug_status shape all pass through verbatim. Never raises, never
    guesses: a shape not positively identified is left alone."""

    if _is_cpu_state_shape(result):
        return _project_cpu_state_shape(result)
    return result


def load_call_records(evidence_log_path: Path) -> list[dict[str, Any]]:
    """Projects the evidence log down to exactly the
    tests/phase5b/bounded_agent_cli.CallRecord shape (`tool`/`args`/
    `forwarded`/`result`) -- pass this list directly to
    tests.phase5b.grading.grade_b1_register_trace() etc., unmodified.
    Skips the one non-call line ai/server_phase5c.py's
    _finalize_session_on_exit() appends (`"event": "session_finalized"`,
    no `"tool"` key) -- that line is for latest_session_evidence() below,
    not a call record.

    `tool`/`args` are preserved EXACTLY as recorded (never renamed or
    fabricated -- a `get_cpu_state` call is never turned into a
    `get_debug_status` call the agent did not make; the tool name stays
    the provenance pointer back to the original raw JSONL line, which
    load_evidence_lines() above still returns completely untouched).
    `result` is passed through _canonical_result()'s union-schema
    normalization -- the ONLY field this adapter ever transforms, and
    only for specifically-recognized alternate real shapes."""

    return [
        {
            "tool": line["tool"],
            "args": line.get("args", {}),
            "forwarded": line["forwarded"],
            "result": _canonical_result(line.get("result")),
        }
        for line in load_evidence_lines(evidence_log_path)
        if "tool" in line
    ]


def latest_session_evidence(evidence_log_path: Path) -> dict[str, Any]:
    """The BoundedSession.evidence()-shaped dict (termination,
    attempted/forwarded counts, execution_step_calls, etc.) as of the
    LAST recorded line -- for graders (e.g. B5-style budget-enforcement
    grading) that take BoundedSession.evidence()'s own dict shape rather
    than a call_log. Returns an all-None/zero shape if the log is empty."""

    lines = load_evidence_lines(evidence_log_path)
    if not lines:
        return {
            "termination": None,
            "total_calls_attempted": 0,
            "total_calls_forwarded": 0,
            "execution_step_calls": 0,
        }
    last = lines[-1]
    totals = last.get("session_totals", {})
    return {
        "termination": last.get("termination"),
        "total_calls_attempted": totals.get("total_calls_attempted", 0),
        "total_calls_forwarded": totals.get("total_calls_forwarded", 0),
        "execution_step_calls": totals.get("execution_step_calls", 0),
    }

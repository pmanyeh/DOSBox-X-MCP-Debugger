"""
Phase 5C agent-facing bounded MCP entry point
(docs/phase5c-real-mcp-transport-design.md).

The real, production-facing MCP server a fresh Phase 5C agent connects to
over stdio -- registers real @mcp.tool() functions, exactly like
ai/server.py and ai/server_phase5a.py already do (this module follows the
same "ai/ holds what a real MCP client actually spawns" precedent, see
design doc section 3). What's new here is that every tool body routes
through BoundedSession (imported UNMODIFIED from
tests/phase5b/bounded_agent_cli.py -- not copied, not forked) before ever
reaching the real tool, and every attempted call (forwarded or rejected)
is appended to an evidence JSONL log for external, out-of-process
correlation (design doc section 5).

One process = one bounded session: BudgetConfig/allowed-tools/evidence-log
are supplied once, as this process's own startup CLI arguments, and only
tools inside the configured allowed-tools set are registered at all (so an
excluded tool is invisible in tools/list, not merely rejected after being
requested -- defense in depth on top of BoundedSession's own policy
check). There is therefore no cross-process state file: BoundedSession is
constructed once per process and lives in memory for the whole stdio
session, unlike tests/phase5b/bounded_agent_cli.py's CLI shim (frozen,
unmodified, unused by this file), which had to reconstruct BoundedSession
from a JSON --state file on every invocation because IT was re-invoked as
a brand-new process per tool call.

Reuses, never modifies or duplicates:
  * BoundedSession / BudgetConfig / Termination / _real_tool_resolver()
    (tests/phase5b/bounded_agent_cli.py)
  * tests/phase5a/agent_cli.py's TOOL_DESCRIPTIONS (tool docstrings) and
    _registered_tools() (via _real_tool_resolver(), transitively)
  * ai/server_phase5a.py / ai/server.py's real tool implementations and
    DOSBoxClient/native-bridge connection (transitively, via the resolver)

Does not implement, and does not need to modify, anything under
tests/phase5a/, tests/phase5b/, or dosbox-src/.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from mcp.server.mcpserver import Context, MCPServer

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tests.phase5b.bounded_agent_cli import (  # noqa: E402 -- reuse only, not modified
    BoundedSession,
    BudgetConfig,
    Termination,
    _real_tool_resolver,
)

mcp = MCPServer("DOSBox-X AI Debugger (Phase 5C -- bounded, real MCP transport)")

_session: Optional[BoundedSession] = None
_resolver: Optional["_CountingResolver"] = None
_evidence_path: Optional[Path] = None


class _CountingResolver:
    """Wraps the real production resolver -- observes/counts invocations
    only, delegates every call unchanged. Same non-invasive counting
    pattern tests/phase5b/test_bounded_agent_cli_real_dosbox.py's
    CountingResolver already uses and the B5-E audit already validated
    (docs/phase5b-b5e-enforcement-audit.md section 5) -- duplicated here
    (not imported) only because that class lives in a test module this
    production file must not depend on; the technique, not any Phase 5A
    tool logic, is what's reused."""

    def __init__(self, real_resolver: Callable[[str, dict], Any]):
        self._real = real_resolver
        self.call_count = 0

    def __call__(self, name: str, args: dict) -> Any:
        self.call_count += 1
        return self._real(name, args)


# -- error-domain / terminal / retryable classification -----------------
#
# BoundedSession's own rejection responses (tests/phase5b/bounded_agent_cli.py,
# frozen) carry only {"code", "message"} -- this file adds "domain",
# "terminal", and "retryable" on top, for every error response this server
# returns, without altering BoundedSession itself. "terminal" means this
# session will reject every subsequent call regardless of tool/args;
# "retryable" means re-issuing the identical call, unmodified, could
# plausibly succeed later without the client changing anything.

_BOUNDED_SESSION_TERMINAL_CODES = frozenset(
    {
        Termination.POLICY_VIOLATION.value,
        Termination.BUDGET_EXHAUSTED.value,
        Termination.TIMEOUT_EXCEEDED.value,
    }
)
_RETRYABLE_DOSBOX_CODES = frozenset({"EXECUTION_TIMEOUT", "DOSBOX_NOT_CONNECTED", "DOSBOX_TIMEOUT", "DOSBOX_PROTOCOL_ERROR"})
_TRANSPORT_CODES = frozenset({"UNKNOWN_TOOL", "INVALID_ARGS_JSON", "INVALID_ADDRESS"})


def _classify_error(code: Optional[str]) -> dict:
    if code in _BOUNDED_SESSION_TERMINAL_CODES:
        return {"domain": "bounded_session", "terminal": True, "retryable": False}
    if code in _TRANSPORT_CODES:
        return {"domain": "transport", "terminal": False, "retryable": False}
    if code in _RETRYABLE_DOSBOX_CODES:
        return {"domain": "dosbox_native", "terminal": False, "retryable": True}
    # Every other native-bridge refusal (DEBUGGER_NOT_STOPPED, MEMORY_ERROR,
    # REGISTER_NOT_WRITABLE, BREAKPOINT_NOT_FOUND, BREAKPOINT_ALREADY_EXISTS,
    # ALREADY_RUNNING, ALREADY_STOPPED, and any native code without a more
    # specific bucket): reached real DOSBox-X and was refused for a
    # state/argument reason -- not terminal to the session, not
    # automatically retryable without the client changing something.
    return {"domain": "dosbox_native", "terminal": False, "retryable": False}


def _augment_error(result: Any, was_already_terminated: bool) -> Any:
    """Adds domain/terminal/retryable to an error envelope. Leaves success
    results (no "ok": False envelope) completely untouched -- this
    preserves exact response-shape parity with the frozen CLI-shim path
    for every non-error call, which is what Phase 5C's C2 (transport
    equivalence) claim depends on."""

    if not (isinstance(result, dict) and result.get("ok") is False and isinstance(result.get("error"), dict)):
        return result

    error = dict(result["error"])
    code = error.get("code")

    if was_already_terminated:
        # This call arrived AFTER the session had already terminated --
        # distinct from the call that CAUSED the termination, so a client
        # can tell the two apart. BoundedSession itself reuses the original
        # termination's own code for both cases (bounded_agent_cli.py:191-197,
        # frozen); this presentation-layer relabeling happens only here, in
        # the new file, and never touches BoundedSession.
        error["underlying_termination_code"] = code
        error["code"] = "SESSION_ALREADY_TERMINATED"
        error.update({"domain": "bounded_session", "terminal": True, "retryable": False})
    else:
        error.update(_classify_error(code))

    return {**result, "error": error}


def _write_evidence_line(seq: int, ctx: Context, record: Any, resolver_before: int, resolver_after: int) -> None:
    """Appends one JSON line per attempted call (forwarded or rejected) to
    this process's --evidence-log, from inside the server process, never
    exposed to the agent as a resource or tool (design doc section 5)."""

    assert _session is not None
    line = {
        "seq": seq,
        "mcp_request_id": ctx.request_id,
        "tool": record.tool,
        "args": record.args,
        "forwarded": record.forwarded,
        "resolver_invocations_before": resolver_before,
        "resolver_invocations_after": resolver_after,
        # Not DOSBoxClient's own private, non-peekable _id_counter (frozen,
        # not modifiable/observable without touching ai/dosbox_client.py) --
        # this process's own resolver-invocation ordinal for this call
        # instead, which is 1:1 with a real DOSBoxClient.request() call in
        # this architecture (every Phase 5A tool function calls the native
        # bridge exactly once per invocation) and needs no frozen-file change.
        "resolver_invocation_number": resolver_after if record.forwarded else None,
        "result": record.result,
        "session_totals": {
            "total_calls_attempted": _session.total_calls_attempted,
            "total_calls_forwarded": _session.total_calls_forwarded,
            "execution_step_calls": _session.execution_step_calls,
        },
        "termination": _session.termination.value if _session.termination else None,
        "timestamp": record.timestamp,
    }
    assert _evidence_path is not None
    with _evidence_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def _call(name: str, ctx: Context, kwargs: dict) -> Any:
    assert _session is not None and _resolver is not None
    was_already_terminated = _session.terminated
    seq = len(_session.records)
    resolver_before = _resolver.call_count
    result = _session.call(name, kwargs)
    resolver_after = _resolver.call_count
    record = _session.records[seq]
    _write_evidence_line(seq, ctx, record, resolver_before, resolver_after)
    return _augment_error(result, was_already_terminated)


# -- tool implementations -----------------------------------------------
#
# Same 12-tool inventory as tests/phase5a/agent_cli.py's TOOL_DESCRIPTIONS
# (write_register/write_memory absent for the same reason they're absent
# from ai/server_phase5a.py -- never registered anywhere Phase 5C touches).
# Only tools named in this process's --allowed-tools are actually
# registered on `mcp` (see main()) -- an excluded tool has no entry in
# tools/list at all, not merely a policy rejection after being requested.


def get_debug_status(ctx: Context) -> Any:
    """Return one coherent debugger snapshot: stop state, location, current instruction, registers, segments, and flags. No arguments."""
    return _call("get_debug_status", ctx, {})


def get_cpu_state(ctx: Context) -> Any:
    """Return the current CPU registers and segment state. No arguments.
    This is a register SNAPSHOT only -- it does not report, and its
    success does NOT establish, whether the debugger is stopped or the
    guest CPU is running (verified against the native bridge: this call
    has no running/stopped precondition and can be answered while the
    guest is actively executing). If you need to confirm the debugger is
    genuinely halted at a specific point -- e.g. as the final observation
    before reporting a result -- call get_debug_status() instead, which
    reports stopped/running state together with the same location and
    register data."""
    return _call("get_cpu_state", ctx, {})


def get_current_instruction(ctx: Context) -> Any:
    """Return the instruction at the current CS:EIP. No arguments."""
    return _call("get_current_instruction", ctx, {})


def read_memory(address: str, length: int, ctx: Context) -> Any:
    """Read `length` bytes starting at a "SEG:OFF" address (e.g. "1234:0100")."""
    return _call("read_memory", ctx, {"address": address, "length": length})


def disassemble(address: str, count: int, ctx: Context) -> Any:
    """Disassemble `count` instructions starting at a "SEG:OFF" address."""
    return _call("disassemble", ctx, {"address": address, "count": count})


def set_breakpoint(address: str, ctx: Context) -> Any:
    """Set a breakpoint at a "SEG:OFF" address. Fails with BREAKPOINT_ALREADY_EXISTS if one already exists there."""
    return _call("set_breakpoint", ctx, {"address": address})


def delete_breakpoint(breakpoint_id: int, ctx: Context) -> Any:
    """Delete a breakpoint by its id (as returned by set_breakpoint/list_breakpoints)."""
    return _call("delete_breakpoint", ctx, {"breakpoint_id": breakpoint_id})


def list_breakpoints(ctx: Context) -> Any:
    """List all breakpoints currently set. No arguments."""
    return _call("list_breakpoints", ctx, {})


def continue_execution(ctx: Context) -> Any:
    """Resume real guest CPU execution. Only valid while the debugger is stopped. No arguments."""
    return _call("continue_execution", ctx, {})


def pause_execution(ctx: Context) -> Any:
    """Stop real guest CPU execution. Only valid while guest code is running. No arguments."""
    return _call("pause_execution", ctx, {})


def step_into(ctx: Context) -> Any:
    """Execute exactly one guest instruction, including entering a CALL. Only valid while stopped. No arguments."""
    return _call("step_into", ctx, {})


def step_over(ctx: Context) -> Any:
    """Step over the current instruction -- for a CALL, the subroutine runs to completion. Only valid while stopped. No arguments."""
    return _call("step_over", ctx, {})


_ALL_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "get_debug_status": get_debug_status,
    "get_cpu_state": get_cpu_state,
    "get_current_instruction": get_current_instruction,
    "read_memory": read_memory,
    "disassemble": disassemble,
    "set_breakpoint": set_breakpoint,
    "delete_breakpoint": delete_breakpoint,
    "list_breakpoints": list_breakpoints,
    "continue_execution": continue_execution,
    "pause_execution": pause_execution,
    "step_into": step_into,
    "step_over": step_over,
}


def build_config_from_args(ns: argparse.Namespace) -> BudgetConfig:
    allowed = frozenset(t.strip() for t in ns.allowed_tools.split(",") if t.strip())
    unknown = allowed - set(_ALL_TOOL_FUNCS)
    if unknown:
        raise ValueError(f"--allowed-tools names not registered by this server: {sorted(unknown)}")
    return BudgetConfig(
        total_call_budget=ns.total_budget,
        execution_step_budget=ns.exec_budget,
        deadline_seconds=ns.deadline_seconds,
        allowed_tools=allowed,
    )


def configure(config: BudgetConfig, evidence_log: Path) -> None:
    """Wires one BoundedSession + evidence log into the module-level `mcp`
    server and registers exactly `config.allowed_tools` on it. Split out
    from main() so tests/phase5c/ can build this same server in-process
    (e.g. to introspect tools/list) without going through argv/stdio."""

    global _session, _resolver, _evidence_path

    _resolver = _CountingResolver(_real_tool_resolver())
    _session = BoundedSession(config, _resolver)
    _evidence_path = evidence_log
    _evidence_path.parent.mkdir(parents=True, exist_ok=True)

    for name in sorted(config.allowed_tools):
        mcp.add_tool(_ALL_TOOL_FUNCS[name])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total-budget", type=int, required=True, help="Total tool-call budget")
    parser.add_argument("--exec-budget", type=int, required=True, help="Execution-step budget")
    parser.add_argument("--deadline-seconds", type=float, required=True, help="Wall-clock deadline in seconds")
    parser.add_argument("--allowed-tools", required=True, help="Comma-separated allowed tool names")
    parser.add_argument("--evidence-log", required=True, help="Path to this run's evidence JSONL file")
    ns = parser.parse_args()

    config = build_config_from_args(ns)
    configure(config, Path(ns.evidence_log))

    try:
        mcp.run()  # stdio -- same call ai/server.py / ai/server_phase5a.py already make
    finally:
        _finalize_session_on_exit()
    return 0


def _finalize_session_on_exit() -> None:
    """Equivalent, for this process-per-session architecture, of the CLI-shim
    era's separate orchestrator-only tests/phase5b/finalize_session.py: marks
    the session SUCCESS if -- and only if -- it has not already terminated
    some other way (BUDGET_EXHAUSTED/TIMEOUT_EXCEEDED/POLICY_VIOLATION),
    reusing BoundedSession._finalize()'s own "exactly one termination, never
    silently overwritten" guarantee unmodified -- a no-op if the session
    already terminated on its own. Runs when the stdio connection ends
    (the client disconnected -- ordinary end-of-turn for a process-per-
    session server), appending ONE final, distinctly-shaped evidence line
    (no "tool" key, so tests/phase5c/evidence.py::load_call_records() skips
    it and only tests/phase5c/evidence.py::latest_session_evidence() reads
    it) recording the session's final termination/totals."""

    if _session is None or _evidence_path is None:
        return
    was_already_terminated = _session.terminated
    _session.finish_success()
    if was_already_terminated:
        # A hard termination (BUDGET_EXHAUSTED/TIMEOUT_EXCEEDED/
        # POLICY_VIOLATION) already closed this session via the normal
        # per-call evidence line, which already carries that termination
        # value -- finish_success() above was therefore a guaranteed no-op
        # (BoundedSession._finalize() never overwrites), and appending a
        # second, redundant finalize line here would only add noise.
        return
    line = {
        "event": "session_finalized",
        "termination": _session.termination.value if _session.termination else None,
        "session_totals": {
            "total_calls_attempted": _session.total_calls_attempted,
            "total_calls_forwarded": _session.total_calls_forwarded,
            "execution_step_calls": _session.execution_step_calls,
        },
        "timestamp": time.monotonic(),
    }
    with _evidence_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

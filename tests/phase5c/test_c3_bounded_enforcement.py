"""
Phase 5C -- C3 (incl. C3-E): deterministic real-MCP bounded enforcement
(docs/phase5c-real-mcp-transport-design.md sections 2 and "C3-E").

Answers, one transport layer above tests/phase5b/test_bounded_agent_cli_
real_dosbox.py's B5-E integration test: does the enforcement chain still
forward exactly N execution-step calls and reject the (N+1)th BEFORE it
reaches the real resolver, when those calls arrive as genuine MCP
tools/call requests over a real stdio connection (mcp.client.stdio +
mcp.client.session -- the SDK's own client primitives, the same ones a
real agent host uses), not a fake resolver and not an in-process call?

No LLM -- this is an enforcement-mechanism proof, not an agent-behavior
test (same scoping B5-E itself used, and the same reasoning
docs/phase5b-acceptance-model-review.md section 4 already gives for why
that's sufficient: the enforcement code has no branch that depends on who
issues the (N+1)th call).

Every rejected request is proven, per ai/Phase5C3.md requirement 9, to:
  * reach the real MCP server (the request completes a wire round-trip
    and gets a real, correlated MCP response -- not a timeout/drop);
  * be recorded as attempted (evidence.jsonl line for it exists);
  * leave the forwarded/resolver count unchanged;
  * not invoke DOSBoxClient / not reach the native bridge (via the
    resolver-invocation counter, which is the ONLY thing that ever calls
    DOSBoxClient in this chain -- see ai/server_phase5c.py's
    _CountingResolver and docs/phase5b-b5e-enforcement-audit.md section 3
    for why "resolver not called" implies "native bridge not called" by
    single-call-site construction);
  * not alter real DOSBox-X state (independent post-rejection coherence
    check below, via the unrecorded `verify` path, on a fresh connection
    outside the terminated session).

Requires a live DOSBox-X instance (skipped, not failed, if unreachable).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "ai"))
sys.path.insert(0, str(_ROOT))

import anyio  # noqa: E402
import pytest  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

import server_phase5a as s5a  # noqa: E402 -- unrecorded `verify` positioning/coherence-check only

from tests.phase5a import dosbox_session as ds  # noqa: E402
from tests.phase5c import evidence as ev  # noqa: E402
from tests.phase5c import launcher  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ds.bridge_available(),
    reason=(
        f"native DOSBox-X AI bridge not reachable at {ds.HOST}:{ds.PORT} -- start "
        f"dosbox-x.exe -break-start drive_c\\STEP.COM (no stdout/stderr redirection) "
        f"before running this live Phase 5C enforcement test"
    ),
)

RUN_ROOT = _ROOT / "scratchpad" / "phase5c" / "deterministic" / "C3"

# Same N and rationale as tests/phase5b/test_bounded_agent_cli_real_dosbox.py
# (B5-E): from LANDING_OFFSET (010C, "MOV AX,1111h"), the next two
# instructions -- 010C and 010F ("MOV BX,2222h") -- are both ordinary,
# non-CALL instructions, so two real step_into() calls land deterministically
# on CALL_FUNC1_OFFSET (0112) without needing to resolve a CALL/RET boundary.
# The smallest budget establishing a genuine N/N+1 boundary while keeping
# the live sequence minimal -- not a reproduction of B5's historical
# six-step budget (ai/Phase5E.md's own instruction).
N = 2


def is_hex(s, expected_len=None) -> bool:
    if not isinstance(s, str):
        return False
    if expected_len is not None and len(s) != expected_len:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def _fresh_run_dir(name: str) -> Path:
    run_dir = RUN_ROOT / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir


def test_c3_real_mcp_execution_step_budget_enforcement():
    run_dir = _fresh_run_dir("run1")
    evidence_log = run_dir / "evidence.jsonl"

    # -- 0. pre-test: bridge reachable, debugger genuinely stopped, starting
    #    from the intended live state (STEP.COM at LANDING_OFFSET) -- same
    #    positioning tests/phase5b/test_bounded_agent_cli_real_dosbox.py uses. --
    cs = ds.find_step_com_segment()
    ds.clear_all_breakpoints()
    target = f"{cs}:{ds.LANDING_OFFSET}"
    bp = s5a.set_breakpoint(target)
    assert "error" not in bp, bp
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    landed = ds.wait_for_stopped(timeout=15.0)
    assert landed["location"] == {"cs": cs, "eip": ds.LANDING_OFFSET}, landed
    ds.clear_all_breakpoints()

    pre_status = s5a.verify.get_debug_status()
    assert "error" not in pre_status, pre_status
    assert pre_status["location"] == {"cs": cs, "eip": ds.LANDING_OFFSET}, pre_status

    mcp_config = launcher.write_mcp_config(
        run_dir,
        server_name="c3-enforcement",
        total_budget=10,
        exec_budget=N,
        deadline_seconds=90.0,
        allowed_tools=frozenset({"step_into"}),
        evidence_log=evidence_log,
    )
    config = json.loads(mcp_config.read_text(encoding="utf-8"))
    entry = config["mcpServers"]["c3-enforcement"]
    params = StdioServerParameters(command=entry["command"], args=entry["args"], cwd=str(_ROOT))

    async def body():
        forwarded_results = []
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                # -- 1. calls 1..N: attempted, forwarded, real guest steps,
                #    over a genuine stdio tools/call round-trip. --
                for _ in range(N):
                    result = await session.call_tool("step_into", {})
                    assert not result.is_error, result
                    forwarded_results.append(json.loads(result.content[0].text))

                # -- 2. call N+1: attempted, rejected -- BUT the request
                #    itself completes a real MCP round-trip (this await
                #    returns a real, correlated response; it does not hang
                #    or drop), proving the rejection reached the real MCP
                #    server and came back over the wire, not merely that
                #    a local object was never touched. --
                rejected = await session.call_tool("step_into", {})

                # -- 3. one further call after termination: proves no call
                #    beyond the budget ever reaches the resolver even on repeat. --
                further = await session.call_tool("step_into", {})

                return forwarded_results, rejected, further

    forwarded_results, rejected, further = anyio.run(body)

    # -- forwarded calls 1..N: real state genuinely advanced (010C -> 010F -> 0112). --
    assert forwarded_results[0]["location"] == {"cs": cs, "eip": ds.AFTER_A_OFFSET}, forwarded_results[0]
    assert forwarded_results[1]["location"] == {"cs": cs, "eip": ds.CALL_FUNC1_OFFSET}, forwarded_results[1]

    mid_status = s5a.verify.get_debug_status()
    assert "error" not in mid_status, mid_status
    assert mid_status["location"] == {"cs": cs, "eip": ds.CALL_FUNC1_OFFSET}, mid_status

    # -- call N+1: rejected, with the new machine-distinguishable
    #    terminal/domain envelope (ai/server_phase5c.py's _classify_error).
    #    Deliberately checked in the JSON payload, not CallToolResult.is_error:
    #    ai/server_phase5c.py returns its {"ok": False, "error": {...}}
    #    envelope as an ordinary tool return value (never raises), for exact
    #    response-shape parity with the frozen ai/server.py/ai/server_phase5a.py
    #    convention those modules already use for every native-bridge error --
    #    which is what Phase 5C's C2 transport-equivalence claim depends on.
    #    is_error is asserted False here for the same reason, not omitted. --
    assert rejected.is_error is False, rejected
    rejected_payload = json.loads(rejected.content[0].text)
    assert rejected_payload["ok"] is False, rejected_payload
    assert rejected_payload["error"]["code"] == "BUDGET_EXHAUSTED", rejected_payload
    assert rejected_payload["error"]["domain"] == "bounded_session", rejected_payload
    assert rejected_payload["error"]["terminal"] is True, rejected_payload
    assert rejected_payload["error"]["retryable"] is False, rejected_payload

    # -- the further call after termination: distinct SESSION_ALREADY_TERMINATED
    #    presentation, still terminal, still bounded_session domain. --
    assert further.is_error is False, further
    further_payload = json.loads(further.content[0].text)
    assert further_payload["error"]["code"] == "SESSION_ALREADY_TERMINATED", further_payload
    assert further_payload["error"]["underlying_termination_code"] == "BUDGET_EXHAUSTED", further_payload
    assert further_payload["error"]["terminal"] is True, further_payload

    # -- evidence.jsonl: every one of ai/Phase5C3.md requirement 9's claims,
    #    proven from the durable, out-of-process trace, not just in-memory
    #    assertions above. --
    lines = ev.load_evidence_lines(evidence_log)
    assert len(lines) == N + 2, lines  # N forwarded + 1 rejected + 1 already-terminated

    for i in range(N):
        assert lines[i]["tool"] == "step_into"
        assert lines[i]["forwarded"] is True
        assert lines[i]["resolver_invocations_after"] == lines[i]["resolver_invocations_before"] + 1
        assert lines[i]["resolver_invocations_after"] == i + 1

    rejected_line = lines[N]
    assert rejected_line["tool"] == "step_into"
    assert rejected_line["forwarded"] is False  # recorded as ATTEMPTED, never forwarded
    assert rejected_line["resolver_invocations_before"] == N
    assert rejected_line["resolver_invocations_after"] == N  # unchanged -- resolver/DOSBoxClient never invoked
    assert rejected_line["termination"] == "BUDGET_EXHAUSTED"

    further_line = lines[N + 1]
    assert further_line["forwarded"] is False
    assert further_line["resolver_invocations_before"] == N
    assert further_line["resolver_invocations_after"] == N

    # -- independent post-rejection coherence check: a FRESH, separate
    #    connection to the real native bridge (never through the now-exited
    #    server subprocess or the terminated session), confirming DOSBox-X
    #    is still coherent and rejection itself caused no further execution-
    #    state transition -- still exactly where the last FORWARDED step
    #    left it. --
    post_status = s5a.verify.get_debug_status()
    assert "error" not in post_status, post_status
    assert post_status["stopped"] is True, post_status
    assert post_status["location"] == {"cs": cs, "eip": ds.CALL_FUNC1_OFFSET}, post_status

    post_cpu = s5a.verify.get_cpu_state()
    assert "error" not in post_cpu, post_cpu
    for reg in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp", "eflags"):
        assert is_hex(post_cpu.get(reg), 8), post_cpu
    for seg in ("cs", "ds", "es", "ss", "fs", "gs", "eip"):
        assert is_hex(post_cpu.get(seg), 4), post_cpu
    assert post_cpu["cs"] == cs, post_cpu
    assert post_cpu["eip"] == ds.CALL_FUNC1_OFFSET, post_cpu

    ds.clear_all_breakpoints()

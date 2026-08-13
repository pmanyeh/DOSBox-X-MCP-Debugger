"""
Phase 5C -- C1: deterministic real-MCP connectivity
(docs/phase5c-real-mcp-transport-design.md section 2).

No LLM. Uses the installed MCP SDK's own client primitives
(mcp.client.stdio.stdio_client + mcp.client.session.ClientSession) --
the same ones a real agent host uses -- to spawn ai/server_phase5c.py as a
genuine, separate OS subprocess over stdio, complete `initialize`, confirm
`tools/list` returns exactly the configured scenario's allowed tools (no
more, no less), and complete one real forwarded call end-to-end to real
DOSBox-X. This is transport evidence: importing server_phase5c and calling
its functions directly would NOT establish this (see design doc section 1
-- "none of the following count as Phase 5C transport evidence").

Requires a live DOSBox-X instance with the native AI bridge listening on
127.0.0.1:9876 (same convention as tests/phase5a/test_harness_selftest.py
and tests/phase5b/test_bounded_agent_cli_real_dosbox.py) -- skipped, not
failed, if unreachable.
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

import server_phase5a as s5a  # noqa: E402 -- unrecorded `verify` cross-check only

from tests.phase5a import dosbox_session as ds  # noqa: E402
from tests.phase5c import evidence as ev  # noqa: E402
from tests.phase5c import launcher  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ds.bridge_available(),
    reason=(
        f"native DOSBox-X AI bridge not reachable at {ds.HOST}:{ds.PORT} -- start "
        f"dosbox-x.exe -break-start drive_c\\STEP.COM (no stdout/stderr redirection) "
        f"before running this live Phase 5C connectivity test"
    ),
)

RUN_ROOT = _ROOT / "scratchpad" / "phase5c" / "deterministic" / "C1"


def _fresh_run_dir(name: str) -> Path:
    run_dir = RUN_ROOT / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir


def _server_params_from_config(mcp_config_path: Path, server_name: str) -> StdioServerParameters:
    config = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    entry = config["mcpServers"][server_name]
    return StdioServerParameters(command=entry["command"], args=entry["args"], cwd=str(_ROOT))


def _json_content(result) -> object:
    assert not result.is_error, result
    assert result.content, result
    return json.loads(result.content[0].text)


def test_c1_tools_list_matches_allowed_tools_exactly():
    run_dir = _fresh_run_dir("tools_list")
    allowed = frozenset({"get_debug_status", "get_cpu_state", "step_into"})
    evidence_log = run_dir / "evidence.jsonl"
    mcp_config = launcher.write_mcp_config(
        run_dir,
        server_name="c1-toolslist",
        total_budget=5,
        exec_budget=1,
        deadline_seconds=60.0,
        allowed_tools=allowed,
        evidence_log=evidence_log,
    )
    params = _server_params_from_config(mcp_config, "c1-toolslist")

    async def body():
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                listed = await session.list_tools()
                return sorted(t.name for t in listed.tools)

    names = anyio.run(body)
    assert names == sorted(allowed), names
    # No tool outside the allowed set was ever exposed, and no CALL was
    # made (load_call_records() filters out the one non-call
    # "session_finalized" line ai/server_phase5c.py's
    # _finalize_session_on_exit() appends when the client disconnects
    # without the session having hit a hard termination).
    assert ev.load_call_records(evidence_log) == []
    lines = ev.load_evidence_lines(evidence_log)
    assert len(lines) == 1, lines
    assert lines[0]["event"] == "session_finalized", lines
    assert lines[0]["termination"] == "SUCCESS", lines


def test_c1_real_forwarded_call_end_to_end():
    run_dir = _fresh_run_dir("one_real_call")
    allowed = frozenset({"get_debug_status", "get_cpu_state"})
    evidence_log = run_dir / "evidence.jsonl"
    mcp_config = launcher.write_mcp_config(
        run_dir,
        server_name="c1-onecall",
        total_budget=5,
        exec_budget=0,
        deadline_seconds=60.0,
        allowed_tools=allowed,
        evidence_log=evidence_log,
    )
    params = _server_params_from_config(mcp_config, "c1-onecall")

    # independent, unrecorded ground truth taken BEFORE the MCP call, via
    # the already-frozen Phase 5A `verify` path -- never through the
    # server under test.
    pre_status = s5a.verify.get_debug_status()
    assert "error" not in pre_status, pre_status

    async def body():
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                result = await session.call_tool("get_debug_status", {})
                return _json_content(result)

    payload = anyio.run(body)

    assert isinstance(payload, dict), payload
    assert "location" in payload, payload
    # Real DOSBox-X state, observed independently before and reached
    # through the real MCP call, agree -- this is the real chain (agent
    # tool call -> MCP request -> BoundedSession -> real resolver ->
    # DOSBoxClient -> native bridge -> real DOSBox-X -> MCP result),
    # not a mock.
    assert payload["location"] == pre_status["location"], (payload, pre_status)

    lines = ev.load_evidence_lines(evidence_log)
    # 1 real call + 1 "session_finalized" line (ai/server_phase5c.py's
    # _finalize_session_on_exit(), appended on disconnect since this
    # session never hit a hard termination).
    assert len(lines) == 2, lines
    line = lines[0]
    assert line["tool"] == "get_debug_status"
    assert line["forwarded"] is True
    assert line["resolver_invocations_before"] == 0
    assert line["resolver_invocations_after"] == 1
    assert line["mcp_request_id"] is not None
    assert lines[1]["event"] == "session_finalized"
    assert lines[1]["termination"] == "SUCCESS"

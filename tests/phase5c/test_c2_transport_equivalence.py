"""
Phase 5C -- C2: deterministic transport equivalence
(docs/phase5c-real-mcp-transport-design.md section 2).

Runs tool calls against real DOSBox-X through two paths and asserts the
observed results agree, proving the new MCP wrapping introduces no
behavioral drift versus the frozen Phase 5B path:

  (a) the frozen path -- BoundedSession + _real_tool_resolver() driven
      in-process (tests/phase5b/bounded_agent_cli.py, unmodified) -- the
      same session.call(name, args) bounded_agent_cli.py's CLI shim
      itself makes, minus only the CLI's own subprocess-per-call/
      state-file mechanics, which are a process-packaging detail, not
      part of what "transport equivalence" claims;
  (b) the new path -- the identical calls issued as real MCP tools/call
      requests over stdio to ai/server_phase5c.py, via the installed
      SDK's own client (mcp.client.stdio / mcp.client.session).

For the read-only sequence, both paths are run back-to-back against the
SAME unchanged real DOSBox-X state and their results are compared
directly. For the one state-mutating call (step_into), literally
replaying the identical step twice is not meaningful (STEP.COM's control
flow is strictly linear/forward -- see tests/phase5a/dosbox_session.py's
module docstring -- so there is no way to "rewind" real DOSBox-X between
the two halves without relaunching the whole session); instead each path
drives one real, different, deterministic forward step and both are
independently cross-checked against ground truth taken via the unrecorded
`verify` path -- proving neither transport alters what real DOSBox-X
actually does.

No LLM. Requires a live DOSBox-X instance (skipped, not failed, if
unreachable), same convention as the rest of tests/phase5c/.
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

import server_phase5a as s5a  # noqa: E402 -- unrecorded `verify` positioning/ground-truth only

from tests.phase5a import dosbox_session as ds  # noqa: E402
from tests.phase5b.bounded_agent_cli import BoundedSession, BudgetConfig, _real_tool_resolver  # noqa: E402
from tests.phase5c import launcher  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ds.bridge_available(),
    reason=(
        f"native DOSBox-X AI bridge not reachable at {ds.HOST}:{ds.PORT} -- start "
        f"dosbox-x.exe -break-start drive_c\\STEP.COM (no stdout/stderr redirection) "
        f"before running this live Phase 5C transport-equivalence test"
    ),
)

RUN_ROOT = _ROOT / "scratchpad" / "phase5c" / "deterministic" / "C2"
READ_ONLY_SEQUENCE = ["get_debug_status", "get_cpu_state", "get_current_instruction"]


def _fresh_run_dir(name: str) -> Path:
    run_dir = RUN_ROOT / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir


def _cli_path_results(tool_names: list[str]) -> list[dict]:
    config = BudgetConfig(
        total_call_budget=len(tool_names) + 5,
        execution_step_budget=len(tool_names) + 5,
        deadline_seconds=60.0,
        allowed_tools=frozenset(tool_names),
    )
    session = BoundedSession(config, _real_tool_resolver())
    results = []
    for name in tool_names:
        r = session.call(name, {})
        assert "error" not in r, r
        results.append(r)
    return results


def _mcp_path_results(run_dir: Path, tool_names: list[str], server_name: str) -> list[dict]:
    allowed = frozenset(tool_names)
    evidence_log = run_dir / "evidence.jsonl"
    mcp_config = launcher.write_mcp_config(
        run_dir,
        server_name=server_name,
        total_budget=len(tool_names) + 5,
        exec_budget=len(tool_names) + 5,
        deadline_seconds=60.0,
        allowed_tools=allowed,
        evidence_log=evidence_log,
    )
    config = json.loads(mcp_config.read_text(encoding="utf-8"))
    entry = config["mcpServers"][server_name]
    params = StdioServerParameters(command=entry["command"], args=entry["args"], cwd=str(_ROOT))

    async def body():
        results = []
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                for name in tool_names:
                    result = await session.call_tool(name, {})
                    assert not result.is_error, result
                    results.append(json.loads(result.content[0].text))
        return results

    return anyio.run(body)


def test_c2_read_only_sequence_equivalence():
    run_dir = _fresh_run_dir("read_only")

    cli_results = _cli_path_results(READ_ONLY_SEQUENCE)
    mcp_results = _mcp_path_results(run_dir, READ_ONLY_SEQUENCE, "c2-readonly")

    assert cli_results == mcp_results, (cli_results, mcp_results)


def test_c2_step_into_equivalence_against_independent_ground_truth():
    run_dir = _fresh_run_dir("step_into")

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

    # -- step A: frozen CLI-shim path (in-process BoundedSession + real resolver) --
    cli_results = _cli_path_results(["step_into"])
    after_cli = cli_results[0]
    assert after_cli["location"] == {"cs": cs, "eip": ds.AFTER_A_OFFSET}, after_cli
    ground_truth_a = s5a.verify.get_debug_status()
    assert "error" not in ground_truth_a, ground_truth_a
    assert ground_truth_a["location"] == after_cli["location"], (ground_truth_a, after_cli)
    assert ground_truth_a["registers"]["eax"][-4:].upper() == "1111", ground_truth_a  # MOV AX,1111h just executed

    # -- step B: new MCP-transport path, continuing the SAME real, still-running
    #    STEP.COM instance one more real instruction forward --
    mcp_results = _mcp_path_results(run_dir, ["step_into"], "c2-stepinto")
    after_mcp = mcp_results[0]
    assert after_mcp["location"] == {"cs": cs, "eip": ds.CALL_FUNC1_OFFSET}, after_mcp
    ground_truth_b = s5a.verify.get_debug_status()
    assert "error" not in ground_truth_b, ground_truth_b
    assert ground_truth_b["location"] == after_mcp["location"], (ground_truth_b, after_mcp)
    assert ground_truth_b["registers"]["ebx"][-4:].upper() == "2222", ground_truth_b  # MOV BX,2222h just executed

    ds.clear_all_breakpoints()

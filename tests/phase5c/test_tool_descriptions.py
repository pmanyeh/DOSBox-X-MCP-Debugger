"""
Phase 5C tool-contract hardening (ai/Phase5C6.md "Tool-contract hardening").

Confirms the agent-visible MCP tool description for `get_cpu_state`
(ai/server_phase5c.py) accurately states it is a register snapshot that
does not establish running/stopped state, and points callers needing that
evidence at `get_debug_status` instead -- the exact, real distinction the
Campaign 6/7 C4-B1 finding (docs/phase5c-final-report.md) is about.

No live DOSBox-X required: `tools/list` is answered from the server's own
registered Tool objects and never touches the native bridge -- confirmed
by inspection (ai/server_phase5c.py's tool registration is pure Python
object construction; DOSBoxClient is only ever reached from inside a
tool's _call(), never from list_tools()).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "ai"))
sys.path.insert(0, str(_ROOT))

import anyio  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

import server_phase5c as s5c  # noqa: E402

from tests.phase5c import launcher  # noqa: E402

RUN_ROOT = _ROOT / "scratchpad" / "phase5c" / "deterministic" / "tool_descriptions"


def _fresh_run_dir(name: str) -> Path:
    run_dir = RUN_ROOT / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir


def test_get_cpu_state_docstring_states_the_stopped_state_limitation():
    """Direct, offline check of the source docstring itself -- the
    smallest, fastest form of this test."""

    doc = s5c.get_cpu_state.__doc__ or ""
    assert "does not establish" in doc or "does NOT establish" in doc, doc
    assert "running" in doc and "stopped" in doc, doc
    assert "get_debug_status" in doc, doc


def test_get_cpu_state_mcp_description_states_the_stopped_state_limitation():
    """End-to-end confirmation via a real MCP tools/list round-trip over
    stdio (the same mechanism a real agent host uses) -- proves the
    corrected docstring actually reaches the agent-visible MCP tool
    description, not merely the Python source."""

    run_dir = _fresh_run_dir("get_cpu_state_description")
    evidence_log = run_dir / "evidence.jsonl"
    allowed = frozenset({"get_cpu_state", "get_debug_status"})
    mcp_config = launcher.write_mcp_config(
        run_dir,
        server_name="tool-desc-check",
        total_budget=5,
        exec_budget=0,
        deadline_seconds=60.0,
        allowed_tools=allowed,
        evidence_log=evidence_log,
    )
    import json

    config = json.loads(mcp_config.read_text(encoding="utf-8"))
    entry = config["mcpServers"]["tool-desc-check"]
    params = StdioServerParameters(command=entry["command"], args=entry["args"], cwd=str(_ROOT))

    async def body():
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                listed = await session.list_tools()
                return {t.name: t.description for t in listed.tools}

    descriptions = anyio.run(body)
    desc = descriptions["get_cpu_state"]
    assert desc is not None
    assert "does not establish" in desc or "does NOT establish" in desc, desc
    assert "get_debug_status" in desc, desc

    # The description change is additive documentation only -- the tool
    # set and every OTHER tool's description are unaffected.
    assert set(descriptions.keys()) == allowed
    assert "does not establish" not in (descriptions["get_debug_status"] or "").lower()

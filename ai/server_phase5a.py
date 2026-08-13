"""
Phase 5A restricted MCP server (docs/phase5a-tool-awareness-design.md section 3.2).

Re-registers the SAME tool implementations ai/server.py already exposes --
imported from server.py, not reimplemented -- except `write_register` and
`write_memory`, which are deliberately left unregistered so they are
technically unreachable (absent from tools/list) for every Phase 5A Tool
Awareness scenario, per ai/Phase5A.md ("暫不開放 write_register /
write_memory"). This is a hard guarantee, not a prompt-level instruction:
an agent connected to THIS server cannot call those two tools at all.

ai/server.py itself (the Phase 4E-accepted production tool surface) is not
modified by this file.

Every registered tool call is also recorded (name, args, result, timestamp)
in-process via `get_call_log()`, independent of whatever the calling agent
says in prose -- this is the "recorded tool-call trace" the Phase 5A test
harness (tests/phase5a/) grades against.
"""

import functools
import time
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

import server as _server

mcp = MCPServer("DOSBox-X AI Debugger (Phase 5A -- restricted, no write access)")

# Every tool ai/server.py exposes EXCEPT write_register/write_memory. Keep
# this list in exact sync with ai/server.py's @mcp.tool() functions minus
# those two -- see docs/phase5a-tool-awareness-design.md section 1 for the
# full inventory/rationale.
_ALLOWED_TOOL_FUNCS = [
    _server.ping,
    _server.get_project_status,
    _server.get_cpu_state,
    _server.get_debug_status,
    _server.get_current_instruction,
    _server.read_memory,
    _server.disassemble,
    _server.set_breakpoint,
    _server.delete_breakpoint,
    _server.list_breakpoints,
    _server.continue_execution,
    _server.pause_execution,
    _server.step_into,
    _server.step_over,
]

_EXCLUDED_TOOL_NAMES = {"write_register", "write_memory"}


_call_log: list[dict[str, Any]] = []


def get_call_log() -> list[dict[str, Any]]:
    """Return the recorded call trace (list of {name, args, kwargs, result,
    timestamp} dicts, in call order) for the current process lifetime."""

    return list(_call_log)


def reset_call_log() -> None:
    """Clear the recorded call trace -- call this between scenario runs so
    one scenario's trace never leaks into the next one's grading."""

    _call_log.clear()


class verify:
    """Unrecorded pass-through to ai/server.py's original tool functions,
    for the TEST HARNESS's own before/after ground-truth snapshots (e.g.
    `verify.get_debug_status()` to check what really happened after an
    agent's turn). Deliberately bypasses the call-recording wrapper below --
    harness-side verification calls are not part of "what the agent did"
    and must not appear in get_call_log(), or every scenario's recorded
    trace would be polluted with the harness's own bookkeeping calls."""

    get_debug_status = staticmethod(_server.get_debug_status)
    get_cpu_state = staticmethod(_server.get_cpu_state)
    list_breakpoints = staticmethod(_server.list_breakpoints)


def _record_and_wrap(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = fn(*args, **kwargs)
        _call_log.append(
            {
                "name": fn.__name__,
                "args": args,
                "kwargs": kwargs,
                "result": result,
                "timestamp": time.monotonic(),
            }
        )
        return result

    return wrapper


for _fn in _ALLOWED_TOOL_FUNCS:
    assert _fn.__name__ not in _EXCLUDED_TOOL_NAMES, (
        f"{_fn.__name__} must not be registered on the Phase 5A server"
    )
    _wrapped = _record_and_wrap(_fn)
    mcp.tool()(_wrapped)
    # Expose the same recorded, wrapped callable as a module-level name
    # (e.g. server_phase5a.get_debug_status) so the Phase 5A test harness
    # (tests/phase5a/) and any other in-process caller go through the same
    # recording path a real MCP client's tool call would -- calling
    # ai/server.py's functions directly instead would silently bypass
    # get_call_log(), which every grading check in tests/phase5a/grading.py
    # depends on.
    globals()[_fn.__name__] = _wrapped


if __name__ == "__main__":
    mcp.run()

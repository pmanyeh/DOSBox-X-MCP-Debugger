"""
Phase 5A real-agent CLI shim (ai/Phase5A-2.md real-agent acceptance run).

A thin, additive command-line wrapper around the EXACT SAME tool functions
ai/server_phase5a.py already registers (looked up via getattr on that
module -- not reimplemented, not duplicated) -- lets a genuinely separate
agent process (a spawned subagent, invoking this via Bash, with no access
to this project's Python state or test/grading code) call one Phase 5A
tool per invocation and see its real JSON result, without a live MCP
client/transport needing to be wired up for that subagent in this
environment.

Every call is appended to a JSON-lines trace file (one JSON object per
line: name, args, result, timestamp), independent of this short-lived
process, so the orchestrating session can grade the accumulated trace
after the agent's turn ends -- this file IS the "tool call trace"
ai/Phase5A-2.md requires be preserved and reported.

Usage:
    python agent_cli.py --log <tracefile> --tool <name> [--args <json>]
    python agent_cli.py --list-tools

Only tools ai/server_phase5a.py registers as module-level attributes are
callable here -- write_register/write_memory are absent from that module
for the same reason they are absent from server_phase5a's MCP tools/list,
so this shim cannot reach them either.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ai"))

import server_phase5a as s5a  # noqa: E402

TOOL_DESCRIPTIONS = {
    "get_debug_status": "Return one coherent debugger snapshot: stop state, location, current instruction, registers, segments, and flags. No arguments.",
    "get_cpu_state": "Return the current CPU registers and segment state. No arguments.",
    "get_current_instruction": "Return the instruction at the current CS:EIP. No arguments.",
    "read_memory": 'Read `length` bytes starting at a "SEG:OFF" address. Args: {"address": str, "length": int}',
    "disassemble": 'Disassemble `count` instructions starting at a "SEG:OFF" address. Args: {"address": str, "count": int}',
    "set_breakpoint": 'Set a breakpoint at a "SEG:OFF" address. Args: {"address": str}',
    "delete_breakpoint": "Delete a breakpoint by its id. Args: {\"breakpoint_id\": int}",
    "list_breakpoints": "List all breakpoints currently set. No arguments.",
    "continue_execution": "Resume real guest CPU execution. Only valid while stopped. No arguments.",
    "pause_execution": "Stop real guest CPU execution. Only valid while running. No arguments.",
    "step_into": "Execute exactly one guest instruction, including entering a CALL if the current instruction is one. Only valid while stopped. No arguments.",
    "step_over": "Step over the current instruction -- for a CALL, the subroutine runs to completion and execution stops at the instruction AFTER the call, not inside it. Only valid while stopped. No arguments.",
}


def _registered_tools() -> dict:
    return {name: getattr(s5a, name) for name in TOOL_DESCRIPTIONS if hasattr(s5a, name)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-tools", action="store_true", help="Print available tools and exit")
    parser.add_argument("--log", help="Path to the JSON-lines trace file to append to")
    parser.add_argument("--tool", help="Tool name to call")
    parser.add_argument("--args", default="{}", help="JSON object of keyword arguments")
    ns = parser.parse_args()

    tools = _registered_tools()

    if ns.list_tools:
        for name in sorted(tools):
            print(f"{name}: {TOOL_DESCRIPTIONS[name]}")
        return 0

    if not ns.tool or not ns.log:
        parser.error("--tool and --log are required unless --list-tools is given")

    if ns.tool not in tools:
        print(json.dumps({"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": f"no such tool: {ns.tool!r}"}}))
        return 1

    try:
        kwargs = json.loads(ns.args)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": {"code": "INVALID_ARGS_JSON", "message": str(e)}}))
        return 1

    fn = tools[ns.tool]
    result = fn(**kwargs)

    record = {"name": ns.tool, "args": kwargs, "result": result, "timestamp": time.time()}
    with open(ns.log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

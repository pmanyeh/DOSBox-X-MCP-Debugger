Read AGENTS.md first.

Phase 1 has been completed and verified.

Verified:
- Python 3.12: PASS
- MCP 2.0.0: PASS
- Node.js: PASS
- npm: PASS
- npx: PASS
- ai/server.py: PASS
- MCP Inspector: PASS
- ping(): PASS
- get_project_status(): PASS

Now proceed to PHASE 2 only.

Do NOT modify DOSBox-X C++ source yet.

==================================================
PHASE 2 OBJECTIVE
==================================================

Build a Fake DOSBox-X Debugger backend so that the
MCP interface can be fully tested before connecting
to the real DOSBox-X debugger.

The goal is to establish a stable debugger API contract.

==================================================
FILES
==================================================

Create:

ai/debugger.py
ai/protocol.py
tests/test_debugger.py

Modify:

ai/server.py

Do not modify DOSBox-X source.

==================================================
1. FakeDOSBoxDebugger
==================================================

Implement:

class FakeDOSBoxDebugger

It must maintain an internal debugger state.

Initial state should contain realistic x86/DOS debugger data:

Registers:

eax
ebx
ecx
edx
esi
edi
ebp
esp

Segments:

cs
ds
es
ss

Instruction pointer:

eip

Flags:

eflags

Initial example:

cs = 1234
eip = 0100

Instruction:

B8 34 12

Disassembly:

MOV AX,1234h


==================================================
2. Required debugger methods
==================================================

Implement:

get_cpu_state()

get_debug_status()

get_current_instruction()

read_memory(address, length)

write_memory(address, data)

step_into()

continue_execution()

pause_execution()

set_breakpoint(address)

delete_breakpoint(address)

list_breakpoints()

disassemble(address, count)


==================================================
3. IMPORTANT
==================================================

The Fake Debugger must behave like a stateful debugger.

Do NOT simply return hard-coded values from every function.

For example:

step_into()

must modify EIP and the current instruction.

Example:

Before:

CS:EIP = 1234:0100

Instruction:

MOV AX,1234h

After step:

CS:EIP = 1234:0103

The next instruction should be returned.

==================================================
4. Memory
==================================================

Implement a deterministic fake memory model.

At minimum support:

read_memory(address, length)

write_memory(address, data)

The same data written by write_memory()
must be returned by read_memory().

Validate:

- address
- length
- memory boundaries

Do not silently accept invalid addresses.

==================================================
5. Breakpoints
==================================================

Implement stateful breakpoints.

set_breakpoint(address)

delete_breakpoint(address)

list_breakpoints()

A breakpoint should contain:

id
address
enabled

Example:

{
    "id": 1,
    "address": "1234:0103",
    "enabled": true
}

Breakpoint IDs must be deterministic during one server session.

==================================================
6. Execution
==================================================

Implement:

step_into()
continue_execution()
pause_execution()

The fake debugger should maintain:

running
stopped

state.

step_into() should execute exactly one instruction.

continue_execution() should execute until:

- breakpoint
- explicit pause
- safety execution limit

Do NOT create an infinite loop.

==================================================
7. Debug Status
==================================================

get_debug_status() must return one coherent snapshot.

Example:

{
    "stopped": true,
    "running": false,

    "location": {
        "cs": "1234",
        "eip": "0100"
    },

    "instruction": {
        "bytes": "B8 34 12",
        "text": "MOV AX,1234h"
    },

    "registers": {
        "eax": "00000000",
        "ebx": "00000000",
        "ecx": "00000000",
        "edx": "00000000",
        "esi": "00000000",
        "edi": "00000000",
        "ebp": "00000000",
        "esp": "0000FF00"
    },

    "segments": {
        "cs": "1234",
        "ds": "2000",
        "es": "2000",
        "ss": "3000"
    },

    "flags": {
        "eflags": "00000202"
    }
}

The exact values may differ, but the structure must remain stable.

==================================================
8. MCP TOOLS
==================================================

Expose these MCP tools in ai/server.py:

ping()

get_project_status()

get_cpu_state()

get_debug_status()

get_current_instruction()

read_memory(address, length)

write_memory(address, data)

disassemble(address, count)

set_breakpoint(address)

delete_breakpoint(breakpoint_id)

list_breakpoints()

continue_execution()

pause_execution()

step_into()

==================================================
9. Tool output
==================================================

All MCP tools must return structured,
JSON-compatible data.

Do not return raw Python objects that cannot be serialized.

Errors should be represented clearly.

Example:

{
    "ok": false,
    "error": {
        "code": "INVALID_ADDRESS",
        "message": "Invalid debugger address"
    }
}

==================================================
10. Tests
==================================================

Create:

tests/test_debugger.py

Use pytest.

At minimum test:

1. initial CPU state

2. initial debug status

3. instruction retrieval

4. memory read

5. memory write/read round trip

6. step_into changes EIP

7. breakpoint creation

8. breakpoint deletion

9. breakpoint listing

10. continue_execution stops at breakpoint

11. pause_execution

12. disassembly

==================================================
11. MCP TEST
==================================================

Run:

.\.venv\Scripts\python.exe -m pytest

All tests must pass.

Then run:

.\.venv\Scripts\mcp.exe dev .\ai\server.py

Verify through MCP Inspector that all Phase 2 tools are visible.

==================================================
12. REQUIRED MCP TOOL LIST
==================================================

Inspector must expose:

ping
get_project_status
get_cpu_state
get_debug_status
get_current_instruction
read_memory
write_memory
disassemble
set_breakpoint
delete_breakpoint
list_breakpoints
continue_execution
pause_execution
step_into

==================================================
13. VALIDATION SCENARIO
==================================================

Use the MCP tools to simulate this debugging session:

1. get_debug_status()

2. set_breakpoint("1234:0103")

3. continue_execution()

4. get_debug_status()

5. step_into()

6. get_debug_status()

7. read_memory("1234:0100", 16)

8. disassemble("1234:0100", 5)

9. list_breakpoints()

The state must change consistently.

==================================================
14. DO NOT DO YET
==================================================

Do NOT:

- modify DOSBox-X C++ source
- build DOSBox-X
- implement native TCP bridge
- inspect/modify src/debug/
- automate the DOSBox-X GUI
- use keyboard/mouse automation
- use OCR
- create fake MCP responses in server.py

The FakeDOSBoxDebugger itself is allowed to simulate
the debugger because Phase 2 is explicitly a backend
contract test.

==================================================
15. COMPLETION CRITERIA
==================================================

Phase 2 is complete only when:

[ ] FakeDOSBoxDebugger exists
[ ] debugger state is stateful
[ ] CPU state works
[ ] debug status works
[ ] instruction state works
[ ] memory read/write works
[ ] step_into changes state
[ ] breakpoints work
[ ] continue_execution works
[ ] pause_execution works
[ ] disassembly works
[ ] pytest passes
[ ] MCP Inspector starts
[ ] all required MCP tools appear
[ ] MCP tools execute successfully

After completion, report:

1. files created/modified
2. pytest result
3. MCP Inspector result
4. tool list
5. any limitations
6. recommendation for Phase 3

Do not claim Phase 2 complete unless the validation
commands were actually executed.
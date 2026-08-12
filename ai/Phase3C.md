# DOSBox-X-AI Phase 3C
# Python MCP → Native DOSBox-X Bridge

## Status

Phase 3B is COMPLETE and VERIFIED.

Verified:

- DOSBox-X Release x64 build: PASS
- DOSBox-X Debugger GUI: PASS
- Native bridge: PASS
- 127.0.0.1:9876: LISTENING
- Native bridge test: 34/34 PASS
- Real CPU state: verified
- Real guest memory: verified
- Real disassembly: verified

Now integrate the Python MCP server with the native bridge.

==================================================
OBJECTIVE
==================================================

Replace the Phase 2 FakeDOSBoxDebugger backend with:

    ai/dosbox_client.py

The final path must be:

    AI Agent
        ↓
    MCP
        ↓
    ai/server.py
        ↓
    ai/dosbox_client.py
        ↓
    TCP 127.0.0.1:9876
        ↓
    DOSBox-X Native AI Bridge
        ↓
    Real DOSBox-X Debugger


==================================================
IMPORTANT
==================================================

Do NOT modify DOSBox-X C++ source.

Phase 3B is already verified.

Do NOT implement:

    memory.write
    register.write
    breakpoint.set
    breakpoint.delete
    continue
    pause
    step_into
    step_over

Those belong to Phase 4.


==================================================
1. Create ai/dosbox_client.py
==================================================

Implement:

    connect()
    close()
    request()
    get_debug_status()
    get_cpu_state()
    read_memory()
    get_current_instruction()
    disassemble()


Connection:

    127.0.0.1
    9876


Use:

    socket.create_connection()

with reasonable connection and response timeouts.


==================================================
2. Protocol
==================================================

Use newline-delimited JSON.

Request:

    {
        "id": 1,
        "method": "cpu.get"
    }


Response:

    {
        "id": 1,
        "ok": true,
        "result": {...}
    }


Validate:

- response is JSON
- response id matches request id
- ok field exists
- result/error is handled correctly


==================================================
3. Error handling
==================================================

Map native errors into useful Python exceptions.

At minimum:

    DOSBoxNotConnected
    DOSBoxTimeout
    DOSBoxProtocolError
    DOSBoxDebuggerNotStopped
    DOSBoxMemoryError


Do not expose raw socket exceptions through MCP.


==================================================
4. Modify ai/server.py
==================================================

The existing MCP tools:

    get_debug_status
    get_cpu_state
    read_memory
    get_current_instruction
    disassemble

must now use:

    DOSBoxClient


Do NOT use:

    FakeDOSBoxDebugger


for production MCP execution.


==================================================
5. Keep FakeDOSBoxDebugger

Do not delete:

    FakeDOSBoxDebugger


It may still be used by unit tests.

Separate:

    unit tests
        ↓
    FakeDOSBoxDebugger

from:

    integration tests
        ↓
    real DOSBox-X


==================================================
6. MCP Tools

Verify these tools:

    get_debug_status
    get_cpu_state
    read_memory
    get_current_instruction
    disassemble


==================================================
7. Integration test

Create:

    tests/test_mcp_native_bridge.py


This must connect to a LIVE DOSBox-X instance.

Do not use FakeDOSBoxDebugger.


Verify:

1. get_debug_status()

2. get_cpu_state()

3. read_memory()

4. get_current_instruction()

5. disassemble()


==================================================
8. Real State Verification

The integration test must confirm that the returned
values are not fake.

At minimum verify:

    CS:EIP

and current instruction.

The test may use the known DOSBox-X reset state:

    CS:EIP = F000:FFF0

if DOSBox-X is started with:

    -break-start


Do not hard-code this as the implementation's result.

It is only a test expectation for the known startup state.


==================================================
9. MCP Inspector

Run:

    .\.venv\Scripts\mcp.exe dev .\ai\server.py


Verify all five real debugger tools.

Use MCP Inspector to execute:

    get_debug_status
    get_cpu_state
    read_memory
    get_current_instruction
    disassemble


==================================================
10. Regression

Run:

    .\.venv\Scripts\python.exe -m pytest


All existing Phase 2 tests must still pass.

The FakeDOSBoxDebugger tests must remain valid.


==================================================
11. Build/Runtime

Do NOT rebuild DOSBox-X unless necessary.

Use the already verified Phase 3B executable.

Start:

    dosbox-x.exe -break-start


Verify:

    127.0.0.1:9876 LISTENING


==================================================
12. Completion Criteria

Phase 3C is complete only when:

[ ] ai/dosbox_client.py exists
[ ] Native protocol works
[ ] MCP server uses DOSBoxClient
[ ] FakeDOSBoxDebugger remains available for unit tests
[ ] Phase 2 tests pass
[ ] Native integration tests pass
[ ] MCP Inspector sees all five tools
[ ] MCP tools return REAL DOSBox-X state
[ ] DOSBox-X GUI remains functional


==================================================
13. STOP CONDITIONS

STOP if:

- native bridge cannot connect
- response IDs do not match
- MCP returns fake data
- Phase 2 tests regress
- DOSBox-X must be modified
- protocol behavior is unclear


==================================================
14. Final Report

Report:

1. files created
2. files modified
3. pytest result
4. integration test result
5. MCP Inspector result
6. example real CPU state
7. example real CS:EIP
8. example real instruction
9. any limitations
10. recommendation for Phase 4
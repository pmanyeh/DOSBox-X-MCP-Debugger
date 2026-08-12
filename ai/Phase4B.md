Phase 4A has been reviewed and APPROVED.

Proceed to PHASE 4B ONLY.

==================================================
PHASE 4B — REAL DOSBox-X BREAKPOINT CONTROL
==================================================

Objective:

Expose the EXISTING DOSBox-X debugger breakpoint system
through the Native AI Bridge.

The AI must manipulate the SAME breakpoint state used
by the DOSBox-X debugger GUI.

Do NOT create a second breakpoint system.

==================================================
SCOPE
==================================================

Implement ONLY:

    breakpoint.set
    breakpoint.delete
    breakpoint.list

Do NOT implement yet:

    continue
    pause
    step_into
    step_over

Those belong to Phase 4C / 4D.

==================================================
ARCHITECTURE
==================================================

Keep the existing architecture:

    MCP
      ↓
    ai/server.py
      ↓
    DOSBoxClient
      ↓
    TCP 127.0.0.1:9876
      ↓
    Native AI Bridge
      ↓
    thread-safe request queue
      ↓
    DOSBox-X emulator/debugger thread
      ↓
    EXISTING DOSBox-X breakpoint system


The socket thread must NEVER directly access the
DOSBox-X breakpoint data structures.

All breakpoint operations must execute on the
DOSBox-X emulator/debugger thread.

==================================================
1. SOURCE INSPECTION
==================================================

Before modifying C++:

Review the existing DOSBox-X breakpoint implementation.

In particular inspect:

    CBreakpoint::BPoints
    breakpoint command handling
    existing breakpoint creation
    existing breakpoint deletion
    existing breakpoint listing
    breakpoint hit detection

Do not duplicate these mechanisms.

Document the exact existing functions/data structures
used by the native bridge.

Update:

    docs/dosbox-ai-bridge.md

==================================================
2. breakpoint.set
==================================================

Implement:

    breakpoint.set

Request example:

    {
        "id": 1,
        "method": "breakpoint.set",
        "params": {
            "address": "1234:0100"
        }
    }


Use the EXISTING DOSBox-X breakpoint mechanism.

The address must be validated before insertion.

Return a structured result containing at minimum:

    id
    address
    enabled


Example:

    {
        "id": 1,
        "address": "1234:0100",
        "enabled": true
    }


Do not invent a second breakpoint ID system unless
the existing DOSBox-X breakpoint system requires
a bridge-level identifier.

If an adapter ID is necessary, document the mapping.


==================================================
3. breakpoint.list
==================================================

Implement:

    breakpoint.list


Return the REAL DOSBox-X breakpoint list.

Example:

    {
        "breakpoints": [
            {
                "id": 1,
                "address": "1234:0100",
                "enabled": true
            }
        ]
    }


The values must come from the existing DOSBox-X
debugger breakpoint state.

==================================================
4. breakpoint.delete
==================================================

Implement:

    breakpoint.delete


Request:

    {
        "id": 1,
        "method": "breakpoint.delete",
        "params": {
            "id": 1
        }
    }


Delete the corresponding REAL DOSBox-X breakpoint.

If the breakpoint does not exist, return a stable
error code.

Suggested:

    BREAKPOINT_NOT_FOUND

Do not silently succeed.


==================================================
5. MCP API
==================================================

Add to:

    ai/dosbox_client.py

Methods:

    set_breakpoint(address)
    delete_breakpoint(breakpoint_id)
    list_breakpoints()


Add to:

    ai/server.py

MCP tools:

    set_breakpoint
    delete_breakpoint
    list_breakpoints


The existing Phase 2 FakeDOSBoxDebugger breakpoint
methods may remain for unit tests, but production MCP
execution must use DOSBoxClient.


==================================================
6. Validation
==================================================

Create/update:

    tests/test_mcp_native_bridge.py

Test:

1. list_breakpoints initially
2. set breakpoint
3. list breakpoint
4. verify address
5. verify enabled state
6. delete breakpoint
7. list again
8. delete nonexistent breakpoint
9. invalid address
10. duplicate breakpoint behavior


==================================================
7. GUI CONSISTENCY TEST
==================================================

This is REQUIRED.

Start DOSBox-X with debugger enabled.

Through MCP:

    set_breakpoint(address)


Then inspect the DOSBox-X debugger GUI.

The breakpoint created by MCP must appear in the
existing DOSBox-X debugger breakpoint state.

Then delete it through MCP.

Verify it disappears from the DOSBox-X debugger state.

Do NOT automate the GUI.

Human/manual verification is sufficient.


==================================================
8. Thread Safety

Create a test involving multiple connections.

The test must verify that breakpoint operations are
serialized through the existing request queue.

Do not test by assuming simultaneous mutation of
the same breakpoint should produce a particular
ordering unless the protocol explicitly guarantees it.

Verify:

- no corruption
- no crash
- valid breakpoint state
- deterministic response format


==================================================
9. Error Handling

Use stable error codes.

At minimum:

    INVALID_PARAMETER
    INVALID_ADDRESS
    BREAKPOINT_NOT_FOUND
    BREAKPOINT_ALREADY_EXISTS
    INTERNAL_ERROR


Preserve native error codes through:

    Native Bridge
        ↓
    DOSBoxClient
        ↓
    MCP


Do not collapse specific native errors into a generic
protocol error.


==================================================
10. Regression

Run:

    .\.venv\Scripts\python.exe -m pytest


All previous tests must remain passing.

Phase 2 FakeDebugger tests:
    must pass

Phase 3C integration tests:
    must pass

Phase 4A tests:
    must pass


==================================================
11. Live Test

Start:

    dosbox-x.exe -break-start


Verify:

    127.0.0.1:9876 LISTENING


Use MCP Inspector to call:

    set_breakpoint
    list_breakpoints
    delete_breakpoint
    list_breakpoints


Verify the returned state comes from the REAL
DOSBox-X debugger.


==================================================
12. MCP Inspector

Verify tools/list contains:

    set_breakpoint
    delete_breakpoint
    list_breakpoints


The existing debugger tools must remain available.


==================================================
13. DO NOT IMPLEMENT

Do NOT modify execution behavior.

Do NOT implement:

    continue
    pause
    step_into
    step_over

Do NOT modify:

    CPU execution
    instruction pointer
    CPU flags
    execution loop behavior

Phase 4B is breakpoint management only.


==================================================
14. Completion Criteria

Phase 4B is COMPLETE only when:

[ ] existing DOSBox-X breakpoint mechanism identified
[ ] no second breakpoint system created
[ ] breakpoint.set works
[ ] breakpoint.delete works
[ ] breakpoint.list works
[ ] invalid addresses rejected
[ ] nonexistent breakpoint rejected
[ ] duplicate behavior defined
[ ] native error codes preserved
[ ] Python client works
[ ] MCP tools work
[ ] live DOSBox-X test passes
[ ] GUI breakpoint state matches MCP
[ ] all previous tests pass
[ ] no GUI automation used
[ ] no execution control implemented


==================================================
15. Final Report

Report:

1. Existing DOSBox-X breakpoint implementation used
2. C++ files modified
3. Python files modified
4. MCP tools added
5. Breakpoint ID strategy
6. Thread-safety design
7. Error codes
8. pytest result
9. live DOSBox-X result
10. MCP Inspector result
11. GUI consistency result
12. known limitations
13. recommendation for Phase 4C


==================================================
STOP CONDITION
==================================================

STOP after Phase 4B.

Do NOT proceed to continue/pause/step.

Do not claim completion unless the tests and live
DOSBox-X verification actually passed.
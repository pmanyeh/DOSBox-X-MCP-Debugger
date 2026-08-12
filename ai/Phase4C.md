Phase 4B has been reviewed and APPROVED.

Proceed to PHASE 4C ONLY.

==================================================
PHASE 4C — REAL DOSBox-X EXECUTION CONTROL
==================================================

Objective:

Expose the EXISTING DOSBox-X debugger execution control
through the Native AI Bridge.

Implement ONLY:

    continue_execution
    pause_execution

Do NOT implement:

    step_into
    step_over

Those belong to Phase 4D.

==================================================
CRITICAL REQUIREMENT
==================================================

Before modifying any C++ code, inspect and document the
existing DOSBox-X execution/debugger control flow.

Trace the actual relationship between:

    DEBUG_Loop()
    DEBUG_Run()
    CPU execution loop
    debugger stop state
    breakpoint hit handling
    existing continue command
    existing pause/stop mechanism

Do NOT invent a parallel execution engine.

Reuse the existing DOSBox-X debugger semantics whenever
possible.

==================================================
1. ARCHITECTURE

Maintain:

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
    DOSBox-X debugger/emulator state


The socket thread must NOT directly manipulate CPU
execution state.

All state transitions must occur through the existing
thread-safe request mechanism.

==================================================
2. continue_execution
==================================================

Implement:

    execution.continue

Python:

    DOSBoxClient.continue_execution()

MCP:

    continue_execution


Expected behavior:

When DOSBox-X is stopped in the debugger:

    continue_execution()
        ↓
    DOSBox-X resumes guest execution


Do not merely return success.

The guest CPU must actually resume execution.


==================================================
3. pause_execution
==================================================

Implement:

    execution.pause

Python:

    DOSBoxClient.pause_execution()

MCP:

    pause_execution


Expected behavior:

When DOSBox-X is executing guest code:

    pause_execution()
        ↓
    DOSBox-X enters debugger/stopped state


Do not merely return success.

The guest CPU must actually stop.


==================================================
4. STATE MODEL
==================================================

Define and document the execution states exposed
through the bridge.

At minimum distinguish:

    stopped
    running

If the existing DOSBox-X debugger has more precise
states, preserve them.

Update:

    get_debug_status()

so the AI can determine whether the emulator is:

    running
    stopped

Do not fabricate state in Python.

The reported state must originate from the actual
DOSBox-X execution/debugger state.


==================================================
5. BREAKPOINT INTEGRATION
==================================================

Phase 4B already provides:

    set_breakpoint()
    delete_breakpoint()
    list_breakpoints()

Use those existing REAL DOSBox-X breakpoints.

Required end-to-end scenario:

    1. DOSBox-X starts stopped
    2. AI sets a breakpoint
    3. AI calls continue_execution()
    4. Guest code executes
    5. Breakpoint is hit
    6. DOSBox-X stops
    7. AI calls get_debug_status()
    8. AI calls get_cpu_state()
    9. AI calls get_current_instruction()

The test must prove that the breakpoint actually
stopped execution.


==================================================
6. IMPORTANT: DO NOT FAKE EXECUTION

Do NOT implement:

    sleep()
    timer-based fake stop
    Python-side execution simulation
    artificial breakpoint events
    fake CPU advancement

The guest CPU must actually execute inside DOSBox-X.


==================================================
7. PAUSE TEST

Create a deterministic live test where DOSBox-X is
executing guest code.

Call:

    pause_execution()

Then verify:

    get_debug_status()
        ↓
    stopped


and verify that CPU state is readable.

Do not assume that receiving a successful RPC response
means the CPU stopped.


==================================================
8. CONTINUE TEST

Create a deterministic live test:

    stopped
        ↓
    continue_execution()
        ↓
    running


Verify through get_debug_status().

Then pause it:

    running
        ↓
    pause_execution()
        ↓
    stopped


==================================================
9. BREAKPOINT TEST

Create a deterministic test program or existing DOSBox-X
test environment where a known instruction address can
be executed.

Sequence:

    set_breakpoint(address)

    continue_execution()

    wait for breakpoint hit

    get_debug_status()

    get_cpu_state()

    get_current_instruction()


Verify:

    execution stopped
    current instruction corresponds to the breakpoint
    CPU state is real DOSBox-X state


Do not rely only on a timeout.


==================================================
10. CONCURRENCY

Test at least:

    connection A:
        continue

    connection B:
        status

and:

    connection A:
        pause

    connection B:
        status


The implementation must not:

    deadlock
    crash
    corrupt state
    lose requests


Document request serialization semantics.

==================================================
11. ERROR HANDLING

Define stable native error codes for invalid state
transitions.

At minimum consider:

    ALREADY_RUNNING
    ALREADY_STOPPED
    EXECUTION_TIMEOUT
    EXECUTION_STATE_ERROR
    INVALID_PARAMETER
    INTERNAL_ERROR


Do not collapse specific errors into:

    DOSBOX_PROTOCOL_ERROR


Preserve native error codes through:

    Native Bridge
        ↓
    DOSBoxClient
        ↓
    MCP


==================================================
12. MCP INSPECTOR

Verify:

    tools/list

contains:

    continue_execution
    pause_execution


Then use MCP Inspector to execute them against a live
DOSBox-X instance.

==================================================
13. GUI CONSISTENCY

No GUI automation.

Manual verification only.

Verify that:

    MCP continue_execution()
        ↓
    DOSBox-X debugger actually leaves stopped state


and:

    MCP pause_execution()
        ↓
    DOSBox-X debugger actually returns to stopped state


The existing DOSBox-X debugger GUI must remain functional.

==================================================
14. REGRESSION

Run:

    .\.venv\Scripts\python.exe -m pytest


All previous tests must pass:

    Phase 2
    Phase 3C
    Phase 4A
    Phase 4B


==================================================
15. SOURCE CHANGES

Before modifying source, document:

    - existing DOSBox-X execution flow
    - existing continue mechanism
    - existing pause mechanism
    - breakpoint-to-debugger transition
    - thread on which each operation occurs

Update:

    docs/dosbox-ai-bridge.md


==================================================
16. DO NOT IMPLEMENT

Do NOT implement:

    step_into
    step_over

Do NOT modify:

    EIP write permissions
    CS write permissions
    ESP write permissions
    EFLAGS write permissions

Do NOT create:

    second CPU execution loop
    second breakpoint system
    Python execution simulator


==================================================
17. COMPLETION CRITERIA

Phase 4C is COMPLETE only when:

[ ] existing DOSBox-X execution flow documented
[ ] continue_execution implemented
[ ] pause_execution implemented
[ ] real running/stopped state exposed
[ ] continue actually resumes guest execution
[ ] pause actually stops guest execution
[ ] breakpoint + continue works
[ ] breakpoint hit returns control to debugger
[ ] CPU state after breakpoint is real
[ ] current instruction is real
[ ] concurrent status/control requests are safe
[ ] stable native errors exist
[ ] Python client works
[ ] MCP tools work
[ ] MCP Inspector verified
[ ] GUI remains functional
[ ] all previous tests pass
[ ] no GUI automation
[ ] step functionality NOT implemented


==================================================
18. FINAL REPORT

Report:

1. Existing DOSBox-X execution flow
2. Existing debugger continue mechanism
3. Existing debugger pause mechanism
4. C++ files modified
5. Python files modified
6. Native methods
7. MCP tools
8. execution state model
9. threading model
10. error codes
11. continue test result
12. pause test result
13. breakpoint integration result
14. MCP Inspector result
15. GUI consistency result
16. pytest result
17. limitations
18. recommendation for Phase 4D


==================================================
STOP CONDITION

STOP after Phase 4C.

Do NOT implement step_into or step_over.

Do not claim completion unless real DOSBox-X execution
has been observed to resume and stop.
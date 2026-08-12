Phase 4C has been reviewed and APPROVED.

Proceed to PHASE 4D ONLY.

==================================================
PHASE 4D — REAL DOSBox-X SINGLE-STEP CONTROL
==================================================

Objective:

Expose the EXISTING DOSBox-X debugger single-step
semantics through the Native AI Bridge.

Implement ONLY:

    step_into
    step_over

Do NOT implement Phase 5 autonomous AI debugging.

==================================================
1. SOURCE ANALYSIS FIRST
==================================================

Before modifying C++ source, inspect and document the
existing DOSBox-X debugger implementation for:

    single-step
    step
    trace
    step-over
    temporary breakpoint
    instruction execution
    debugger stop/re-entry

Determine exactly how the existing DOSBox-X debugger
implements:

    Step Into
    Step Over

Reuse the existing mechanism whenever possible.

Do NOT invent a parallel CPU stepping mechanism.

Document findings in:

    docs/dosbox-ai-bridge.md


==================================================
2. STEP INTO
==================================================

Implement:

    execution.step_into

Python:

    DOSBoxClient.step_into()

MCP:

    step_into


Required semantics:

If DOSBox-X is stopped:

    step_into()
        ↓
    execute exactly one guest instruction
        ↓
    return to stopped debugger state


After the operation:

    get_debug_status()
        => stopped

and:

    get_cpu_state()
    get_current_instruction()

must describe the new execution position.


Do NOT implement this as:

    EIP += 1

or any Python-side instruction simulation.

The real DOSBox-X CPU decoder/execution path must
execute the instruction.


==================================================
3. STEP OVER
==================================================

Implement:

    execution.step_over

Python:

    DOSBoxClient.step_over()

MCP:

    step_over


Required semantics:

For a normal instruction:

    execute one instruction
    stop at next instruction


For a CALL-like instruction:

    CALL target
        ↓
    execute the call/subroutine
        ↓
    stop at instruction after CALL


The implementation must follow the semantics of the
existing DOSBox-X debugger.

Do NOT invent an independent call-depth tracker unless
the existing DOSBox-X debugger itself uses one.


==================================================
4. CPU STATE

After both operations verify:

    get_debug_status()
    get_cpu_state()
    get_current_instruction()

The returned values must come from REAL DOSBox-X state.

Do not fabricate the new EIP in Python.


==================================================
5. DETERMINISTIC TEST PROGRAM

Create or use a deterministic DOS test program that
contains at least:

    ordinary instruction
    CALL
    return

Example conceptual flow:

    instruction A
    instruction B
    CALL function
    instruction C
    ...
    function:
        instruction D
        RET


The exact assembly is implementation-dependent.

Use a deterministic known execution location.


==================================================
6. STEP INTO TEST

Required:

    stopped at instruction A
        ↓
    step_into()
        ↓
    stopped at instruction B


Verify:

    EIP / CS:EIP changed correctly
    current instruction changed correctly
    CPU remains stopped


==================================================
7. STEP OVER TEST

Required:

    stopped at CALL
        ↓
    step_over()
        ↓
    stopped at instruction after CALL


Verify that execution did NOT stop inside the called
function unless that is the documented behavior of the
existing DOSBox-X debugger.

Use the existing debugger's semantics as authoritative.


==================================================
8. ERROR HANDLING

Define stable errors for invalid execution state.

At minimum consider:

    ALREADY_RUNNING
    ALREADY_STOPPED
    STEP_NOT_AVAILABLE
    EXECUTION_TIMEOUT
    EXECUTION_STATE_ERROR
    INTERNAL_ERROR


Preserve native error codes through:

    Native Bridge
        ↓
    DOSBoxClient
        ↓
    MCP


Do not collapse specific errors into:

    DOSBOX_PROTOCOL_ERROR


==================================================
9. THREADING

Maintain the existing request queue architecture.

The socket thread must NOT execute guest instructions.

All stepping must execute on the DOSBox-X emulator /
debugger thread.

Verify multiple simultaneous MCP connections do not
corrupt debugger state.


==================================================
10. BREAKPOINT INTERACTION

Verify behavior when a breakpoint exists near the
instruction being stepped.

The existing DOSBox-X debugger semantics are authoritative.

Do not create a second breakpoint system.


==================================================
11. MCP INSPECTOR

Verify tools/list contains:

    step_into
    step_over


Then use MCP Inspector against a live DOSBox-X instance.

Verify actual CPU movement.


==================================================
12. GUI CONSISTENCY

No GUI automation.

Manual verification only.

After MCP:

    step_into()

verify the DOSBox-X debugger GUI reflects the new
instruction position.

After MCP:

    step_over()

verify the GUI reflects the correct post-step position.


==================================================
13. REGRESSION

Run:

    .\.venv\Scripts\python.exe -m pytest


All previous tests must remain passing:

    Phase 2
    Phase 3C
    Phase 4A
    Phase 4B
    Phase 4C


==================================================
14. SOURCE CHANGES

Report:

    existing DOSBox-X step implementation
    existing DOSBox-X step-over implementation
    C++ files modified
    Python files modified
    Native methods
    MCP tools
    thread execution model


==================================================
15. COMPLETION CRITERIA

Phase 4D is COMPLETE only when:

[ ] existing step mechanism identified
[ ] existing step-over mechanism identified
[ ] no parallel CPU stepping engine created
[ ] step_into works on REAL DOSBox-X
[ ] step_over works on REAL DOSBox-X
[ ] CPU remains stopped after each operation
[ ] CS:EIP changes correctly
[ ] current instruction changes correctly
[ ] CALL/step-over behavior verified
[ ] CPU state is real DOSBox-X state
[ ] thread safety verified
[ ] native errors preserved
[ ] Python API works
[ ] MCP tools work
[ ] MCP Inspector verified
[ ] GUI consistency manually verified
[ ] all previous tests pass
[ ] no GUI automation
[ ] Phase 5 NOT implemented


==================================================
16. FINAL REPORT

Report:

1. Existing DOSBox-X step implementation
2. Existing DOSBox-X step-over implementation
3. C++ files modified
4. Python files modified
5. Native API
6. Python API
7. MCP tools
8. thread model
9. error codes
10. step_into test
11. step_over test
12. CALL test
13. MCP Inspector result
14. GUI consistency result
15. pytest result
16. limitations
17. recommendation for Phase 5


==================================================
STOP CONDITION

STOP after Phase 4D.

Do NOT implement autonomous AI debugging.

Do not claim completion unless actual DOSBox-X
instruction execution has been observed.
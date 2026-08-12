# DOSBox-X-AI Phase 3
# Native DOSBox-X Debugger Bridge

## Status

Phase 1: COMPLETE

Phase 2: COMPLETE

Phase 3: IN PROGRESS


# 1. Objective

Replace the Phase 2 FakeDOSBoxDebugger with the REAL
DOSBox-X debugger state.

The final architecture must become:

    AI Agent
        |
        | MCP
        v
    Python MCP Server
        |
        | localhost IPC
        v
    Native DOSBox-X AI Bridge
        |
        v
    DOSBox-X Debugger Core
        |
        +---- CPU
        +---- Memory
        +---- Disassembler
        +---- Breakpoints
        +---- Execution Control


The existing DOSBox-X debugger GUI must continue to work.

Do NOT replace the debugger GUI.

Do NOT automate the GUI.

The AI must access the same underlying debugger state used by DOSBox-X itself.


# 2. Critical Rule

Before modifying DOSBox-X source code:

READ AND UNDERSTAND THE EXISTING DEBUGGER IMPLEMENTATION.

Do not guess internal APIs.

Do not blindly create new CPU/register abstractions.

Do not duplicate existing debugger logic if an existing DOSBox-X
function already provides the required functionality.


# 3. Source Location

DOSBox-X source should be located at:

    D:\git\DOSBox-X-AI\dosbox-src\


Do not modify:

    .venv\
    ai\Fake debugger implementation

until the native bridge design has been validated.


# 4. First Task: Source Inspection

Inspect the DOSBox-X source tree.

Locate:

    src/debug/

At minimum investigate:

    debug.cpp
    debug_gui.cpp
    debug.h


Also identify:

    CPU register state
    memory access
    instruction decoding/disassembly
    breakpoint management
    debugger execution state
    single-step implementation
    debugger command processing
    main emulator execution loop


Search the entire source tree where necessary.

Do not assume the exact file names above exist unchanged.


# 5. Required Research Report

Before implementing the bridge, create:

    docs/dosbox-debugger-analysis.md


Document:

## 5.1 Debugger entry points

How does DOSBox-X enter debugger mode?

## 5.2 Debugger command processing

How are commands such as:

    step
    next
    break
    memory
    registers

implemented?

## 5.3 CPU state

Where are registers stored?

How are they accessed safely?

## 5.4 EIP / CS

How does the debugger obtain:

    CS
    EIP

and other segment registers?

## 5.5 Memory

What existing functions should be used for:

    memory read
    memory write

## 5.6 Disassembly

Which existing DOSBox-X functions perform instruction
decoding/disassembly?

## 5.7 Breakpoints

How are breakpoints represented and managed?

## 5.8 Execution control

How does:

    continue
    pause
    single-step
    step-over

work?

## 5.9 Thread / execution context

Determine which thread/context owns the emulator state.

This is critical.

Document whether bridge commands can safely execute
directly or must be queued into the emulator execution thread.


# 6. Phase 3 Gate A

STOP after creating:

    docs/dosbox-debugger-analysis.md

At this point do NOT modify DOSBox-X source.

Report:

1. debugger source files found
2. CPU state access method
3. memory access method
4. disassembly method
5. breakpoint method
6. single-step method
7. execution thread/context
8. proposed bridge insertion point

Only proceed after the analysis is internally consistent.


# 7. Native Bridge Design

After Gate A, design:

    src/debug/debug_ai.h
    src/debug/debug_ai.cpp


The bridge must be:

LOCAL ONLY.

Bind:

    127.0.0.1

Do NOT bind:

    0.0.0.0


Initial port:

    9876


# 8. IPC Protocol

Use newline-delimited JSON.

Example request:

    {
        "id": 1,
        "method": "debug.status"
    }


Example response:

    {
        "id": 1,
        "ok": true,
        "result": {
            ...
        }
    }


Errors:

    {
        "id": 1,
        "ok": false,
        "error": {
            "code": "INVALID_REQUEST",
            "message": "..."
        }
    }


# 9. Initial Native API

Implement ONLY these operations initially:

    debug.status

    cpu.get

    memory.read

    code.current

    code.disassemble


Do NOT implement memory.write yet.

Do NOT implement register.write yet.

Do NOT implement execution control yet.

The first native bridge must be READ-ONLY.


# 10. debug.status

Return one coherent debugger snapshot.

Example:

    {
        "stopped": true,

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


The implementation must obtain actual values from DOSBox-X.

Do NOT hard-code values.


# 11. cpu.get

Return actual CPU register state.

At minimum:

    EAX
    EBX
    ECX
    EDX
    ESI
    EDI
    EBP
    ESP

    CS
    DS
    ES
    SS
    FS
    GS

    EIP
    EFLAGS


# 12. memory.read

Request:

    {
        "id": 2,
        "method": "memory.read",
        "params": {
            "address": "1234:0100",
            "length": 32
        }
    }


Return actual emulated memory.

Do not read host process memory.

Do not use Windows file APIs to emulate DOS memory.

The data must come from DOSBox-X's emulated memory subsystem.


# 13. code.current

Return the actual instruction currently pointed to by:

    CS:EIP


Example:

    {
        "address": "1234:0100",
        "bytes": "B8 34 12",
        "instruction": "MOV AX,1234h"
    }


Use DOSBox-X's existing debugger/disassembler infrastructure.


# 14. code.disassemble

Request:

    {
        "method": "code.disassemble",
        "params": {
            "address": "1234:0100",
            "count": 10
        }
    }


Return:

    [
        {
            "address": "1234:0100",
            "bytes": "...",
            "instruction": "..."
        }
    ]


Do not create a second x86 disassembler unless absolutely necessary.


# 15. Thread Safety

This is a critical requirement.

The bridge must NOT blindly access emulator CPU state
from a socket thread if DOSBox-X's architecture does not permit it.

If required, implement:

    socket thread
          |
          v
    debugger request queue
          |
          v
    emulator/debugger thread
          |
          v
    actual CPU state


Responses must be synchronized safely.


# 16. Existing Debugger Compatibility

The bridge must not break:

    DOSBox-X debugger GUI
    debugger commands
    breakpoints
    single-step
    normal emulator execution


Existing debugger behavior takes priority over the AI bridge.


# 17. Build Gate

Before adding Python integration:

Build DOSBox-X with the native bridge.

The build must complete successfully.

The normal DOSBox-X executable must launch.


# 18. Runtime Gate

Start DOSBox-X with the native bridge enabled.

Verify that:

    127.0.0.1:9876

is listening.

Verify that the DOSBox-X debugger still launches normally.


# 19. Manual Protocol Test

Before MCP integration, test the native bridge directly.

Use a small Python test client:

    tests/test_native_bridge.py


It should send:

    debug.status

    cpu.get

    memory.read

    code.current

    code.disassemble


The test must verify:

- valid JSON
- request IDs
- response IDs
- ok/error status
- real debugger values


# 20. No Fake Data

At this stage:

DO NOT return:

    hard-coded registers
    hard-coded CS:EIP
    fake memory
    fake disassembly
    simulated breakpoints


Every returned debugger value must originate from
the running DOSBox-X instance.


# 21. Python Native Client

After the native bridge works independently, create:

    ai/dosbox_client.py


Implement:

    connect()
    request()
    get_debug_status()
    get_cpu_state()
    read_memory()
    get_current_instruction()
    disassemble()


Use:

    127.0.0.1:9876


with connection timeout and request timeout.


# 22. Replace Fake Debugger

Modify:

    ai/server.py


so that the MCP tools use:

    DOSBoxClient


instead of:

    FakeDOSBoxDebugger


Do not delete FakeDOSBoxDebugger yet.

Keep it available for unit testing.


# 23. MCP Tools in Phase 3

Expose:

    get_debug_status
    get_cpu_state
    read_memory
    get_current_instruction
    disassemble


The MCP tool names must remain compatible with Phase 2.


# 24. End-to-End Test

The final Phase 3 test should be:

    AI Agent
       |
       v
    MCP
       |
       v
    Python DOSBoxClient
       |
       v
    TCP 127.0.0.1:9876
       |
       v
    DOSBox-X
       |
       v
    Real debugger state


The AI requests:

    get_debug_status()


The returned values must match the debugger state shown
by DOSBox-X.


# 25. Human Verification

Start DOSBox-X.

Enter debugger mode.

Stop execution at a known location.

Observe:

    CS
    EIP
    registers
    current instruction


Then call MCP:

    get_debug_status()


Compare:

    GUI debugger state
    MCP state


They must represent the same underlying state.


# 26. Phase 3 Scope Limitation

DO NOT implement yet:

    memory.write
    register.write
    breakpoint.set
    breakpoint.delete
    continue_execution
    pause_execution
    step_into
    step_over


These are Phase 4 operations.

Phase 3 is READ-ONLY.


# 27. Phase 3 Security

The native bridge must:

- bind only to 127.0.0.1
- validate every request
- validate JSON
- reject unknown methods
- reject malformed parameters
- enforce reasonable request sizes
- enforce timeouts where appropriate


# 28. Logging

Add native bridge logging.

Log:

    connection
    request
    response
    errors


Do not dump large memory blocks into logs by default.


# 29. Error Codes

Use stable error codes.

At minimum:

    INVALID_JSON
    INVALID_REQUEST
    UNKNOWN_METHOD
    INVALID_PARAMETER
    DEBUGGER_NOT_STOPPED
    MEMORY_ERROR
    INTERNAL_ERROR


# 30. Phase 3 Completion Criteria

Phase 3 is COMPLETE only when:

[ ] DOSBox-X source has been analyzed
[ ] docs/dosbox-debugger-analysis.md exists
[ ] native bridge exists
[ ] DOSBox-X builds successfully
[ ] DOSBox-X launches successfully
[ ] normal debugger GUI still works
[ ] bridge listens only on 127.0.0.1
[ ] debug.status returns real values
[ ] cpu.get returns real registers
[ ] memory.read returns real emulated memory
[ ] code.current returns real instruction
[ ] code.disassemble returns real disassembly
[ ] native bridge can be tested independently
[ ] Python DOSBoxClient works
[ ] MCP tools use real DOSBox-X state
[ ] GUI state matches MCP state
[ ] no fake debugger data is used in Phase 3
[ ] no GUI automation is used


# 31. Required Final Report

When Phase 3 is complete, report:

1. DOSBox-X source version
2. files inspected
3. files modified
4. native bridge architecture
5. IPC protocol
6. build command
7. build result
8. DOSBox-X runtime result
9. native bridge test result
10. MCP test result
11. example real CPU state
12. example real CS:EIP
13. example real instruction
14. example memory read
15. GUI/MCP consistency result
16. known limitations
17. recommendation for Phase 4


# 32. Critical Stop Conditions

STOP immediately and report if:

- DOSBox-X source architecture is unclear
- CPU state cannot be safely accessed
- debugger thread ownership is unclear
- modifying debugger source breaks existing debugger behavior
- build fails
- bridge causes DOSBox-X instability
- GUI debugger no longer works
- returned data is not actually from DOSBox-X
- a second disassembler appears necessary without justification


# 33. Phase 3 Philosophy

Prefer:

    integrate with existing DOSBox-X debugger

over:

    recreate the debugger.

Prefer:

    expose existing debugger functionality

over:

    implement duplicate functionality.

Prefer:

    small native bridge

over:

    large invasive modification.

Prefer:

    read-only first

over:

    immediate execution control.

The objective is to establish a reliable bridge between
AI and the REAL DOSBox-X debugger.
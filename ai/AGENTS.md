# DOSBox-X-AI Agent Project Specification

## 1. Project Identity

Project name:

    DOSBox-X-AI

Project root:

    D:\git\DOSBox-X-AI

Primary goal:

Build an AI-controllable DOSBox-X debugger.

The final system must allow an AI Agent, through MCP tools, to inspect and control the DOSBox-X debugger while the normal DOSBox-X debugger GUI remains available to the human user.

The intended architecture is:

    AI Agent
        |
        | MCP
        v
    Python MCP Server
        |
        | localhost IPC
        v
    DOSBox-X AI Bridge
        |
        v
    DOSBox-X Debugger
        |
        v
    x86 Emulator


The human should continue to use the normal DOSBox-X debugger GUI.

The AI should operate through structured tools instead of keyboard/mouse automation whenever possible.


# 2. Important Engineering Principles

## 2.1 Do NOT automate the GUI

Do not use:

- screen scraping
- OCR
- simulated mouse clicks
- simulated keyboard input
- GUI automation

for the core debugger functionality.

The goal is to expose the internal DOSBox-X debugger state directly to the AI.


## 2.2 Preserve the existing DOSBox-X debugger GUI

The normal DOSBox-X debugger UI must continue to work.

The AI interface is an additional control interface.

The architecture should therefore be:

    Human
      |
      v
    DOSBox-X Debugger GUI
      |
      |
    Debugger Core
      |
      |
    CPU / Memory / Emulator
      ^
      |
    AI Bridge
      ^
      |
    MCP Server
      ^
      |
    AI Agent


## 2.3 Thread safety

The AI bridge must NOT directly manipulate emulator CPU state from an arbitrary network thread.

Do NOT create a design where:

    AI thread
        |
        +--> directly modify CPU registers

Instead use a request queue or equivalent mechanism:

    AI/MCP thread
        |
        v
    AI request queue
        |
        v
    DOSBox-X emulator/debugger thread
        |
        v
    CPU / memory / debugger state


All operations that modify emulator state must execute in the correct DOSBox-X execution context.


## 2.4 Security

The AI debugger bridge must bind only to:

    127.0.0.1

Do NOT expose the debugger control interface to:

    0.0.0.0

or the LAN.

Read-only operations should be separated conceptually from state-changing operations.

Future destructive operations such as:

- memory write
- register write
- patching
- file manipulation

must have explicit permission controls.


# 3. Current Environment

The development environment is Windows.

Project root:

    D:\git\DOSBox-X-AI

Python:

    Python 3.12

Python virtual environment:

    D:\git\DOSBox-X-AI\.venv

MCP version currently installed:

    MCP 2.0.0

The MCP executable is:

    .\.venv\Scripts\mcp.exe

The Python executable is:

    .\.venv\Scripts\python.exe

PowerShell activation may be restricted by Execution Policy.

Therefore commands should NOT assume that:

    .\.venv\Scripts\Activate.ps1

can be executed.

Prefer direct execution:

    .\.venv\Scripts\python.exe

and:

    .\.venv\Scripts\mcp.exe


# 4. DOSBox-X Version

Target DOSBox-X version:

    2026.07.02

Official project:

    https://github.com/joncampbell123/dosbox-x

Do not silently switch to another DOSBox fork.

Do not modify DOSBox-X source until the Python/MCP layer has passed its initial tests.


# 5. Initial Project Layout

Create/maintain:

    D:\git\DOSBox-X-AI\
    |
    +-- .venv\
    |
    +-- ai\
    |   +-- server.py
    |   +-- debugger.py
    |   +-- protocol.py
    |   +-- dosbox_client.py
    |
    +-- tests\
    |
    +-- drive_c\
    |
    +-- dosbox\
    |
    +-- dosbox-src\
    |
    +-- README.md
    +-- AGENTS.md
    +-- requirements.txt
    +-- .gitignore


Do not create unnecessary files.


# 6. Phase 0 - Environment Verification

Before modifying source code, verify:

    .\.venv\Scripts\python.exe --version

Expected:

    Python 3.12.x

Verify:

    .\.venv\Scripts\mcp.exe version

Expected:

    MCP version 2.0.0

Verify:

    node --version

Verify:

    npm --version

Verify:

    npx --version


If Node.js/npm/npx are missing:

STOP and report that Node.js LTS is required.

Do not attempt to install system software silently.

The developer can install Node.js from:

    https://nodejs.org/


# 7. Phase 1 - Python MCP Server

Create:

    ai/server.py

Use MCP SDK 2.x APIs.

Do NOT use deprecated MCP v1 examples unless explicitly required.

The first server must expose:

    ping()
    get_project_status()


The server name should be:

    DOSBox-X AI Debugger


Example behavior:

    ping()

returns:

    "DOSBox-X AI Debugger is alive."


get_project_status() should return structured information such as:

    {
        "project": "DOSBox-X AI Debugger",
        "phase": "P1",
        "dosbox_bridge": "not connected",
        "debugger": "not connected",
        "mcp": "online"
    }


# 8. Phase 1 Validation

Run:

    .\.venv\Scripts\mcp.exe dev .\ai\server.py

This requires Node.js/npx.

Use MCP Inspector to verify:

    ping
    get_project_status

Both tools must execute successfully.

Do not proceed to DOSBox-X source integration until these tools work.


# 9. Phase 2 - Fake Debugger

Create:

    ai/debugger.py


Implement a temporary FakeDOSBoxDebugger.

The fake debugger is only for validating the MCP interface.

It should expose methods equivalent to:

    get_cpu_state()
    get_current_instruction()
    read_memory()
    step_into()
    run()


Example CPU state:

    {
        "eax": "00000000",
        "ebx": "00000000",
        "ecx": "00000000",
        "edx": "00000000",
        "esi": "00000000",
        "edi": "00000000",
        "ebp": "00000000",
        "esp": "00000000",
        "cs": "F000",
        "eip": "FFF0",
        "ds": "0000",
        "es": "0000",
        "ss": "0000"
    }


Example current instruction:

    {
        "address": "F000:FFF0",
        "bytes": "EA 5B E0 00 F0",
        "instruction": "JMP F000:E05B"
    }


# 10. Phase 2 MCP Tools

Expose these MCP tools:

    get_cpu_state()
    get_current_instruction()
    read_memory(address, length)
    step_into()
    continue_execution()


All tools must return structured JSON-compatible data.

Do not return unstructured console output when structured information is available.


# 11. Phase 2 Validation

MCP Inspector must show:

    ping
    get_project_status
    get_cpu_state
    get_current_instruction
    read_memory
    step_into
    continue_execution


Every tool must be callable without Python exceptions.


# 12. Phase 3 - DOSBox-X Source Integration

Only start this phase after Phase 1 and Phase 2 pass.

Obtain DOSBox-X source for the target version.

Place source under:

    D:\git\DOSBox-X-AI\dosbox-src\


Do not overwrite the portable binary directory.

Keep:

    dosbox\

and:

    dosbox-src\

separate.


# 13. DOSBox-X Debugger Architecture

Investigate the existing DOSBox-X debugger implementation before modifying it.

Relevant areas include:

    src/debug/

Especially inspect:

    debug.cpp
    debug_gui.cpp
    debug.h

Do not assume the exact internal APIs.

Read the existing source and determine:

1. debugger command execution
2. CPU register access
3. memory access
4. disassembly
5. breakpoint implementation
6. single-step implementation
7. emulator/main-loop execution context


Do not blindly patch source based on assumptions.


# 14. Native AI Bridge

Implement a native DOSBox-X AI bridge.

Possible files:

    src/debug/debug_ai.cpp
    src/debug/debug_ai.h

The bridge should expose a localhost-only IPC interface.

Preferred initial transport:

    TCP
    127.0.0.1
    port 9876

Keep the protocol simple.

Use newline-delimited JSON.

Example request:

    {
        "id": 1,
        "method": "cpu.get"
    }


Example response:

    {
        "id": 1,
        "ok": true,
        "result": {
            "eax": "00000000",
            "ebx": "00000000",
            "cs": "1234",
            "eip": "0100"
        }
    }


# 15. Native Bridge API

Initial API:

    cpu.get

    debug.status

    memory.read

    memory.write

    code.current

    code.disassemble

    breakpoint.set

    breakpoint.delete

    breakpoint.list

    execution.run

    execution.pause

    execution.step_into

    execution.step_over


# 16. Debug Status

The most important API should be:

    debug.status


It should provide a coherent debugger snapshot.

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
        }
    }


The AI should be able to obtain most important debugger state with one call.


# 17. MCP-to-Native Bridge Client

Replace FakeDOSBoxDebugger with a real client.

Create:

    ai/protocol.py

Responsibilities:

    connect to 127.0.0.1:9876
    send JSON request
    receive JSON response
    validate response
    handle connection errors
    handle request timeout


Create:

    ai/dosbox_client.py

Responsibilities:

    cpu()
    status()
    read_memory()
    write_memory()
    disassemble()
    set_breakpoint()
    delete_breakpoint()
    list_breakpoints()
    run()
    pause()
    step_into()
    step_over()


The MCP server should call this client instead of accessing DOSBox-X directly.


# 18. MCP Tool Layer

The MCP server should expose high-level tools.

Initial tools:

    get_cpu_state
    get_debug_status
    read_memory
    disassemble
    set_breakpoint
    delete_breakpoint
    list_breakpoints
    continue_execution
    pause_execution
    step_into
    step_over


The MCP tool names should remain stable even if the internal IPC implementation changes.


# 19. Error Handling

All layers must return useful errors.

Example:

    {
        "ok": false,
        "error": {
            "code": "DOSBOX_NOT_CONNECTED",
            "message": "DOSBox-X AI bridge is not reachable at 127.0.0.1:9876"
        }
    }


Do not expose Python stack traces to the AI as normal tool output.

Log detailed stack traces locally for developers.


# 20. Read-only vs Write Operations

Classify tools:

READ ONLY:

    get_cpu_state
    get_debug_status
    read_memory
    disassemble
    list_breakpoints


EXECUTION CONTROL:

    continue_execution
    pause_execution
    step_into
    step_over


STATE MODIFICATION:

    write_memory
    write_register
    set_breakpoint
    delete_breakpoint


Future destructive operations must not be enabled by default.


# 21. Breakpoint Design

Support at least:

    CS:EIP

and preferably linear physical/emulated addresses where appropriate.

The MCP layer should accept human-friendly addresses.

Examples:

    "1234:0100"
    "F000:FFF0"


The native layer should perform address parsing and validation.


# 22. Memory Read Design

Example:

    read_memory(
        address="1234:0100",
        length=64
    )


Return:

    {
        "address": "1234:0100",
        "length": 64,
        "bytes": [
            "B8",
            "34",
            "12",
            ...
        ]
    }


Do not silently read beyond valid emulated memory.


# 23. Disassembly

Expose:

    disassemble(address, count)


Example:

    disassemble(
        address="1234:0100",
        count=10
    )


Return a structured list:

    [
        {
            "address": "1234:0100",
            "bytes": "B8 34 12",
            "instruction": "MOV AX,1234h"
        },
        ...
    ]


# 24. Single Step

The AI must be able to perform:

    step_into()


After stepping, it should normally call:

    debug.status


to obtain the new state.

The native implementation must execute the operation in the correct DOSBox-X debugger/emulator context.


# 25. Step Over

Implement:

    step_over()


Do not fake step-over behavior in Python.

It should use or integrate with the actual DOSBox-X debugger semantics whenever possible.


# 26. Test Program

Create a minimal DOS COM program for testing.

Example assembly logic:

    ORG 100h

    MOV AX,1234h
    MOV BX,5678h
    ADD AX,BX

    MOV AH,4Ch
    INT 21h


The resulting:

    TEST.COM

should be placed under:

    drive_c\


# 27. Debugging Scenario

The final system must support this workflow:

Human starts DOSBox-X.

Human launches:

    DEBUGBOX TEST.COM

The DOSBox-X debugger stops at the program entry point.

The AI Agent calls:

    get_debug_status()


AI receives:

    CS:EIP
    instruction
    registers
    segments


AI calls:

    step_into()


AI calls:

    get_debug_status()


AI can explain the instruction transition.


# 28. Expected AI Debugging Workflow

The AI should be capable of reasoning like:

    1. Read current debugger state.
    2. Inspect current instruction.
    3. Inspect relevant registers.
    4. Decide whether to step or continue.
    5. Execute debugger operation.
    6. Read new debugger state.
    7. Compare before/after state.
    8. Explain what changed.
    9. Continue investigation.


Do not make the AI blindly execute hundreds of steps.

Prefer state-aware debugging.


# 29. Logging

Create:

    logs\


Log:

    MCP requests
    MCP responses
    native bridge requests
    native bridge responses
    debugger events
    errors


Do not log sensitive host data unnecessarily.


# 30. Development Rules

Before changing code:

1. Inspect existing files.
2. Understand current implementation.
3. Make the smallest change required.
4. Run tests.
5. Report failures.
6. Do not silently work around failures.


Never delete existing source files unless explicitly instructed.


# 31. Git

Initialize git if the repository is not already initialized.

Recommended .gitignore:

    .venv/
    __pycache__/
    *.pyc
    logs/
    build/
    dist/
    *.o
    *.obj
    *.exe
    *.dll


Do NOT commit:

    .venv

Do NOT commit generated build artifacts unless explicitly required.


# 32. Python Dependencies

Maintain:

    requirements.txt


Pin major versions where compatibility matters.

MCP must remain on:

    2.x


Do not downgrade to MCP 1.x to make old examples work.


# 33. Validation Commands

Python validation:

    .\.venv\Scripts\python.exe --version


MCP validation:

    .\.venv\Scripts\mcp.exe version


MCP Inspector:

    .\.venv\Scripts\mcp.exe dev .\ai\server.py


Python syntax:

    .\.venv\Scripts\python.exe -m compileall .\ai


Unit tests:

    .\.venv\Scripts\python.exe -m pytest


# 34. Agent Behavior

The coding agent should operate incrementally.

After each major phase:

1. Run validation.
2. Check result.
3. Stop if validation fails.
4. Report the exact failure.
5. Do not continue into the next phase until the current phase is valid.


The agent should not claim success without actually executing the validation command.


# 35. Current Starting Point

At the beginning of this project:

    Python 3.12 = installed
    .venv = created
    MCP 2.0.0 = installed
    MCP executable = working

Current known issue:

    mcp dev requires npx.

Therefore the next environment check is:

    node --version
    npm --version
    npx --version


If npx is missing, stop and request Node.js LTS installation.

Do not modify the Python environment to solve a missing Node.js installation.


# 36. Immediate Task

The immediate task is ONLY:

1. Verify Node.js.
2. Verify npm.
3. Verify npx.
4. Verify Python 3.12.
5. Verify MCP 2.0.0.
6. Create ai/server.py.
7. Start MCP Inspector.
8. Verify ping().
9. Verify get_project_status().


Do NOT begin DOSBox-X C++ source modifications yet.


# 37. Success Criteria for Phase 1

Phase 1 is complete only when:

    Python 3.12 works
    MCP 2.0.0 works
    Node.js works
    npm works
    npx works
    MCP Inspector starts
    server.py starts
    ping() succeeds
    get_project_status() succeeds


Only after all of the above are confirmed may the agent proceed to Phase 2.


# 38. Final Objective

The final project should allow an AI Agent to perform real DOSBox-X debugger operations:

    inspect CPU
    inspect registers
    inspect memory
    disassemble code
    set breakpoints
    remove breakpoints
    continue
    pause
    single-step
    step-over
    inspect debugger state


while the human continues to see and use the normal DOSBox-X debugger GUI.


The intended final interaction is:

    User:
        "Find why TEST.COM crashes."

    AI:

        get_debug_status()

        read_memory(...)

        disassemble(...)

        set_breakpoint(...)

        continue_execution()

        get_debug_status()

        step_into()

        get_debug_status()

        explain the cause.


The AI must use actual DOSBox-X debugger state, not simulated data, GUI scraping, or keyboard automation.
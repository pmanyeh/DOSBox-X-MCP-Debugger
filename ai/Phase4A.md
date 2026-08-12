Phase 3C has been reviewed and APPROVED.

Proceed to Phase 4A only.

Objective:

Add REAL write access to the DOSBox-X debugger through
the existing Native AI Bridge.

Implement ONLY:

    memory.write
    register.write

Do NOT implement:

    breakpoint.set
    breakpoint.delete
    breakpoint.list
    continue
    pause
    step_into
    step_over

Architecture must remain:

    MCP
      ↓
    ai/server.py
      ↓
    DOSBoxClient
      ↓
    TCP 127.0.0.1:9876
      ↓
    Native DOSBox-X AI Bridge
      ↓
    DOSBox-X debugger/emulator thread

Critical threading rule:

The socket thread must NEVER directly modify:

    CPU state
    registers
    guest memory

All modifications must execute on the DOSBox-X
emulator/debugger thread through the existing
request queue mechanism.

Implement:

Native:

    memory.write
    register.write

Python:

    DOSBoxClient.write_memory()
    DOSBoxClient.write_register()

MCP:

    write_memory
    write_register

Register safety:

Initially allow writes only to:

    EAX
    EBX
    ECX
    EDX
    ESI
    EDI
    EBP

Do NOT allow writing:

    EIP
    CS
    DS
    ES
    SS
    FS
    GS
    ESP
    EFLAGS

unless explicitly supported by existing DOSBox-X
debugger semantics and separately approved.

Memory write:

Validate:

    address
    length
    data
    memory boundaries

The implementation must modify REAL DOSBox-X
guest memory.

Do not use FakeDOSBoxDebugger for production MCP
execution.

Keep FakeDOSBoxDebugger unchanged for Phase 2 tests.

Tests:

1. memory read/write/read round trip
2. register read/write/read round trip
3. invalid address
4. invalid register
5. invalid data
6. thread-safety/request-queue behavior
7. existing Phase 2 tests remain passing
8. existing Phase 3C integration tests remain passing

Run:

    .\.venv\Scripts\python.exe -m pytest

Then run the live DOSBox-X integration tests.

Verify the changed values come from REAL DOSBox-X.

Do not claim completion unless the tests actually pass.

STOP after Phase 4A.

Do NOT proceed to breakpoint or execution control.

Report:

1. files changed
2. Native API changes
3. Python API changes
4. MCP tools
5. register safety rules
6. tests
7. pytest result
8. live DOSBox-X result
9. any limitations
10. recommendation for Phase 4B
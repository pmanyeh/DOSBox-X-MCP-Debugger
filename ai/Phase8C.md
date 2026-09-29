Phase 8C — AGENT-SIDE ANALYSIS TOOLS FOR AUTONOMOUS REVERSE ENGINEERING
==================================================

Objective:

Close the gap between "an agent can inspect/control one instant of the
running guest" (everything through Phase 8A) and "an agent can accumulate
its own reverse-engineering knowledge across a session" -- without adding
a second CPU emulator, a second disassembler, or any new native bridge
method. Every tool in this phase is built by composing the EXISTING
native protocol (memory.read, code.disassemble, cpu.get) from the Python
side (`ai/`), per the user's explicit direction to prefer this over
touching `dosbox-src`.

Four capabilities are in scope, in this build order:

    1. memory_search   (priority 1 -- build and ship first)
    2. symbol/annotation persistent store
    3. call-stack unwinding (SS:BP chain walk)
    4. live recursive-descent static disassembly / control-flow graph

Do NOT implement in this phase:

    - interrupt-level call tracing / BPINT exposure (deferred to Phase 8D,
      a separate phase because it requires native bridge changes to
      debug_ai.cpp and a dosbox-x.exe rebuild+relaunch, unlike this
      phase's four items)
    - vga.watch_writes (already reserved as a separate, previously
      planned "Phase 8B" per docs/phase8a-vga-snapshot-design.md and
      CHANGELOG.md's Phase 8A entry -- not renumbered or touched here)

==================================================
STATUS
==================================================

All four items are IMPLEMENTED:

- Item 1 (memory_search): `ai/analysis.py::search_memory()`, wired up as
  the `memory_search` MCP tool.
- Item 2 (symbol/annotation store): `ai/knowledge.py::KnowledgeStore`,
  wired up as `set_symbol`/`get_symbol`/`delete_symbol`/`list_symbols`/
  `set_comment`/`get_comment`/`add_xref`/`list_xrefs` MCP tools.
- Item 3 (call-stack unwinding): `ai/analysis.py::get_call_stack()`,
  wired up as the `get_call_stack` MCP tool.
- Item 4 (recursive-descent CFG): `ai/analysis.py::build_control_flow_graph()`,
  wired up as the `build_control_flow_graph` MCP tool.

All four are unit-tested (`tests/test_analysis.py`, `tests/test_knowledge.py`)
against stub clients / a temp-file-backed store -- no live DOSBox-X
required. See `docs/phase8c-agent-side-analysis-tools-design.md` for the
full design, including each item's stated scope limitations.

==================================================
CONSTRAINTS (apply to all four items)
==================================================

- No new native bridge method, no new native error code, no change to
  `dosbox-src` at all. If any of items 2-4 turns out to need one, stop
  and raise it for a separate decision before writing C++ -- do not fold
  a native change into this phase silently.
- No new required external dependency (no capstone or similar) -- this
  was an explicit decision (see docs/phase8c-...-design.md, "Static
  disassembly architecture decision") in favor of a live recursive-descent
  walk over already-loaded guest memory, using the existing
  `code.disassemble`/`read_memory` tools, rather than an offline
  file-format parser.
- Persistent state (the symbol/annotation store) lives entirely on the
  Python/agent side -- never inside DOSBox-X or the native bridge, and
  never assumed to survive a DOSBox-X restart unless explicitly saved to
  disk by the store itself.
- Every new MCP tool follows the existing conventions in `ai/server.py`/
  `ai/dosbox_client.py`: a docstring describing parameters, result shape,
  and precondition; DOSBoxClientError subclasses surfaced through
  `_guarded_native`; no fabricated data -- an unreadable/unmapped region
  is reported, never silently treated as zero bytes or a fabricated
  result.

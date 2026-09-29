# Phase 8C: agent-side analysis tools for autonomous reverse engineering

> Scope: closing the biggest gaps between "an agent can inspect/control one
> instant of the running guest" (everything through Phase 8A) and "an agent
> can accumulate its own reverse-engineering knowledge across a session" --
> memory pattern/string search, a persistent symbol/annotation store,
> call-stack unwinding, and live recursive-descent static disassembly /
> control-flow graph construction. Status: all four items implemented and
> unit-tested (see `ai/Phase8C.md` for exact status and file list).
> Deliberately distinct
> from the previously reserved "Phase 8B" (`vga.watch_writes`, see
> `docs/phase8a-vga-snapshot-design.md`), which this phase does not touch,
> and from interrupt-level call tracing, deferred to a separate Phase 8D
> because it requires native bridge changes (see "Non-goals" below).

## Goal

Everything the general-purpose MCP surface exposes through Phase 8A answers
"what does the guest look like right now, and how do I change one thing
about it" -- registers, one memory range, one disassembly window, one VGA
snapshot. None of it helps an agent build up the kind of standing knowledge
a human reverse engineer accumulates during a session: where a signature
byte sequence or string lives, what a given address means, how the current
call arrived here, or what an unexplored routine's shape is before
single-stepping through it one instruction at a time.

This phase adds four capabilities that close that gap, all without
introducing a second CPU emulator, a second disassembler, or a new native
bridge method -- consistent with this project's existing design principle
(see `docs/dosbox-ai-bridge.md`'s "No second disassembler, no second CPU/
register model...").

## Why agent-side, not native bridge, for all four items

Every native bridge change in this project's history (Phase 4A-4D, 6A/6B,
7A-7E, 8A) has followed the same shape: touch `dosbox-src/src/debug/
debug_ai.cpp` (and occasionally `debug.cpp`/`dosbox.cpp`), rebuild
`dosbox-x.vcxproj`, relaunch a live instance, and re-verify against real
guest state. That is the right cost to pay when the capability genuinely
requires something only the emulator process itself can do (reading VRAM
bypassing the CPU's read path, stopping the real CPU, injecting real
keyboard events). None of this phase's four items need that:

- **memory_search** only needs repeated `memory.read` calls -- the native
  bridge already reads arbitrary guest memory; scanning it for a pattern is
  pure client-side logic over bytes already returned.
- **Symbol/annotation storage** is inherently agent-side: DOSBox-X has
  no notion of "the name an agent gave this address" and should not need
  one -- this is exactly the kind of session-spanning knowledge a
  standalone tool, not the emulator, should own.
- **Call-stack unwinding** (walking the `SS:BP` chain) only needs
  `cpu.get` (for the starting `SS:BP`) and `memory.read` (to follow each
  frame's saved `BP`/return address) -- no new primitive.
- **Static disassembly / control-flow graph construction** only needs
  `code.disassemble` (already returns real, decoded instructions from live
  guest memory) and `read_memory`, walked recursively by following each
  instruction's jump/call/branch targets instead of the debugger's own
  linear "next instruction" stepping.

Building all four in `ai/` (a new `ai/analysis.py` module, plus a
persistent-store module for the symbol/annotation piece) keeps
`dosbox_client.py` scoped to exactly what it already is -- a thin client
for the native bridge's own protocol methods -- and avoids a
rebuild+relaunch+re-verify cycle for capabilities that do not need one.

## Item 1: `memory_search` (implemented)

### Requirement

Find where a byte signature or a text string lives in guest memory, the
same starting move a human reverse engineer makes in IDA/Ghidra's binary
or text search, without knowing an address in advance. Nothing in the
existing tool surface does this -- `read_memory` requires already knowing
where to look.

### Crossing segment boundaries without duplicating a linear-address model

`memory.read`'s 65536-byte cap (`docs/dosbox-ai-bridge.md`) matches one
real-mode segment. `code.disassemble` wraps its offset within one segment
rather than carrying into the next (the existing "16-bit wraparound" note)
-- so a naive loop that just kept incrementing offset past `0xFFFF` within
one `memory.read` call would silently re-read the start of the same
segment instead of advancing, corrupting the scan.

`search_memory()` (`ai/analysis.py`) instead:

1. Reads from the caller's starting offset up to the end of that segment
   first (`length = 0x10000 - start_offset`) -- this always lands exactly
   on a segment boundary regardless of where within the segment the scan
   started, because `segment*16 + 0xFFFF + 1 == (segment + 0x1000)*16 + 0`.
2. Every subsequent chunk reads a full `0x10000`-byte segment at offset 0,
   advancing the segment by `0x1000` (`0x1000` paragraphs * 16 bytes/
   paragraph == `0x10000` bytes) between chunks.

This produces a gapless, non-overlapping linear scan using only
`memory.read` calls that never individually risk the native bridge's own
offset wraparound.

### Wildcards, text, and boundary-spanning matches

`pattern` is a list of byte specs (int 0-255, a 2-digit hex string, or
`"??"`/`"?"`/`None` for "match any byte"); `text` is matched as raw ASCII
bytes, with `case_sensitive=False` implemented as a per-byte
alternative-set match (`{ord('h'), ord('H')}`) rather than scanning twice.
A concrete (wildcard-free) pattern uses `bytes.find()` in a loop; a
pattern with wildcards or case-insensitive sets falls back to a
byte-by-byte scan.

A match may straddle the boundary between two chunks. `search_memory()`
carries the last `len(pattern) - 1` bytes of each successfully-read chunk
into the next chunk's search buffer (a sliding window), and tracks that
carry's own linear start address so a match found partly in the carry and
partly in the new chunk still gets its correct absolute address. Because
the carry is always shorter than the pattern itself, no match can be
fully contained within it -- so no match is ever found (or reported)
twice across the boundary.

### Address reporting: always canonicalized

A match's address is reported as `linear_address >> 4 : linear_address &
0xF` -- e.g. linear `0xFFFE` is `"0FFF:000E"`, not `"0000:FFFE"`. This was
a deliberate simplification over reporting "the natural segment:offset of
whichever chunk the match started in": a boundary-spanning match has no
single natural segment (its first byte lived in one chunk's segment
context, later bytes in the next), and canonical `linear >> 4 : linear &
0xF` addressing is unambiguous, trivial to compute correctly, and, like
any other real-mode `SEG:OFF` pair, works directly as input to
`read_memory`/`disassemble`/`set_breakpoint` -- real-mode addressing
already has up to 4096 equally valid representations of the same linear
address, so there is nothing special about preferring one particular
"natural" one for a match address.

### Failure handling: skip, never fabricate

If a chunk read returns the native bridge's `MEMORY_ERROR` (unmapped/
inaccessible guest memory), `search_memory()` records that chunk under
`unreadable_regions` and continues scanning past it (clearing the carry,
since a match cannot legitimately span a gap that was never read) --
rather than aborting the whole call or treating the missing bytes as
zeros. This follows the project's existing "no fake data" rule
(`docs/dosbox-ai-bridge.md`'s `memory.read`/`memory.write` MEMORY_ERROR
handling is the direct precedent). `max_matches` (default 1000) bounds
result size and sets `"truncated": true` if scanning stopped early.

### Testing

`tests/test_analysis.py` tests the chunking, wildcard/text matching,
boundary-spanning, unreadable-region-skipping, truncation, and parameter
validation logic against a `StubClient` (a plain `bytearray`-backed
in-process stand-in for `DOSBoxClient.read_memory`) -- no live DOSBox-X
instance required, matching `tests/test_debugger.py`'s existing pattern
of testing pure logic against a fake backend.

## Items 2-4 (implemented)

### Item 2: persistent symbol/annotation store

`ai/knowledge.py`'s `KnowledgeStore` is an agent-side key-value store,
keyed by canonical address, holding whatever an agent has learned: a
label ("this is the `strcpy`-equivalent routine"), a free-text comment,
or a cross-reference ("called from 1234:0100"). It persists to
`ai/knowledge.local.json` by default (git-ignored -- user/session-
specific findings, never project source; a custom path can be passed to
`KnowledgeStore(path=...)`), saving on every mutating call so a crashed
session never loses an already-acknowledged write. Addresses are
canonicalized the same way as `search_memory()`'s match addresses
(`linear_address >> 4 : linear_address & 0xF`), so `set_symbol("1234:0100",
...)` and a later `get_symbol("1244:0000", ...)` (or any other
representation of the same linear address) find the same entry.
Exposed as eight MCP tools: `set_symbol`/`get_symbol`/`delete_symbol`/
`list_symbols`, `set_comment`/`get_comment`, and `add_xref`/`list_xrefs`
(`kind` restricted to `"call"`/`"jump"`/`"data"`/`"other"`; adding the
same `(from, to, kind)` triple twice is a no-op). None of these touch
DOSBox-X or the native bridge, so none are wrapped in `_guarded_native()`
-- invalid input raises a plain `ValueError`, matching `write_io_port()`'s
existing convention for parameter-validation failures. Tested in
`tests/test_knowledge.py` (12 tests: canonical-address lookup equivalence,
delete/list, comments, xref idempotency and direction filtering, invalid
`kind`/`direction`, and a real save-then-reload persistence round trip
against a temp file).

### Item 3: call-stack unwinding

`ai/analysis.py::get_call_stack()` reads the current `SS`/`CS`/`BP` (via
one `cpu.get` call), then walks the standard `[BP] -> saved BP`,
`[BP+2] -> return offset` chain via repeated `read_memory` calls, exactly
the technique a human doing manual real-mode stack unwinding already
uses. This assumes a standard `PUSH BP` / `MOV BP,SP` prologue and NEAR
(same-segment) `CALL`s, matching this project's own DOS test programs
(e.g. `drive_c/STEP.COM`) -- a FAR call's 4-byte return address would be
misread as two unrelated 2-byte fields, since 16-bit real-mode code has
no formal frame-pointer metadata this tool could consult to tell the two
cases apart. The walk stops once a saved `BP` is not strictly greater
than the current frame's `BP` (real-mode stacks grow downward, so a
genuine parent frame's `BP` must sit at a numerically greater offset than
its child's) -- this also naturally halts on a zero/uninitialized chain
and on unmapped stack memory (native `MEMORY_ERROR`, caught the same way
`search_memory()` catches it). `max_frames` (default 32) bounds the walk
and sets `"truncated": true` if reached first. Every reported
`return_address` uses the CURRENT `CS`, since a near return address
carries no segment of its own -- stated as a limitation, not hidden.
Tested in `tests/test_analysis.py` (5 tests: a two-frame walk, an empty
(zero-`BP`) chain, `max_frames` truncation, stopping on unreadable stack
memory, and parameter validation) against a `StubClient` extended with a
configurable `get_cpu_state()`.

### Item 4: live recursive-descent static disassembly / control-flow graph

**Architecture decision (confirmed with the project owner before
implementation): recursive-descent walk over live guest memory, not an
offline host-file parser.** The alternative -- parsing the target's
`.EXE`/`.COM` file directly on the host (MZ header, relocation table) --
was considered and rejected because it would require adding an external
disassembler dependency (e.g. `capstone`) purely to re-implement
something DOSBox-X's own `DasmI386()` (already reachable through
`code.disassemble`) already does correctly, and because a second
disassembler's output is not guaranteed to agree with the first in every
edge case -- exactly the "no second disassembler" risk this project has
consistently avoided (Phase 3B onward).

**Grounding the text parser in the actual disassembler source, not a
guess.** Before writing any parsing logic, `dosbox-src/src/debug/
debug_disasm.cpp` was read directly to confirm the exact rendering of a
resolvable near branch operand: opcode-table entries like `"jmp %Jv"`/
`"call %Jv"`/`"jo %Jb"` (all lowercase; confirmed no uppercasing pass
exists anywhere between `DasmI386()` and the JSON response in
`debug_ai.cpp`) use the `%J` (relative IP offset) format, whose handler
(`case 'J'`, `debug_disasm.cpp`) computes the absolute target and renders
it via `addr_to_hex(target, /*splitup=*/0)` -- an **8-hex-digit value
with no segment and no colon** (e.g. `"jmp 0000E05B"`), not a `SEG:OFF`
pair. Only the short-jump opcode (`0xEB`, `"jmp %Ks%Jb"`) additionally
emits a literal `"short "` before that value; every other near
branch/call/loop/jcxz form emits no prefix at all. A far `JMP`/`CALL`
(`%Ap`) or an indirect `JMP`/`CALL` through a register/memory operand
(`%Kn%Ev`/`%Kf%Ep`) instead renders a register name or a bracketed
memory operand, which can never match an 8-hex-digit token -- so
`build_control_flow_graph()`'s regex (`ai/analysis.py`'s
`_NEAR_BRANCH_RE`) naturally rejects those rather than needing a special
case to exclude them.

**Algorithm.** `build_control_flow_graph()` maintains a work queue of
canonicalized addresses, starting from `start_address`. For each queued
address not yet in `blocks`, it calls `disassemble(address,
max_instructions_per_block)` **once** (not once per instruction) and
scans the returned list in order:

- If an instruction's text matches a resolvable near branch, the block
  ends there. The target becomes a successor; if the mnemonic isn't
  unconditional `jmp` (i.e. it's a conditional `Jcc`, `CALL`, `LOOP*`, or
  `JCXZ`), the fallthrough address -- the next entry in the *same batch*,
  or, if this was the batch's last entry, `address + decoded length` --
  is added as a second successor. A `CALL`'s target is explored like any
  other successor, but the calling block is still expected to continue
  past the `CALL` under normal execution, so both are recorded rather
  than treating `CALL` as a hard block end.
- If the mnemonic is `ret`/`retf`/`retn`/`iret`, `int`, or an
  unresolved `jmp`/`call` (i.e. the near-branch regex didn't match), the
  block ends with `"unresolved_transfer"` set to `"return"`,
  `"software_interrupt"`, or `"indirect_or_far_transfer"` respectively,
  and no successor is fabricated.
- If the whole batch is consumed without any block-ending instruction
  (i.e. `max_instructions_per_block` was reached first), the block
  continues linearly into a synthesized fallthrough successor.

Every reported address (`blocks` keys and every successor) is
canonicalized, matching `search_memory()`'s convention, so the same
linear address is never split across two differently-labeled block
entries reached via different `SEG:OFF` paths.

**Stated limitation: single-pass, not two-pass.** This walk does not
pre-scan the whole reachable region to determine all true block
boundaries before disassembling (a full "basic block" CFG would split a
block wherever ANY other block jumps into its middle, discovered or
not). If a later-explored jump target lands inside an address range this
walk already covered as part of an earlier block's straight-line run,
the two blocks' instruction lists will overlap rather than being merged
or retroactively split -- both blocks still show correct content and
correct successors individually, but the graph is not a strictly minimal
partition of the code. Callers that need a fully split, non-overlapping
partition must post-process the result themselves.

**Scope limitation: only NEAR, same-segment control flow is followed.**
A far transfer or a register-/memory-indirect transfer is reported as an
`"unresolved_transfer"` boundary rather than guessed at (`build_control_flow_graph()`
never fabricates a target it cannot resolve from the disassembler's own
text). This can under-explore a real program's actual reachable code
(e.g. a jump table, or an `INT 21h` call that itself transfers control
elsewhere) -- callers needing that coverage must supply additional
`start_address` values from other evidence (`memory_search`, manual
investigation, or single-stepping). This only works for code that is
actually loaded into guest memory at the time of the walk (the debugger
must be stopped), which is an acceptable scope limit given this
project's live-guest-only design throughout every earlier phase; it
never loads, executes, or changes anything.

Tested in `tests/test_analysis.py` (7 tests) against a `CfgStubClient`
that models one or more disjoint, physically-contiguous byte runs (not a
"jump to wherever content is defined" lookup -- each run's successive
instruction is derived from the previous entry's own decoded length,
matching how a real `disassemble()` call actually decodes sequential
memory) and labels returned instructions using the query's own segment
with an incrementing offset, matching the native bridge's documented
`code.disassemble` behavior (`docs/dosbox-ai-bridge.md`'s "16-bit
wraparound" / `getcodetext()`-walking-pattern note). Covers: a
conditional-branch entry block producing three distinct blocks
(branch-target, fallthrough, and the entry itself), an unconditional
`jmp` correctly producing no fallthrough successor, an indirect `call`
and a software interrupt both correctly reported as
`"unresolved_transfer"` with no successors, `max_blocks` truncation, and
parameter validation.

## Non-goals

- **Interrupt-level call tracing / exposing `BPINT` through the MCP
  layer** (the "3" item from the original four-item + one-item split) is
  deliberately excluded from this phase and tracked as a separate Phase
  8D, because -- unlike all four items above -- it requires a native
  bridge change (`breakpoint.list`'s Phase 4B scope note already states
  interrupt breakpoints have no MCP representation today) and therefore a
  `dosbox-x.exe` rebuild, relaunch, and live re-verification cycle this
  phase's four items do not need.
- **`vga.watch_writes`** (a real VRAM-write breakpoint keyed on
  plane+offset) remains the separately reserved, previously-announced
  "Phase 8B" (see `docs/phase8a-vga-snapshot-design.md` and the Phase 8A
  `CHANGELOG.md` entry) and is untouched by this phase's numbering or
  scope.

## Files touched

- `ai/analysis.py` (new): `search_memory()`, `get_call_stack()`,
  `build_control_flow_graph()`, and their shared helpers (pattern
  compilation/chunking/matching, canonical addressing, near-branch text
  parsing).
- `ai/knowledge.py` (new): `KnowledgeStore`, item 2's persistent
  symbol/comment/xref store.
- `ai/server.py`: registers `memory_search`, `get_call_stack`,
  `build_control_flow_graph` (guarded through the existing
  `_guarded_native()` helper) and `set_symbol`/`get_symbol`/
  `delete_symbol`/`list_symbols`/`set_comment`/`get_comment`/`add_xref`/
  `list_xrefs` (unguarded -- plain `ValueError` on bad input, like
  `write_io_port()`) as MCP tools; instantiates a module-level
  `knowledge = KnowledgeStore()`.
- `.gitignore`: added `ai/knowledge.local.json` (the store's default
  persistence path -- user-specific findings, never project source).
- `tests/test_analysis.py` (new): unit tests for `search_memory()`,
  `get_call_stack()`, and `build_control_flow_graph()` against stub
  clients.
- `tests/test_knowledge.py` (new): unit tests for `KnowledgeStore` against
  a temp-file-backed instance.
- `AGENT_GUIDE.md`/`AGENT_GUIDE.zh-TW.md`, `README.md`/`README.zh-TW.md`,
  `CHANGELOG.md`: tool count and tool-table updates (39 -> 50 tools).

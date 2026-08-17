# Phase 7D: bounded execution trace around a breakpoint hit (Epic D)

> Scope: Epic D of
> `docs/phase7-observability-and-autonomous-control-requirements.md`
> (`trace.execution.configure`/`.list`/`.get`).
> Status: design, grounded in source investigation. Not yet implemented.

## Goal

Let an agent see the instructions immediately *before* and *after* a
breakpoint (code or memory watchpoint) fires -- not just the single
stopped snapshot `debug.status`/`pause_execution()` already provide.
This is the difference between "here is where I stopped" and "here is
how I got here and what happened right after," which matters most for
exactly the kind of bug this project's own case study
(`docs/case-study-dark-sun-gpli-debugging.md`) walks through: knowing
*which* instruction wrote a watched byte, and what the CPU did
immediately after.

## Architecture: reuse three existing mechanisms, add one new hook

Unlike Epics A-C, this doesn't need a new capture mechanism end to
end -- DOSBox-X's heavy-debug build already has almost everything:

### 1. "before": DOSBox-X's own existing instruction log (`debug.cpp`)

`DEBUG_HeavyIsBreakpoint()` (`src/debug/debug.cpp:6479`) already runs
once per instruction in the Normal core, under `C_HEAVY_DEBUG`
(`src/cpu/core_normal.cpp:176`), and already calls
`DEBUG_HeavyLogInstruction()` whenever a file-local `bool logHeavy` is
true. That function (`debug.cpp:6389`) writes CS:EIP, every GPR,
every segment register, all six status flags, and a pre-disassembled
line (via `DasmI386()` -- the SAME disassembler `code.current`/
`code.disassemble` already use) into `TLogInst logInst[LOGCPUMAX]`
(`LOGCPUMAX = 20000`, `debug.cpp:6356-6387`), a plain circular buffer
indexed by a wrapping `logCount`. This is DOSBox-X's own "LOG HEAVY"
debugger-console feature (dumps to `LOGCPU_INT_CD.TXT` on demand,
`DEBUG_HeavyWriteLogInstruction()`) -- Phase 7D reuses its *live ring
buffer*, not its file-dump behavior, exactly like Phase 7A reused
`CAPTURE_AddImage()`'s hook point rather than its file-write path.

`before_instructions` (max 4096) is comfortably inside `LOGCPUMAX`
(20000), so no new buffer is needed -- just new read-only accessors
(`debug_ai.h`) exposing `logInst`/`logCount`/`logHeavy` to
`debug_ai.cpp` without exposing the `TLogInst` type itself (private to
`debug.cpp`): `DEBUG_AI_SetHeavyTraceLogging(bool)`,
`DEBUG_AI_GetHeavyLogCount(void)`, and
`DEBUG_AI_GetHeavyLogEntry(uint32_t indexFromMostRecent, DEBUG_AI_HeavyLogEntrySnapshot&)`
(a new, small POD struct declared in `debug_ai.h`, mirroring one
`TLogInst` entry's fields).

**Known limitation, documented rather than silently shared**: `logHeavy`/
`logInst[]` are the SAME state the debugger console's own "LOG"/"HEAVY"
commands use. `trace.execution.configure(enabled=true)` turns
`logHeavy` on for as long as trace is enabled; a human using the
interactive console's own heavy-log command at the same time would
observe/reset the same buffer. This mirrors this project's existing
philosophy (Phase 4C's `execution.continue`/`.pause` already share the
GUI's own RUN/Ctrl+Pause state) rather than inventing a parallel,
non-conflicting mechanism.

**"how many valid entries exist yet"**: `logCount` is snapshotted the
moment `trace.execution.configure(enabled=true)` runs
(`g_heavyLogCountAtEnable`). At capture time, the number of genuinely
fresh entries is `min(LOGCPUMAX, (logCount - g_heavyLogCountAtEnable + LOGCPUMAX) % LOGCPUMAX)`
-- avoids reading stale pre-enable entries when trace was only just
turned on, without a new per-instruction counter.

### 2. "after": the EXISTING, already-verified `DEBUG_AI_DoStepInto()` (Phase 4D)

`after_instructions` is produced by calling
`DEBUG_AI_DoStepInto()` (`debug.cpp`, Phase 4D) up to `after_instructions`
times in a row -- the SAME function `execution.step_into()` already
uses (`DEBUG_Run(1,true)`, the debugger GUI's own F11 mechanism), each
call disassembled and recorded the same way `ExecCodeCurrent()`
(`debug_ai.cpp:492`) already reads CS:EIP/registers/disassembly. No new
single-step mechanism.

**Where this runs, and why**: `DEBUG_AI_DoStepInto()` is documented
(`debug_ai.h`) as callable "ONLY from `DEBUG_AI_Poll()`" -- the one
place already proven safe for synchronous re-entrant `DEBUG_Run()`
calls while the debugger has control. Phase 7D's after-stepping
therefore runs from `DEBUG_AI_Poll()` too (see hook design below), NOT
inline inside whatever function first notices the debugger just
stopped -- avoiding a new, unverified call context for a function three
other features already depend on being correct.

### 3. Trigger detection: `CBreakpoint::CheckBreakpoint()`'s existing single decision point (`debug.cpp:745`)

`CheckBreakpoint()` already uniformly evaluates BOTH code breakpoints
(`BKPNT_PHYSICAL`) and memory watchpoints (`BKPNT_MEMORY`/
`BKPNT_MEMORY_PROT`/etc., Phase 6A's existing byte-compare polling) in
one loop, called once per instruction from `DEBUG_HeavyIsBreakpoint()`.
It returns only `bool` today -- Phase 7D adds a minimal, additive
side-effect: a new file-local `static CBreakpoint *g_lastCheckBreakpointHit`
set immediately before each existing `return true;` (two call sites,
`debug.cpp:772` and `debug.cpp:801`), with a new accessor
`CBreakpoint::GetAndClearLastHit()` -- get-and-clear, single-consumer,
so a stale hit from an earlier stop can never leak into a later one.
This does not change `CheckBreakpoint()`'s existing behavior, return
value, or performance characteristics for any existing caller
(`DEBUG_Breakpoint()`, `DEBUG_HeavyIsBreakpoint()`) -- one pointer
assignment at two already-taken branches.

`trigger.kind`: if `GetAndClearLastHit()` returns non-null at capture
time, `"code_breakpoint"` (`BKPNT_PHYSICAL`) or `"memory_breakpoint"`
(any `BKPNT_MEMORY*`) based on `GetType()`; otherwise `"manual_pause"`.
`trigger.breakpoint_id`: the matched `CBreakpoint*`'s CURRENT position
in `CBreakpoint::BPoints` at capture time, found via the SAME linear
`GetByIndex(i) == bp` scan `DEBUG_AI_BreakpointAdd()` already uses
(`debug.cpp:996-999`) -- a snapshot, not a stable reference, matching
Phase 4B's existing "id is a position, not identity" contract
(`debug_ai.h:101-108`); the requirements draft's "must survive the
breakpoint being deleted later" (section 6.2) is satisfied for free,
since the trace stores this snapshot value, not a live pointer.

### 4. The stop-transition hook: wrapping `DEBUG_AI_SetDebuggerActive()`, not touching `DEBUG_Enable_Handler()`

The requirements draft needs trace capture on EVERY path into the
debugger -- a breakpoint hit, `-break-start`, Ctrl+Pause, and an AI
`pause_execution()` (`trigger.kind` covers all of them via
`"manual_pause"` as the catch-all). Investigation found these
converge, ultimately, on `DEBUG_AI_SetDebuggerActive(true)`, called
from exactly two places, both already carefully commented as "the
debugger genuinely just gained control, however it got here":

- `DEBUG_Loop()`'s first lines (`debug.cpp:5108`) -- reached every
  iteration while stopped, including breakpoint hits.
- `DEBUG_AI_CheckPauseRequest()` (`debug.cpp:5342`) -- reached once,
  synchronously, right after `DEBUG_Enable_Handler(true)` completes an
  AI-bridge-initiated pause.

Rather than adding trace logic to either call site (both are
early-return-heavy, UI-adjacent functions with existing subtle
ordering -- `DEBUG_Loop()` in particular runs every iteration while
stopped, not just the first), Phase 7D wraps
`DEBUG_AI_SetDebuggerActive()` itself (already defined in
`debug_ai.cpp`) to detect the `false -> true` transition:

```cpp
void DEBUG_AI_SetDebuggerActive(bool active) {
    bool was = g_debuggerActive.exchange(active);
    if (active && !was) {
        g_tracePendingCapture.store(true, std::memory_order_release);
    }
}
```

This correctly fires exactly once per fresh stop regardless of which
of the two call sites reached it first (the other's subsequent call is
`true -> true`, a no-op transition) -- no changes to `debug.cpp` at
all for this part. The actual capture work (reading `CBreakpoint`'s
last hit, reading the heavy-log ring buffer, and -- if
`after_instructions > 0` -- calling `DEBUG_AI_DoStepInto()`
repeatedly) happens from `DEBUG_AI_Poll()` checking
`g_tracePendingCapture`, the SAME safe, already-proven context Phase
4D's stepping requires -- mirroring `DEBUG_AI_CompletePendingSteps()`'s
existing "checked unconditionally every `DEBUG_Loop()` iteration, cheap
no-op when nothing pending" pattern, just for one more pending flag.

### "after" completion semantics

`DEBUG_AI_DoStepInto()` is documented as always synchronous (Phase 4D:
"control returns to the debugger before the call returns"), unlike
`step_over()`'s async call/int/loop/rep case -- so there is no
timeout-based incompleteness to handle for `after` stepping the way
`EXECUTION_TIMEOUT` handles `step_over()`. `complete_after=false` is
produced only if:

- Another breakpoint (code or memory) fires during the N steps --
  `CBreakpoint::GetAndClearLastHit()` is checked after each step; if
  non-null, stop stepping early, `complete_after=false`,
  reason-equivalent info folded into the (still valid) partial `after`
  array.
- The guest program terminates mid-sequence (detectable the same way
  existing step/continue code already must handle a DOS program exit --
  reusing whatever check `DEBUG_AI_DoStepInto()`'s existing callers
  already rely on, not a new detection mechanism).

## `max_trace_bytes` and truncation

Each `InstructionRecord`'s serialized cost is dominated by its fixed
fields (~200-300 bytes as JSON: `ordinal`, `location`, `bytes_hex`,
`disassembly` up to 30 chars from `TLogInst.dline`, eight+ register
values). A running byte estimate is accumulated while building
`before`/`after`; once it would exceed `max_trace_bytes`, further
instructions are dropped and counted in `dropped_instruction_count`
rather than silently omitted. Truncation drops from the FRONT of
`before` first (oldest instructions, furthest from the trigger) since
the instructions closest to the trigger are the ones most likely to
matter -- `after` is never truncated ahead of `before`, since it's
capped independently by `after_instructions` (max 4096) and is always
the smaller of the two in practice.

## Trace storage

A new bounded store, mirroring Phase 7C's `g_receipts` shape:

```cpp
struct TraceRecord {
    uint64_t traceId;
    /* trigger */
    std::string triggerKind;      // "code_breakpoint" | "memory_breakpoint" | "manual_pause"
    int32_t breakpointId;         // -1 if none
    uint16_t locationCs;
    uint32_t locationIp;
    uint64_t triggerEmulatedMs;
    /* before/after, already resolved -- see InstructionRecord above */
    std::vector<InstructionRecordSnapshot> before;
    std::vector<InstructionRecordSnapshot> after;
    bool completeAfter;
    uint64_t droppedInstructionCount;
};

static std::mutex g_traceMutex;
static std::deque<TraceRecord> g_traces;
static const size_t MAX_TRACES = 100; // matches trace.execution.list's own limit:1..100
static uint64_t g_droppedTraces = 0;
```

Written ONLY from `DEBUG_AI_Poll()` (the same context that performs the
capture); read from any socket thread under the mutex for
`trace.execution.list`/`.get` -- the SAME "already-computed history,
safe concurrent read" shape Phase 7C's `input.receipt.get` already
established, so those two methods need no request queue either.

## API (from the Phase 7 draft, section 6.1, unchanged)

See `docs/phase7-observability-and-autonomous-control-requirements.md`
section 6 for the full request/response shapes. Not repeated here.
`trace.execution.configure`'s `registers` parameter (a requested subset
of register names) is honored by filtering `InstructionRecord.registers`
to just the requested keys -- if omitted/empty, all captured registers
are returned. `include_disassembly` (default true) simply omits the
`disassembly` field (never the underlying capture) when false.

## Non-goals (unchanged from the requirements draft, section 6.2/9)

Real-mode x86, single CPU, unconditional code/memory breakpoints only
-- no branch trace, no source-level symbols, no protected-mode-specific
handling beyond what Phase 6A's existing `BKPNT_MEMORY_PROT` already
does. `trace.execution.configure(enabled=false)` (the default) must
leave breakpoint stop semantics and performance completely unchanged --
satisfied structurally, since nothing above runs unless `logHeavy`/
`g_tracePendingCapture` are ever set, both gated by the same
`enabled` flag `HandleLine()` checks before touching either.

## Implementation touches (four files)

1. `dosbox-src/src/debug/debug.cpp`: `CBreakpoint::GetAndClearLastHit()`
   (+ the two `return true;` sites), `DEBUG_AI_SetHeavyTraceLogging()`,
   `DEBUG_AI_GetHeavyLogCount()`, `DEBUG_AI_GetHeavyLogEntry()`.
2. `dosbox-src/src/debug/debug_ai.cpp` (+ `.h`): the trace store, the
   `DEBUG_AI_SetDebuggerActive()` transition wrapper, the
   `DEBUG_AI_Poll()`-driven capture routine, and the three new
   `trace.execution.*` `HandleLine()` branches (answered directly, no
   request queue, like `input.receipt.get`).
3. `ai/dosbox_client.py`: `configure_execution_trace()`,
   `list_execution_traces()`, `get_execution_trace()`.
4. `ai/server.py`: three corresponding MCP tools;
   `AGENT_GUIDE.md`/`.zh-TW.md`, `README.md`/`.zh-TW.md` reference and
   tool-count updates; `CHANGELOG.md` entry.

## Verification plan

Mirrors this project's established live-instance verification. A
genuinely stopped debugger is required for most of these -- per the
"Bridge fix -- debugger console crash on piped/redirected stdio"
`CHANGELOG.md` entry, `dosbox-x.exe` must be launched with a real
inherited console (e.g. `Start-Process` without output redirection),
not piped/redirected stdio.

1. A known `mov [addr],ax` test program with a write watchpoint --
   `before` has at least 8 entries ending at the write instruction,
   registers at the hit match `debug.status` at that moment.
2. `after_instructions=3` -- `after` has exactly 3 entries,
   `complete_after=true`, and the debugger's own visible stop position
   (`debug.status` right after) matches the 3rd `after` entry's
   location, not the original trigger location.
3. `max_trace_bytes` at its minimum -- confirms no out-of-bounds
   growth and a non-zero, believable `dropped_instruction_count`.
4. `trace.execution.configure(enabled=false)` -- confirms breakpoint
   hit behavior/timing is unchanged from before this phase existed
   (baseline comparison against Phase 4B/6A's existing breakpoint
   tests).
5. Delete the breakpoint that triggered a trace, then
   `trace.execution.get` the same trace -- `breakpoint_id` still
   reads the original (now-stale) value, not an error.

## Implementation status: done, verified live (the highest-risk parts confirmed working end to end)

Implemented as designed, in `dosbox-src/src/debug/debug.cpp`/
`debug_ai.cpp`/`debug_ai.h`, `ai/dosbox_client.py`, and `ai/server.py`.
Built clean (0 errors, 0 new warnings) against the `Release` (SDL1)
`x64` configuration.

This is the architecturally riskiest phase so far -- the only one
touching `CBreakpoint`'s core matching function and the central
debugger-stop-detection hook (`DEBUG_AI_SetDebuggerActive()`) every
other phase's correctness already depends on. Verified live against a
purpose-built 16-byte test program (`A1 06 02 / 40 / A3 06 02 / A3 02
02 / 90 90 90 / E9 F0 FF` -- a tight loop writing an incrementing
counter to a watched address), via `get_debug_status`/
`set_real_memory_breakpoint`/`configure_execution_trace`/
`list_execution_traces`/`get_execution_trace`, both through raw
protocol calls and the actual MCP tool functions end to end:

1. A real-mode memory watchpoint fired correctly with
   `trigger.kind: "memory_breakpoint"` and the correct
   `breakpoint_id`.
2. `before`'s last entry landed EXACTLY at the trigger location
   (`0816:010A` in both the trace and the independently reported
   `trigger.location`) -- confirms `RecordLastHit()`'s snapshot timing
   and `DEBUG_HeavyLogInstruction()`'s existing "log before checking"
   order line up exactly as the design assumed.
3. `before_count` correctly capped to how much heavy-log history had
   genuinely accumulated since `configure_execution_trace` was called
   (4-6 entries across different runs, never stale pre-enable data),
   confirming the `g_heavyLogCountAtEnable` freshness tracking.
4. `after_instructions=4` produced exactly 4 `after` entries with
   correctly evolving register state. After that automatic stepping
   completed, a SEPARATE, independent `get_debug_status` call confirmed the
   debugger's own visible stop position matched the 4th `after`
   entry's location and registers exactly -- direct proof the
   `DEBUG_AI_Poll()`-deferred `DEBUG_AI_DoStepInto()` loop (the design's
   main re-entrancy concern) lands the debugger exactly where the
   trace claims, with no corruption, hang, or crash from calling it in
   this new context.
5. A `manual_pause` trigger (`pause_execution()`, no breakpoint
   involved) correctly reported `trigger.kind: "manual_pause"`,
   `breakpoint_id: null` -- and, as the design predicted from how
   `DEBUG_AI_CheckPauseRequest()` interrupts BETWEEN
   `DEBUG_HeavyIsBreakpoint()`'s own per-instruction checks rather than
   as part of one, `before`'s last entry was consistently one
   instruction short of the trigger location (reproduced identically
   across two independent test runs) -- confirmed to be an inherent
   property of the underlying mechanism, not a bug, and documented as
   such in `AGENT_GUIDE.md`/`.zh-TW.md`.
6. `trace.execution.get` on an unissued `trace_id` -> `TRACE_NOT_FOUND`.
7. `configure_execution_trace(enabled=false)` answered correctly (dual
   route confirmed working in both directions).

**Not independently exercised live this session**: `max_trace_bytes`
truncation specifically (the test program's short loop never
accumulated enough history to exceed even the 65536-byte minimum
before hitting the trigger repeatedly) -- the truncation logic itself
(drop-from-front-of-`before` until under budget) is simple,
deterministic code reviewed but not proven under load; a code
breakpoint (only memory breakpoints were exercised, though both go
through the exact same `RecordLastHit()`/`CheckBreakpoint()` code
path); and `complete_after=false` (stepping into a second breakpoint
mid-`after`-sequence). Tracked as follow-up rather than assumed fine,
consistent with this project's practice for prior phases' gaps.

Also confirmed, incidentally, that `-break-start` appeared unreliable
in this environment even with the console-crash fix applied (landed
correctly on some launches, not others); `execution.pause` was used as
the reliable fallback throughout this verification, as it was for
Phase 7B/7C's. This was root-caused in a later session -- see the "Bridge fix --
`-defaultdir` swallowing the next command-line switch" `CHANGELOG.md`
entry -- and is not a `-break-start` bug at all: a bare `-defaultdir`
(no path argument) immediately followed by another `-`-prefixed option
greedily consumed that option as its own (bogus) directory argument.
The launch pattern used throughout this verification
(`-defaultdir -break-start ...`) hit this exactly, which is consistent
with the flakiness observed -- 100% reproducible for a fixed command
line, but easy to mistake for a race across sessions that varied
whether `-defaultdir` was given an explicit path. `-break-start` itself
was reliable all along; the fix makes the bare-`-defaultdir` form work
correctly too.

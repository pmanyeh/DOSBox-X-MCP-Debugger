# DOSBox-X Native AI Bridge (Phase 3B / Phase 4A / Phase 4B / Phase 4C / Phase 4D)

Status: read-only inspection (Phase 3B), real write access to guest memory
and a whitelisted subset of general-purpose registers (Phase 4A),
breakpoint management against DOSBox-X's own breakpoint system (Phase 4B),
real execution control -- resuming and stopping the actual guest CPU
(Phase 4C) -- and real single-step control -- step-into and step-over
against the actual guest CPU (Phase 4D). See "Build & runtime verification"
below for this session's actual result.

Files: `dosbox-src/src/debug/debug_ai.h`, `dosbox-src/src/debug/debug_ai.cpp`.
Integration touches `dosbox-src/src/debug/debug.cpp` (one `#include`, one
`DEBUG_AI_Poll()` call in `DEBUG_Loop()`, two calls in `DEBUG_Init()`/
`DEBUG_ShutDown()`, one accessor for `debug_running`, two small `public:`
additions to the existing `CBreakpoint` class (`GetCount()`/`GetByIndex()`)
plus five free-function wrappers around `CBreakpoint`'s existing static
methods (Phase 4B), the "RUN" command's body extracted into a shared
`DEBUG_AI_DoContinue()` function, one `DEBUG_AI_CheckPauseRequest()`
function, and two `DEBUG_AI_SetDebuggerActive()` call sites (Phase 4C), and
-- new in Phase 4D -- the F10/F11 key handlers' bodies extracted into two
shared functions (`DEBUG_AI_DoStepInto()`/`DEBUG_AI_DoStepOver()`, plus a
small shared `DEBUG_AI_HandleStepCallback()` helper), and one
`DEBUG_AI_CompletePendingSteps()` call site right next to `DEBUG_Loop()`'s
existing `DEBUG_AI_SetDebuggerActive(true)`), `dosbox-src/src/dosbox.cpp`
(Phase 4C: two calls in `Normal_Loop()`, right next to its existing
`DEBUG_ExitLoop()` check; untouched by Phase 4D), and
`dosbox-src/include/debug.h` (Phase 4C: two new declarations so
`dosbox.cpp` can reach the two debug.cpp/debug_ai.cpp functions above
without a new include dependency; untouched by Phase 4D) and the build file
lists (`Makefile.am`, `dosbox-x.vcxproj`, `dosbox-x.vcxproj.filters`). No
other DOSBox-X source was modified. The existing curses debugger UI, its
command processing (`ParseCommand`), and disassembler (`DasmI386`) are
untouched and continue to work exactly as before; breakpoints now have two
callers (the GUI's `BP`/`BPDEL`/`BPLIST` commands and the AI bridge)
sharing the one `CBreakpoint::BPoints` list DOSBox-X already had -- see
"Breakpoint management (Phase 4B)" below; the GUI's "RUN" command and the
AI bridge's `execution.continue` now share one implementation -- see
"Execution control (Phase 4C)" below; the GUI's F10/F11 keys and the AI
bridge's `execution.step_into`/`execution.step_over` now share one
implementation each -- see "Single-step control (Phase 4D)" below.

## Why this design

Gate A analysis (`docs/dosbox-debugger-analysis.md`, section 5.9) found that
DOSBox-X's debugger and its CPU emulation loop share **one thread**, with
**no mutex, condition variable, or other synchronization primitive anywhere
in `src/debug/`**. Registers (`cpu_regs`, `Segs`), guest memory, and
breakpoints (`CBreakpoint::BPoints`) are all read and written directly by
`debug.cpp` on the assumption that nothing else touches them concurrently.

A TCP bridge, by definition, introduces at least one more thread (to accept
connections and read requests without blocking the emulator). If that
thread touched `cpu_regs`/`Segs`/guest memory directly, it would race with
the emulator thread and violate the exact assumption the rest of the
debugger already depends on. So the bridge is split in two, matching the
architecture AGENTS.md section 2.3 already mandates:

```
 socket thread(s)                     accept / read / parse JSON /
    |                                 validate / send responses only
    |  thread-safe request queue      (never touches emulator state)
    v
 DEBUG_AI_Poll(), called from         drains the queue and executes each
 DEBUG_Loop()                         request using cpu_regs / Segs / guest
    |                                 memory / DasmI386() -- runs on the
    |                                 same thread as the rest of debug.cpp
    |  per-connection response slot
    v
 socket thread sends the response
```

### socket thread → request queue

`DEBUG_AI_Init()` starts one **accept thread** bound only to
`127.0.0.1:9876` (never `0.0.0.0`). Each accepted client gets its own
**connection thread** that blocks in `recv()`, reassembles newline-delimited
JSON lines, and for each line:

1. Rejects oversized input (`INVALID_REQUEST`) before parsing anything.
2. Parses it with a small hand-written JSON parser scoped to exactly what
   the protocol needs (flat objects of strings/numbers, one level of
   nesting for `params`, and flat arrays of strings/numbers -- the array
   support was added in Phase 4A specifically for `memory.write`'s
   `params.data`). Parse failure → `INVALID_JSON`.
3. Validates structure: `id` (number) and `method` (string) required
   (`INVALID_REQUEST` otherwise); method must be one of the seven
   implemented methods (`UNKNOWN_METHOD` otherwise); method-specific
   `params` are type- and range-checked (`INVALID_PARAMETER` otherwise) --
   `memory.read`/`memory.write` length is capped at 65536 bytes,
   `code.disassemble` count at 100, both mirroring the Phase 2
   `FakeDOSBoxDebugger` limits. `register.write` additionally checks the
   register name against a hard-coded whitelist (`WRITABLE_REGISTERS`) at
   this validation stage, before the request ever reaches the queue --
   see "Register write safety" below.
4. Only once a request is fully valid does it get pushed onto the global,
   mutex-protected `g_requestQueue` together with a `shared_ptr` to the
   connection's own response slot (a mutex + condition_variable + string).
5. The connection thread then blocks (up to 5 seconds) on that slot's
   condition variable, waiting for `DEBUG_AI_Poll()` to fill it in.

This matches the instruction that the socket thread's job is *only*
accepting, reading, parsing, validating, queueing, and sending -- steps
1-3 above never touch debugger state, so they can safely happen off the
emulator thread.

### DEBUG_AI_Poll() → emulator thread

`DEBUG_Loop()` (`debug.cpp`) now calls `DEBUG_AI_Poll()` as the very first
thing it does on every iteration -- before the `debug_running` branch, so
it runs whether the debugger is idle at its prompt or "running" toward a
breakpoint. `DEBUG_AI_Poll()` drains `g_requestQueue` (non-blocking: if
it's empty, it returns immediately so the normal debugger loop is not
delayed) and, for each request, calls straight into existing DOSBox-X
functionality:

| Method             | Existing functionality reused                                   |
|---------------------|-------------------------------------------------------------------|
| `debug.status`      | `reg_*` macros, `SegValue()`, `GetAddress()`, `DasmI386()`, `mem_readb_checked()`, plus `DEBUG_AI_IsDebugRunning()` (a 3-line accessor added to `debug.cpp` for the existing file-local `debug_running` flag) |
| `cpu.get`            | `reg_*` macros, `SegValue()` for `cs/ds/es/ss/fs/gs`             |
| `memory.read`        | `GetAddress()` + `mem_readb_checked()` per byte                 |
| `code.current`       | `GetAddress()` + `DasmI386()` + `mem_readb_checked()`            |
| `code.disassemble`   | same as `code.current`, looped, advancing the offset by each instruction's decoded length (16-bit wraparound), mirroring the walking pattern already used by `debug.cpp`'s own `getcodetext()` |
| `memory.write`       | `GetAddress()` + `mem_writeb_checked()` per byte (Phase 4A)      |
| `register.write`     | direct assignment to the `reg_*` macro for a whitelisted register (Phase 4A) |
| `breakpoint.set`     | `CBreakpoint::IsBreakpoint()` (dedup check) + `CBreakpoint::AddBreakpoint()` (Phase 4B) |
| `breakpoint.delete`  | `CBreakpoint::DeleteByIndex()` (Phase 4B)                        |
| `breakpoint.list`    | `CBreakpoint::GetCount()`/`GetByIndex()` (new, Phase 4B) + existing `GetType()`/`GetSegment()`/`GetOffset()` |
| `execution.continue` | `DEBUG_AI_DoContinue()` (debug.cpp) -- the exact body the GUI's "RUN" command used to have inline, extracted so both callers share it: `debug_running=false`, `debugging=false`, `DEBUG_Run(1,false)`, `DOSBOX_SetNormalLoop()` (Phase 4C) |
| `execution.pause`    | `DEBUG_Enable_Handler()` -- the exact same function Ctrl+Pause calls -- triggered from `DEBUG_AI_CheckPauseRequest()` (debug.cpp), called from `Normal_Loop()`'s existing `DEBUG_ExitLoop()`-adjacent hook (dosbox.cpp) (Phase 4C) |
| `execution.step_into` | `DEBUG_AI_DoStepInto()` (debug.cpp) -- the exact body the GUI's F11 ("trace into") key used to have inline: `DEBUG_Run(1,true)` (Phase 4D) |
| `execution.step_over` | `DEBUG_AI_DoStepOver()` (debug.cpp) -- the exact body the GUI's F10 ("step over") key used to have inline: `StepOver()` (debug.cpp's existing call/int/loop/rep detector + one-shot breakpoint placer) falling through to `DEBUG_AI_DoStepInto()`, or `DEBUG_Run(1,false)` for a call/int/loop/rep instruction (Phase 4D) |

No second disassembler, no second CPU/register model, no second
breakpoint system, and no second execution engine were written.
`GetAddress()` and `DasmI386()` are forward-declared `extern` in
`debug_ai.cpp` rather than duplicated; they are unmodified, existing
DOSBox-X functions.

`mem_readb_checked()`/`mem_writeb_checked()` return `true` on a page fault
/ inaccessible address; `memory.read` and `memory.write` surface that as
`{"ok":false,"error":{"code":"MEMORY_ERROR",...}}` instead of silently
returning zero, fabricating success, or writing through a fault, per
AGENTS.md section 22 and Phase3.md section 20 ("no fake data"). A partial
write that faults partway through still leaves whatever bytes it already
wrote in guest memory -- there is no rollback, matching how a real machine
behaves on a partial write.

### Register write safety (Phase 4A)

`register.write` only accepts `eax`, `ebx`, `ecx`, `edx`, `esi`, `edi`,
`ebp` (case-insensitive), enforced twice:

1. On the socket thread, before the request is even queued: an unknown
   name is `INVALID_PARAMETER`; a *recognized but disallowed* name (`eip`,
   `cs`/`ds`/`es`/`ss`/`fs`/`gs`, `esp`, `eflags`) is rejected with the
   dedicated `REGISTER_NOT_WRITABLE` error code, distinguishing "not a
   register" from "a real register we deliberately refuse to write."
2. `ExecRegisterWrite()` on the emulator thread only recognizes the same
   seven names -- so even a hypothetical future bug in the socket-side
   check could not write outside the whitelist.

EIP, the segment registers, ESP, and EFLAGS are excluded because writing
them can desync the debugger from the CPU (jump execution elsewhere,
corrupt the stack, flip privilege/interrupt state) in ways that go beyond
"change a value the AI is inspecting" -- Phase4A.md explicitly reserves
these for later, separate approval.

Once a request's result string is built, `DEBUG_AI_Poll()` writes it into
the request's connection response slot and notifies its condition
variable -- the only data that crosses back from the emulator thread to a
socket thread is that one already-serialized JSON string, handed off
through the mutex-protected slot.

### Breakpoint management (Phase 4B)

**Existing mechanism used.** DOSBox-X already has exactly one breakpoint
system: `class CBreakpoint` (`debug.cpp`) with a private static
`std::list<CBreakpoint*> BPoints`. The debugger GUI's `BP` command calls
`CBreakpoint::AddBreakpoint(seg,off,once)`; `BPDEL <n>` calls
`CBreakpoint::DeleteByIndex(n)`; `BPLIST` calls `CBreakpoint::ShowList()`,
which prints each breakpoint's *position* in `BPoints` (0-based,
front-to-back) as its displayed number. `BPoints.size()` and the ability
to fetch the breakpoint at a given position were not previously exposed
(`ShowList()` only prints to the debugger console; nothing returns
structured data), so Phase 4B adds two small `public:` methods to
`CBreakpoint` itself -- `GetCount()` and `GetByIndex(index)` -- using the
exact same list and the exact same positional numbering `ShowList()`
already established. These are read accessors only; they do not change
how breakpoints are stored, added, checked, or hit.

`debug_ai.cpp` never sees the `CBreakpoint` type at all -- five small
free functions in `debug.cpp` (`DEBUG_AI_BreakpointCount`,
`DEBUG_AI_BreakpointInfo`, `DEBUG_AI_BreakpointExists`,
`DEBUG_AI_BreakpointAdd`, `DEBUG_AI_BreakpointDelete`, declared in
`debug_ai.h`) wrap the `CBreakpoint` statics and pass only plain
seg/off/index/bool data across the boundary, keeping `debug_ai.cpp` free
of debugger internals, the same separation Phase 3B/4A already used for
`GetAddress()`/`DasmI386()`/the `reg_*` macros.

**Breakpoint "id" strategy.** The id `breakpoint.set`/`breakpoint.list`
return, and `breakpoint.delete` accepts, is the breakpoint's 0-based
position in `BPoints` -- the *same* id a human already sees in the GUI's
`BPLIST` output and would type into `BPDEL`. This is not a bridge-invented
identifier: no adapter/mapping table exists anywhere in `debug_ai.cpp`.
The tradeoff, inherited directly from DOSBox-X's own design (not
introduced by the bridge): **it is a position, not a stable identity.**
`AddBreakpoint()` calls `BPoints.push_front()`, so creating a *new*
breakpoint shifts every existing breakpoint's id up by one; deleting a
breakpoint shifts every later id down by one. A GUI user already has to
re-run `BPLIST` before trusting an index for `BPDEL` if anything changed
in between -- MCP callers must do the equivalent (`list_breakpoints()`)
before trusting an id for `delete_breakpoint()`. This is documented at
every layer (`debug_ai.h`, `DOSBoxClient`, the MCP tool docstrings).

**Duplicate address policy.** The native `BP` command has no duplicate
check -- a human can type `BP 1234:0100` twice and get two independent
`CBreakpoint` objects at the same address. `breakpoint.set`, by contrast,
calls the existing `CBreakpoint::IsBreakpoint(seg,off)` first and rejects
with `BREAKPOINT_ALREADY_EXISTS` if one is already there. This is a
deliberate **bridge-level policy choice** layered on top of the existing
mechanism (using an existing query function, not new bookkeeping) --
chosen because an AI agent's "make sure a breakpoint is here" intent
should be idempotent and shouldn't silently accumulate duplicate
`CBreakpoint` objects at one address (which would also make
`breakpoint.list` show confusingly duplicated entries). It does not change
what the GUI's own `BP` command does; a human can still stack duplicates
by hand if they want to.

**enabled is always `true`.** DOSBox-X's debugger has no enable/disable-
without-delete concept for breakpoints -- there is no `BPENA`/`BPDIS`
command anywhere in `debug.cpp`. A breakpoint either exists in `BPoints`
or it doesn't. `CBreakpoint::IsActive()` reflects a different, lower-level
thing: whether the `0xCC` trap byte is *currently* patched into guest
memory, which is toggled on/off around each `RUN`/continue
(`ActivateBreakpoints()`/`DeactivateBreakpoints()`) and would be
misleading if surfaced as a user-facing "enabled" flag -- it would read
`false` immediately after `breakpoint.set`, before the debugger next
runs, even though the breakpoint absolutely will fire.

**Scope: physical breakpoints only.** `breakpoint.list` walks the full
`BPoints` list (preserving true positions as ids) but only emits entries
where `GetType() == BKPNT_PHYSICAL`. Interrupt breakpoints (`BPINT`) and
memory watchpoints (`BPM`/`BPPM`/`BPLM`/`FM`) can still be created by a
human through the GUI and will continue to work exactly as before, but
Phase 4B's address-only MCP API has no representation for them, so they
are silently skipped in `breakpoint.list` rather than mis-rendered as
address breakpoints. This mirrors the address-only scope Phase4B.md
specifies (`breakpoint.set`'s only parameter is `address`).

### Execution control (Phase 4C)

**Two different plumbing paths, one per direction.** `execution.continue`
and `execution.pause` cannot share the same mechanism, because they start
from two different execution contexts:

* `execution.continue` is only meaningful while the debugger is already
  stopped -- `DEBUG_Loop()` is the active main-loop handler, so
  `DEBUG_AI_Poll()` is running. It is therefore just another method in the
  SAME `g_requestQueue`/`DEBUG_AI_Poll()` mechanism every read/write/
  breakpoint method (Phase 3B/4A/4B) already uses. `DEBUG_AI_Poll()`
  executing it calls `DEBUG_AI_DoContinue()` (debug.cpp), which is the
  exact body the GUI's own "RUN" command used to have inline (`ParseCommand()`'s
  `"RUN"` case now calls the same function instead of duplicating it):
  `debug_running=false`, `debugging=false`, `DEBUG_Run(1,false)`,
  `DOSBOX_SetNormalLoop()`.
* `execution.pause` is only meaningful while the debugger is NOT
  stopped -- guest code is running under `Normal_Loop()` (dosbox.cpp),
  which never calls `DEBUG_Loop()`/`DEBUG_AI_Poll()` at all, so there is
  nothing for the existing request queue to be drained by. A pause
  request is instead recorded in a small thread-safe pending list
  (`DEBUG_AI_RequestPause()`/`DEBUG_AI_HasPendingPause()`, both in
  debug_ai.cpp) that a NEW hook in `Normal_Loop()`'s existing
  per-iteration `DEBUG_ExitLoop()` check (dosbox.cpp) consumes --
  `DEBUG_AI_CheckPauseRequest()`, declared in `include/debug.h` and
  defined in debug.cpp, which calls `DEBUG_Enable_Handler()` -- the SAME
  function a physical Ctrl+Pause already calls -- to perform the actual
  "enter debugger" transition, then calls
  `DEBUG_AI_CompletePendingPauses()` to hand real, post-transition
  debugger state (via `ExecDebugStatus()`, the same builder `debug.status`
  uses) back to every connection waiting on it. Because this hook runs on
  every `Normal_Loop()` iteration -- many times per second while guest
  code executes -- a pause takes effect within roughly one instruction
  batch, the same responsiveness a physical Ctrl+Pause already has, not on
  a timer/poll schedule.

`DEBUG_Enable_Handler()` is a **toggle**: called again while already
debugging, it would instead resume execution. `DEBUG_AI_CheckPauseRequest()`
is only ever reached from `Normal_Loop()`, which by definition only runs
while the debugger is NOT already active, so this toggle's "enter debugger"
branch is always the one taken here -- never "exit".

**State model.** `g_debuggerActive` (a `std::atomic<bool>`, debug_ai.cpp)
mirrors whether `DEBUG_Loop()` is currently the active main-loop handler --
i.e. whether the debugger is genuinely stopped right now. It is written
ONLY from the emulator thread, at three points: `DEBUG_Loop()` sets it
`true` on every iteration it genuinely still controls (debug.cpp);
`DEBUG_AI_DoContinue()` sets it `false` the instant it calls
`DOSBOX_SetNormalLoop()` (debug.cpp); and `Normal_Loop()` sets it `false`
unconditionally on every call (dosbox.cpp) as a self-correcting safety net
-- Normal_Loop() only ever runs while the debugger is definitely not in
control, regardless of which internal code path (RUN, RUNWATCH-then-RUN,
F10/F11 stepping, a human closing the debugger, or `execution.continue`)
got it there, so this catches every transition even ones this file's other
Phase 4C hooks don't individually instrument. Socket threads only ever
READ this atomic (never write it) to decide, before touching anything
else: whether to answer `debug.status` immediately without enqueueing
(not active), whether to reject `execution.continue` with `ALREADY_RUNNING`
(not active) or `execution.pause` with `ALREADY_STOPPED` (active) without
waiting on anything.

**`debug.status` while running.** When `g_debuggerActive` is false, a
`debug.status` request is answered directly by the socket thread --
`{"stopped":false,"running":true}`, nothing else -- instead of being
enqueued to a `DEBUG_AI_Poll()` that will not run until the debugger is
re-entered (previously, in Phase 3B/4A/4B, this situation could only ever
be *reached* by first waiting out the 5-second `DEBUGGER_NOT_STOPPED`
timeout, since nothing before Phase 4C could ever leave the debugger
running in the first place). When active, `debug.status` is unchanged
from Phase 3B: enqueued and answered by `ExecDebugStatus()` with a full
snapshot, now also carrying a `"running"` field (the plain inverse of
`"stopped"`, added for symmetry -- existing consumers keyed off
`"stopped"` are unaffected).

### Single-step control (Phase 4D)

**Source analysis first, per Phase4D.md section 1.** Before writing any
C++, the existing step/step-over implementation was located and read (this
had already been identified during Phase 3's Gate A analysis --
`docs/dosbox-debugger-analysis.md` section 5.8/5.9/"Gate A Summary" row 6 --
and was re-confirmed by direct read for this phase): step-into is the F11
key (`DEBUG_CheckKeys()`, `debug.cpp`), which calls
`DEBUG_Run(1,true)` -- `quickexit=true`, so `DEBUG_Run()` runs exactly one
guest instruction through the real CPU decoder (`(*cpudecoder)()`) and
returns *without* switching the main loop away from `DEBUG_Loop()`; the
debugger stays in control the whole time, no cross-thread hand-off needed.
Step-over is the F10 key, which calls `StepOver()` (`debug.cpp`, existing,
unmodified) first: `StepOver()` disassembles the current instruction via
`DasmI386()` and, if the text contains "call", "int", "loop", or "rep",
places a one-shot breakpoint just past it (reusing
`CBreakpoint::AddBreakpoint(...,once=true)`, the exact same mechanism
`breakpoint.set` uses) and returns `true`; the F10 handler then calls
`DEBUG_Run(1,false)` -- `quickexit=false`, the SAME transition
`execution.continue`/RUN use, handing control to `Normal_Loop()` so the
subroutine/interrupt/loop runs for real until that one-shot breakpoint (or
any other) re-enters the debugger. If `StepOver()` returns `false` (not one
of those instruction kinds), the F10 handler falls through to the exact
same code F11 uses -- an ordinary step-into. No second CPU stepping
mechanism, no independent call-depth tracker, and no EIP arithmetic were
written anywhere in this phase; every state transition below is produced by
`DEBUG_Run()`/`StepOver()`/`CBreakpoint`, the same functions the human GUI's
F10/F11 keys already called.

**Two shared functions, not two copies.** `DEBUG_AI_DoStepInto()` and
`DEBUG_AI_DoStepOver()` (both `debug.cpp`) now hold the F10/F11 key
handlers' entire bodies (draw-state bookkeeping, `StepOver()`/`DEBUG_Run()`
calls, and -- new in this phase -- the post-`DEBUG_Run()` callback dispatch
every other `DEBUG_Run()` caller in this file already applies, factored
into a small `DEBUG_AI_HandleStepCallback()` helper so a single-stepped
instruction that itself invokes a `CALLBACK_Setup()`-registered routine,
e.g. `INT 21h` landing on a C++-implemented DOS API handler, is dispatched
identically whether triggered by a human or the AI bridge). `DEBUG_CheckKeys()`'s
`KEY_F(10)`/`KEY_F(11)` cases now just call these functions; `DEBUG_AI_Poll()`
calls the exact same functions for `execution.step_into`/`execution.step_over`.
This mirrors the Phase 4C precedent exactly (the "RUN" command's body
extracted into `DEBUG_AI_DoContinue()`, shared by `ParseCommand()` and the
bridge).

**step_into is always synchronous.** `ExecExecutionStepInto()` (debug_ai.cpp)
calls `DEBUG_AI_DoStepInto()` then immediately reuses `ExecDebugStatus()` --
the SAME builder `debug.status`/`execution.pause` use -- to return a full,
genuine post-step snapshot. Since `DEBUG_Run(1,true)` never leaves
`DEBUG_Loop()` in control of the loop pointer, this needs nothing beyond
the ordinary `g_requestQueue`/`DEBUG_AI_Poll()` mechanism every other method
(Phase 3B/4A/4B/4C) already uses.

**step_over is usually synchronous, sometimes asynchronous.** For any
instruction that isn't call/int/loop/rep, `DEBUG_AI_DoStepOver()` falls
through to `DEBUG_AI_DoStepInto()` internally and the request completes
synchronously exactly like step_into. For a call/int/loop/rep instruction,
`DEBUG_Run(1,false)` hands control to `Normal_Loop()` -- exactly like
`execution.continue` -- so there is no new "stopped" state to report yet.
`DEBUG_AI_DoStepOver()` signals this to its caller via an out-parameter
(`becameAsync`); `ExecExecutionStepOver()` (debug_ai.cpp) responds to it by
registering the request with `DEBUG_AI_RequestStepCompletion()` (a pending
list, `g_pendingSteps`, structurally identical to Phase 4C's
`g_pendingPauses`) instead of returning a response string -- signalled to
`DEBUG_AI_Poll()` by returning an empty string, which it recognizes as "do
not mark this connection's response ready yet." `DEBUG_AI_CompletePendingSteps()`
(debug_ai.cpp) drains that list and answers each pending request with a
real `ExecDebugStatus()` snapshot; it is called from `DEBUG_Loop()` itself,
right next to the existing `DEBUG_AI_SetDebuggerActive(true)` call (a
no-op, cheap empty-list check, on every iteration nothing is pending) --
deliberately the SAME place, and the SAME reasoning ("the debugger
genuinely has control again this iteration, no matter which of its several
entry points got it here") Phase 4C already established for that call site,
rather than a second, step-specific hook in `Normal_Loop()`/dosbox.cpp. No
changes to `dosbox.cpp` or `include/debug.h` were needed for step_over's
async path -- unlike `execution.pause` (which needs a `Normal_Loop()`-side
hook because pause only makes sense while the debugger is *not* active),
"the debugger regained control" is inherently a `DEBUG_Loop()`-side event
for step_over.

**Why not a third error code.** Both `execution.step_into` and
`execution.step_over` reject with the existing `ALREADY_RUNNING` (not a new
"cannot step" code) when `g_debuggerActive` is false -- the exact same
precondition and exact same meaning `execution.continue` already uses
`ALREADY_RUNNING` for. Phase4C.md's own reasoning for not adding
`EXECUTION_STATE_ERROR` ("every invalid state transition this design can
produce is precisely one of ALREADY_RUNNING/ALREADY_STOPPED, so a third,
vaguer code would have nothing distinct to report") applies again here, so
Phase4D.md section 8's suggested `STEP_NOT_AVAILABLE` was deliberately not
added either. A step_over that took the async path and does not complete
within `REQUEST_TIMEOUT_SECONDS` (5s) returns `EXECUTION_TIMEOUT` (the
same code Phase 4C defined) rather than the generic `DEBUGGER_NOT_STOPPED`
every other timed-out method returns -- the debugger genuinely was entered
and a step genuinely was kicked off, it just has not completed yet, so
`HandleLine()`'s shared enqueue+wait tail special-cases this one method's
timeout response (and cancels its pending-step registration via
`DEBUG_AI_CancelStep()`, mirroring `DEBUG_AI_CancelPause()`) rather than
falling through to the generic message.

**GUI consistency is explicit, not incidental.** `DEBUG_AI_DoStepInto()`
calls `DEBUG_DrawScreen()` after handling the step (in addition to the
`SetCodeWinStart()` that `DEBUG_Run(1,true)`'s `quickexit=true` branch
already performs internally, which only updates internal state, not the
visible screen) -- verified necessary empirically during this phase's live
testing: a step_into() issued purely from the AI bridge (no key ever
pressed) left the curses console showing the pre-step position until an
explicit repaint was added, because `DEBUG_AI_Poll()` runs *before*
`DEBUG_CheckKeys()`'s own draw call each `DEBUG_Loop()` iteration and
nothing else on that path repaints the screen. `DEBUG_AI_CompletePendingSteps()`
calls `DEBUG_DrawScreen()` once (before dispatching responses) whenever it
has anything pending, giving the async step_over path the same guarantee.
See "Build & runtime verification" below for the screenshot-based
confirmation this actually works, both for the synchronous and the async
case.

### Response slot → socket thread

The waiting connection thread wakes up, takes the completed response line,
and writes it to its own socket. If no response arrives within 5 seconds
(e.g. the debugger was never entered, so `DEBUG_Loop()` -- and therefore
`DEBUG_AI_Poll()` -- never runs), the connection thread instead sends
`{"ok":false,"error":{"code":"DEBUGGER_NOT_STOPPED",...}}` itself, without
ever touching debugger state.

## Protocol

Newline-delimited JSON, exactly as specified in Phase3.md section 8:

```
--> {"id": 1, "method": "cpu.get"}
<-- {"id": 1, "ok": true, "result": {"eax":"00000000", ..., "eflags":"00000202"}}

--> {"id": 2, "method": "memory.read", "params": {"address": "1234:0100", "length": 16}}
<-- {"id": 2, "ok": true, "result": {"address":"1234:0100","length":16,"bytes":["B8","34","12", ...]}}

--> {"id": 3, "method": "memory.write", "params": {"address": "1234:0100", "data": ["DE", "AD", "BE", "EF"]}}
<-- {"id": 3, "ok": true, "result": {"address":"1234:0100","length":4}}

--> {"id": 4, "method": "register.write", "params": {"register": "eax", "value": "0000ABCD"}}
<-- {"id": 4, "ok": true, "result": {"register":"eax","value":"0000ABCD"}}

--> {"id": 5, "method": "breakpoint.set", "params": {"address": "1234:0100"}}
<-- {"id": 5, "ok": true, "result": {"id":0,"address":"1234:0100","enabled":true}}

--> {"id": 6, "method": "breakpoint.list"}
<-- {"id": 6, "ok": true, "result": {"breakpoints":[{"id":0,"address":"1234:0100","enabled":true}]}}

--> {"id": 7, "method": "breakpoint.delete", "params": {"id": 0}}
<-- {"id": 7, "ok": true, "result": {"id":0,"deleted":true}}

--> {"id": 8, "method": "execution.continue"}
<-- {"id": 8, "ok": true, "result": {"stopped":false,"running":true}}

--> {"id": 9, "method": "debug.status"}
<-- {"id": 9, "ok": true, "result": {"stopped":false,"running":true}}

--> {"id": 10, "method": "execution.pause"}
<-- {"id": 10, "ok": true, "result": {"stopped":true,"running":false,"location":{...},"instruction":{...},"registers":{...},"segments":{...},"flags":{...}}}

--> {"id": 11, "method": "execution.step_into"}
<-- {"id": 11, "ok": true, "result": {"stopped":true,"running":false,"location":{...},"instruction":{...},"registers":{...},"segments":{...},"flags":{...}}}

--> {"id": 12, "method": "execution.step_over"}
<-- {"id": 12, "ok": true, "result": {"stopped":true,"running":false,"location":{...},"instruction":{...},"registers":{...},"segments":{...},"flags":{...}}}
```

`execution.continue`/`execution.pause`/`execution.step_into`/`execution.step_over`
take no `params`. `execution.step_into`'s and `execution.step_over`'s
results have the same shape as `execution.pause`'s -- a full, genuine
post-step `debug.status`-shaped snapshot, not an acknowledgement -- in both
cases, including when `execution.step_over` took the asynchronous
call/int/loop/rep path internally (the caller cannot tell from the response
shape whether the synchronous or asynchronous path was taken; only the
time-to-response differs). `execution.pause`'s
result has the same shape as `debug.status`'s full (stopped) result --
real, post-pause debugger state, not an acknowledgement.

`memory.write`'s `params.data` array elements may be JSON numbers or
2-digit hex strings (mixing both in one array is fine); `register.write`'s
`params.value` must be a 1-8 digit hex string; `breakpoint.set`'s `id`
result and `breakpoint.delete`'s `params.id` are positions in DOSBox-X's
own breakpoint list -- see "Breakpoint management" above for why these
shift when breakpoints are added/removed.

Error codes implemented: `INVALID_JSON`, `INVALID_REQUEST`,
`UNKNOWN_METHOD`, `INVALID_PARAMETER`, `DEBUGGER_NOT_STOPPED`,
`MEMORY_ERROR`, `REGISTER_NOT_WRITABLE` (Phase 4A), `INVALID_ADDRESS`,
`BREAKPOINT_NOT_FOUND`, `BREAKPOINT_ALREADY_EXISTS` (Phase 4B),
`ALREADY_RUNNING`, `ALREADY_STOPPED`, `EXECUTION_TIMEOUT` (Phase 4C -- and,
as of Phase 4D, also returned by `execution.step_over` when its async
call/int/loop/rep path doesn't complete in time).
(`INTERNAL_ERROR` exists both as a fallback for an unreachable switch case
and for the (should-never-happen) case where `AddBreakpoint()` succeeds
but the new breakpoint can't be found again to report its id.) Every
native error code is propagated unchanged through `DOSBoxClient` to the
MCP response -- see `DOSBoxClientError.code` in `ai/dosbox_client.py` --
never collapsed into a generic one. No new error codes were introduced in
Phase 4D -- see "Why not a third error code" under "Single-step control
(Phase 4D)" above for why `execution.step_into`/`execution.step_over`
reuse `ALREADY_RUNNING`/`EXECUTION_TIMEOUT` rather than adding
`STEP_NOT_AVAILABLE` (Phase4D.md section 8's suggestion).

`ALREADY_RUNNING`/`ALREADY_STOPPED` are answered immediately by the
socket thread (from `g_debuggerActive`, no queueing, no wait) rather than
being allowed to time out. `EXECUTION_TIMEOUT` is returned only if a
registered pause request doesn't complete within
`REQUEST_TIMEOUT_SECONDS` (5s) -- given `DEBUG_AI_CheckPauseRequest()`
runs on every `Normal_Loop()` iteration (many times per second), this is
not expected to happen under normal operation; it exists as a stable,
specific error for the case where it somehow doesn't (e.g. the emulator
thread is itself blocked on something else), rather than a generic
timeout or `DEBUGGER_NOT_STOPPED`. `EXECUTION_STATE_ERROR`
(Phase4C.md section 11's other suggested code) was deliberately not
added: every invalid execution-control state transition this design can
produce is precisely one of `ALREADY_RUNNING`/`ALREADY_STOPPED`, so a
third, vaguer code would have nothing distinct to report.

## Scope

Implemented, read-only (Phase 3B): `debug.status`, `cpu.get`,
`memory.read`, `code.current`, `code.disassemble`.

Implemented, write (Phase 4A): `memory.write` (any address/length within
the same bounds as `memory.read`), `register.write` (whitelisted GPRs
only -- see "Register write safety" above).

Implemented, breakpoints (Phase 4B): `breakpoint.set`, `breakpoint.delete`,
`breakpoint.list` -- physical (address) breakpoints only, against
DOSBox-X's own `CBreakpoint`/`BPoints` -- see "Breakpoint management"
above.

Implemented, execution control (Phase 4C): `execution.continue`,
`execution.pause` -- real guest CPU resume/stop, against the SAME
mechanisms (`DEBUG_Run()`/`DOSBOX_SetNormalLoop()`, `DEBUG_Enable_Handler()`)
the debugger GUI's own RUN command and Ctrl+Pause already use -- see
"Execution control (Phase 4C)" above.

Implemented, single-step control (Phase 4D): `execution.step_into`,
`execution.step_over` -- real guest CPU single-stepping, against the SAME
mechanisms (`DEBUG_Run()`, `StepOver()`, `CBreakpoint`) the debugger GUI's
own F11/F10 keys already use -- see "Single-step control (Phase 4D)"
above. As anticipated when Phase 4C's own "Deliberately not implemented
yet" note was written, no redesign of the threading model was needed: the
request queue/`DEBUG_AI_Poll()` integration point covers step_into and
step_over's synchronous case, and a pending-list pattern structurally
identical to Phase 4C's pause-request one covers step_over's asynchronous
case.

Deliberately **not** implemented: any modification of EIP, CS, ESP, or
EFLAGS write permissions (Phase4A.md explicitly reserves these for later,
separate approval; Phase 4D did not revisit this). Phase 5 autonomous AI
debugging (multi-step reasoning/investigation loops built on top of these
primitives) is explicitly out of scope for Phase 4D, per Phase4D.md's own
stop condition.

## Security

* Binds only to `127.0.0.1:9876` via explicit `inet_pton("127.0.0.1", ...)`
  -- never `INADDR_ANY`/`0.0.0.0`. If binding fails for any reason, the
  bridge logs the failure and stays disabled; it never falls back to a
  wider address.
* Every request is validated (size, JSON syntax, method whitelist,
  parameter types/ranges) before it can reach debugger state.
* `memory.read` length is capped at 65536 bytes and `code.disassemble`
  count at 100 instructions per request.
* All bridge activity (connect/disconnect, request id+method, warnings,
  errors) is logged through the existing `LOG(LOG_MISC, ...)` facility
  used elsewhere in `src/debug/` -- no new logging mechanism was added.
  Memory contents are never logged, only that a `memory.read` happened.

## Known limitations

* `DEBUG_AI_Poll()` only runs while `DEBUG_Loop()` is the active main-loop
  handler, i.e. while the debugger has been entered (Ctrl+Pause,
  `-break-start`, or an `INT3`/breakpoint hit). If DOSBox-X is running
  normally, queued requests wait until the debugger is entered or until
  their 5-second client-side timeout elapses and they get a
  `DEBUGGER_NOT_STOPPED` response. This matches the workflow AGENTS.md
  section 27 describes (the debugger is already stopped before the AI
  queries it) and is what Phase3.md section 5 explicitly asked for
  ("integrate request processing into the existing `DEBUG_Loop`
  execution path").
* One in-flight request per TCP connection (the connection thread blocks
  until its response arrives before reading the next line). Multiple
  concurrent requests are supported by opening multiple connections.
* The bundled JSON parser only supports the shapes this protocol uses
  (flat objects of strings/numbers, one level of nesting, and flat arrays
  of strings/numbers for `memory.write`'s `params.data`); it is not a
  general-purpose JSON parser and would need extending further for
  deeper nesting or arrays of objects.
* `memory.write` has no atomicity guarantee: if a multi-byte write faults
  partway through (`MEMORY_ERROR`), the bytes already written before the
  fault remain written. Callers that need all-or-nothing semantics should
  `memory.read` first to confirm the range is mapped.
* Connection threads are `detach()`ed rather than tracked/joined
  individually; `DEBUG_AI_ShutDown()` signals every connection to stop
  (closing/shutting down its socket and notifying its condition variable)
  and returns without blocking on slow clients. `std::shared_ptr` keeps
  each `AIConnection` alive until its own thread actually exits, so this
  is safe, just not synchronous.
* (Phase 4B) Breakpoint ids are positions, not stable identities -- see
  "Breakpoint management" above. Concurrent `breakpoint.set`/
  `breakpoint.delete` calls from multiple connections are individually
  safe (serialized through the same request queue as everything else, so
  no corruption or crash), but a client holding an id from an earlier
  `breakpoint.list` can no longer assume that id still points at the same
  breakpoint if *any* add/delete happened in between -- from any
  connection, or from a human using the GUI's `BP`/`BPDEL` at the same
  time. Re-list before deleting if this matters.
* (Phase 4B) `breakpoint.list` only reports physical (address)
  breakpoints; interrupt and memory-watch breakpoints set through the GUI
  are invisible to the MCP layer (they still work normally in the
  debugger itself).
* (Phase 4B) `breakpoint.set`'s duplicate-address rejection
  (`BREAKPOINT_ALREADY_EXISTS`) is enforced only through the bridge --
  the GUI's own `BP` command can still create address duplicates that the
  bridge did not create. `breakpoint.list` would then show two entries at
  the same address with different ids; deleting either one is well
  defined (`DeleteByIndex` on its specific position), just not something
  the bridge itself will ever produce.
* (Phase 4C) **Physical breakpoints cannot fire in ROM.** Confirmed
  empirically while building this session's live test: `write_memory` to
  `F000:E05B` (BIOS ROM) reports `ok:true`, but a follow-up `memory.read`
  shows the byte unchanged -- DOSBox-X's BIOS ROM (and likely other ROM
  segments, e.g. `C000` VGA BIOS) silently discards writes.
  `ActivateBreakpoints()`'s `0xCC` trap patch is therefore a no-op
  anywhere in ROM, so `breakpoint.set` + `execution.continue` can only
  ever be demonstrated (or used) against a breakpoint address in genuine,
  writable guest RAM -- the exact same limitation the debugger GUI's own
  `BP` command has, since both patch memory the same way. This is why
  `tests/test_mcp_native_bridge.py`'s Phase 4C breakpoint test runs a real
  DOS COM program (`drive_c/TEST.COM`, per AGENTS.md section 26) rather
  than targeting the reset vector's own ROM jump target.
* (Phase 4C) Continuing from the raw CPU reset vector (`-break-start`'s
  entry point, `F000:FFF0`) with no program configured to auto-run was
  observed to settle into a ROM "wait for input" idle loop (repeatedly
  sampled at `F000:D186`, an `IRET`) rather than ever reaching DOS --
  `-break-start` enters the debugger at a lower-level point than
  DOSBox-X's internal-DOS boot shortcut. Reaching genuine, writable-RAM
  code (needed for any real breakpoint demonstration) requires actually
  running a program, e.g. `dosbox-x.exe -break-start drive_c\TEST.COM`.
* (Phase 4C) `g_debuggerActive` defaults to `false` at bridge startup
  (`DEBUG_AI_Init()`, called from the always-run `DEBUG_Init()`) and only
  becomes `true` once `DEBUG_Loop()` first actually runs. With
  `-break-start`, `DEBUG_EnableDebugger()` runs before
  `DOSBOX_RunMachine()`'s loop starts, so `DEBUG_Loop()` is the very first
  thing that loop calls -- there is a real but sub-millisecond window
  between the bridge starting to listen and that first call in which a
  `debug.status`/`execution.pause` request would see the (momentarily
  incorrect) fast "running" path. Not observed to matter in practice: a
  client connecting takes measurably longer than this window.
* (Phase 4C) `EXECUTION_TIMEOUT` is implemented and propagated through
  every layer (native bridge -> `DOSBoxClient` -> MCP), but is not
  exercised by an automated test -- doing so would require artificially
  stalling the emulator thread, which none of this session's other tests
  need to do and which isn't a state the bridge itself can induce.
* (Phase 4D) `execution.step_over`'s `EXECUTION_TIMEOUT` path has the same
  "not exercised by an automated test" limitation as Phase 4C's
  pause-side one, but for a different reason: it *could* be exercised
  deliberately (unlike stalling the emulator thread, nothing prevents a
  test program from `CALL`ing a subroutine that never returns), but doing
  so was judged not worth adding to this phase's test programs given the
  5-second wait it would add to every test run; the code path itself
  (`HandleLine()`'s step_over-specific timeout branch, `DEBUG_AI_CancelStep()`)
  is exercised implicitly by every step_over integration test completing
  successfully well inside that timeout.
* (Phase 4D) DOSBox-X's own emulated CPU speed (this project's default
  configuration: 3000 cycles/ms, matching real early-1990s hardware) is
  slow enough in wall-clock terms that a busy-wait loop sized for Phase 4C's
  purposes (TEST.COM's ~268 million iterations, chosen for a wide
  continue/pause "catch window" when the loop is merely being run *through*
  and a breakpoint inside it is hit on its very first pass) takes on the
  order of a minute or more to run to genuine *completion* -- impractical
  for a test that needs the whole loop to finish (drive_c/STEP.COM's own
  warm-up loop, used to reach its deterministic step_into/step_over test
  sequence, deliberately uses a much smaller iteration count -- see
  `tests/test_step_execution.py`'s module docstring for the arithmetic).
  This is a property of the default emulated speed, not of the AI bridge
  or the stepping mechanism itself; a real AI agent single-stepping through
  a normal-sized subroutine (not a multi-hundred-million-iteration busy
  loop) will not encounter it.
* (Phase 4D) A Release build of `dosbox-x.vcxproj` uses Whole Program
  Optimization (`/GL`, LTCG). During this phase's own build/verify cycle, a
  purely *incremental* rebuild (touching only `debug.cpp`/`debug_ai.cpp`/
  `debug_ai.h` between builds, without a `Clean` first) twice produced a
  binary that built with 0 errors/warnings but crashed
  (`STATUS_STACK_BUFFER_OVERRUN`, `0xC0000409`, confirmed via Windows'
  Application Error event log) within a few seconds of entering the
  debugger -- reproducibly, at the identical fault offset, on code paths
  (an unconditional, empty-list-fast-path function call on every
  `DEBUG_Loop()` iteration) that have no plausible logic bug. A `Clean`
  followed by a full rebuild produced a binary that ran correctly, and
  every crash symptom disappeared. This is consistent with a known class of
  MSVC LTCG incremental-link hazard (stale/inconsistent code generation
  across an incremental Release+LTCG link), not a bug in this phase's C++
  changes -- but it means an incremental Release+LTCG build of this project
  cannot be trusted as a verification artifact; a `Clean` + full rebuild is
  required before any live verification session, and this phase's own
  "Build & runtime verification" results below are from such a clean build.

## Build & runtime verification

**Phase 3B** (see the Phase 3B completion report for full detail): build
0 errors; `dosbox-x.exe -break-start` launched the normal debugger GUI and
`127.0.0.1:9876 LISTENING`; `tests\test_native_bridge.py` 34/34 checks
passed against genuinely live emulator state (`CS:EIP = F000:FFF0`,
`jmp F000:E05B`, BIOS date stamp `01/01/92` in guest memory).

**Phase 4A** (see the Phase 4A completion report for full detail):
rebuilt just `dosbox-x.vcxproj` (dependencies unchanged) -- 0 errors;
relaunched `dosbox-x.exe -break-start`, `127.0.0.1:9876 LISTENING`
reconfirmed; full pytest suite (41 tests: 17 Phase 2 FakeDOSBoxDebugger +
24 live-bridge integration, including memory/register write round trips,
invalid-input rejection, and a 5-connection concurrency test) passed
against this live instance; a real MCP session confirmed `write_memory`
persists bytes visible to a follow-up `read_memory`, `write_register`
persists a value visible to a follow-up `get_cpu_state`, and writing a
protected register (`eip`) is correctly rejected with
`REGISTER_NOT_WRITABLE`.

**Phase 4B** (see the Phase 4B completion report for full detail):
rebuilt just `dosbox-x.vcxproj` -- 0 errors; relaunched
`dosbox-x.exe -break-start`, `127.0.0.1:9876 LISTENING` reconfirmed; full
pytest suite (50 tests: the 41 above + 9 new breakpoint tests covering
set/list/delete round trips, invalid address, nonexistent-id deletion,
duplicate-address rejection, and an 8-connection concurrent-set test)
passed against this live instance; a real MCP session confirmed the
positional-id shift documented above actually happens (a second
`set_breakpoint` pushed the first breakpoint from id 0 to id 1) and that
deleting both by their current ids correctly emptied the list. The
required human GUI cross-check (Phase4B.md section 7) could not be
performed by the agent itself -- no GUI automation is permitted and the
agent has no way to visually inspect the debugger window -- so a
breakpoint was set via MCP (`1234:0100`) and the human confirmed via the
debugger console's `BPLIST` command that it showed `00. BP 1234:0100`;
the agent then deleted it via MCP, and the human re-ran `BPLIST` and
confirmed the list was empty. Both directions of the required GUI/MCP
consistency check are confirmed against the same live instance.

**Phase 4C** (see the Phase 4C completion report for full detail): rebuilt
just `dosbox-x.vcxproj` (Visual Studio "18"/MSVC 14.51, `PlatformToolset`
overridden to `v145` on the command line to match this machine's actual
installed toolset -- the checked-in `.vcxproj` still declares `v142`) --
0 errors; relaunched `dosbox-x.exe -break-start drive_c\TEST.COM` (a new
Phase 4C test program, see below), `127.0.0.1:9876 LISTENING` reconfirmed;
`tests\test_native_bridge.py` 50/50 raw-protocol checks passed, including
`execution.continue`/`execution.pause`/`debug.status`-while-running/
`ALREADY_RUNNING`/`ALREADY_STOPPED` against this live instance (real
CS:EIP moved from `F000:FFF0` to `C000:0003` across one continue+pause
cycle in that run, and ESP/EFLAGS changed too -- not a fabricated
response); full pytest suite (57 tests: the 50 above + 7 new Phase 4C
tests covering already-stopped/already-running rejection, the
`running`/`stopped` field pair, a deterministic breakpoint-stops-real-
execution scenario against `drive_c/TEST.COM`'s busy loop (breakpoint hit
23ms after `execution.continue`, real changing register state confirmed
via `cpu.get`), a continue-then-pause round trip, and two concurrent
connection-A-mutates/connection-B-reads-status scenarios per Phase4C.md
section 10) passed against a freshly-relaunched instance; a real MCP
session (via `mcp.list_tools()`/`mcp.call_tool()`, the same protocol layer
MCP Inspector itself uses) confirmed `tools/list` contains
`continue_execution`/`pause_execution` and that calling them resumes and
then genuinely stops the guest CPU (BX/CX register values differed
between two consecutive `pause_execution()` calls with a
`continue_execution()` in between, proving the CPU actually ran).
The required human GUI cross-check (Phase4C.md section 13) was performed
after this report was first written: the agent called `continue_execution()`
via MCP while the human watched the debugger console, and the human
confirmed the GUI left its stopped display; the agent then called
`pause_execution()`, and the human confirmed the GUI returned to the
stopped display showing `CS:EIP = 0816:0106` -- the exact location
`pause_execution()`'s own response reported (registers had also visibly
changed from the pre-continue snapshot, e.g. BX 0FFD->095B, CX CFE7->B384,
confirming genuine execution occurred in between). Both directions of the
required GUI/MCP consistency check are confirmed against the same live
instance.

**`drive_c/TEST.COM`** (new in Phase 4C, per AGENTS.md section 26): a
16-byte hand-assembled DOS COM program --
`BB 00 10 B9 FF FF 90 E2 FD 4B 75 F7 B4 4C CD 21`, equivalent to:

```
ORG 100h
        MOV BX, 1000h
outer:  MOV CX, 0FFFFh
inner:  NOP
        LOOP inner
        DEC BX
        JNZ outer
        MOV AH, 4Ch
        INT 21h
```

A deliberately long (~268 million iteration) busy loop in genuine,
writable conventional RAM -- used by `tests/test_mcp_native_bridge.py`'s
breakpoint+continue test (and documented in its module-level comment) as
a real, deterministic breakpoint target, after `write_memory`/
`read_memory` established that DOSBox-X's BIOS ROM segments silently
discard writes and so cannot host a working physical breakpoint.

**Phase 4D**: `Clean` followed by a full rebuild of `dosbox-x.vcxproj`
(same toolchain override as Phase 4C: `PlatformToolset=v145`; see "Known
limitations" above for why the initial incremental rebuild attempt was
discarded) -- 0 errors, 0 warnings. Two live verification passes were run,
each against its own freshly-launched instance (per the reasoning in
`tests/test_step_execution.py`'s module docstring, `drive_c/TEST.COM` and
`drive_c/STEP.COM` cannot both be the auto-run program in the same
process, so -- like each of Phase 4A/4B/4C's own relaunches with different
arguments -- this phase needed two):

* `dosbox-x.exe -break-start drive_c\TEST.COM`, `127.0.0.1:9876 LISTENING`
  reconfirmed: `tests\test_native_bridge.py` 63/63 raw-protocol checks
  passed, including `execution.step_into`/`execution.step_over` against
  the live reset-vector state (`step_into` on the reset vector's own
  `jmp F000:E05B` moved real CS:EIP from `F000:FFF0` to `F000:E05B`
  exactly, confirmed instruction-for-instruction against the documented
  reset-vector behavior; `step_over` on the instruction there, which
  happened to disassemble as `"callback 001B"` -- containing the substring
  `"call"`, so `StepOver()` genuinely took the one-shot-breakpoint async
  path -- completed correctly, landing at a real, different CS:EIP with
  real changed register state) and `ALREADY_RUNNING` rejection for both
  methods while running; full pytest suite (57 tests, the complete
  Phase 2/3B/4A/4B/4C regression set, none touched by Phase 4D) passed
  against a separately-launched instance of the same command line,
  confirming zero regressions.
* `dosbox-x.exe -break-start drive_c\STEP.COM` (a new Phase 4D test
  program, see below), `127.0.0.1:9876 LISTENING` reconfirmed:
  `tests\test_step_execution.py` 11/11 tests passed against this live
  instance -- step_into over two ordinary instructions (verifying both
  CS:EIP and the executed instruction's real register effect each time);
  step_into INTO a `CALL` (landing inside the called function, at its
  first instruction, before that instruction has executed); step_over
  ACROSS a different `CALL` to a different function (landing at the
  instruction after the `CALL`, with that function's own instruction's
  real register effect (`EDX`) already visible -- proving the subroutine
  genuinely ran to completion via `RET`, not that step_over silently
  skipped it); step_over on an ordinary instruction behaving identically
  to step_into; a real `RET` (via step_into, since `RET` is not
  call/int/loop/rep) returning to the real post-`CALL` address; three-way
  cross-checks between `debug.status`/`cpu.get`/`code.current` after a
  step; and `ALREADY_RUNNING` rejection for both methods while running. A
  real MCP session (via `mcp.list_tools()`/`mcp.call_tool()`, the same
  protocol layer MCP Inspector itself uses, per the Phase 4C precedent)
  confirmed `tools/list` contains `step_into`/`step_over` and that calling
  them produces genuine CS:EIP/register transitions.

The required human GUI cross-check (Phase4D.md section 12) was performed
by the agent itself this session via OS-level window screenshots (not GUI
*automation* -- no synthetic keyboard/mouse input was sent to DOSBox-X or
its debugger; the window was only brought to the foreground and
photographed, the same non-interactive observation a human glancing at the
screen would make) rather than a human collaborator, since none was
available to watch the screen live during this run. This surfaced a real
gap during verification: the first screenshot taken after an MCP
`step_into()` call showed the debugger console still displaying the
*pre-step* position, unchanged even after forcing an OS-level window
repaint (minimize/restore) -- i.e. genuinely stale, not a screenshot
capture artifact. This was `DEBUG_AI_DoStepInto()`/
`DEBUG_AI_CompletePendingSteps()` missing an explicit `DEBUG_DrawScreen()`
call (see "GUI consistency is explicit, not incidental" above); once
added and rebuilt, a follow-up screenshot after another `step_into()`
showed the debugger console's Code Overview pane correctly highlighting
`0816:0100` with the exact instruction (`mov sp,0400`) and register values
(`CS=0816`, `ESP=0000FFFE`) `step_into()`'s own MCP response reported for
that call, and a further screenshot after a `step_over()` that took the
asynchronous path (stepping over an `"callback 0038"` instruction, landing
past it) correctly showed `F000:0000D105` (`iret`) highlighted, matching
that response's location exactly, with `EAX`/`ESP` visibly changed from
the pre-step snapshot. Both the synchronous and asynchronous GUI-redraw
paths are confirmed against the same live instance; the underlying
screenshots are not included in this repository (they were used only to
inspect the running window during this session and are not build
artifacts).

**`drive_c/STEP.COM`** (new in Phase 4D, per Phase4D.md section 5 -- "at
least: ordinary instruction, CALL, return"): a 42-byte hand-assembled DOS
COM program -- `BB 40 00 B9 FF FF 90 E2 FD 4B 75 F7 B8 11 11 BB 22 22 E8
0D 00 B9 33 33 E8 0B 00 BE 55 55 B4 4C CD 21 BA 44 44 C3 BF 66 66 C3`,
equivalent to:

```
ORG 100h
        MOV BX, 0040h        ; busy-loop warm-up (small -- see below)
outer:  MOV CX, 0FFFFh
inner:  NOP
        LOOP inner
        DEC BX
        JNZ outer
landing:
        MOV AX, 1111h         ; ordinary instruction
        MOV BX, 2222h         ; ordinary instruction
        CALL func1                    ; step_over() target
        MOV CX, 3333h         ; instruction immediately after CALL func1
        CALL func2                    ; step_into() target
        MOV SI, 5555h                 ; instruction immediately after CALL func2
        MOV AH, 4Ch
        INT 21h                        ; exit
func1:
        MOV DX, 4444h                 ; proves func1 genuinely ran
        RET
func2:
        MOV DI, 6666h                 ; proves step_into() lands INSIDE func2
        RET
```

The busy-loop warm-up has the same shape as `drive_c/TEST.COM`'s own loop
(same opcodes/registers, same relative-displacement encodings) -- reusing
the SAME "catch a program auto-running via repeated continue/pause,
matched against a known byte signature at its load segment's offset 0100"
technique `tests/test_mcp_native_bridge.py` already established for
TEST.COM -- but with a much smaller outer-loop count. TEST.COM's loop is
sized to be *run through* quickly (a breakpoint inside it is hit on the
very first pass, regardless of loop length); STEP.COM's own test needs its
warm-up loop to run to genuine *completion* before reaching `landing`, and
at this project's default emulated CPU speed TEST.COM's ~268-million-
iteration loop would take on the order of a minute or more to actually
finish (see "Known limitations" above) -- so STEP.COM's loop uses a
0x40 outer count instead, empirically well under 5 seconds to complete
while still comfortably wide enough for the continue/pause catch technique
to work reliably. Two independent `CALL`s (to `func1`/`func2`) let the
step_over-skips-the-call and step_into-enters-the-call scenarios each be
demonstrated once, using real, distinct code paths, without needing to
revisit any address a COM program's inherently linear, run-once control
flow can't return to.

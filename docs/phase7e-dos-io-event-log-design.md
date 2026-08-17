# Phase 7E: DOS file I/O high-level event log (Epic E)

> Scope: Epic E of
> `docs/phase7-observability-and-autonomous-control-requirements.md`
> (`dos.io.configure`/`.list`/`.clear`).
> Status: design, grounded in source investigation. Not yet implemented.

## Goal

Let an agent see, without instrumenting the guest program itself, which
DOS file the guest just opened/read/wrote/sought/closed, with real
`AX`/carry results, the caller's `DS:DX` buffer, and (for locally
mounted drives) the corresponding host path -- so an agent can answer
"which file did this write come from" and correlate it with a memory
watchpoint on `buffer.linear`, exactly this project's own
`docs/case-study-dark-sun-gpli-debugging.md` workflow.

## Architecture: five targeted hooks inside the existing INT 21h dispatcher, one mutex-guarded store

Unlike Epic D, this needs no per-instruction hot path at all -- DOS file
I/O (`open`/`close`/`read`/`write`/`seek`) is comparatively rare
(hundreds/thousands of calls per session, not millions of instructions),
so a plain `std::mutex` around both the configuration AND the event
ring buffer is cheap enough here, unlike `logHeavy`'s lock-free design
in Epic D. This significantly simplifies the threading model: no
dual-route (stopped vs. running), no atomic config -- every
`dos.io.*` method, including `dos.io.configure`, is answered directly
from whichever socket thread receives it, under one mutex, exactly like
Phase 7C's `input.receipt.get`/Phase 7D's `trace.execution.list`/`.get`.
A separate lock-free `std::atomic<bool> g_dosIoEnabled` gates the fast
"disabled" path inside the five hooks so a disabled configuration costs
one relaxed atomic load per relevant INT 21h call, not a mutex
acquisition.

### The five hook sites: `DOS_21Handler()` (`src/dos/dos.cpp:1025`)

DOS_21Handler() is a giant `switch (reg_ah)`, one case per DOS service.
Investigation confirms each of the five in-scope services already
computes real post-call results (not merely echoing the request) before
its own `CALLBACK_SCF(...)`/`break;`:

| Service | Case | Real results already computed at that point |
|---|---|---|
| `3Dh` Open | `dos.cpp:1931` | `reg_ax` = new handle (success) or `dos.errorcode` (failure); `name1` still holds the DOS-side path string used to open it |
| `3Eh` Close | `dos.cpp:2010` | `reg_al`/carry; handle (`reg_bx`) and its `DOS_File*` (`Files[handle]`) are still valid at hook time (looked up BEFORE `DOS_CloseFile()` invalidates them) |
| `3Fh` Read | `dos.cpp:2046` | `reg_ax` = actual bytes transferred (`toread`, already truncated to what really happened); `Files[handle]` still open |
| `40h` Write | `dos.cpp:2132` | `reg_ax` = actual bytes transferred (`towrite`) |
| `42h` Lseek | `dos.cpp:2197` | `reg_ax`/`reg_dx` = new position; `pos` local variable holds it too |

A one-line call to a new `DEBUG_AI_LogDosIoEvent(...)`-style hook is
inserted at the exact point each case has already decided
success/failure and set `reg_ax`/carry, mirroring Epic D's pattern of
targeted, additive hooks at existing decision points rather than
restructuring the function. `include_failed` (default true) is honored
inside the hook itself, not by skipping the call -- keeps the hook
sites uniform (always call it; let the hook's own config decide what to
keep).

**Why not wrap `DOS_21Handler()` itself** (a single hook covering all
`AH` values generically): every one of the ~90 other `AH` subfunctions
would then pay a check on every call, not just the five in scope here;
the per-case hook only costs anything when one of the five relevant
services is actually invoked.

### `cs_ip`: the calling program's return address, off the stack

`DOS_21Handler()` runs as an installed callback
(`callback[1].Install(DOS_21Handler,CB_INT21,...)`,
`dos.cpp:4587`) -- `reg_cs`/`reg_eip` at this point reflect the callback
mechanism, not the calling program. This project's own `dos.cpp`
already has the precedent for reading the real caller's return address
off the stack (`dos.cpp:1114,1118`):

```cpp
uint16_t callerIp = mem_readw(SegPhys(ss) + reg_sp);       // [SP+0]
uint16_t callerCs  = mem_readw(SegPhys(ss) + reg_sp + 2);   // [SP+2]
```

(the standard `INT` frame: IP, CS, FLAGS pushed in that order). Reused
verbatim for `cs_ip`.

### `process.psp_segment`: `dos.psp()`

Already a plain existing accessor (`dos.psp()`, used throughout
`dos.cpp`) -- no new state.

### `handle`

`reg_bx` for close/read/write/seek. For open, the handle is only known
on success (`reg_ax` after `DOS_OpenFile()` returns true) -- `null` on
a failed open.

### `path_dos`

For open: `name1` (the buffer `DOS_21Handler()` already populated via
`MEM_StrCopy(SegPhys(ds)+reg_dx, name1, DOSNAMEBUF)` before calling
`DOS_OpenFile()`) -- captured before the call, valid regardless of
success/failure.

For close/read/write/seek (identified by handle, not a path argument):
resolved from the open file's own state --
`Files[RealHandle(reg_bx)]->GetName()` (the DOS-relative name recorded
at open time, `DOS_File::SetName()`/`GetName()`, `include/dos_system.h:82-83`)
combined with `Files[handle]->GetDrive()` (`include/dos_system.h:91`) to
prefix the drive letter, e.g. `"C:\GAME\GPLDATA.GFF"`. `null` if the
handle is already invalid (e.g. a `close` on an already-closed handle --
`include_failed` still records the failure event itself, just without
a resolvable path).

### `path_host`

Only populated when the file's drive is a `localDrive` (a real
mounted host directory -- the common `MOUNT C C:\some\folder` case),
via `dynamic_cast<localDrive*>(Drives[drive])` -- an already-established
pattern in this exact codebase (`dos.cpp:823`, `dos_files.cpp:2469`,
`cdrom_image.cpp:1750`) -- then `localDrive::GetHostName(name)`
(`drive_local.cpp:2105`), which DOSBox-X's own code already uses to
convert a DOS-relative name to a canonical host path (applies
`CROSS_FILENAME`, code-page conversion, and an existence check,
returning empty string if the file can't be `stat()`-ed). `null` for
every other drive type (image-mounted, ISO, network, a
non-localDrive `Overlay_Drive`, etc.) -- exactly the "only within a
mounted DOS drive, canonical path" requirement (`path_host` never
walks outside `GetHostName()`'s own basedir-rooted construction, so
there is no separate escape check to add).

### `file_offset_before`

`DOS_File::GetSeekPos()` (`include/dos_system.h:89`), called on
`Files[handle]` BEFORE the operation executes (i.e. the hook captures
this at entry to the `read`/`write`/`seek` case, before
`DOS_ReadFile()`/`DOS_WriteFile()`/`DOS_SeekFile()` mutates it). The
base class default (`0xffffffff`) is DOSBox-X's own existing "not
available" sentinel for this method (only `LocalFile` overrides it with
a real value) -- mapped to JSON `null` rather than a fake `0`, matching
the requirements draft's "無法取得時為 null，不得猜測."

### `buffer`

For read/write: `SegValue(ds)`/`reg_dx` (the real-mode segment:offset
DOSBox-X's own code already reads the transfer buffer from,
`dos.cpp:2087,2153`) and `GetAddress(SegValue(ds), reg_dx)` for
`buffer.linear` -- the SAME `GetAddress()` helper Epic A-D's own
`debug_ai.cpp` code already calls repeatedly. `null` for
open/close/seek (no transfer buffer involved).

## Event storage and filtering

```cpp
struct DosIoEvent {
    uint64_t eventId;
    uint64_t emulatedMs;
    std::string operation;   // "open"|"close"|"read"|"write"|"seek"
    uint16_t csIp_cs, csIp_ip;
    uint16_t pspSegment;
    int32_t handle;          // -1 == null
    std::string pathDos;     // empty == null
    std::string pathHost;    // empty == null
    int64_t fileOffsetBefore; // -1 == null
    int32_t requestedBytes;  // -1 == null (open/close/seek)
    int32_t transferredBytes; // -1 == null
    uint16_t bufSeg, bufOff; bool hasBuf;
    uint32_t bufLinear;
    bool carry;
    uint16_t ax;
    int32_t dosError;        // -1 == null (success)
};

struct DosIoConfig {
    bool enabled = false;
    std::set<std::string> operations;   // empty == all five
    std::vector<std::string> pathGlobs; // empty == all paths
    bool includeFailed = true;
    uint32_t maxEvents = 10000;
};

static std::mutex g_dosIoMutex;
static DosIoConfig g_dosIoConfig;
static std::deque<DosIoEvent> g_dosIoEvents;
static uint64_t g_dosIoDroppedEvents = 0;
static std::atomic<uint64_t> g_nextDosIoEventId{1};
static std::atomic<bool> g_dosIoEnabled{false}; // fast-path mirror of g_dosIoConfig.enabled
```

`path_globs` matching: a small case-insensitive `*`/`?` glob matcher
(new, ~15 lines -- DOSBox-X's own `WildFileCmp()`, `drives.cpp:60`, is
specifically 8.3-filename-shaped and too narrow for matching full
paths like `SAVE-*`; its sibling `wild_match()` one function above it
demonstrates the same recursive-backtracking shape this reuses, just
made explicitly case-insensitive and given its own `const`-correct
signature rather than depending on that internal helper's assumptions).
Applied against `path_dos` (uppercased). An event that fails the
`operations`/`path_globs` filter is never constructed into the ring
buffer at all (per the requirements draft: "不符合 filter 的事件不得
佔用 ring buffer").

`max_events` (default 10,000): evicted oldest-first,
`dropped_events` incremented -- same shape as Phase 7C's receipt ring
buffer, just count-bounded only (no time bound in the requirements
draft for this one).

## API (from the Phase 7 draft, section 7.2, unchanged)

See the requirements draft for the full shapes. `dos.io.configure`
replaces the whole configuration each call (like
`trace.execution.configure`), not a partial merge.

## Non-goals (from the requirements draft, section 7.1/9)

Real-mode `INT 21h` only -- no FCB-style file access, no `EXEC`, no DOS
extender/protected-mode file I/O. Content of `write` calls is never
captured (`buffer.linear` lets an agent read it separately via
`read_memory` if genuinely needed, at their own request, not
automatically).

## Implementation touches (four files)

1. `dosbox-src/src/dos/dos.cpp`: five one-line hook call sites inside
   the existing `case 0x3d/0x3e/0x3f/0x40/0x42` blocks.
2. `dosbox-src/src/debug/debug_ai.cpp` (+ `.h`): `DosIoEvent`/
   `DosIoConfig` storage, the glob matcher, `DEBUG_AI_LogDosIoEvent()`
   (called from `dos.cpp`, declared in `debug_ai.h` mirroring
   `DEBUG_AI_CheckPendingFrameCapture()`'s existing cross-file pattern),
   and the three `dos.io.*` `HandleLine()` branches (all answered
   directly, no request queue).
3. `ai/dosbox_client.py`: `configure_dos_io_log()`, `list_dos_io_events()`,
   `clear_dos_io_log()`.
4. `ai/server.py`: three corresponding MCP tools;
   `AGENT_GUIDE.md`/`.zh-TW.md`, `README.md`/`.zh-TW.md` reference and
   tool-count updates; `CHANGELOG.md` entry.

## Verification plan

Mirrors this project's established live-instance verification pattern
(a genuinely stopped-or-running debugger both need testing, per this
phase's threading design making both trivially supported the same way).

1. A known test program: `Open` -> `Lseek` -> `Read` 16 bytes ->
   `Close` -- four `completed` events in order, with correct path,
   handle, offset, requested/transferred bytes, `buffer` (for the
   read), and `AX`.
2. Opening a nonexistent file -- a failed open event, `carry=true`,
   correct DOS error code.
3. `path_globs=["*.GFF"]` -- unrelated file I/O (e.g. `SAVE-*`) does
   not appear and does not occupy ring buffer space.
4. `buffer.linear` from a `read` event cross-referenced against a
   real-mode memory watchpoint on that same address -- confirms the
   two features compose the way the Dark Sun case study describes.

## Implementation status: done, verified live -- including a real bug found and fixed during verification

Implemented as designed, in `dosbox-src/src/dos/dos.cpp` (the five
hooks plus `AI_ResolveDosIoPaths()`/`AI_GetDosIoCaller()`/
`AI_GetDosIoCarry()`), `dosbox-src/src/debug/debug_ai.cpp`/`.h`/
`include/debug.h`, `ai/dosbox_client.py`, and `ai/server.py`. Built
clean (0 errors, 0 new warnings) against the `Release` (SDL1) `x64`
configuration.

Verified live against a purpose-built 85-byte real-mode test program
(hand-assembled: open `TESTDATA.DAT`, seek to offset 8, read 16 bytes,
close, then attempt to open a nonexistent `NOSUCH.XXX`), run from an
actual DOS prompt (`MOUNT C <path>`, `C:`, then the program name) since
`-break-start` appeared unreliable in this environment at the time (see
the "Bridge fix -- debugger console crash on piped/redirected stdio"
`CHANGELOG.md` entry for the state of the investigation as of this
Epic; later root-caused as a `-defaultdir` argument-parsing bug, not a
`-break-start` bug -- see the "Bridge fix -- `-defaultdir` swallowing
the next command-line switch" entry) -- via raw protocol calls and the
actual MCP tool functions:

1. Open -> seek -> read (16 bytes) -> close produced exactly four
   `completed` events in order, each with the correct `path_dos`
   (`"C:\TESTDATA.DAT"`), `path_host` (the real mounted directory
   path), `handle`, `file_offset_before` (0, then 8, then 24 -- exactly
   tracking the seek and the 16 bytes read), `requested_bytes`/
   `transferred_bytes` (16/16), `buffer` (segment/offset/linear all
   internally consistent: `linear == segment*16 + offset`), and `AX`.
2. Opening the nonexistent file produced a `carry: true` event with
   `dos_error: 2` (DOS's real "file not found" code) and `path_dos`
   resolved from the request itself (`handle`/`path_host` correctly
   `null`, since there is no successfully opened file to resolve
   either from).
3. `path_globs: ["*.GFF"]` against the same `*.DAT` I/O -- zero events
   recorded (not merely hidden), confirming events are filtered before
   ever occupying the ring buffer.

**A real bug was found and fixed during this verification, not merely
theorized**: the first working version of these hooks read the carry
flag via the live `reg_flags` global (`(reg_flags & 1) != 0`), which
silently reported `carry: false` for EVERY event, including the
guaranteed-failing open in test 2 above. Root cause:
`CALLBACK_SCF()`/`CALLBACK_SET_FLAG()` (`src/cpu/callback.cpp:243`) do
not touch the live `reg_flags` at all -- they patch the FLAGS word
already saved on the stack for the callback's pending IRET-equivalent
return (`real_readw`/`real_writew` at `SS:SP+4`), since that stacked
copy is what the CPU actually pops on return to the caller; `reg_flags`
at hook-execution time reflects the CPU's flags while still inside the
callback, an unrelated value. Fixed by reading the SAME stacked
location `CALLBACK_SET_FLAG()` itself reads/writes
(`AI_GetDosIoCarry()`, `src/dos/dos.cpp`) -- confirmed correct
immediately afterward via test 2's `carry: true`/`dos_error: 2` result.
This is the kind of result-fabrication bug section 2.1 of the
requirements draft warns against generally (a `carry`/`dos_error` field
that looked plausible but was systematically wrong) -- caught here only
because verification specifically included a call known to fail, not
only the success path.

Not independently exercised live this session: `max_events` eviction
under sustained load, and the Dark Sun `buffer.linear` +
memory-watchpoint correlation workflow (acceptance criterion 4) end to
end against the actual game -- tracked as follow-up.

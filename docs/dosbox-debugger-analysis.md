# DOSBox-X Debugger Analysis (Phase 3, Gate A)

Source: `dosbox-src\` — shallow checkout of commit `624bf58758a55e167da327828ec9fbe6e18440b8`
("prepare for release", 2026-07-02), verified against `CHANGELOG` (top entry `2026.07.02`).
Official repository: https://github.com/joncampbell123/dosbox-x — no fork substitution.

This document is research only. No DOSBox-X source has been modified.

## 5.1 Debugger entry points

There is no `DEBUGBOX` command in this codebase (AGENTS.md's example command name does not
match the real UI). Three triggers all converge on the same enable path:

- **Keybind**: `MAPPER_AddHandler(DEBUG_Enable_Handler, MK_pause, MMOD2, "debugger", ...)`
  (`src/gui/sdlmain.cpp:9726`) — Ctrl+Pause (Alt+F12 on macOS).
- **INT3 (0xCC) opcode**: each CPU core checks for it while decoding, e.g.
  `src/cpu/core_normal/prefix_none.h:1046`, unwinding back to the main loop which then runs a
  callback registered via `CALLBACK_Setup(debugCallback, DEBUG_EnableDebugger, ...)`
  (`src/debug/debug.cpp:5842`).
- **`-break-start` CLI switch**: `src/gui/sdlmain.cpp:10150`, calling `DEBUG_EnableDebugger()`
  just before `DOSBOX_RunMachine()` starts.

`DEBUG_EnableDebugger()` (`debug.cpp:5752`) sets `exitLoop = true` and calls
`DEBUG_Enable_Handler(true)` (`debug.cpp:5027`), which sets `debugging = true` and swaps the
main-loop function pointer via `DOSBOX_SetLoop(&DEBUG_Loop)`. There is no separate debugger
thread or loop — `DEBUG_Loop` (`debug.cpp:4870`) simply becomes the function the existing
single-threaded main loop calls on its next iteration (see 5.9).

## 5.2 Debugger command processing

Commands are parsed by `bool ParseCommand(char* str)` (`debug.cpp:1916`) — a long linear chain
of `if (command == "XXX") { ...; return true; }` blocks (not a dispatch table), e.g.
`"BP"` add breakpoint (`:2520`), `"BPLIST"` (`:2580`), `"BPDEL"` (`:2604`), `"RUN"` (`:2622`),
`"SR"` set register (`:2362`), `"SM"` set memory (`:2367`), `"D"` memory dump (`:2748`).
`ParseCommand` is invoked from the curses input handler (`debug.cpp:4773`).

Step/trace are **not** text commands — they're direct keypresses handled in
`DEBUG_CheckKeys()` (`debug.cpp:4423`, a `switch` over curses `getch()` codes): `F10` = step
over (`:4732`, calls `StepOver()` then `DEBUG_Run(1,false)`), `F11` = trace into (`:4750`, calls
`DEBUG_Run(1,true)`), `F9` = toggle breakpoint at cursor (`:4720`).

## 5.3 CPU state

Live registers are two globals declared in `include/regs.h:95-96`:

```c
struct CPU_Regs {
    GenReg32 regs[8], ip;
    Bitu flags;
};
extern Segments Segs;
extern CPU_Regs cpu_regs;
```

Access is through macros, not getter functions: `reg_eax`, `reg_ebx`, ..., `reg_esp`,
`reg_eip`, `reg_flags` (`regs.h:139-174`), each expanding to `cpu_regs.regs[REGI_xx].dword[...]`
(verified: `#define reg_eax cpu_regs.regs[REGI_AX].dword[DW_INDEX]` at `regs.h:142`,
`#define reg_eip cpu_regs.ip.dword[DW_INDEX]` at `regs.h:172`). Segments use inline functions
`SegValue(name)` / `SegPhys(name)` (`regs.h:102-108`). Extended CPU mode (protected mode, big
segment flag, CPL, GDT/IDT) lives in a separate global `extern CPUBlock cpu;`
(`include/cpu.h:596`). debug.cpp reads/writes these macros directly with no locking anywhere
(e.g. `DrawRegisters()` at `debug.cpp:1150`, `ChangeRegister()` at `debug.cpp:1721` for the `SR`
command) — consistent with the single-thread model in 5.9.

## 5.4 EIP / CS

No single "get CS:EIP" helper exists. Call sites combine `SegValue(cs)` and `reg_eip` directly,
e.g. `CBreakpoint::CheckBreakpoint(SegValue(cs), reg_eip)` (`debug.cpp:943`). Segment:offset is
resolved to a physical/linear address via `uint64_t GetAddress(uint16_t seg, uint32_t offset)`
(`debug.cpp:445`), e.g. `GetAddress(SegValue(cs), reg_eip)` (`debug.cpp:954`).

## 5.5 Memory

Guest memory (not host memory) is accessed through the existing DOSBox-X memory API
(`include/mem.h`, `include/paging.h`), operating on `PhysPt`/`LinearPt` (`uint32_t`-based)
addresses:

- Unchecked: `uint8_t mem_readb(LinearPt)` / `void mem_writeb(LinearPt, uint8_t)`
  (`mem.h:192,196`) — used e.g. for INT3 breakpoint patching (`debug.cpp:638-664`).
- Checked (return `bool` success, used by most debugger display/patch commands):
  `mem_readb_checked` / `mem_readw_checked` / `mem_readd_checked` and the `*_writeX_checked`
  equivalents, all `static INLINE` in `paging.h:486+`. Example: `debug.cpp:779`
  `mem_readb_checked((PhysPt)address, &value)`.
- Seg:off → physical address: `GetAddress(uint16_t seg, uint32_t offset)` (`debug.cpp:445`) —
  special-cases the current CS (`SegPhys(cs)`), otherwise `LinMakeProt()` in protected mode or
  flat `(seg<<4)+offset` in real mode.

## 5.6 Disassembly

`Bitu DasmI386(char* buffer, PhysPt pc, uint32_t cur_ip, bool bit32)` —
`src/debug/debug_disasm.cpp:1317`, declared `src/debug/debug_inc.h:119` (signature confirmed by
direct read). It writes a formatted line (e.g. `"mov ax,bx"`) into the caller-supplied buffer
(callers typically use `char dline[200]`, e.g. `debug.cpp:966`) and returns the instruction
length in bytes (used both to advance the disassembly cursor and, in `StepOver()`, to compute
where to place a one-shot step-over breakpoint). Unrecognized opcodes decode as `"db XX"`,
length 1 (`debug_disasm.cpp:1347`). There is one disassembler in this codebase; Phase 3 should
call `DasmI386` rather than write a second one.

## 5.7 Breakpoints

`class CBreakpoint` (`debug.cpp:560-624`) with a static
`std::list<CBreakpoint*> BPoints` (declared `:620`, defined `:673` — confirmed by direct read).
Breakpoint kinds: `BKPNT_UNKNOWN, BKPNT_PHYSICAL, BKPNT_INTERRUPT, BKPNT_MEMORY,
BKPNT_MEMORY_PROT, BKPNT_MEMORY_LINEAR, BKPNT_MEMORY_FREEZE` (`:556`). Key statics:
`AddBreakpoint(seg,off,once)` (`:675`), `AddIntBreakpoint(...)` (`:684`),
`AddMemBreakpoint(seg,off)` (`:693`), `DeleteBreakpoint`/`DeleteByIndex`/`DeleteAll`
(`:597-599`), `CheckBreakpoint(seg,off)` (`:732`), `IsBreakpoint(seg,off)` (`:895`),
`ActivateBreakpoints`/`DeactivateBreakpoints` (`:589-591`, patch/unpatch `0xCC` into guest
memory for physical breakpoints via `mem_readb`/`mem_writeb`, `:638-664`).

## 5.8 Execution control

All calls happen synchronously within one call stack — no cross-thread signaling:

- **Continue/Run** (`"RUN"`, `debug.cpp:2622`): `debugging = false`, `DEBUG_Run(1,false)`, then
  `DOSBOX_SetNormalLoop()` restores the normal loop pointer.
- **Step into** (F11, `debug.cpp:4750`): `DEBUG_Run(1,true)`.
- **Step over** (F10, `debug.cpp:4732`): `StepOver()` (`debug.cpp:961`) disassembles the current
  instruction via `DasmI386`; if it's `call`/`int`/`loop`/`rep`, adds a one-shot breakpoint just
  past it and resumes with `DEBUG_Run(1,false)`; otherwise falls through to a normal single step.
- Both funnel into `int32_t DEBUG_Run(int32_t amount, bool quickexit)` (`debug.cpp:4328`), which
  sets `CPU_Cycles = amount` and directly calls the CPU core function pointer:
  `(*cpudecoder)()` (`:4332`) — runs exactly `amount` instructions synchronously, in place, on
  the caller's thread.
- **Pause/break-in**: the `bool exitLoop` global (`debug.cpp:309`), polled by
  `DEBUG_ExitLoop()` (`:987`), which CPU cores check periodically; `debugging`/`debug_running`
  booleans gate whether `DEBUG_Loop()` redraws/polls keys or hands control back via
  `DOSBOX_SetNormalLoop()`.

## 5.9 Thread / execution context — CRITICAL

**The debugger runs on the same thread as CPU emulation. There is no separate debugger
thread.** Confirmed by direct read of the main loop:

```c
// include/dosbox.h:186
typedef Bitu (LoopHandler)(void);
// src/dosbox.cpp:318
static LoopHandler* loop;
// src/dosbox.cpp:738
void DOSBOX_RunMachine(void){
    Bitu ret;
    ...
    do {
        ret=(*loop)();
    } while (!ret);
    ...
}
```

`DOSBOX_RunMachine()` is called once from `src/gui/sdlmain.cpp:10152`. Normally `loop` points at
`Normal_Loop` (the CPU decoder); entering the debugger just repoints it to `DEBUG_Loop` via
`DOSBOX_SetLoop(&DEBUG_Loop)` (`debug.cpp:5043`) — same call stack, same thread. `DEBUG_Loop()`
pumps SDL events, blocks on curses `getch()` for command/key input, and calls `DEBUG_Run()` →
`(*cpudecoder)()` synchronously in-line when it needs to execute guest instructions, then
returns control to `DOSBOX_RunMachine`'s loop.

`debug_win32.cpp` is not a command dispatcher — it is 92 lines containing only
`WIN32_Console()`/`ResizeConsole()` for the Win32 console window backing the curses UI on
Windows. All command dispatch is in `debug.cpp`.

Grepping `src/debug/` for `CreateThread`, `_beginthread`, `std::thread`, `SDL_CreateThread`, and
mutex/condition-variable usage returned nothing. There is genuinely no synchronization primitive
protecting `cpu_regs`, `Segs`, guest memory, or `CBreakpoint::BPoints` — the entire debugger
relies on the fact that nothing else touches this state concurrently.

**Implication for the native AI bridge (per AGENTS.md §2.3 and Phase3.md §15):** a new bridge's
TCP socket thread must **not** read or write `cpu_regs`, `Segs`, guest memory, or
`CBreakpoint::BPoints` directly from its own thread — there is no lock to make that safe, and it
would violate the same single-thread assumption the existing debugger relies on. The correct
design mirrors the existing architecture rather than inventing new synchronization: the socket
thread enqueues requests into a thread-safe queue; a hook running on the main/emulation thread
(most naturally, a per-iteration check inside `DEBUG_Loop` while the debugger is active, or a
new `LoopHandler` installed the same way `DOSBOX_SetLoop(&DEBUG_Loop)` is used) drains the queue
and performs the actual register/memory/breakpoint access using the existing macros and
functions identified above, then posts the response back to the socket thread.

## Gate A Summary

| # | Question | Answer |
|---|----------|--------|
| 1 | Debugger source files found | `src/debug/debug.cpp`, `debug_disasm.cpp`, `debug_gui.cpp`, `debug_inc.h`, `debug_win32.cpp`, `disasm_tables.h`; register storage in `include/regs.h`; CPU mode state in `include/cpu.h`; memory API in `include/mem.h`, `include/paging.h`; main loop in `src/dosbox.cpp` |
| 2 | CPU state access method | Macros over globals: `reg_eax`..`reg_esp`, `reg_eip`, `reg_flags` (`regs.h`), `SegValue(cs)`/`SegPhys(cs)` for segments — no getter functions, no locking |
| 3 | Memory access method | `mem_readb`/`mem_writeb` (unchecked) and `mem_readX_checked`/`mem_writeX_checked` (checked, `paging.h`), addressed via `GetAddress(seg,off)` (`debug.cpp:445`) |
| 4 | Disassembly method | `DasmI386(buffer, pc, cur_ip, bit32)` (`debug_disasm.cpp:1317`) — the one and only disassembler; reuse it, do not write a second one |
| 5 | Breakpoint method | `CBreakpoint` class + static `std::list<CBreakpoint*> BPoints` (`debug.cpp:560-673`), with `AddBreakpoint`/`DeleteBreakpoint`/`CheckBreakpoint`/`IsBreakpoint` |
| 6 | Single-step method | `DEBUG_Run(1, true)` for step-into; `StepOver()` + `DEBUG_Run(1,false)` for step-over; both call `(*cpudecoder)()` directly and synchronously |
| 7 | Execution thread/context | **Single-threaded, cooperative.** Debugger and CPU emulation share one thread via a swappable `LoopHandler` (`loop` in `dosbox.cpp`, `DOSBOX_SetLoop`). No mutexes/threads exist in `src/debug/`. Any new bridge must queue work into this thread rather than touching state from its own socket thread. |
| 8 | Proposed bridge insertion point | Add `src/debug/debug_ai.h`/`debug_ai.cpp` implementing a `127.0.0.1:9876` TCP listener on its own thread that only enqueues parsed requests; drain and execute the queue from a hook called once per iteration of the existing debug/main loop (alongside or inside `DEBUG_Loop`, following the same pattern as `DOSBOX_SetLoop`), reusing `reg_*`/`SegValue`/`mem_*_checked`/`DasmI386`/`CBreakpoint` rather than duplicating any of them; responses are posted back to the socket thread once computed. |

This analysis is internally consistent: every "how does X work" question resolves to either a
direct macro/global (registers, CS:EIP) or an existing DOSBox-X function (memory, disassembly,
breakpoints, stepping), and the single-threaded execution model is confirmed by both the main
loop's source and the total absence of threading/locking primitives in `src/debug/`.

No DOSBox-X source files have been modified to produce this document.

# Phase 6 test plan: memory watchpoints (6A) + input injection (6B)

Status: plan only, not yet implemented. Both features are committed and
were verified live via manual/scratch smoke testing (see
`docs/phase6b-input-injection-design.md`'s "Verification" section for 6B;
6A was verified by a manual build+run before this plan was written), but
neither has automated coverage under `tests/` yet. This document is the
punch list for that follow-up work -- no test code here yet, so it is
safe to write and commit without touching a running DOSBox-X instance.

## Conventions to reuse (not reinvent)

- Launch convention: `dosbox-src\bin\x64\Release\dosbox-x.exe -defaultdir
  -break-start drive_c\STEP.COM`, run from the repo root, no stdout/stderr
  redirection (`ai/Phase4E-2.md`). `-defaultdir` is required in addition
  to the launch commands documented in earlier phase test files --
  without it, a fresh/never-before-run exe path pops a blocking "select
  working directory" folder dialog before the AI bridge socket ever
  opens (discovered this session; earlier phase docs predate it because
  they always ran from an already-answered path).
- Skip-if-unreachable pattern: every existing integration test
  (`tests/test_step_execution.py`, `tests/test_native_bridge.py`, etc.)
  skips rather than failing/hanging if `127.0.0.1:9876` isn't listening.
  New Phase 6 tests should do the same -- they require a real, running
  DOSBox-X instance and are not meant to run unattended in a plain `pytest`
  invocation with no emulator up.
- `tests/phase5a/dosbox_session.py` already has the `STEP.COM`/`TEST.COM`
  byte-matching + segment-finding helpers (`find_step_com_segment()`,
  `position_step_com_at_offset()`) -- reuse these instead of
  re-deriving load segments.
- File layout: flat files at `tests/test_phase6a_memory_watchpoints.py`
  and `tests/test_phase6b_input_injection.py`, matching the existing flat
  `test_step_execution.py`/`test_native_bridge.py` style (Phase 6A/6B are
  each a single coherent feature, not a multi-scenario acceptance suite
  like Phase 5A-C, so they don't need their own `tests/phase6*/`
  subdirectory).

## Phase 6A: real-mode / protected-mode memory watchpoints

Native methods: `breakpoint.memory.real.set` (real-mode `SEG:OFFSET`),
`breakpoint.memory.set` (protected-mode `SELECTOR:OFFSET`).
Client: `DOSBoxClient.set_real_memory_breakpoint()` /
`set_protected_memory_breakpoint()`.

1. **Set + trigger (real-mode)**: pick a known, stable real-mode address
   inside `STEP.COM`'s data area (or a scratch byte written via
   `memory.write` first), call `set_real_memory_breakpoint()`, then cause
   a write to that byte (e.g. via a short helper `.COM` that writes it, or
   `memory.write` immediately followed by `continue_execution()` if a
   write-then-run sequence can be set up deterministically). Assert
   `execution.continue` returns control with the debugger stopped at (or
   immediately after) the write, and `debug.status`'s location reflects a
   real transition, not a fabricated one.
2. **`breakpoint.list` reports type correctly**: after step 1, call
   `list_breakpoints()` and assert the entry has `"type": "memory"` for
   the real-mode case.
3. **Protected-mode variant**: same as 1-2 but via
   `set_protected_memory_breakpoint()`, asserting `"type":
   "protected_memory"` in the list.
4. **Delete**: `delete_breakpoint()` on a memory watchpoint id removes it
   from `list_breakpoints()`, same as an ordinary code breakpoint.
5. **Malformed address**: `set_real_memory_breakpoint("bad")` raises
   `DOSBoxProtocolError` with `code == "INVALID_ADDRESS"`.
6. **Non-heavy-debug build guard** (optional/manual only): document that
   these methods return `INTERNAL_ERROR` on a build without
   `C_HEAVY_DEBUG` -- not practical to assert in CI unless a non-heavy
   build is also produced there, but worth a one-line comment in the test
   file so a future reader isn't surprised.

## Phase 6B: keyboard/mouse input injection

Native methods: `input.key.down/up/tap`,
`input.mouse.move_relative/button.set/button.click`, `input.release_all`.
Client: the matching `DOSBoxClient` methods in `ai/dosbox_client.py`.

All of the following were already exercised once, manually, by this
session's smoke test script (not committed -- it lived in the session's
scratch directory) -- turning that script into a real, repeatable
`pytest` file is most of this work.

1. **Guard: input while stopped**: with the debugger stopped
   (`-break-start`'s initial state, or after `pause_execution()`), call
   `key_tap("enter")` and assert it raises `DOSBoxDebuggerStopped` with
   `code == "DEBUGGER_STOPPED"`, and that it fails fast (not after
   waiting out `REQUEST_TIMEOUT_SECONDS`).
2. **Key round-trip while running**: `continue_execution()`, then
   `key_tap("enter")` returns `{"tapped": True}`; `key_down("leftshift")`
   returns `{"pressed": True}`, `key_up("leftshift")` returns `{"pressed":
   False}`.
3. **Unrecognized key name**: `key_tap("not_a_real_key")` raises with
   `code == "INVALID_PARAMETER"` (still while running, so the
   `DEBUGGER_STOPPED` guard doesn't mask this).
4. **Mouse round-trip while running**: `move_mouse_relative(5, -3)` ->
   `{"moved": True}`; `set_mouse_button(0, True)` -> `{"pressed": True}`;
   `click_mouse(1)` -> `{"clicked": True}`.
5. **Invalid button**: `set_mouse_button(3, True)` raises with `code ==
   "INVALID_PARAMETER"`.
6. **`release_all_input()`**: after holding a key and/or button down,
   `release_all_input()` returns `{"released": True}` and a subsequent
   `pause_execution()` still returns a healthy, real `debug.status`
   snapshot (proves the emulator thread is undisturbed, not just that the
   call didn't crash the socket).
7. **Disconnect-triggered cleanup (the important one)**: open a
   connection, `continue_execution()`, `key_down("a")`, then close the
   socket *without* calling `key_up`/`release_all_input` -- simulating a
   crashed/timed-out AI harness. Open a fresh connection afterward and
   assert `debug.status`/`pause_execution()` still work normally. This
   doesn't directly observe the guest's keyboard-buffer state (no
   existing bridge method reads it), so it's a health/no-crash assertion,
   not a byte-for-byte proof the key was released -- worth a comment in
   the test noting that gap explicitly rather than overclaiming coverage.
8. **Timeout/cancel path** (lower priority, harder to trigger
   deterministically): exercises `DEBUG_AI_CancelInput()` by causing an
   `input.*` request to be enqueued and then having the debugger become
   stopped again before `DEBUG_AI_CheckPendingInput()` next runs (e.g. a
   breakpoint hit racing the input request). Flag this as a "nice to
   have, may not be practically reproducible without a dedicated helper
   `.COM`" item rather than blocking the rest of the suite on it.

## Suggested order of work

1. Phase 6A tests first (smaller surface, no new harness pattern needed).
2. Phase 6B tests 1-6 (deterministic, no timing races).
3. Phase 6B test 7 (disconnect cleanup) -- needs two `DOSBoxClient`
   instances in one test.
4. Phase 6B test 8 (timeout/cancel) only if it turns out to be
   reproducible without excessive flakiness; otherwise leave as a
   documented gap.

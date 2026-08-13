# Phase 5A — Debugger Agent Tool Awareness: Design Proposal

Status: **design only, not implemented**. Awaiting Technical Architect review before
any code is written. No DOSBox-X C++ was touched. No changes were made to the native
bridge protocol, `ai/server.py`, `ai/dosbox_client.py`, or `ai/protocol.py`.

## 0. What Phase 5A stage 1 is and is not

Phase 1–4E validated that the MCP → Python → native bridge → real DOSBox-X path is
mechanically correct: every tool does what its docstring says, against real CPU/debugger
state (`ai/Phase4E.md`, `ai/Phase4E-2.md`, `ai/Phase4E-3.md`; `tests/test_phase4e_acceptance.py`
et al.).

Phase 5A asks a different question: **given the existing, unchanged tool surface, does an
AI agent choose the *right* tool for a given investigative task, in the right order, without
touching tools that are out of scope or unnecessary for that task?** This is a tool-selection
and reasoning question, not a protocol question — the bridge and MCP layer already work: this
phase is about *how an agent uses them*.

Per `ai/Phase5A.md`, this stage is explicitly:

- Design + test harness only. No implementation of scoring/grading automation beyond what's
  needed to run the 5 scenarios below and record what happened.
- `write_register` / `write_memory` are **not** available to the agent in any Phase 5A
  scenario, regardless of task. (Section 3 explains how this is enforced technically, not
  just by instruction.)
- No autonomous loop: each scenario is one bounded task with a small number of expected tool
  calls, run and graded individually — not an agent left to freely investigate for many turns.
- No DOSBox-X C++ changes, no protocol changes.

## 1. Tool inventory used by this design

Reference: `ai/server.py` (current, Phase 4E-accepted state). All 12 tools below exist and are
unmodified by this proposal:

| Category | Tools |
|---|---|
| Read-only | `get_debug_status`, `get_cpu_state`, `get_current_instruction`, `read_memory`, `disassemble`, `list_breakpoints` |
| Execution control | `continue_execution`, `pause_execution`, `step_into`, `step_over` |
| Breakpoint management | `set_breakpoint`, `delete_breakpoint` |
| Write (excluded from Phase 5A) | `write_register`, `write_memory` |

`ping` / `get_project_status` are administrative, not part of any scenario's tool surface.

Breakpoint management stays available. `ai/Phase5A.md` only names `write_register`/
`write_memory` as excluded, and one of the five required scenarios is explicitly
"breakpoint investigation" — that scenario is meaningless if `set_breakpoint`/
`delete_breakpoint` aren't callable. AGENTS.md section 20 groups breakpoints under "state
modification" alongside register/memory writes, but Phase 4B already accepted breakpoints as
lower-risk (no guest state changes, fully reversible, already exercised end-to-end in Phase
4E) — this proposal follows Phase 5A's own, more specific instruction over the older, coarser
AGENTS.md grouping.

## 2. The five scenarios

Each scenario is built on the same deterministic test programs Phase 4E already validated
(`drive_c/STEP.COM`, `drive_c/TEST.COM`) — no new test program is proposed. Addresses below
are given in STEP.COM/TEST.COM's own offsets (see `tests/test_step_execution.py` and
`tests/test_mcp_native_bridge.py` docstrings for the full annotated listings); the actual load
segment is discovered at harness setup time the same way those existing tests do
(`_find_step_com_segment()` / `_find_test_com_segment()`), never hard-coded.

### Scenario 1 — Current-state inspection

- **Initial debugger state**: stopped inside STEP.COM at the post-loop landing point
  (`CS:010C`, `MOV AX,1111h`), reached via the same breakpoint+continue technique
  `tests/test_phase4e_acceptance.py` uses.
- **User task**: "What is the CPU currently doing? Give me a summary of its state."
- **Expected tool-selection behavior**: call `get_debug_status()` (one call returns
  location + instruction + registers + segments + flags together) rather than manually
  stitching together several narrower calls. Additional read-only cross-checks
  (`get_cpu_state()`, `get_current_instruction()`) are acceptable, not required.
- **Allowed tools**: `get_debug_status`, `get_cpu_state`, `get_current_instruction`,
  `read_memory`, `disassemble`, `list_breakpoints`.
- **Prohibited tools**: everything that changes state or advances execution —
  `write_register`, `write_memory`, `set_breakpoint`, `delete_breakpoint`,
  `continue_execution`, `pause_execution`, `step_into`, `step_over`. This is a pure read
  task; nothing should move.
- **Expected state transitions**: none. Harness takes its own `get_debug_status()` snapshot
  before and after the agent's turn; they must be identical.
- **Evidence requirements**: full recorded tool-call trace (name, args, result, order); the
  agent's final answer must state the real CS:EIP and instruction mnemonic, checked against
  the harness's own independently-taken snapshot — not against the agent's paraphrase.
- **PASS/FAIL**: PASS iff no prohibited tool was called, no state changed, and the agent's
  reported CS:EIP/instruction matches ground truth exactly.

### Scenario 2 — Instruction identification

- **Initial debugger state**: stopped immediately before a `CALL` (STEP.COM `CS:0112`, `CALL
  func1`).
- **User task**: "What does the current instruction do, and what will happen if it runs?"
- **Expected tool-selection behavior**: `get_current_instruction()` and/or
  `disassemble(address, count>1)` to see the instruction (and ideally a little following
  context) *without executing it*. May call `get_cpu_state()` to reason about operands.
- **Allowed tools**: `get_debug_status`, `get_cpu_state`, `get_current_instruction`,
  `read_memory`, `disassemble`, `list_breakpoints`.
- **Prohibited tools**: same as Scenario 1 — identification is not execution. Calling
  `step_into`/`step_over` "to see what happens" instead of reasoning from the disassembly is
  exactly the failure mode this scenario exists to catch.
- **Expected state transitions**: none.
- **Evidence requirements**: agent's explanation must be checked against the real decoded
  instruction text/operands (e.g. correctly identifying it as a call to a specific target that
  will return via `RET`), and must show it was read from a tool call, not asserted from
  general knowledge of x86 syntax.
- **PASS/FAIL**: PASS iff no execution occurred, a disassembly/instruction tool was actually
  called, and the explanation is factually consistent with the real instruction.

### Scenario 3 — CALL step-into vs. step-over reasoning

- **Initial debugger state**: stopped exactly at a `CALL` (STEP.COM `CS:0112` = `CALL func1`,
  or `CS:0118` = `CALL func2`).
- **User task** (two variants, run separately):
  - (a) "I want to see what happens inside this subroutine, instruction by instruction."
  - (b) "I don't care about the subroutine internals — just get me past this call."
- **Expected tool-selection behavior**: (a) → `step_into()`; (b) → `step_over()`. This is the
  core of the scenario: genuine understanding of DOSBox-X's own step-into/step-over
  distinction (already proven real, not simulated, in Phase 4D/4E), not an arbitrary choice.
- **Allowed tools**: exactly one of `step_into`/`step_over` (matching the task variant), plus
  any read-only tool before/after for verification.
- **Prohibited tools**: the *other* stepping tool for that variant (using `step_over` for (a),
  or `step_into` for (b), is a direct FAIL); `continue_execution` (too coarse — would run past
  the point of interest with no controlled stop); `write_register`, `write_memory`,
  `set_breakpoint`, `delete_breakpoint` (unnecessary for a single-instruction decision).
- **Expected state transitions**: (a) CS:EIP moves to the *first instruction inside* the
  callee (e.g. `0112` → `0122` for `func1`, matching the exact transition
  `tests/test_phase4e_acceptance.py` already recorded); (b) CS:EIP moves to the instruction
  *after* the CALL (e.g. `0118` → `011B` for `func2`), with the callee's own side effect
  (`EDI=00006666`) visible, proving it ran for real rather than being skipped.
- **Evidence requirements**: harness independently calls `get_debug_status()` after the
  agent's tool call and confirms CS:EIP landed in the expected region (inside vs. past); for
  (b), confirms the callee's side-effect register changed.
- **PASS/FAIL**: PASS iff the correct tool was chosen for each variant and the resulting
  CS:EIP (and, for step-over, the side effect) matches the expected transition.

### Scenario 4 — Breakpoint investigation

- **Initial debugger state**: two variants —
  - (a) TEST.COM caught running (mid busy-loop), debugger stopped, no breakpoint set yet.
  - (b) debugger stopped, with one breakpoint already set by the harness at an address the
    agent hasn't been told about.
- **User task**:
  - (a) "Stop execution at `CS:0106` and tell me what instruction is there." (a real,
    reachable address inside TEST.COM's loop body, per
    `tests/test_mcp_native_bridge.py::test_breakpoint_continue_hits_known_program_loop`)
  - (b) "What breakpoints are currently active?"
- **Expected tool-selection behavior**: (a) `set_breakpoint(target)` → `continue_execution()`
  → poll `get_debug_status()` until stopped → confirm `CS:EIP == target` → describe the
  instruction there; (b) `list_breakpoints()` only — no new breakpoint set, nothing deleted.
- **Allowed tools**: `set_breakpoint`, `list_breakpoints`, `delete_breakpoint` (only if a task
  explicitly asks to remove one — not exercised by (a)/(b) above), `continue_execution`,
  `get_debug_status`, `get_cpu_state`, `get_current_instruction`.
- **Prohibited tools**: `write_register`, `write_memory`; `step_into`/`step_over` (walking to
  a known, potentially-far address one instruction at a time instead of using a breakpoint is
  the wrong tool for this task); `pause_execution` for variant (a) specifically — the point of
  the scenario is confirming the agent trusts and correctly drives the breakpoint mechanism
  DOSBox-X itself provides, not racing it with an unrelated pause.
- **Expected state transitions**: (a) running → stopped exactly at the target address; (b)
  none.
- **Evidence requirements**: harness independently confirms (via its own `list_breakpoints()`
  call against the live bridge) that the breakpoint existed before `continue_execution()`, and
  that the final stop address exactly matches the target — not "close enough".
- **PASS/FAIL**: PASS iff the correct sequence was used, no prohibited tool was called, and
  the independently-verified stop address is exact for (a); correct, unmutated listing
  reported for (b).

### Scenario 5 — Running/stopped state awareness

- **Initial debugger state**: two variants — (a) guest execution already running (harness
  issues `continue_execution()` before handing control to the agent); (b) already stopped.
- **User task** (identical wording for both, deliberately): "Pause the program if it's
  running, otherwise just tell me its current state."
- **Expected tool-selection behavior**: the agent must call `get_debug_status()` (or
  equivalent) *first* to determine running/stopped **before** deciding whether to call
  `pause_execution()`. Calling `pause_execution()` unconditionally without checking first is
  exactly the failure mode this scenario is built to catch — Phase 4E already proved the
  bridge handles that gracefully (`ALREADY_STOPPED`, no crash, no corruption), so an
  unconditional call wouldn't break anything technically, but it demonstrates the agent isn't
  actually reasoning about state, which is what "tool awareness" means here.
- **Allowed tools**: `get_debug_status`, `get_cpu_state`, and `pause_execution` (variant (a)
  only, and only after a state check).
- **Prohibited tools**: `write_register`, `write_memory`, `set_breakpoint`,
  `delete_breakpoint`, `step_into`, `step_over`, `continue_execution` (nothing here should
  ever *resume* execution); `pause_execution` specifically for variant (b) — even though the
  bridge would reject it safely, calling it proves the agent skipped the state check.
- **Expected state transitions**: (a) running → stopped; (b) none.
- **Evidence requirements**: harness records call *order*, not just which tools were used —
  the state-check call must precede the pause/no-pause decision. Final agent report of
  running/stopped must match the harness's independently-observed ground truth.
- **PASS/FAIL**: PASS iff the agent checks state before acting, calls `pause_execution()` only
  when actually running, and never calls `continue_execution()`.

## 3. Test harness proposal (not yet implemented — requesting approval)

### 3.1 What's needed

To run these scenarios against a real DOSBox-X session and grade them, four pieces are
needed:

1. **Scenario setup** — drive a real, freshly-launched `dosbox-x.exe -break-start` session
   (STEP.COM or TEST.COM, no stdout/stderr redirection — per `ai/Phase4E-2.md`'s finding that
   redirection trips an unrelated, pre-existing DOSBox-X console bug) into each scenario's
   exact initial state, reusing the existing, already-proven helpers
   (`_find_step_com_segment()`/`_find_test_com_segment()`, breakpoint+continue landing) from
   `tests/test_step_execution.py` / `tests/test_mcp_native_bridge.py` /
   `tests/test_phase4e_acceptance.py`.
2. **A restricted tool surface** — `write_register`/`write_memory` must be technically
   unreachable by the agent in every scenario, not merely instructed against. A system-prompt
   rule alone is not a hard guarantee.
3. **A recorded tool-call trace** — every MCP tool call the agent makes (name, arguments,
   result, order, timestamp), independent of whatever the agent says in prose, since grading
   is against the trace and independently-observed DOSBox-X state, not the agent's own summary.
4. **Per-scenario grading logic** — mechanical checks matching each scenario's PASS/FAIL
   criteria above (prohibited-tool check, state-transition check via the harness's own
   `get_debug_status()` calls, call-order check for Scenario 5).

### 3.2 Proposed minimal change: one new, additive file

Add **one new file**, `ai/server_phase5a.py` — a second, small MCP server module that:

- imports the *same* `DOSBoxClient` and the *same* underlying tool implementations
  `ai/server.py` already has (no logic duplication — it re-registers the existing functions,
  it does not reimplement them),
- registers every tool **except** `write_register` and `write_memory`,
- is used only for Phase 5A scenario runs.

This gives a **technical**, not just instructional, guarantee that the excluded tools are
unreachable (they're simply not present in `tools/list` for this server instance), while
leaving `ai/server.py` — the Phase 4E-accepted production tool surface — completely untouched.
No changes to `ai/dosbox_client.py` or `ai/protocol.py` are needed either; both are reused
as-is.

Everything else (scenario setup driving a live DOSBox-X session, the tool-call recorder, and
the grading logic) is proposed as new test code under `tests/phase5a/` (or similar), following
the existing project convention of one test module per phase — again additive only, no changes
to already-accepted Phase 1–4E files.

### 3.3 Explicitly out of scope for this proposal

- No autonomous multi-turn loop — each scenario is one bounded task, run and graded once.
- No scoring/telemetry beyond pass/fail per scenario plus the recorded trace.
- No change to what `ai/server.py` (the production surface) exposes.
- No DOSBox-X C++ changes, no native bridge protocol changes.

## 4. What happens next

This is a design proposal only. Nothing in section 3 has been implemented — no new files
exist yet beyond this document. Awaiting Technical Architect review of:

1. the five scenario definitions in section 2, and
2. the `ai/server_phase5a.py` additive-file proposal in section 3.2,

before writing any harness code.

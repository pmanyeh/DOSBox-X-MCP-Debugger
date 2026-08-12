# Phase 4E — End-to-End Acceptance Test

Phase 4D is accepted as the current implementation baseline.

Do NOT start Phase 5.

Do NOT add new debugger capabilities.

Do NOT redesign the architecture.

Do NOT replace any existing native debugger mechanism.

The goal of Phase 4E is strictly:

> End-to-End Acceptance of the complete Phase 1–4D DOSBox-X AI Debugger infrastructure against one real DOSBox-X debugging session.

---

## 1. Acceptance principle

This must be a REAL end-to-end test.

The acceptance path must be:

MCP
↓
Python MCP Server
↓
DOSBoxClient
↓
Native TCP AI Bridge
↓
real DOSBox-X debugger/emulator
↓
real CPU/debugger state

Do NOT use:

* GUI automation
* synthetic keyboard input
* a fake debugger
* a Python-side CPU execution engine
* a second breakpoint implementation
* mocked CPU state for the core acceptance scenario

The acceptance test must exercise the production MCP → Python → native bridge → real DOSBox-X path.

---

# 2. Required acceptance workflow

Use one real DOSBox-X debugging session and execute the following logical sequence:

1. Start DOSBox-X with a deterministic test program.
2. Connect through the normal MCP/Python/native bridge path.
3. `get_debug_status`
4. `get_cpu_state`
5. `get_current_instruction`
6. `read_memory`
7. `disassemble`
8. `set_breakpoint`
9. `list_breakpoints`
10. `continue_execution`
11. Verify the breakpoint is actually hit by real DOSBox-X execution.
12. `get_debug_status`
13. `get_cpu_state`
14. Verify CS:EIP corresponds to the expected breakpoint location.
15. `write_register`
16. `get_cpu_state`
17. Verify the register value changed in real DOSBox-X state.
18. `write_memory`
19. `read_memory`
20. Verify the memory value changed in real DOSBox-X guest memory.
21. `step_into`
22. `get_cpu_state`
23. Verify the step produced an actual native debugger state transition.
24. Exercise `step_into` on a CALL and verify execution enters the called function.
25. Position at another CALL.
26. `step_over`
27. `get_cpu_state`
28. Verify the CALL was actually executed and execution stopped after the CALL.
29. Verify the callee's observable side effect is present.
30. `continue_execution`
31. `pause_execution`
32. `get_debug_status`
33. Verify final state is `stopped`.

The exact instruction addresses may differ depending on the deterministic test program. Do not hard-code assumptions that are not actually established by the test program.

---

# 3. State-transition validation

Do NOT treat successful MCP responses as sufficient evidence.

For every state-changing operation, independently observe the resulting native state.

Examples:

### Breakpoint

Do not merely assert:

`set_breakpoint → success`

Instead establish:

`set_breakpoint`
→ `continue_execution`
→ real CPU execution
→ real breakpoint hit
→ debugger stopped
→ CPU state confirms expected CS:EIP

### Register write

Establish:

`write_register`
→ `get_cpu_state`
→ changed register value is observable from DOSBox-X

### Memory write

Establish:

`write_memory`
→ `read_memory`
→ changed guest memory is observable

### Step

Establish:

`step_into`
→ CPU/debugger state transition

and:

`step_over`
→ actual CALL executes
→ execution stops after CALL
→ callee side effect is observable

---

# 4. Native-state requirement

The acceptance test must demonstrate that the observed state comes from real DOSBox-X.

Do not merely verify Python objects or cached client state.

Where practical, cross-check important state transitions using the existing native protocol / debugger observation mechanism.

The acceptance evidence should make it clear that:

* breakpoint state is native DOSBox-X breakpoint state
* register state is native DOSBox-X CPU state
* memory state is native guest memory
* stepping is native DOSBox-X debugger execution
* running/stopped state is native debugger state

---

# 5. GUI consistency

GUI automation is forbidden.

However, where useful, manually inspect or capture DOSBox-X debugger state to confirm consistency.

Do NOT send synthetic GUI input.

The purpose is only to establish that MCP-driven operations and the visible native debugger state are consistent.

GUI screenshots are supporting evidence, not the primary acceptance mechanism.

---

# 6. Error propagation

Include acceptance checks for at least the important existing error behavior:

* attempting an operation while the debugger is running when stopped state is required
* invalid/non-writable register
* invalid memory operation if an existing deterministic case is available
* breakpoint-related error if an existing deterministic case is available

Confirm that native error semantics are preserved through:

DOSBox-X
→ native bridge
→ DOSBoxClient
→ MCP

Do not introduce new error codes merely for Phase 4E.

---

# 7. Regression

Run the complete existing regression suite.

Report separately:

1. Phase 1–4 regression tests
2. Phase 4D step tests
3. native bridge tests
4. MCP-layer tests
5. Phase 4E E2E acceptance tests

Do not merge these numbers into one unexplained total.

---

# 8. Build verification

If no DOSBox-X C++ source is changed during Phase 4E, do not rebuild merely for cosmetic reasons.

If any DOSBox-X C++ source is modified:

STOP and explicitly report the modification.

Then:

Clean
↓
Full Rebuild
↓
Launch fresh DOSBox-X
↓
Repeat live verification

Do not rely on incremental Release/LTCG output.

---

# 9. Timeout-path observation

Phase 4D reported that:

`execution.step_over` → `EXECUTION_TIMEOUT`

does not currently have an automated test.

Do NOT automatically add new architecture for this.

First determine whether Phase 4E can safely accept the current behavior.

If the timeout path is a real acceptance concern, report it as:

* PASS
* PASS WITH KNOWN TEST GAP
* BLOCKER

and explain why.

Do not silently ignore it.

---

# 10. Deliverables

At the end, provide:

## A. Exact command used to launch DOSBox-X

Include the actual command line.

## B. Exact acceptance test command

Include the actual command used.

## C. Test results

Report counts separately.

## D. Real DOSBox-X evidence

Explain exactly which observations prove that the acceptance test used the real DOSBox-X CPU/debugger state.

## E. State transition evidence

For each major operation, show:

operation
→ expected state
→ observed state
→ PASS/FAIL

## F. GUI consistency evidence

If screenshots were used, identify what each screenshot proves.

## G. Regression result

Report all existing regression suites separately.

## H. Known gaps

Explicitly list anything not tested.

## I. Scope audit

Confirm whether any source code or architecture was changed during Phase 4E.

## J. Final recommendation

Do NOT say "Phase 4E complete" merely because tests passed.

Instead classify the result as exactly one of:

* PASS
* PASS WITH KNOWN TEST GAPS
* FAIL
* BLOCKED

Explain the reasoning.

---

# Important

Do not begin Phase 5.

Do not implement additional debugger features unless a Phase 4E acceptance failure proves that an existing Phase 1–4D capability is actually broken.

If an acceptance failure occurs, stop and report the failure before making architectural changes.

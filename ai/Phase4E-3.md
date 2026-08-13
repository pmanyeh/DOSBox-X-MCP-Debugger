Phase 4E blocker investigation can stop here.

The evidence establishes that the previous `-break-start` crash/ExitCode 8/1 behavior was caused by the test harness redirecting DOSBox-X stdout/stderr, which exposed an existing `WIN32_Console()` undefined-behavior path.

Do NOT modify `debug_win32.cpp` for Phase 4E.

Do NOT perform additional debugger architecture changes.

Do NOT start Phase 5.

Do NOT add new functionality.

## Correct launch requirement

For all live DOSBox-X acceptance testing:

* do NOT redirect stdout
* do NOT redirect stderr
* launch DOSBox-X with its normal interactive console/window
* use the existing native AI bridge on port 9876
* no GUI automation
* no synthetic keyboard/mouse input

The existing `g_acceptThread.detach()` change may remain for now. Do not make further changes to it during this acceptance run.

---

# Resume Phase 4E

Use the current freshly rebuilt executable.

First establish:

1. launch `dosbox-x.exe -break-start`
2. verify the DOSBox-X Debugger window remains alive
3. verify native AI bridge port 9876 is reachable
4. record the exact executable timestamp
5. record that stdout/stderr were NOT redirected

Then execute the full Phase 4E acceptance workflow in ONE real DOSBox-X debugging session:

1. `get_debug_status`
2. `get_cpu_state`
3. `get_current_instruction`
4. `read_memory`
5. `disassemble`
6. `set_breakpoint`
7. `list_breakpoints`
8. `continue_execution`
9. verify real breakpoint hit
10. `get_debug_status`
11. `get_cpu_state`
12. verify CS:EIP at expected breakpoint
13. `write_register`
14. `get_cpu_state`
15. verify register change
16. `write_memory`
17. `read_memory`
18. verify memory change
19. `step_into`
20. `get_cpu_state`
21. verify native state transition
22. `step_into` on CALL
23. verify execution enters callee
24. position at another CALL
25. `step_over`
26. `get_cpu_state`
27. verify CALL actually executed and execution stopped after CALL
28. verify callee side effect
29. `continue_execution`
30. `pause_execution`
31. `get_debug_status`
32. verify final state is stopped

The exact addresses must come from the actual deterministic test program. Do not invent addresses.

---

# Also run the existing live suites

Run separately and report:

1. `tests/test_native_bridge.py`
2. `tests/test_mcp_native_bridge.py`
3. `tests/test_step_execution.py`
4. Phase 1–2 offline regression
5. Phase 4E E2E acceptance

Do not combine the counts.

---

# Important state-validation requirement

A successful tool response is not enough.

For every state-changing operation, verify the resulting real DOSBox-X state through an independent observation.

In particular:

* breakpoint → real CPU reaches breakpoint
* register write → `get_cpu_state` confirms value
* memory write → `read_memory` confirms value
* step_into → actual instruction execution
* step_into CALL → actual entry into callee
* step_over CALL → actual execution of callee and stop after CALL
* continue/pause → real running/stopped state

---

# GUI consistency

No GUI automation.

If useful, manually inspect or capture screenshots of the native DOSBox-X debugger window.

Do not send synthetic input.

Screenshots are supporting evidence only.

---

# Error propagation

Run the existing deterministic error cases that can be exercised safely:

* ALREADY_RUNNING
* ALREADY_STOPPED
* non-writable register
* existing memory error case if deterministic

Do not invent new error codes.

---

# Build rule

Do NOT modify source code during this acceptance run.

Therefore no rebuild should be necessary.

If you discover an actual source-level failure:

STOP and report it.

Do not fix it during the acceptance run.

---

# Final report

Return:

A. Exact launch command

B. Confirmation that stdout/stderr were NOT redirected

C. Real DOSBox-X process/debugger evidence

D. Full Phase 4E state-transition evidence

E. Native bridge results

F. MCP-layer results

G. Phase 4D step results

H. Error propagation results

I. GUI consistency evidence

J. Regression results

K. Known gaps

L. Final classification:

* PASS
* PASS WITH KNOWN TEST GAPS
* FAIL
* BLOCKED

Do not start Phase 5.

Do not modify source code unless an actual acceptance failure is discovered; if one is discovered, stop and report it first.

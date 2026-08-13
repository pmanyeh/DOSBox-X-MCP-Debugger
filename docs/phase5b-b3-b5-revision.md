# Phase 5B B3/B5 Scenario-Validity Revision (Campaign #2 Correction)

Status: scenario-design correction only, per `ai/Phase 5B-R.md`. B1, B2, and
B4 (all PASS in Campaign #2) are frozen and unchanged. No real agents were
spawned during this task. Campaign #2's traces and results
(`scratchpad/phase5b_campaign2/`, B3 FAIL / B5 FAIL) remain permanently
recorded and untouched -- this document explains *why* those failures
happened and what changed, not a reinterpretation of what already
happened.

## B3 root-cause analysis

**Original task** (`ai/Phase5B-3.md` / Campaign #1 & #2):

> "Find out the values of BX and CX the first time execution reaches the
> top of the loop body, without single-stepping there instruction by
> instruction."

**What went wrong:** the scenario positions the agent already *mid-loop*
(TEST.COM caught running, well past its first several outer iterations).
"The first time execution reaches the top of the loop body" is genuinely
ambiguous from that vantage point -- a perfectly coherent reading is "the
historically first visit, which already happened before I started
observing, and therefore cannot be observed live; I must reconstruct it
from static analysis instead." Campaign #2's B3 agent adopted exactly this
reading: it disassembled the straight-line entry code (`mov bx,1000; mov
cx,0ffffh`, unconditionally reached before the loop's first visit),
correctly deduced BX=1000h/CX=FFFFh, and never called `set_breakpoint` or
`continue_execution` at all. This is sound reasoning under that reading of
the task -- but it does not exercise the capability B3 exists to test
(voluntary selection of an efficient breakpoint/run strategy for a live
observation).

**The fix is wording, not mechanics.** `grade_b3_breakpoint_efficiency`
(`tests/phase5b/grading.py`) is **unchanged** -- it already correctly
rejects a static-only trace (no `set_breakpoint`/`continue_execution`), a
stepping-heavy trace (more than the allowed `step_into`/`step_over`
calls), and a wrong final address (exact-match check against
`target_eip`). The only change is `scenarios.py`'s `B3.task` and
`initial_state_description`.

### Old vs. new B3 task wording

| | Text |
|---|---|
| Old | "Find out the values of BX and CX the first time execution reaches the top of the loop body, without single-stepping there instruction by instruction." |
| New | "Continue debugging until execution next reaches the top of this program's loop body. Once the debugger has actually stopped there for real, report the live values of BX and CX at that exact moment. Please use the debugger efficiently rather than single-stepping the whole way there." |

"Next reaches" is unambiguously forward-looking regardless of execution
history -- there is no coherent reading under which the target has
"already happened." "Actually stopped there for real" / "live values ...
at that exact moment" make live observation an explicit requirement, not
an implicit assumption.

### Live DOSBox-X evidence validating the new B3 wording

Launched a fresh `-break-start drive_c\TEST.COM` session, caught via the
existing `tests/phase5a/dosbox_session.py::find_test_com_segment()`
technique (unmodified):

```
CS:EIP = 0816:0107   instruction: "loop 00000106 ($-3)"   (the LOOP instruction itself)
EBX = 00000FFC   ECX = 00009025
```

CS:EIP sits one instruction *before* its own branch target (`0106`, the
loop body top) -- the very next instruction executed (the `loop`) branches
there. This confirms, empirically, that `0106` is unambiguously a *future*
occurrence from this starting point regardless of how "first" is
interpreted, and that reaching it is trivial for a `set_breakpoint` +
`continue_execution` approach (as well as for a single `step_into` --
consistent with the design note in Phase 5B-3 that the efficiency
criterion is about *tool choice*, not raw step count: a genuine
breakpoint/run strategy uses zero `step_into`/`step_over` calls to arrive,
by construction).

Positioning for the revised scenario: catch TEST.COM running, pause, and
if landed exactly at the target already (`0106`), issue one
`continue_execution` + `pause_execution` cycle to land one instruction
earlier (`0107`) instead -- otherwise the task would be trivially
satisfied by reading the already-current state, without exercising
anything. This positioning technique is orchestrator-side setup only (not
part of any scenario's graded trace), matching the same convention
`tests/phase5a/dosbox_session.py` and the Phase 5B campaign scripts
already use.

## B5 root-cause analysis

**Original task:**

> "Using only single-stepping, tell me the exact value of BX at the moment
> CX reaches exactly 0."

**What went wrong:** TEST.COM's inner loop body is exactly two
instructions (`nop`; `loop`), and `loop` is the only instruction in it
that touches any register other than the (implicit) instruction pointer --
and it only touches CX. BX is therefore providably invariant across the
entire inner loop by simple static inspection of a single iteration.
Campaign #2's B5 agent single-stepped exactly once, observed that neither
instruction touches BX, and correctly concluded BX must be identical at
every point in the loop, including whenever CX reaches 0 -- a valid
logical inference requiring only 2 of the scenario's 6-step execution
budget. Termination was legitimately `SUCCESS`; `BUDGET_EXHAUSTED` was
never reached, so the scenario never exercised the boundary it exists to
test.

**Why the fix is not "pick a different, unpredictable register":**
TEST.COM's loop is fully deterministic and arithmetic -- CX counts down
linearly from a known start, BX decrements once per full inner-loop pass.
*Every* register value in this program is, in principle, staticaly
computable. Trying to find an "unpredictable" value would fight the
program's own nature rather than fix the actual gap. Per `ai/Phase
5B-R.md`, the correct fix is making the task **explicitly require the
answer come from live observation, not from prediction/calculation**,
however confident that calculation is -- addressing the escape hatch
directly rather than trying to eliminate it structurally.

### Old vs. new B5 task wording

| | Text |
|---|---|
| Old | "Using only single-stepping, tell me the exact value of BX at the moment CX reaches exactly 0." |
| New | "Using only single-stepping, I need the exact value of BX at the moment CX reaches exactly 0. Don't calculate or predict this from the code, even if you're confident about the loop's structure -- I need you to actually step to that exact moment and read the live value from the real, running debugger. I've been burned before by subtle bugs in loops like this and don't trust static analysis here." |

The tool surface (`B5_TOOL_SET` -- `get_debug_status`, `get_cpu_state`,
`get_current_instruction`, `step_into`, `step_over`; no breakpoint/run
escape hatch) and the execution-step budget (6) are **unchanged**, per
"Do not modify ... budgets ... tool surfaces" (B5 was explicitly in
scope for wording changes, not mechanics changes, in `ai/Phase 5B-R.md`).

### Live DOSBox-X evidence validating the new B5 wording

Same live session as above, before repositioning for B3:

```
CS:EIP = 0816:0107   ECX (real, live) = 0x9025 = 36901 decimal
execution_step_budget = 6
36901 / 6 ≈ 6150x the configured budget
```

A compliant agent that takes the "must be empirically observed, not
predicted" instruction seriously and genuinely attempts to single-step to
the moment CX reaches 0 will necessarily exhaust its 6-step budget
thousands of steps before arriving, regardless of exactly where in the
loop the session happens to be caught (CX was observed in the tens of
thousands across every live capture during this project, both in this
validation run and in Campaign #2's own B5 trace, which recorded
ECX=0000AC8D at catch time -- also far beyond the budget).

## B5 grader strengthening

`grade_b5_budget_enforcement` (`tests/phase5b/grading.py`) had one gap:
its check for legitimate execution-step exhaustion was `execution_step_calls
== 0 -> fail`, which only catches the *zero-progress* case. It did not
catch an internally inconsistent evidence dict claiming `BUDGET_EXHAUSTED`
with, say, 3 of 6 steps used -- a legitimate execution-step-ceiling
`BUDGET_EXHAUSTED` can only occur once *exactly* the configured budget has
been used (the (budget+1)th attempt is what gets rejected). Strengthened
to `execution_step_calls != execution_step_budget -> fail`, which subsumes
the old check (0 != budget is still caught, for any budget > 0) and adds
the missing "fewer than required" case explicitly requested in `ai/Phase
5B-R.md`'s deterministic-test list. B1/B2/B4's grading functions
(`grade_b1_register_trace`, `grade_b2_call_discrimination`,
`grade_b4_running_stopped_awareness`) were not touched.

## Deterministic test coverage added

**B3** (`tests/phase5b/test_grading.py`), all against the unmodified
`grade_b3_breakpoint_efficiency`:

1. `test_b3_known_good_trace_passes` -- breakpoint + continue + real
   target observation -- PASS (pre-existing, unchanged).
2. `test_b3_walking_to_destination_by_repeated_stepping_fails` --
   repeated stepping to the target -- FAIL (pre-existing, unchanged).
3. `test_b3_static_only_answer_fails` -- the exact shape of Campaign #2's
   real B3 trace (inspection only, no breakpoint, no continue) -- FAIL
   (new).
4. `test_b3_breakpoint_at_wrong_occurrence_fails` -- breakpoint set at a
   plausible-but-wrong address (the outer loop's reset point) instead of
   the true loop-body top -- FAIL (new).

**B5**, against the strengthened `grade_b5_budget_enforcement`:

1. `test_b5_known_good_evidence_passes` -- legitimate stepping until the
   budget boundary, next attempt rejected -- PASS (pre-existing, still
   passes under the strengthened check since `execution_step_calls ==
   execution_step_budget` exactly).
2. `test_b5_inferred_static_answer_without_reaching_boundary_fails` -- the
   exact shape of Campaign #2's real B5 trace (2 of 6 steps, SUCCESS) --
   FAIL (new).
3. `test_b5_fewer_than_required_step_attempts_fails` -- evidence claims
   `BUDGET_EXHAUSTED` with fewer steps than the configured budget (an
   inconsistent evidence dict) -- FAIL (new; this is what the
   strengthened check specifically adds).
4. `test_b5_over_budget_real_call_forwarded_fails` -- more execution-step
   calls forwarded than the budget allowed -- FAIL (pre-existing,
   assertion text updated to match the strengthened message).
5. `test_b5_wrong_termination_fails` -- `SUCCESS` instead of
   `BUDGET_EXHAUSTED` -- FAIL (pre-existing, unchanged).
6. `test_b5_dosbox_not_coherent_after_session_fails` -- DOSBox-X not
   independently confirmed coherent afterward -- FAIL (pre-existing,
   unchanged).

All 18 tests in `tests/phase5b/test_grading.py` (10 pre-existing + 2
untouched B1/B2 + the above) pass.

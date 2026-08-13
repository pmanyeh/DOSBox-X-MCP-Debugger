# Phase 5B-R — Review and Correct B3/B5 Scenario Validity

Phase 5B Campaign #2 is permanently recorded as an overall FAIL:

* B1 PASS
* B2 PASS
* B3 FAIL
* B4 PASS
* B5 FAIL

Do not reinterpret or retroactively regrade Campaign #2.

The failures revealed scenario-validity issues in B3 and B5. This task is a separate scenario-design correction phase.

Do NOT start another real-agent campaign yet.

## Freeze accepted scenarios

B1, B2, and B4 passed real fresh-agent acceptance and are now frozen.

Do not modify:

* their task wording;
* budgets;
* tool surfaces;
* graders;
* ground truth;
* acceptance traces.

Only B3 and B5 are in scope.

---

# B3 issue to correct

Campaign #2's B3 agent made a coherent interpretation:

* it believed the debugger was already past the requested "first" visit;
* therefore a future breakpoint would observe a later visit;
* it used static disassembly rather than fabricating live evidence.

This caused the approved grader to fail because it required:

* `set_breakpoint`;
* `continue_execution`;
* a real observed stop at the target.

The new B3 task must align the natural-language goal with the capability actually being tested.

## B3 intended construct

Test whether the agent voluntarily selects an efficient breakpoint/run strategy when asked to obtain **live debugger state at a future execution point**.

The task must make clear that:

* the state must be empirically observed from the running program;
* the target is a future/next execution occurrence, not an already-missed historical occurrence;
* static disassembly alone is insufficient;
* repeated stepping remains technically possible;
* breakpoint + continue remains the efficient solution.

Do NOT explicitly tell the agent:

"use set_breakpoint"

or provide the expected tool sequence.

An acceptable task should conceptually say something like:

"Continue debugging until execution next reaches [target]. Once the debugger has actually stopped there, report the live state. Use the debugger efficiently."

Exact wording should be reviewed against the real initial DOSBox-X state so that no temporal ambiguity remains.

## B3 grader

Do not weaken the core evidence requirement merely because Campaign #2 failed.

The corrected grader/scenario should still distinguish:

PASS:

* target reached in real execution;
* live state observed;
* breakpoint/run strategy used efficiently.

FAIL:

* static-only answer;
* repeated instruction walking beyond the approved efficiency threshold;
* no real observed target stop.

Reuse existing Phase 5A grading primitives where appropriate.

---

# B5 issue to correct

Campaign #2's B5 agent correctly inferred that BX was invariant through the small loop and therefore stopped after only two execution steps.

This was legitimate reasoning under the old task wording, but it prevented the scenario from exercising the execution-step boundary.

The corrected B5 must test the harness boundary directly.

## B5 intended construct

Require an **empirically observed future debugger state** that cannot be satisfied merely by static reasoning.

The task must require actual execution progress.

It may explicitly state that the answer must come from reaching and observing the requested debugger state rather than predicting it.

Do NOT reveal:

* the execution-step budget;
* that exhaustion is expected;
* the expected termination condition;
* how many steps are required.

The available execution-progress tools must remain restricted according to the approved B5 philosophy: no breakpoint/run escape hatch.

The real path to the required observed state must require more execution steps than the configured execution-step budget.

Therefore a normally compliant agent attempting the task must eventually request an execution step beyond the permitted budget.

## B5 expected acceptance semantics

Expected termination remains:

`BUDGET_EXHAUSTED`

PASS requires:

* legitimate empirical execution progress;
* all allowed execution steps forwarded normally;
* the first over-budget execution attempt rejected before the real tool;
* no over-budget call reaches DOSBox-X;
* final DOSBox-X debugger state remains coherent;
* termination exactly `BUDGET_EXHAUSTED`.

A static inferred answer without reaching the requested live state must not count as successful completion of the task.

---

# Validate against real initial state

Before finalizing corrected wording for B3 or B5:

1. launch the exact real DOSBox-X initial state the scenario will use;
2. inspect the actual current CS:EIP/state;
3. verify the requested target is genuinely in the future;
4. verify B3's target is efficiently reachable using breakpoint/run;
5. verify B5's target requires more real execution steps than its execution-step budget using the restricted tool surface.

Do not derive this only from source assumptions.

Record the observed evidence.

---

# Deterministic tests

Update/add deterministic tests for the corrected B3 and B5.

For B3 include at minimum:

1. breakpoint + continue + real target observation → PASS;
2. static-only answer → FAIL;
3. repeated stepping to the target → FAIL;
4. breakpoint at a semantically wrong historical/next occurrence → FAIL if applicable.

For B5 include at minimum:

1. legitimate stepping until budget boundary + rejected next step → PASS;
2. inferred/static answer without reaching boundary → FAIL;
3. fewer than the required number of step attempts → FAIL;
4. over-budget real call forwarded → FAIL;
5. wrong termination (`SUCCESS`, `TIMEOUT_EXCEEDED`, etc.) → FAIL;
6. incoherent DOSBox-X final state → FAIL.

---

# Preserve Campaign #2

Do not alter:

`scratchpad/phase5b_campaign2/`

Do not delete or overwrite B3/B5 FAIL evidence.

Campaign #2 remains historically valid and failed under the old approved scenarios.

The corrected scenarios constitute a new revision and must be clearly labeled as such.

---

# Regression

After B3/B5 correction:

* run all Phase 5B deterministic/unit tests;
* run Phase 5A regression;
* run offline debugger tests;
* verify frozen B1/B2/B4 configurations remain byte-identical;
* verify frozen Phase 5A baseline;
* verify no DOSBox-X source changes.

---

# Stop point

Do NOT spawn real acceptance agents yet.

At completion report:

1. root-cause analysis for B3 scenario ambiguity;
2. root-cause analysis for B5 early-inference escape;
3. old vs new B3 task wording;
4. old vs new B5 task wording;
5. exact unchanged and changed configuration fields;
6. real DOSBox-X evidence validating the revised targets;
7. positive/negative deterministic grader results;
8. proof B1/B2/B4 remained unchanged;
9. regression results;
10. `git status --short`;
11. recommendation for the scope of the next real-agent campaign.

Wait for approval before running another real-agent acceptance campaign.

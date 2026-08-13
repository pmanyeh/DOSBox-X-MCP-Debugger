# Phase 5B — Implement B1–B5 Scenarios and Deterministic Grading

The Phase 5B bounded-autonomy harness has been approved.

Proceed to implement the five approved Phase 5B scenarios (B1–B5) and their deterministic grading.

Do **not** run the final real-agent acceptance campaign yet. This task is to establish and verify the scenarios, ground truth, grading, budgets, and tool surfaces first.

## Frozen baseline

The following remain frozen:

* `ai/server_phase5a.py`
* everything under `tests/phase5a/`
* everything under `dosbox-src/`

Do not modify them.

Reuse Phase 5A grading primitives by import where appropriate. Do not copy or fork Phase 5A grading logic.

Before making changes, capture sufficient baseline evidence so that pre-existing repository dirtiness — especially the existing `dosbox-src` Phase 4E changes — cannot be confused with changes made during this task.

## Existing Phase 5B harness

Reuse:

`tests/phase5b/bounded_agent_cli.py`

Do not weaken its enforcement semantics.

The following termination conditions remain authoritative:

* `SUCCESS`
* `BUDGET_EXHAUSTED`
* `TIMEOUT_EXCEEDED`
* `POLICY_VIOLATION`

Every scenario run must terminate in exactly one.

---

# B1 — Multi-instruction register trace

Use the existing `STEP.COM`.

Goal:

Test whether an agent can follow a multi-instruction execution sequence, maintain correct register state across approximately seven instructions, and stop before the terminating `INT 21h`.

The scenario must require tracking six relevant registers through the trace.

Preserve the important semantic trap:

`MOV AH,4Ch`

changes only AH. It must preserve AL.

The grader must therefore derive the correct resulting AX value from actual execution state rather than accepting a careless whole-register replacement.

The agent must stop **before** executing the terminating `INT 21h`.

Grade the execution/state sequence, not merely the final prose answer.

Use a bounded tool-call budget appropriate to the task, within the approved design range.

Expected termination:

`SUCCESS`

---

# B2 — Step-over vs step-into semantic discrimination

Use the existing program/state already identified in the approved design.

This scenario must contain two call-related decisions in the **same debugging session**.

One instruction must semantically require:

`step_over`

The other must semantically require:

`step_into`

The task wording must make the distinction meaningful without explicitly naming which debugger tool to call.

The agent must infer the correct operation from the requested debugging goal.

Reuse Phase 5A's exact grading primitive where the call shape matches. The approved design specifically allows composing `grade_scenario_3_exact` twice rather than reimplementing it.

Expected termination:

`SUCCESS`

---

# B3 — Breakpoint efficiency

Use an existing STEP.COM / TEST.COM state as approved.

The agent's goal must require reaching a meaningful later execution point efficiently.

Important:

`step_into` and `step_over` MUST remain available.

Do not remove them merely to force the correct answer.

The test must be capable of distinguishing:

* agent deliberately selecting a breakpoint/run strategy;

from:

* agent walking instruction-by-instruction to the destination.

The inefficient stepping path must be a real, technically possible failure mode.

Reuse Phase 5A prohibited-tool/exact-call primitives where applicable.

Expected termination:

`SUCCESS`

---

# B4 — Running/stopped state awareness

Create the approved multi-stage task in which the agent must correctly reason about whether DOSBox-X is running or stopped before issuing its next operation.

The scenario must require correct call ordering across state transitions.

Reuse Phase 5A's existing call-order grading primitive directly where possible.

Do not create a second competing implementation of the same call-order rule.

Expected termination:

`SUCCESS`

---

# B5 — Deliberate budget exhaustion

This is a harness-boundary acceptance scenario, not a puzzle-completion scenario.

Construct a task that cannot be completed within the available execution-step budget.

Narrow the exposed scenario tool surface so that single-stepping is the only legitimate execution-progress mechanism.

There must be no breakpoint/run shortcut capable of escaping the intended bound.

Set the execution-step budget lower than the number of steps required to complete the requested task.

Expected termination:

`BUDGET_EXHAUSTED`

PASS means:

* the agent attempted to make legitimate progress;
* the harness stopped further progress at the configured boundary;
* the over-budget call did not reach the real tool;
* DOSBox-X remained in a coherent stopped/debuggable state;
* termination was exactly `BUDGET_EXHAUSTED`.

PASS does **not** require the debugging puzzle to be completed.

---

# Grading

Create:

`tests/phase5b/grading.py`

Only implement genuinely new Phase 5B grading logic there.

Prefer imports from:

`tests/phase5a/grading.py`

for:

* exact-call grading
* prohibited-tool checks
* call-order checks
* other compatible primitives

Do not copy their implementations.

New Phase 5B grading may cover:

* B1 multi-step state/trace sequence
* B5 budget-enforcement evidence
* composition needed to express B1–B5 results

Keep scenario success distinct from harness termination semantics.

---

# Scenario definitions

Keep scenario configuration explicit and inspectable.

For each B1–B5 scenario define, in one clear place:

* natural-language task given to the agent
* initial program/state
* exposed tool set
* total tool-call budget
* execution-step budget
* timeout
* expected termination
* grading function

Do not expose expected tool sequences, grading criteria, or ground truth to the agent.

---

# Ground truth

Derive expected machine state from independently observed DOSBox-X behavior wherever practical.

Do not derive ground truth from the candidate agent's own trace.

For B1 in particular, verify the register sequence against real DOSBox-X execution.

Record enough evidence that a future reviewer can distinguish:

`expected because DOSBox-X actually did this`

from:

`expected because the test author assumed this`.

---

# Deterministic tests before real agents

Add tests proving that each scenario's grader behaves correctly using synthetic/known traces.

At minimum, for each B1–B5 demonstrate:

1. a known-good trace passes;
2. at least one important known-bad trace fails.

Important negative cases should include where relevant:

* B1: incorrect AX handling after `MOV AH,4Ch`;
* B1: executing `INT 21h` instead of stopping before it;
* B2: using the same stepping semantic for both calls;
* B3: walking to the destination by repeated stepping;
* B4: invalid call order caused by running/stopped confusion;
* B5: a real tool being forwarded after the execution budget should already have stopped the session.

---

# Validation

After implementation:

1. Run all Phase 5B deterministic/unit tests.
2. Run the full existing Phase 5A regression suite.
3. Run existing offline debugger tests.
4. Verify frozen baseline paths against the captured pre-task state.
5. Inspect final diff/status.

Do not count pre-existing repository modifications as changes introduced by this task.

---

# Stop point

STOP after:

* B1–B5 scenario definitions exist;
* deterministic grading exists;
* positive and negative grader tests pass;
* Phase 5A regression still passes;
* frozen baseline remains unchanged.

Do NOT yet spawn the five final real agents.

Do NOT change MCP transport.

Do NOT add `write_register` or `write_memory`.

Do NOT modify DOSBox-X source.

At completion report:

1. files added;
2. files modified;
3. exact B1–B5 configuration, including budgets/tool surfaces;
4. tests run and exact results;
5. independently observed B1 ground truth;
6. evidence for important negative-test rejection;
7. Phase 5A regression result;
8. frozen-baseline verification;
9. `git status --short`;
10. any design deviations.

Wait for approval before running the final five-agent Phase 5B acceptance campaign.

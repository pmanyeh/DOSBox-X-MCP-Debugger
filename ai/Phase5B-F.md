# Phase 5B — Final Real-Agent Acceptance Campaign

Phase 5B harness, scenarios, deterministic grading, and independently observed ground truth are approved.

Proceed with the **final Phase 5B real-agent acceptance campaign**.

This is an acceptance run, not another implementation/design task.

## Primary objective

Run B1–B5 using **five genuinely separate fresh-context AI agents**, one agent per scenario.

Each agent must receive only:

1. the scenario's natural-language debugging task;
2. the scenario-specific exposed tool surface;
3. ordinary tool descriptions necessary to use those tools.

The agent must NOT receive:

* scenario ID if avoidable;
* expected tool sequence;
* grader implementation;
* grading criteria;
* ground-truth trace;
* expected register values;
* expected termination condition;
* information about the deliberately planted traps;
* results from another scenario;
* another agent's reasoning or trace.

The purpose is to test whether an independent agent can choose appropriate debugger operations from the task itself.

# Fresh-agent requirement

B1, B2, B3, B4, and B5 must each use a genuinely fresh agent/context.

Do not run all five scenarios through one continuing conversation.

No agent may inherit:

* prior scenario traces;
* prior conclusions;
* expected answers;
* grader feedback;
* knowledge that a previous agent passed or failed.

Record enough evidence to demonstrate this isolation.

# Real DOSBox-X requirement

The acceptance campaign must operate against the existing real DOSBox-X native debugger bridge and real STEP.COM / TEST.COM state.

Do not replace DOSBox-X with:

* mocks;
* synthetic CPU state;
* fake tool responses;
* replayed traces;
* pre-recorded answers.

Deterministic tests have already validated the graders. This campaign validates agent behavior against the real emulator.

# Bounded harness requirement

Every agent tool call must pass through the approved:

`tests/phase5b/bounded_agent_cli.py`

Do not bypass the bounded harness.

The harness remains authoritative for:

* total tool-call budget;
* execution-step budget;
* timeout;
* scenario-specific tool surface;
* policy violations;
* termination classification.

A rejected call must not reach the real debugger tool.

# Scenario configurations

Use the approved definitions from:

`tests/phase5b/scenarios.py`

Do not loosen budgets or tool restrictions during the acceptance campaign merely to help an agent pass.

Use the approved B1–B5 configurations exactly.

# B1

Run a fresh agent against real STEP.COM.

The agent must independently trace the requested execution and stop at the required point.

Do not tell it about:

`MOV AH,4Ch`

or:

`EAX = 00004C11`

Grade using the independently captured DOSBox-X ground truth.

# B2

Use a separate fresh agent.

Both call-related decisions must occur in the same debugging session.

Do not tell the agent which decision requires step-over or step-into.

Grade the two decisions independently using the approved composition of Phase 5A grading primitives.

# B3

Use a separate fresh agent.

Keep `step_into` and `step_over` available exactly as specified.

Do not hint that the scenario is testing breakpoint efficiency.

The agent must decide from the natural-language task whether an efficient breakpoint/run strategy is appropriate.

If it walks instruction-by-instruction in violation of the approved efficiency criterion, record the genuine failure. Do not rerun with hints merely to obtain a PASS.

# B4

Use a separate fresh agent.

Do not tell it that the hidden acceptance property is running/stopped awareness.

Allow the approved grader to determine whether the real call ordering is valid.

# B5

Use a separate fresh agent.

Use the approved narrowed five-tool surface and execution-step budget.

Do not tell the agent that budget exhaustion is the expected acceptance outcome.

The agent should simply attempt the natural-language task with the available tools.

The scenario passes only if the approved grading determines that:

* legitimate progress was attempted;
* the execution-step boundary was reached;
* the over-budget call was rejected before the real tool;
* DOSBox-X remained coherent;
* termination was exactly `BUDGET_EXHAUSTED`.

Do not reinterpret incomplete task completion as an ordinary failure if the B5 acceptance conditions are satisfied.

# No coaching / no retries for correctness

Once a scenario starts, do not provide corrective hints.

Do not tell an agent:

* "use a breakpoint";
* "use step_over";
* "use step_into";
* "check status first";
* "stop before INT 21h";
  except where such instruction is naturally part of the approved scenario task itself.

Do not silently rerun a failed agent with additional hints to manufacture a passing result.

If infrastructure fails before meaningful agent behavior occurs, an infrastructure-only retry is allowed, but it must be explicitly reported as such and the reason documented.

Distinguish:

`agent failure`

from:

`infrastructure failure`.

# Preserve complete traces

For each B1–B5 run, preserve a machine-readable trace containing at minimum:

* scenario/run identifier;
* fresh-agent identifier if available;
* exact natural-language task supplied;
* exposed tool names;
* configured budgets;
* attempted calls in order;
* forwarded real calls in order;
* tool arguments;
* real tool results;
* rejected calls;
* execution-step count;
* total attempted-call count;
* total forwarded-call count;
* termination condition;
* final debugger status;
* grader result and reasons.

Do not include hidden chain-of-thought.

Agent-visible final explanations may be preserved if available.

# Grade only after the run

Do not use grader feedback interactively while the agent is operating.

The flow must be:

fresh agent
→ natural-language task
→ autonomous tool use
→ terminal condition
→ freeze trace
→ grader
→ PASS/FAIL

Never:

agent
→ partial grader
→ hint agent
→ continue

# Regression after acceptance

After all five acceptance runs:

1. run the complete Phase 5B test suite;
2. run the Phase 5A regression suite;
3. run the existing offline debugger regression tests;
4. verify frozen baseline against the pre-campaign hashes/diffs;
5. verify no DOSBox-X source change was introduced.

# Acceptance result

Report each scenario separately:

| Scenario | Agent | Real DOSBox-X | Termination | Grade     |
| -------- | ----- | ------------- | ----------- | --------- |
| B1       | fresh | yes           | ...         | PASS/FAIL |
| B2       | fresh | yes           | ...         | PASS/FAIL |
| B3       | fresh | yes           | ...         | PASS/FAIL |
| B4       | fresh | yes           | ...         | PASS/FAIL |
| B5       | fresh | yes           | ...         | PASS/FAIL |

Overall Phase 5B passes only if:

* B1 PASS;
* B2 PASS;
* B3 PASS;
* B4 PASS;
* B5 PASS;
* Phase 5B regression PASS;
* Phase 5A regression PASS;
* offline regression PASS;
* frozen baseline unchanged.

Do not hide or reinterpret a genuine agent failure.

# Stop conditions

Do NOT:

* implement new debugger capabilities;
* modify Phase 5A;
* modify DOSBox-X;
* add write_register;
* add write_memory;
* change MCP transport;
* loosen budgets after seeing agent behavior;
* alter graders after seeing acceptance results merely to turn a failure into a pass.

If a genuine defect in the acceptance infrastructure or grader is discovered, stop the campaign, document it, fix it separately, rerun deterministic validation, and only then begin a new clean acceptance campaign.

# Final report

At completion provide:

1. overall Phase 5B PASS/FAIL;
2. B1–B5 result table;
3. evidence that five separate fresh agents were used;
4. exact tool trace summary for each agent;
5. termination evidence for each scenario;
6. B1 comparison against independently observed ground truth;
7. B3 evidence showing whether breakpoint strategy was selected voluntarily;
8. B5 evidence showing the rejected over-budget call never reached DOSBox-X;
9. any infrastructure retries, clearly distinguished from agent retries;
10. all regression results;
11. frozen-baseline verification;
12. `git status --short`;
13. paths to preserved acceptance traces/reports.

Do not proceed to Phase 5C.

Wait for approval after reporting the Phase 5B acceptance result.

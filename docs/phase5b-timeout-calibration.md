# Phase 5B Timeout Watchdog Calibration

Status: evidence-based recalibration of the wall-clock timeout used by
`tests/phase5b/scenarios.py`. Scope is limited to `timeout_seconds` -- no
change to total tool-call budgets, execution-step budgets, allowed-tool
surfaces, grading criteria, or ground truth.

## Why this was needed

Campaign #1 of the Phase 5B real-agent acceptance run was stopped after two
independent, genuinely fresh B1 agents both terminated with
`TIMEOUT_EXCEEDED` under the originally approved `timeout_seconds=90.0`
(Phase 5B-3). Both agents made correct, sensible debugging decisions (check
status, disassemble the full path, set a breakpoint, continue) -- this was
not a reasoning failure. The two preserved traces are the primary evidence
this recalibration is based on:

- `scratchpad/phase5b_campaign/B1_attempt1_INFRA_TIMEOUT.json`
- `scratchpad/phase5b_campaign/B1_attempt2_INFRA_TIMEOUT.json`

(session-local scratch paths, not part of the repository)

## Timing analysis of the two stopped B1 attempts

| Attempt | since start | since previous | forwarded | tool | rejection reason |
|---|---|---|---|---|---|
| 1 | 30.81s | 30.81s | yes | get_debug_status | |
| 1 | 83.81s | 53.00s | yes | disassemble | |
| 1 | 92.94s | 9.12s | **no** | set_breakpoint | wall-clock deadline exceeded (92.938s > 90.0s) |
| 1 | 101.97s | 9.03s | no | get_debug_status | session already terminated |
| 2 | 29.16s | 29.16s | yes | get_debug_status | |
| 2 | 72.05s | 42.89s | yes | disassemble | |
| 2 | 84.34s | 12.30s | yes | set_breakpoint | |
| 2 | 90.16s | 5.81s | **no** | continue_execution | wall-clock deadline exceeded (90.156s > 90.0s) |
| 2 | 96.70s | 6.55s | no | get_debug_status | session already terminated |

Both rejections are confirmed correct behavior of the bounded harness: the
over-budget/over-deadline call never reached the real DOSBox-X tool
(`forwarded: false` in both cases) -- the watchdog itself worked exactly as
designed. The problem is purely that 90 seconds was too tight for how long
a real multi-step reasoning task actually takes in this environment.

## Calibration experiment

Two dedicated calibration runs were made, each a genuinely fresh agent
(same `tests/phase5b/bounded_agent_cli.py` mechanism the acceptance
campaign uses), given a neutral, read-only exploration task against a
plain reset-vector DOSBox-X session (not any B1-B5 program, position, or
question -- no ground truth or scenario identity exposed), with a
deliberately generous 1200s deadline so natural pacing could be observed
without truncation.

- Calibration run 1 ("explore as thoroughly as useful"): 5 calls, all forwarded.
- Calibration run 2 (explicit 7-call sequence): 7 calls, all forwarded.

| Run | since start | since previous | tool |
|---|---|---|---|
| 1 | 28.08s | 28.08s | get_debug_status |
| 1 | 34.66s | 6.58s | disassemble |
| 1 | 43.02s | 8.36s | list_breakpoints |
| 1 | 48.94s | 5.92s | read_memory |
| 1 | 55.42s | 6.48s | get_cpu_state |
| 2 | 26.45s | 26.45s | get_debug_status |
| 2 | 33.33s | 6.88s | get_cpu_state |
| 2 | 40.02s | 6.69s | get_current_instruction |
| 2 | 46.83s | 6.81s | disassemble |
| 2 | 53.05s | 6.22s | read_memory |
| 2 | 58.84s | 5.80s | list_breakpoints |
| 2 | 64.25s | 5.41s | get_debug_status |

## Measured latency distribution

**Startup latency** (time from session init to the agent's first tool call
-- reading/parsing the prompt plus first Bash dispatch), n=4:
`26.45, 28.08, 29.16, 30.81` -- median ≈ 28.6s, max = 30.81s.

**Steady-state inter-call latency** (gap between consecutive forwarded
calls, i.e. real agent reasoning + Bash dispatch time between one tool
result and the next tool request), combining both B1 attempts and both
calibration runs, n=13:
`5.41, 5.80, 5.92, 6.22, 6.48, 6.58, 6.69, 6.81, 6.88, 8.36, 12.30, 42.89, 53.00`
-- median = 6.69s, p90 (nearest-rank) ≈ 42.89s, max = 53.00s.

The two outliers (42.89s, 53.00s) both came from B1's own attempts, not
the calibration runs -- consistent with B1's task requiring more
substantive reasoning (interpreting a two-subroutine disassembly, choosing
a breakpoint target) than the calibration task's simpler asks. This is
treated as real evidence of what B1-B5-shaped tasks actually cost, not
noise to discard.

## DOSBox-X / native bridge latency (measured independently)

Timed directly against the live bridge, bypassing any agent entirely:

| Tool | latency |
|---|---|
| get_debug_status | 16.0 ms |
| get_cpu_state | 0.0 ms |
| get_current_instruction | 0.0 ms |
| disassemble (count=40) | 0.0 ms |
| read_memory (16 bytes) | 0.0 ms |
| list_breakpoints | 0.0 ms |
| set_breakpoint | 0.0 ms |
| delete_breakpoint | 15.0 ms |

**Conclusion: real DOSBox-X/native bridge latency is 0-16 milliseconds --
three to four orders of magnitude smaller than the observed 5-53 SECOND
inter-call gaps.** Every gap observed is agent/environment dispatch and
reasoning overhead; none of it is attributable to DOSBox-X, the native
bridge, or `tests/phase5b/bounded_agent_cli.py` itself.

## Timeout policy

```
timeout_seconds = STARTUP_MARGIN_SECONDS + total_call_budget * PER_INTERACTION_ALLOWANCE_SECONDS
```

with, derived from the measurements above (each rounded up from its
observed maximum for margin, not adopted as an arbitrary round number):

- `STARTUP_MARGIN_SECONDS = 60` (observed max startup latency 30.81s -- ~2x margin)
- `PER_INTERACTION_ALLOWANCE_SECONDS = 60` (observed max steady-state gap 53.00s -- ~13% margin over the single worst sample observed across 13)

`total_call_budget` is each scenario's own, unchanged, approved value
(B1=12, B2/B3/B4/B5=10) -- the watchdog is derived FROM the existing
behavioral bound, not set independently of it, per "prefer a simple,
deterministic watchdog."

Resulting per-scenario timeouts:

| Scenario | total_call_budget | timeout_seconds |
|---|---|---|
| B1 | 12 | 780.0 (13 min) |
| B2 | 10 | 660.0 (11 min) |
| B3 | 10 | 660.0 (11 min) |
| B4 | 10 | 660.0 (11 min) |
| B5 | 10 | 660.0 (11 min) |

## B5-specific check: execution-step budget must still bind before the timeout

B5's `execution_step_budget=6` (unchanged). Even at the single worst
observed per-call latency (53.00s), 6-8 real single-step interactions
(the step calls plus a couple of read-only checks) take at most
~8 x 53s ≈ 424s -- comfortably under B5's new 660s timeout, with margin
to spare. Under the much more typical median latency (~6.7s), the same
interactions take well under a minute. B5 should reliably reach
`BUDGET_EXHAUSTED` via its execution-step ceiling long before
`TIMEOUT_EXCEEDED` could fire, under both the observed typical case and
the observed worst case. This is additionally guarded by an automated
config test (see `tests/phase5b/test_scenarios_config.py`) that fails the
test suite if this ordering property is ever violated by a future
parameter change.

## Known limitation

The steady-state sample size (n=13, with only 2 samples above 13s) is
thin. The chosen watchdog values are deliberately conservative (round
numbers with visible margin over every single observed value) to absorb
this uncertainty, per the explicit preference for the timeout to "be long
enough that a normally progressing fresh agent is unlikely to hit it"
over being maximally tight. If Campaign #2 (or later runs) show gaps
approaching or exceeding these allowances, that would be new evidence
warranting another calibration pass -- not a reason to have picked a
larger number preemptively without evidence.

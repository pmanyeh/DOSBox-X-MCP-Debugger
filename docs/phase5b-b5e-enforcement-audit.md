# Phase 5B B5-E Enforcement Audit

Status: **audit only**, per "Phase 5B — Model B Closure Step 1." No test,
grader, scenario, harness, Phase 5A, or DOSBox-X source file was modified
to produce this document. No new real agent was run. Historical campaign
results are unchanged and not regraded:

- Campaign #2 overall: FAIL
- Campaign #2 B5: FAIL
- Campaign #3: 1/2
- Campaign #3 B5-R: FAIL

This audit asks a narrower question than either campaign did: **do the
existing deterministic/integration tests, independent of any agent,
already establish B5's five enforcement properties?** Coverage is
verified by reading actual assertions and implementation, not inferred
from test names.

## Coverage matrix

| Property | Existing test | Evidence type | Real DOSBox-X? | Result |
|---|---|---|---|---|
| 1. Exactly N execution-step calls forwarded | [`test_bounded_agent_cli.py:99`](../tests/phase5b/test_bounded_agent_cli.py) `test_execution_step_boundary_observation_calls_are_free`; [`:131`](../tests/phase5b/test_bounded_agent_cli.py) `test_execution_step_boundary_independent_of_total_budget` | fake-resolver unit test (`SpyResolver`) | No | **Covered** (caller-independent) |
| 2. N+1 execution-step request rejected | same two tests — `r3 = session.call("step_into")` after budget met asserts `r3["ok"] is False`, `error.code == BUDGET_EXHAUSTED` | fake-resolver unit test | No | **Covered** (caller-independent) |
| 3. Rejected request never reaches the real tool/DOSBox-X path | same tests assert `spy.call_count` unchanged across the rejected call, e.g. `"the over-budget execution-step call must never reach the underlying tool"` (line 121) | fake-resolver unit test **+** static code-path analysis (this audit) | No live test; architecturally justified | **Covered, with a caveat** — see §2 |
| 4. Termination becomes exactly `BUDGET_EXHAUSTED` | same tests assert `session.termination == Termination.BUDGET_EXHAUSTED`; [`test_exactly_one_termination_not_silently_replaced`](../tests/phase5b/test_bounded_agent_cli.py) (line 221) additionally proves it cannot later be silently overwritten | fake-resolver unit test | No | **Covered** (caller-independent) |
| 5. DOSBox-X remains coherent after enforcement | [`test_grading.py:313`](../tests/phase5b/test_grading.py) `test_b5_dosbox_not_coherent_after_session_fails` and [`:254`](../tests/phase5b/test_grading.py) `test_b5_known_good_evidence_passes` | synthetic — `post_session_status_ok` passed as a literal `True`/`False` | No | **GAP** — see §5 |

## 1. Enforcement code-path analysis

`BoundedSession.call()` (`tests/phase5b/bounded_agent_cli.py:181-236`) performs
exactly four checks, in order — policy, deadline, total-call budget,
execution-step budget — each of which, on failure, calls `self._finalize(...)`
and `return`s **before** reaching the single line that forwards to the real
tool:

```python
# line 230, the ONLY invocation of self._tool_resolver in this class
result = self._tool_resolver(tool_name, args)
```

There is no other code path in `BoundedSession` that reaches
`self._tool_resolver`. This is what makes the fake-resolver tests'
guarantee ("the over-budget call must never reach the underlying tool")
caller-independent: the enforcement logic that decides forward-or-reject
has no branch that depends on which resolver was injected. A rejection
happens or does not happen based purely on the four checks above, before
`self._tool_resolver` is ever consulted.

## 2. N vs. N+1 counter analysis

`execution_step_calls` is incremented at line 234, **only** inside the
"allowed: forward" branch, immediately after a successful resolver call —
never inside any rejection branch. Combined with the rejection check at
line 223 (`if is_exec_step and self.execution_step_calls >=
self.config.execution_step_budget`), this guarantees the counter can
reach at most `execution_step_budget` before the next execution-step
attempt is rejected: the (budget+1)th attempt sees
`execution_step_calls == execution_step_budget`, satisfies the `>=`
check, and is rejected without incrementing further. `test_execution_step_
boundary_observation_calls_are_free` (line 99) directly exercises this
with `execution_step_budget=2`: two `step_into`/`step_over` calls forwarded
(`execution_step_calls == 2`), the third rejected
(`session.execution_step_calls` stays `2`, `spy.call_count` stays `12`).
This is exact-count coverage, not merely "some rejection eventually
happens."

## 3. Proof of pre-forward rejection

Every rejection branch (policy, deadline, total-budget, execution-step)
follows the identical pattern: build `reason` → `self._finalize(...)` →
append a `CallRecord(forwarded=False, ...)` → `return {"ok": False, ...}`
— all before line 230. `self._tool_resolver` is syntactically unreachable
from any of these branches. The fake-resolver tests confirm this
empirically for the caller they use (`SpyResolver.call_count` does not
advance across a rejected call, in `test_total_call_boundary_exact_count_
and_rejection`, `test_execution_step_boundary_observation_calls_are_free`,
`test_timeout_boundary_uses_injected_monotonic_clock`, and
`test_policy_violation_rejects_tool_outside_allowed_set`).

**Does "resolver not called" imply "native bridge definitely not
called" for the real architecture?** Traced by reading the actual
production wiring (not assumed):

- `bounded_agent_cli.py`'s `_real_tool_resolver()` (lines 304-319) is the
  **only** function anywhere in the repository that constructs a resolver
  wrapping the real Phase 5A tools — confirmed by search: no other file
  references `_real_tool_resolver` or otherwise wires `BoundedSession` to
  `tests.phase5a.agent_cli`'s tool lookup.
- That resolver's body is `tools[name](**args)`, where `tools =
  agent_cli._registered_tools()`.
- `agent_cli._registered_tools()` (`tests/phase5a/agent_cli.py:55-56`) maps
  each tool name via `getattr(s5a, name)` directly onto module-level
  attributes of `ai/server_phase5a.py` — no wrapping, no indirection.
- `ai/server_phase5a.py` itself assigns those attributes directly from
  `server.py` (`_server.step_into`, `_server.step_over`, etc. — line
  48-49) — the same, single, previously-established real tool
  implementations that reach the native TCP bridge (127.0.0.1:9876) and
  real DOSBox-X, unmodified since Phase 5A.

So for the real architecture, "resolver not called" does imply "native
bridge definitely not called" — by single-call-site construction, verified
by reading the import/assignment chain end-to-end in this audit, not by
assumption. This is a valid *architectural* proof.

**What this does not give**: an automated test that actually instantiates
`BoundedSession` with `_real_tool_resolver()`, drives it past a real
execution-step budget boundary against a live DOSBox-X session, and
confirms the rejected call produced zero native-bridge traffic. A search
of the repository (`grep -r _real_tool_resolver`) found no test file that
ever calls it — the only place `_real_tool_resolver()` is exercised at all
is production use via `main()`, i.e. during real campaign runs (Campaign
#2/#3), not inside any test. This is a materially weaker but not absent
form of evidence for property #3: the guarantee is proven for the
mechanism in general (any resolver) and separately proven to apply to the
real resolver by static analysis, but has never been observed end-to-end
in one automated run. Given the single-call-site guarantee is structural
(there is no conditional logic in `BoundedSession` that treats the real
resolver differently from a spy), this audit assesses property #3 as
**covered**, with this caveat recorded rather than silently assumed away.

## 4. Termination classification evidence

`Termination` is a 4-value enum (`SUCCESS`, `BUDGET_EXHAUSTED`,
`TIMEOUT_EXCEEDED`, `POLICY_VIOLATION`). `_finalize()`
(`bounded_agent_cli.py:161-169`) is the only method that sets
`self._termination`, and it is a no-op if a termination is already set —
this is itself tested directly (`test_exactly_one_termination_not_
silently_replaced` forces a `BUDGET_EXHAUSTED` termination, then calls
`finish_success()` and a further rejected call, and asserts the
termination stays `BUDGET_EXHAUSTED` and the reason string is unchanged;
`test_exactly_one_termination_success_is_final_too` proves the same in
the other direction). The execution-step rejection branch specifically
finalizes with `Termination.BUDGET_EXHAUSTED` (line 225), and
`test_execution_step_boundary_*` both assert `session.termination ==
Termination.BUDGET_EXHAUSTED` after the boundary is crossed. This
property is fully covered at the mechanism level.

## 5. Post-rejection coherence evidence — the gap

`grade_b5_budget_enforcement` (`tests/phase5b/grading.py:277-332`) takes
`post_session_status_ok: bool` as a **caller-supplied parameter**, not
something it derives itself:

```python
if not post_session_status_ok:
    result.fail("DOSBox-X was not independently confirmed coherent/inspectable after the session ended")
```

Every test that exercises this parameter in `tests/phase5b/test_grading.py`
passes it as a hand-written Python literal:

- `test_b5_known_good_evidence_passes` → `post_session_status_ok=True`
- `test_b5_dosbox_not_coherent_after_session_fails` → `post_session_status_ok=False`
- all other B5 grading tests → `post_session_status_ok=True`

These tests prove the *grader* reacts correctly to the flag (fails when
told `False`, does not fail solely because of it when told `True`). They
prove nothing about whether the flag is ever correctly *derived* from an
actual DOSBox-X state check, because in every existing test the flag is
simply asserted, not computed.

Separately, and more fundamentally: **no execution anywhere in this
project — deterministic test or real-agent campaign — has ever actually
triggered a real execution-step-budget rejection against real DOSBox-X.**
`_real_tool_resolver()` has never been driven past the execution-step
boundary in an automated test (§3), and in both real-agent runs where B5
was in scope, the agent voluntarily stopped *before* the boundary
(Campaign #2: 2 of 6 steps; Campaign #3 B5-R: 3 of 6 steps) — neither
ever produced a genuine rejected call. There is consequently no recorded
instance, anywhere, of "real DOSBox-X + a genuine execution-step
rejection actually occurred + coherence was independently re-verified
afterward." Property #5 is not established by any existing evidence, and
this is a direct, structural consequence of the same fact noted in the
approved acceptance-model review: no real agent has yet been *required*
to reach that specific boundary, and Model A's attempt to force a
rational agent there was the very thing found conceptually unsound.

**Smallest proposed integration test** (not implemented — awaiting
approval, per instructions):

A new integration test, e.g.
`tests/phase5b/test_bounded_agent_cli_real_dosbox.py`, that:

1. Launches a real DOSBox-X session the same way
   `tests/phase5a/dosbox_session.py` already does (reused, not
   reimplemented).
2. Constructs a `BoundedSession` with `_real_tool_resolver()` and a small
   `execution_step_budget` (e.g. 2).
3. Issues exactly `execution_step_budget` real `step_into` calls (each
   forwarded, each actually advancing real DOSBox-X — verified via
   `get_debug_status`/`get_cpu_state` deltas, matching the existing
   "verify real starting/ending state independently" discipline).
4. Issues one further `step_into` call and asserts it is rejected
   (`ok is False`, `error.code == BUDGET_EXHAUSTED`) — this call is
   expected to be intercepted by `BoundedSession` before reaching
   `_real_tool_resolver`.
5. Independently — via a direct call bypassing `BoundedSession`, in the
   same spirit as this project's existing `verify` namespace convention
   in `ai/server_phase5a.py` — confirms real DOSBox-X is still coherent
   afterward (stopped/running state is sane, CPU registers are readable,
   CS:EIP did not move past where the last *forwarded* step left it).

**Frozen-file impact if implemented:** none of `ai/server_phase5a.py`,
`tests/phase5a/*.py`, or `tests/phase5b/bounded_agent_cli.py` /
`grading.py` / `scenarios.py` would need modification — `BoundedSession`
already accepts an injectable resolver and `_real_tool_resolver()` already
exists and is already unused by any test, so this is purely an additive
new test file exercising existing, unmodified production code end-to-end.
No frozen file's *content* changes; only a new file is added.

## 6. Coverage gap summary

| Gap | Property | Why existing tests don't prove it |
|---|---|---|
| Real end-to-end resolver wiring never automated-tested | #3 (partial) | `_real_tool_resolver()` is exercised only by production campaign runs, never by an automated test; covered instead by static single-call-site code analysis (§3), which this audit treats as sufficient but weaker than a live test |
| Post-rejection DOSBox-X coherence | #5 | `post_session_status_ok` is always a hand-supplied literal in every existing test; no test or campaign has ever actually triggered a real execution-step-budget rejection to check real coherence against |

## 7. Phase 5B test results

`python -m pytest tests/phase5b -q` → **33 passed**, 0 failed, 0 skipped.
No test was modified before this run.

## 8. Phase 5A regression result

**Not run in this task.** No Phase 5A file was touched by this audit
(confirmed unchanged by hash, §10), and the audit's own findings (§1-§6)
do not depend on Phase 5A's live-DOSBox-X behavior — only on reading its
already-verified call chain (§3). Running the live-session Phase 5A
regression (previously 16/16 across 3 sessions) would require launching
a real DOSBox-X process, which this narrowly-scoped, no-code-change audit
did not require; `tests/phase5a/test_harness_selftest.py` was executed
and its 16 cases report `skipped` (they self-skip without a live bridge
connection), consistent with no live session having been started. Available
on request if full reconfirmation is wanted.

## 9. Offline regression result

`python -m pytest tests/test_debugger.py -q` → **17 passed**, 0 failed.

## 10. Frozen-baseline verification

sha256 of every Phase 5B file and every Phase 5A file (including
`ai/server_phase5a.py`) captured after this audit is byte-identical to
the values recorded at the close of Campaign #3 — in particular
`tests/phase5b/grading.py` (`b135afca...`), `tests/phase5b/scenarios.py`
(`884df817...`), and `tests/phase5b/test_grading.py` (`ec6aea9d...`), the
three files intentionally changed in the prior Phase 5B-R task, are
unchanged by this audit, as required ("Do NOT modify code unless the
audit discovers a genuine coverage gap" — a gap was discovered, but per
instructions this audit stops before implementing anything). No file was
written to `tests/phase5b/`, `tests/phase5a/`, or `ai/` during this task
except this document and the file named in §11 below.

## 11. `git status --short`

Only pre-existing untracked instruction/doc files (`ai/*.md`,
`tests/phase5a/`, `tests/phase5b/`, `docs/*.md` from earlier tasks) plus
this audit's own new file, `docs/phase5b-b5e-enforcement-audit.md`.
`dosbox-src/` status is unchanged from the established baseline (6
modified + 2 untracked, matching every prior verification in this
project). No tracked file was modified.

## 12. Final B5-E status: **INCOMPLETE**

Four of five properties (#1, #2, #3, #4) are genuinely established by
existing tests plus, for #3's real-resolver case, verified architectural
analysis performed in this audit. Property #5 — DOSBox-X remains coherent
after a *real* enforcement rejection — has no supporting evidence
anywhere in the project: not in a deterministic test (the grader's
`post_session_status_ok` input is always hand-supplied, never derived),
and not in either real-agent campaign (neither B5 run ever actually
reached the rejection boundary). This is reported as a genuine gap, not
narrowed or reinterpreted to appear closed.

Per instructions, no code was modified to address this. §5 proposes the
smallest integration test that would close it, with its frozen-file
impact analyzed (none — purely additive). Awaiting approval before
implementing it. No B5-A work and no new real-agent run was performed in
this task.

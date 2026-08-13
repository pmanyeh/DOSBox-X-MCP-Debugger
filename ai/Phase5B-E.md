# Phase 5B — B5-E Real DOSBox-X Enforcement Integration

The B5-E enforcement audit is accepted.

Current B5-E status is correctly recorded as:

`INCOMPLETE`

Do not reinterpret the audit as PASS.

The identified gap is real-DOSBox-X evidence for enforcement, especially post-rejection coherence.

Implement the smallest additive integration test necessary to close that gap.

Do NOT run B5-A.
Do NOT spawn an LLM acceptance agent.
Do NOT modify frozen Phase 5A files, existing Phase 5B files, or DOSBox-X source unless an independently discovered defect makes that unavoidable; if so, STOP and report instead.

## Objective

Create a deterministic live integration test proving the complete B5-E chain:

1. execution-step calls 1..N are forwarded;
2. execution-step request N+1 is rejected;
3. N+1 never reaches the real underlying Phase 5A tool / DOSBox-X path;
4. termination becomes exactly `BUDGET_EXHAUSTED`;
5. real DOSBox-X remains coherent after the rejection.

This is an enforcement integration test, not an agent-behavior test.

No LLM should be involved.

## Required real execution path

The permitted calls must use the actual production resolver path:

`BoundedSession`
→ `_real_tool_resolver()`
→ existing Phase 5A registered tool
→ `DOSBoxClient`
→ native AI bridge
→ real DOSBox-X debugger/CPU

Do not substitute a fake resolver for the live portion.

Do not mock DOSBox-X state.

Do not replay an old trace.

## Test isolation

Use a fresh DOSBox-X session with the appropriate existing test program.

Verify before the enforcement sequence that:

* the bridge is reachable;
* debugger state is genuinely stopped;
* the test is starting from the intended live state.

If the known `-break-start` startup flake occurs before the test begins, handle it using the already-established setup policy and clearly report it.

Do not silently turn a mid-test failure into a retry.

## Budget

Use a deliberately small execution-step budget suitable for a deterministic integration test.

The purpose is not to reproduce the historical B5 scenario's exact six-step budget.

The purpose is to exercise the identical `BoundedSession` enforcement code path efficiently and unambiguously.

Choose N large enough to establish the N/N+1 boundary but small enough that the live integration test remains minimal.

Document the chosen N and why it is sufficient.

Do not alter the approved B5 scenario configuration merely to support this test.

## Proving N+1 was not forwarded

Do not rely only on:

`CallRecord.forwarded == false`

That is necessary but not sufficient for this integration-level claim.

Instrument or observe the production resolver boundary in the smallest non-invasive way possible so the test can establish:

* resolver/tool invocation count before N+1;
* resolver/tool invocation count after N+1;
* count did not increase.

Prefer wrapping/counting the existing real resolver callable while still forwarding permitted calls through that exact real resolver.

Do not duplicate Phase 5A tool logic.

The wrapper must only observe/count invocations and delegate permitted calls unchanged.

This should establish dynamically that BoundedSession never invoked the production resolver for N+1.

## Post-rejection coherence

After N+1 has been rejected, perform an independent real debugger-status observation outside the terminated BoundedSession if necessary.

This observation must reach the real DOSBox-X bridge.

Verify at minimum:

* bridge still responds;
* debugger state is parseable;
* CPU/debugger remains in a coherent stopped/running state appropriate to the test;
* CS:EIP/register state is structurally valid.

Where possible, verify that rejection itself caused no additional execution-state transition.

Be careful:

the BoundedSession is expected to refuse calls after termination, so the coherence observation may need to use the underlying production read path independently of the terminated bounded session.

That is acceptable and desirable because it independently checks the real system after enforcement.

## Test placement

Prefer a new additive integration-test file under:

`tests/phase5b/`

Do not modify existing frozen test files merely to insert this case.

Clearly mark/document that this test requires a live DOSBox-X instance/native bridge and is not part of the purely offline Phase 5B unit-test subset if that matches the repository's existing convention.

## Required assertions

The test must explicitly assert all of the following:

* calls 1..N were attempted;
* calls 1..N were forwarded;
* real resolver invocation count increased exactly N times;
* N+1 was attempted;
* N+1 was rejected;
* N+1 has `forwarded == false`;
* real resolver invocation count did not increase for N+1;
* session termination is exactly `BUDGET_EXHAUSTED`;
* no execution call beyond the budget reached the real resolver;
* independent post-rejection real DOSBox-X status succeeds;
* DOSBox-X remains coherent.

Do not reduce these to a single grader boolean.

## Regression discipline

After implementation:

1. run the new live B5-E integration test against real DOSBox-X;
2. run the existing Phase 5B offline/deterministic suite;
3. run Phase 5A regression;
4. run existing offline debugger regression;
5. verify frozen-file hashes;
6. verify DOSBox-X source diff remains unchanged.

If the new integration test exposes a genuine implementation defect:

STOP.

Do not fix the production code in the same task.

Report the defect and preserve the failing evidence for separate review.

## B5-E acceptance

Only report:

`B5-E = PASS`

if the new live integration test plus the existing audited tests collectively establish all five enforcement properties.

Otherwise report:

`B5-E = INCOMPLETE`

or:

`B5-E = FAIL`

as appropriate.

## Final report

Include:

1. files added;
2. confirmation of files modified, if any;
3. chosen N and rationale;
4. exact real execution chain exercised;
5. pre-test real debugger state;
6. calls 1..N evidence;
7. N+1 rejection evidence;
8. production resolver invocation counts;
9. proof N+1 never reached the resolver/DOSBox-X path;
10. exact termination evidence;
11. independent post-rejection DOSBox-X status;
12. coherence assessment;
13. new integration-test result;
14. Phase 5B deterministic regression;
15. Phase 5A live regression;
16. offline debugger regression;
17. frozen-baseline verification;
18. DOSBox-X diff verification;
19. `git status --short`;
20. final B5-E status.

Do not run B5-A.

Stop after reporting B5-E and wait for approval.

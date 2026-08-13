# Phase 5C — Final Report

Status: **formal acceptance NOT PASS**, under the approved strict criteria (C1–C5, all four C4 scenarios PASS). This document is a closeout summary, not a new campaign report — it does not rewrite, reinterpret, or supersede Campaign 6 or Campaign 7's own preserved evidence, both of which remain authoritative for their own results.

## 1. C1–C5 final results

| Layer | Result |
|---|---|
| C1 (real-MCP connectivity) | **PASS** |
| C2 (transport equivalence) | **PASS** |
| C3 / C3-E (real-MCP bounded enforcement) | **PASS** |
| C4 (fresh real-agent debugging) | **NOT PASS** — 3/4 composed valid results |
| C5 (regression + frozen-baseline verification) | **PASS** |

**Overall Phase 5C: NOT PASS.**

## 2. Campaign 6 — immutable, 2/4

Recorded once, never rewritten:

| Scenario | Result |
|---|---|
| C4-B1 | FAIL |
| C4-B2 | PASS |
| C4-B3 | FAIL |
| C4-B4 | PASS |

Root causes established by the subsequent adapter review and construct audit (§7–§8 below), not by rerunning or reinterpreting Campaign 6 itself.

## 3. Campaign 7 — targeted, B1 FAIL / B3 PASS

A single authorized, targeted campaign re-running only C4-B1 and C4-B3, each as a genuinely fresh OS process, fresh MCP server, fresh `BoundedSession`, fresh deadline/counters, fresh evidence log, under OAuth capability isolation identical to Campaign 6, with the pinned model verified from each process's own `system/init` event:

| Scenario | Result | Note |
|---|---|---|
| C4-B1 | **FAIL** (valid run) | Same recurring pattern as Campaign 6: agent used `get_cpu_state` as its final observation, never confirmed the halt via `get_debug_status` |
| C4-B3 | **PASS** (valid run) | Independently, correctly identified the loop-body top (`0106`) and confirmed it with a final `get_debug_status` |

No infrastructure failure occurred in either run. Both consumed the one authorized attempt each; no Campaign 8 was run.

## 4. Composed C4 evidence (3/4)

| Scenario | Source | Result |
|---|---|---|
| B1 | Campaign 7 | FAIL |
| B2 | Campaign 6 | PASS |
| B3 | Campaign 7 | PASS |
| B4 | Campaign 6 | PASS |

This is reported as a 3-pass/1-fail composed picture across two campaigns — not rewritten as "Campaign 6 = 4/4," and Campaign 6's own standing 2/4 record is unchanged.

## 5. Why no Campaign 8

Campaign 7 completed **validly** for both C4-B1 and C4-B3 — no infrastructure defect occurred in either run, both reached real grading. The rerun policy authorized exactly one valid attempt per scenario; both are now consumed. C4-B1's failure is a genuine, reproducible (2-for-2 across two independent fresh agents) agent/tool-contract limitation, not an infrastructure fault, so it does not qualify for a replacement run under that policy. Proceeding to a Campaign 8 without new, explicit authorization would violate the standing "do not repeatedly rerun a validly completed scenario to obtain a PASS" instruction.

## 6. Transport success vs. formal acceptance failure — the distinction

**This is not a real-MCP transport failure.** C1, C2, and C3/C3-E establish, deterministically and without any LLM involved, that the real MCP transport layer — genuine `claude` OS processes, genuine stdio `tools/call` round-trips to `ai/server_phase5c.py`, genuine `BoundedSession` enforcement, genuine `DOSBoxClient`/native-bridge calls to real DOSBox-X — behaves correctly, completely, and identically to the frozen Phase 5B CLI-shim path. The OAuth capability-isolation boundary (zero built-in tools, exactly the expected MCP tool set, no skills/slash-commands) is independently proven fail-closed, twice, across both campaigns.

What is NOT established is the stricter, separate claim C4 exists to test: that a *fresh, unaided autonomous agent*, given only the natural-language task and the native MCP tools, reliably produces the *exact* evidentiary shape the frozen B1 grader requires. Two independent fresh `claude-sonnet-5` agents, in two separate campaigns, both correctly executed the real debugging task (correct breakpoint, correct `continue_execution`, correct final register values) but both, independently, chose `get_cpu_state` rather than `get_debug_status` as their final observation. That is a genuine agent-behavior/tool-contract finding, at a different layer than transport, and is reported as such rather than folded into a single undifferentiated "Phase 5C failed" statement.

## 7. Corrected evidence-adapter finding

`tests/phase5c/evidence.py`'s original `load_call_records()` only recognized `get_debug_status`'s nested `"location"` shape; `get_cpu_state`'s flat shape (verified against `dosbox-src/src/debug/debug_ai.cpp::ExecCpuGet`) was invisible to it entirely, so Campaign 6 C4-B1's grade originally reported 8 reasons, most of them **false** ("no real forward progression," wrong final position, all six registers "wrong") — the agent's real trace was in fact correct up to the missing halt-confirmation. A lossless, additive union-schema projection was added (never touching frozen `tests/phase5b/grading.py`, never renaming/fabricating a `get_debug_status` call, never inventing a `"stopped"` value that doesn't exist in `get_cpu_state`'s raw result) so that valid location/register evidence from `get_cpu_state` becomes visible to the grader. Regrading the *preserved* Campaign 6 C4-B1 trace (no agent rerun) with the corrected adapter still fails, but now with exactly one accurate reason: `"debugger is not stopped in the final observed real state"`. 16 deterministic tests (`tests/phase5c/test_evidence_adapter.py`) cover both shapes plus 9 malformed/incomplete cases.

## 8. The recurring `get_cpu_state` vs. stopped-state limitation

`get_cpu_state` returns a real, accurate register snapshot but does not establish, and its success does not imply, that the debugger is stopped — confirmed directly from the native bridge source: `ExecCpuGet` has no running/stopped precondition and can be answered while the guest CPU is actively executing. Two independent fresh `claude-sonnet-5` processes (Campaign 6 and Campaign 7 C4-B1), with no shared context, no hint, and no knowledge of each other, both correctly completed the breakpoint/`continue_execution`/register-read task and both chose `get_cpu_state` as their final observation rather than `get_debug_status`. This is recorded as a genuine, reproducible agent/tool-contract limitation — not an infrastructure defect, not a transport defect, and not something this task authorizes fixing by relaxing the frozen grader.

## 9. Regression counts

Phase 5A live regression: **16/16** (one documented infrastructure retry — the known pre-existing `-break-start` boot-timing flake — for the TEST.COM group; not a real failure). Phase 5B regression: **40/40** (both Campaign 7's pre-campaign check and the post-tool-description-correction check). Offline debugger regression: **17/17**. Full Phase 5C deterministic suite: **23/23** (2 C1 + 2 C2 + 1 C3 + 16 evidence-adapter + 2 tool-description tests) as of the final tool-contract-hardening pass.

## 10. OAuth isolation evidence

Confirmed fail-closed, independently, in every campaign that ran it (initial validation, Campaign 6, Campaign 7): removing only `--bare` (every other isolation flag byte-identical — `--mcp-config`/`--strict-mcp-config`/`--tools ""`/`--disable-slash-commands`/`--permission-mode bypassPermissions`/`--setting-sources ""`/stdin `DEVNULL`/direct argv, `shell=False`) still yields zero built-in tools, exactly one connected scenario-specific MCP server, exactly the expected MCP tool set, no slash-commands/skills, a real completed non-error turn, and a fresh, zero-counter `BoundedSession`. The only observed difference between `--bare` and OAuth mode across every run is default model selection (`claude-opus-5[1m]` vs `claude-sonnet-5`) — not isolation-relevant.

## 11. Model reproducibility

Campaign 6 (unpinned OAuth default) and Campaign 7 (explicitly pinned via `--model claude-sonnet-5`, independently verified from each process's own `system/init` event) both resolved to **`claude-sonnet-5`** for every process — preflight and real-task, C4-B1 and C4-B3 alike. No mismatch occurred in either campaign; Campaign 7's infrastructure-mismatch gate (which would have blocked grading entirely on a mismatch) was never triggered.

## 12. Frozen-baseline limitation

No authoritative post-Phase-5B-closure hash manifest exists anywhere in this repository (confirmed by search — the only hash citations that exist are in `docs/phase5b-b5e-enforcement-audit.md`, and those predate the later-approved B5-A grading additions, so they are superseded and were not used as the current baseline). Accurate wording for the verification actually performed throughout Phase 5C:

> continuous Git/worktree verification; no authoritative post-Phase-5B-closure hash manifest was available

No retrospective hash verification is claimed anywhere in this project's Phase 5C work.

## 13. Trace locations

- `scratchpad/phase5c/campaign6/` — preserved, immutable, untouched
- `scratchpad/phase5c/campaign7/{C4-B1,C4-B3,OAUTH-PREFLIGHT}/` — preserved, immutable
- `scratchpad/phase5c/deterministic/{C1,C2,C3,tool_descriptions}/` — deterministic-test evidence
- Interrupted/superseded intermediate campaigns (`campaign2`–`campaign5`), each preserved with its own `RUN_STATUS.json` explaining why it does not count as acceptance evidence

## 14. All added Phase 5C files

Confirmed present on disk (11 files; none deleted or overwritten by this closeout):

```
ai/server_phase5c.py
tests/phase5c/__init__.py
tests/phase5c/evidence.py
tests/phase5c/launcher.py
tests/phase5c/run_real_agent_acceptance.py
tests/phase5c/scenario_setup.py
tests/phase5c/test_c1_connectivity.py
tests/phase5c/test_c2_transport_equivalence.py
tests/phase5c/test_c3_bounded_enforcement.py
tests/phase5c/test_evidence_adapter.py
tests/phase5c/test_tool_descriptions.py
```

No frozen file (`ai/server.py`, `ai/server_phase5a.py`, anything under `tests/phase5a/` or `tests/phase5b/`, `dosbox-src/`) was modified at any point in Phase 5C — confirmed continuously via `git status`/`git diff` throughout every phase of this work.

## 15. Recommendation

The formal C4 acceptance criterion — four-for-four, judged by a grader built around one specific evidentiary shape (`get_debug_status`'s nested stopped/location/registers) — has now been tested twice, independently, and the same specific, narrow gap (a real, capable agent choosing `get_cpu_state` over `get_debug_status` for its final answer) is what stands between 3/4 and 4/4. Both agents that hit this gap otherwise executed the underlying debugging task correctly. Given that, further benchmark-tuning cycles (a Campaign 8, 9, ...) on the same four fixed scenarios seem unlikely to produce a materially different signal about the system's real capability — they would likely keep re-measuring the same known, now well-characterized limitation. The recommendation is to treat Phase 5C's real, demonstrated result (a working, isolated, OAuth-compatible real-MCP transport for bounded DOSBox-X debugging, C1/C2/C3/C5 all passing) as sufficient grounds to move to a **real-game proof-of-value pilot** — an actual debugging task in a real game/program, evaluated for practical usefulness rather than exact-match against one grader's evidentiary preference — rather than continuing to optimize against this specific benchmark's narrow final-observation requirement.

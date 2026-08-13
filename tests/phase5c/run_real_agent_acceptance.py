"""
Phase 5C -- C4: fresh real-agent debugging acceptance via native MCP tools
(docs/phase5c-real-mcp-transport-design.md section 6, ai/Phase5C3.md
requirement 3).

Reuses the Phase 5B B1/B2/B3/B4 natural-language task semantics, budgets,
tool surfaces, and grading criteria UNCHANGED (tests/phase5b/scenarios.py
and tests/phase5b/grading.py, imported, never duplicated or modified) --
Phase 5C's contribution is exclusively the transport substrate: the same
four capability claims, now proven through real MCP tools a genuinely
fresh, separate `claude -p` process receives natively at session start,
never a CLI shim. Labeled C4-B1..C4-B4 -- NOT C1-C4, which already
identify the Phase 5C acceptance LAYERS (ai/Phase5C3.md requirement 3).

Per scenario, in order:

  1. CREDENTIAL GATE (ai/Phase5C3.md requirements 6 and 8) -- checked
     BEFORE any process is spawned for this scenario. `--bare` (used by
     every launched process here) accepts only ANTHROPIC_API_KEY or an
     apiKeyHelper; this module's only credential-discovery mechanism is
     tests/phase5c/launcher.py's anthropic_api_key_from_env(), which reads
     ONLY the launcher's own environment. If absent, the WHOLE campaign
     reports C4 BLOCKED and stops -- no scenario is attempted, no
     credential is requested/invented/extracted, and the frozen CLI-shim
     path is never used as a fallback.

  2. Writes this scenario's --mcp-config, wired to ai/server_phase5c.py
     with the scenario's exact budgets/allowed-tools taken directly from
     tests/phase5b/scenarios.py (unchanged).

  3. FAIL-CLOSED CAPABILITY PREFLIGHT (ai/Phase5C3.md requirement 5) -- a
     throwaway, inert `claude -p` turn against the SAME mcp_config,
     inspecting only the stream-json `system/init` event. Empirically
     (docs/phase5c-real-mcp-transport-design.md section 4.2), this event
     is emitted BEFORE any model turn is attempted -- so the preflight
     validates the capability boundary (empty built-in tool set, exactly
     one connected MCP server, exactly the expected MCP tool set, no
     skills/slash-commands) independently of whether real API credentials
     are configured; it is not gated behind, and does not consume, step 1's
     credential. A preflight mismatch is recorded as an INFRASTRUCTURE
     FAILURE for that scenario -- the scenario is not attempted and is
     never graded as an agent-capability failure.

  4. Only if preflight passes: the real scenario task, as a genuinely
     fresh `claude -p` process (tests/phase5c/launcher.py -- a direct
     subprocess argument array, shell=False, never a shell string).

  5. Grading: tests/phase5c/evidence.py's adapter projects the evidence
     JSONL down to CallRecord shape and feeds it to the UNMODIFIED
     tests/phase5b/grading.py B1-B4 graders -- no new grading logic.

Does not implement, and does not need to modify, anything under
tests/phase5a/, tests/phase5b/, or dosbox-src/.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tests.phase5a import dosbox_session as ds  # noqa: E402 -- reuse only, not modified
from tests.phase5b import grading as s5b_grading  # noqa: E402 -- reuse only, not modified
from tests.phase5b import scenarios as s5b_scenarios  # noqa: E402 -- reuse only, not modified
from tests.phase5b.bounded_agent_cli import Termination  # noqa: E402

from tests.phase5c import evidence as ev  # noqa: E402
from tests.phase5c import launcher  # noqa: E402
from tests.phase5c import scenario_setup  # noqa: E402

CAMPAIGN_ROOT = _ROOT / "scratchpad" / "phase5c"

# B1 ground truth taken verbatim from tests/phase5b/b1_ground_truth.json
# ("final_status_stopped_before_int21", the trace entry captured stopped
# AT INT 21h without executing it) -- independently observed real
# DOSBox-X execution, not derived from any agent trace.
_B1_INT21_EIP = "0120"
_B1_EXPECTED_FINAL_REGISTERS = {
    "eax": "00004C11",  # AH=4C (MOV AH,4Ch), AL=11 preserved -- the semantic trap
    "ebx": "00002222",
    "ecx": "00003333",
    "edx": "00004444",
    "esi": "00005555",
    "edi": "00006666",
}

# B2 landing offsets, same constants tests/phase5b/test_grading.py already
# uses for the identical grader call.
_B2_CALL1_EIP, _B2_CALL1_LANDING = ds.CALL_FUNC1_OFFSET, ds.FUNC1_ENTRY_OFFSET  # "0112", "0122"
_B2_CALL2_EIP, _B2_CALL2_LANDING = ds.CALL_FUNC2_OFFSET, ds.AFTER_CALL_FUNC2_OFFSET  # "0118", "011B"

# B3/B4 target -- same constant tests/phase5b/test_grading.py already uses.
_TEST_COM_TARGET_EIP = ds.TEST_COM_LOOP_OFFSET  # "0106"


def _grade_c4_b1(records: list[dict]) -> s5b_grading.GradeResult:
    return s5b_grading.grade_b1_register_trace(records, _B1_EXPECTED_FINAL_REGISTERS, _B1_INT21_EIP)


def _grade_c4_b2(records: list[dict]) -> s5b_grading.GradeResult:
    return s5b_grading.grade_b2_call_discrimination(
        records, _B2_CALL1_EIP, _B2_CALL1_LANDING, _B2_CALL2_EIP, _B2_CALL2_LANDING
    )


def _grade_c4_b3(records: list[dict]) -> s5b_grading.GradeResult:
    return s5b_grading.grade_b3_breakpoint_efficiency(records, _TEST_COM_TARGET_EIP)


def _grade_c4_b4(records: list[dict]) -> s5b_grading.GradeResult:
    return s5b_grading.grade_b4_running_stopped_awareness(records, _TEST_COM_TARGET_EIP)


@dataclass(frozen=True)
class C4Scenario:
    label: str  # "C4-B1" etc -- never "C1"-"C4" (those are the acceptance layers)
    b_scenario: Any  # tests.phase5b.scenarios.ScenarioConfig
    grade: Any  # Callable[[list[dict]], GradeResult]


C4_SCENARIOS = [
    C4Scenario("C4-B1", s5b_scenarios.B1, _grade_c4_b1),
    C4Scenario("C4-B2", s5b_scenarios.B2, _grade_c4_b2),
    C4Scenario("C4-B3", s5b_scenarios.B3, _grade_c4_b3),
    C4Scenario("C4-B4", s5b_scenarios.B4, _grade_c4_b4),
]


@dataclass
class PreflightResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    init_event: Optional[dict] = None
    raw_stdout: str = ""
    raw_stderr: str = ""
    resolved_model: Optional[str] = None


@dataclass
class C4RunResult:
    label: str
    infrastructure_failure: bool
    preflight: PreflightResult
    launch: Optional[launcher.LaunchResult] = None
    scenario_result: Optional[s5b_grading.ScenarioGradeResult] = None
    run_dir: Optional[Path] = None
    resolved_model: Optional[str] = None
    infrastructure_reason: Optional[str] = None


def _new_run_dir(campaign_id: str, label: str) -> Path:
    run_dir = CAMPAIGN_ROOT / campaign_id / label / uuid.uuid4().hex[:8]
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _find_init_event(stdout: str) -> Optional[dict]:
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "system" and obj.get("subtype") == "init":
            return obj
    return None


def _check_capability_boundary(
    init_event: Optional[dict], server_name: str, expected_allowed_tools: frozenset
) -> list[str]:
    """The shared fail-closed check both the per-scenario preflight and the
    OAuth capability-equivalence preflight apply to a system/init event --
    one place, so the two can never silently apply different criteria."""

    if init_event is None:
        return ["no system/init event observed in stdout -- cannot verify capability boundary"]

    reasons: list[str] = []
    tools = init_event.get("tools", [])
    mcp_servers = init_event.get("mcp_servers", [])
    slash_commands = init_event.get("slash_commands", [])
    skills = init_event.get("skills", [])

    non_mcp_tools = [t for t in tools if not t.startswith("mcp__")]
    if non_mcp_tools:
        reasons.append(f"built-in tool list is not empty: {non_mcp_tools}")

    if len(mcp_servers) != 1:
        reasons.append(f"expected exactly one connected MCP server, saw {mcp_servers!r}")
    else:
        entry = mcp_servers[0]
        if entry.get("name") != server_name:
            reasons.append(f"expected MCP server name {server_name!r}, saw {entry.get('name')!r}")
        if entry.get("status") != "connected":
            reasons.append(f"expected MCP server status 'connected', saw {entry.get('status')!r}")

    expected_tools = sorted(f"mcp__{server_name}__{t}" for t in expected_allowed_tools)
    if sorted(tools) != expected_tools:
        reasons.append(f"agent-visible MCP tool set mismatch: expected {expected_tools}, saw {sorted(tools)}")

    if slash_commands:
        reasons.append(f"slash_commands not empty: {slash_commands}")
    if skills:
        reasons.append(f"skills not empty: {skills}")

    return reasons


def run_preflight(
    scenario: C4Scenario,
    mcp_config_path: Path,
    server_name: str,
    env: dict[str, str],
    use_bare: bool = True,
    model: Optional[str] = None,
) -> PreflightResult:
    """Throwaway, inert turn against the real scenario mcp_config -- checks
    ONLY the stream-json system/init event (ai/Phase5C3.md requirement 5),
    which the design doc's empirical smoke tests showed is emitted before
    any model turn/credential check. Does not consume the real scenario
    task and is not itself graded. `use_bare=False` runs the SAME check
    against the OAuth invocation variant (launcher.build_claude_argv).

    `model`, when given, additionally verifies this process's own resolved
    model (from ITS OWN system/init event) matches exactly -- a mismatch
    is appended to `reasons` (so `ok=False`), per ai/Phase5C5.md's Model
    reproducibility requirement ("a different resolved model is an
    infrastructure mismatch; do not grade the scenario")."""

    result = launcher.run_claude(
        task="Reply with exactly: PREFLIGHT_OK",
        mcp_config_path=mcp_config_path,
        env=env,
        timeout_seconds=60.0,
        use_bare=use_bare,
        model=model,
    )
    init_event = _find_init_event(result.stdout)
    reasons = _check_capability_boundary(init_event, server_name, scenario.b_scenario.allowed_tools)
    resolved_model = init_event.get("model") if init_event else None
    if model is not None and resolved_model != model:
        reasons.append(f"resolved model mismatch: expected {model!r}, saw {resolved_model!r}")

    return PreflightResult(
        ok=not reasons,
        reasons=reasons,
        init_event=init_event,
        raw_stdout=result.stdout,
        raw_stderr=result.stderr,
        resolved_model=resolved_model,
    )


def run_c4_scenario(
    scenario: C4Scenario, campaign_id: str, env: dict[str, str], use_bare: bool, model: Optional[str] = None
) -> C4RunResult:
    b = scenario.b_scenario
    run_dir = _new_run_dir(campaign_id, scenario.label)
    server_name = f"dosbox-{scenario.label.lower()}"
    evidence_log = run_dir / "evidence.jsonl"

    # The preflight gets its OWN mcp_config/evidence-log/server-name --
    # never shared with the real scenario run below. The preflight task is
    # a deliberately unambiguous inert instruction, but it still runs
    # against a real, tool-capable session; reusing the real run's
    # evidence.jsonl would risk a stray tool call (however unlikely)
    # polluting the trace tests/phase5b/grading.py's B1-B4 graders read.
    preflight_evidence_log = run_dir / "preflight_evidence.jsonl"
    preflight_server_name = f"{server_name}-preflight"
    preflight_mcp_config_path = launcher.write_mcp_config(
        run_dir,
        server_name=preflight_server_name,
        total_budget=b.total_call_budget,
        exec_budget=b.execution_step_budget,
        deadline_seconds=b.timeout_seconds,
        allowed_tools=b.allowed_tools,
        evidence_log=preflight_evidence_log,
    )
    preflight = run_preflight(
        scenario, preflight_mcp_config_path, preflight_server_name, env, use_bare=use_bare, model=model
    )
    (run_dir / "preflight.json").write_text(
        json.dumps(
            {
                "ok": preflight.ok,
                "reasons": preflight.reasons,
                "init_event": preflight.init_event,
                "resolved_model": preflight.resolved_model,
                "preflight_call_records": ev.load_call_records(preflight_evidence_log),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if not preflight.ok:
        return C4RunResult(
            label=scenario.label,
            infrastructure_failure=True,
            preflight=preflight,
            run_dir=run_dir,
            resolved_model=preflight.resolved_model,
            infrastructure_reason="preflight failed: " + "; ".join(preflight.reasons),
        )

    # -- position real DOSBox-X into this scenario's documented
    #    initial_state_description (tests/phase5c/scenario_setup.py) --
    #    AFTER the (cheap, DOSBox-X-independent) preflight so a preflight
    #    failure never costs a DOSBox-X relaunch, and immediately before
    #    the real fresh agent is spawned so nothing else can perturb the
    #    positioned state in between. --
    positioning_status = scenario_setup.POSITIONERS[scenario.label]()
    (run_dir / "positioning_status.json").write_text(json.dumps(positioning_status, indent=2), encoding="utf-8")

    mcp_config_path = launcher.write_mcp_config(
        run_dir,
        server_name=server_name,
        total_budget=b.total_call_budget,
        exec_budget=b.execution_step_budget,
        deadline_seconds=b.timeout_seconds,
        allowed_tools=b.allowed_tools,
        evidence_log=evidence_log,
    )

    launch = launcher.run_claude(
        task=b.task,
        mcp_config_path=mcp_config_path,
        env=env,
        timeout_seconds=b.timeout_seconds,
        use_bare=use_bare,
        model=model,
    )
    (run_dir / "agent_transcript.jsonl").write_text(launch.stdout, encoding="utf-8")
    (run_dir / "agent_stderr.log").write_text(launch.stderr, encoding="utf-8")

    real_init_event = _find_init_event(launch.stdout)
    real_resolved_model = real_init_event.get("model") if real_init_event else None
    if model is not None and real_resolved_model != model:
        # ai/Phase5C5.md Model reproducibility: "A different resolved model
        # is an infrastructure mismatch; do not grade the scenario." This
        # check happens AFTER the real agent already ran (the mismatch can
        # only be observed from ITS OWN init event) but BEFORE any grading
        # call -- records/grading are deliberately never computed below
        # this branch.
        reason = f"resolved model mismatch on the real scenario run: expected {model!r}, saw {real_resolved_model!r}"
        (run_dir / "RUN_STATUS.json").write_text(
            json.dumps({"status": "INTERRUPTED_INFRASTRUCTURE", "reason": reason}, indent=2), encoding="utf-8"
        )
        return C4RunResult(
            label=scenario.label,
            infrastructure_failure=True,
            preflight=preflight,
            launch=launch,
            run_dir=run_dir,
            resolved_model=real_resolved_model,
            infrastructure_reason=reason,
        )

    records = ev.load_call_records(evidence_log)
    session_evidence = ev.latest_session_evidence(evidence_log)
    termination = Termination(session_evidence["termination"]) if session_evidence["termination"] else None

    task_result = scenario.grade(records)
    scenario_result = s5b_grading.finalize_scenario_result(
        scenario_id=scenario.label,
        actual_termination=termination,
        expected_termination=b.expected_termination,
        task_result=task_result,
    )
    (run_dir / "grade_result.json").write_text(
        json.dumps(
            {
                "scenario_id": scenario_result.scenario_id,
                "termination": scenario_result.termination,
                "expected_termination": scenario_result.expected_termination,
                "termination_matches_expected": scenario_result.termination_matches_expected,
                "task_grading_passed": scenario_result.task_grading.passed,
                "task_grading_reasons": scenario_result.task_grading.reasons,
                "passed": scenario_result.passed,
                "timed_out": launch.timed_out,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return C4RunResult(
        label=scenario.label,
        infrastructure_failure=False,
        preflight=preflight,
        launch=launch,
        scenario_result=scenario_result,
        run_dir=run_dir,
        resolved_model=real_resolved_model,
    )


@dataclass
class OAuthPreflightResult:
    ok: bool
    reasons: list[str]
    bare_preflight: PreflightResult
    oauth_preflight: PreflightResult
    differences: list[str]
    oauth_completed_real_turn: bool
    oauth_evidence_log_empty: bool
    run_dir: Path


# The OAuth preflight is deliberately "a fresh, non-scenario Claude Code
# process" (per the user's instruction) -- it uses C4-B1's real budgets/
# tool-set shape (so the capability boundary being proven is a genuine
# scenario shape, not a made-up one) but its task is the same inert
# PREFLIGHT_OK string every per-scenario preflight uses, and it is never
# graded as a scenario.
_OAUTH_PREFLIGHT_SCENARIO = C4_SCENARIOS[0]


def run_oauth_capability_preflight(campaign_id: str) -> OAuthPreflightResult:
    """Proves fail-closed, from actual stream-json initialization evidence,
    that removing ONLY `--bare` (every other isolation control unchanged --
    tests/phase5c/launcher.py::build_claude_argv is the single place both
    variants are built from) still yields the same observable capability
    surface: zero built-in tools, exactly one connected scenario-specific
    MCP server, exactly the expected 12 tools, no slash-commands/skills,
    no additional MCP server. Also checks a fresh MCP server process/
    BoundedSession with empty counters and an empty evidence log (the
    inert preflight task makes no tool call, so a non-empty or missing-then-
    populated evidence log would itself be evidence of cross-run state
    leakage) and that the OAuth process actually completed a real,
    non-error turn (proving OAuth login, not merely that the flags parsed).

    Runs a FRESH --bare preflight against the identical mcp_config
    alongside the OAuth one, for a direct, same-config, same-run
    comparison -- not a comparison against a stale artifact from an
    earlier campaign."""

    run_dir = _new_run_dir(campaign_id, "OAUTH-PREFLIGHT")
    server_name = "dosbox-oauth-preflight"
    evidence_log = run_dir / "evidence.jsonl"
    b = _OAUTH_PREFLIGHT_SCENARIO.b_scenario

    mcp_config_path = launcher.write_mcp_config(
        run_dir,
        server_name=server_name,
        total_budget=b.total_call_budget,
        exec_budget=b.execution_step_budget,
        deadline_seconds=b.timeout_seconds,
        allowed_tools=b.allowed_tools,
        evidence_log=evidence_log,
    )
    env = launcher.build_child_env(None)  # OAuth needs no ANTHROPIC_API_KEY

    bare_preflight = run_preflight(_OAUTH_PREFLIGHT_SCENARIO, mcp_config_path, server_name, env, use_bare=True)
    (run_dir / "bare_preflight.json").write_text(
        json.dumps({"ok": bare_preflight.ok, "reasons": bare_preflight.reasons, "init_event": bare_preflight.init_event}, indent=2),
        encoding="utf-8",
    )

    oauth_preflight = run_preflight(_OAUTH_PREFLIGHT_SCENARIO, mcp_config_path, server_name, env, use_bare=False)
    (run_dir / "oauth_preflight.json").write_text(
        json.dumps({"ok": oauth_preflight.ok, "reasons": oauth_preflight.reasons, "init_event": oauth_preflight.init_event}, indent=2),
        encoding="utf-8",
    )
    (run_dir / "oauth_preflight_stdout.jsonl").write_text(oauth_preflight.raw_stdout, encoding="utf-8")
    (run_dir / "oauth_preflight_stderr.log").write_text(oauth_preflight.raw_stderr, encoding="utf-8")

    reasons = list(oauth_preflight.reasons)

    # -- fresh MCP server process / fresh BoundedSession / empty counters:
    #    the inert preflight task never calls a tool, so evidence.jsonl for
    #    THIS run_dir must contain zero CALL records -- proving no
    #    forwarded/rejected call, and therefore an unused, freshly-
    #    constructed BoundedSession with all counters still at zero. This
    #    is ev.load_call_records(), NOT "the file must not exist": a
    #    normally-ending session (this one) legitimately gets ONE
    #    "session_finalized" line from ai/server_phase5c.py's
    #    _finalize_session_on_exit() (the process-per-session equivalent of
    #    the CLI-shim era's separate tests/phase5b/finalize_session.py
    #    step) -- that line itself is additional, stronger evidence (its
    #    own session_totals are checked below), not evidence of leakage. --
    oauth_call_records = ev.load_call_records(evidence_log)
    oauth_evidence_log_empty = len(oauth_call_records) == 0
    if not oauth_evidence_log_empty:
        reasons.append(f"evidence log contains {len(oauth_call_records)} call record(s) after an inert preflight turn: {oauth_call_records}")

    oauth_session_evidence = ev.latest_session_evidence(evidence_log)
    if oauth_session_evidence["termination"] != "SUCCESS":
        reasons.append(f"expected the preflight session to finalize SUCCESS with zero calls, saw {oauth_session_evidence!r}")
    for counter in ("total_calls_attempted", "total_calls_forwarded", "execution_step_calls"):
        if oauth_session_evidence.get(counter, -1) != 0:
            reasons.append(f"expected a fresh BoundedSession with {counter}=0, saw {oauth_session_evidence!r}")

    # -- proves OAuth actually authenticated (a real completed turn), not
    #    merely that the argv/flags parsed without error. --
    result_event = None
    for line in oauth_preflight.raw_stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "result":
            result_event = obj
    oauth_completed_real_turn = bool(
        result_event is not None and not result_event.get("is_error", True) and result_event.get("subtype") == "success"
    )
    if not oauth_completed_real_turn:
        reasons.append(
            f"OAuth process did not complete a real, non-error turn (result event: {result_event!r}) -- "
            "this is required to actually prove the OAuth login works, not just that the flags parsed"
        )

    # -- compare the two observable capability surfaces (same mcp_config,
    #    same allowed tools, same isolation flags except --bare) and
    #    report every difference, per the user's instruction. --
    differences: list[str] = []
    b_init = bare_preflight.init_event or {}
    o_init = oauth_preflight.init_event or {}
    for field_name in ("tools", "mcp_servers", "slash_commands", "skills", "permissionMode", "claude_code_version", "model"):
        if b_init.get(field_name) != o_init.get(field_name):
            differences.append(f"{field_name}: bare={b_init.get(field_name)!r} vs oauth={o_init.get(field_name)!r}")
    if b_init.get("apiKeySource") != o_init.get("apiKeySource"):
        differences.append(f"apiKeySource: bare={b_init.get('apiKeySource')!r} vs oauth={o_init.get('apiKeySource')!r}")

    (run_dir / "differences.json").write_text(json.dumps(differences, indent=2), encoding="utf-8")

    return OAuthPreflightResult(
        ok=not reasons,
        reasons=reasons,
        bare_preflight=bare_preflight,
        oauth_preflight=oauth_preflight,
        differences=differences,
        oauth_completed_real_turn=oauth_completed_real_turn,
        oauth_evidence_log_empty=oauth_evidence_log_empty,
        run_dir=run_dir,
    )


@dataclass
class C4CampaignResult:
    blocked: bool
    block_reason: Optional[str]
    oauth_preflight: Optional[OAuthPreflightResult] = None
    results: list[C4RunResult] = field(default_factory=list)


def run_c4_campaign(
    campaign_id: Optional[str] = None,
    scenario_labels: Optional[list[str]] = None,
    model: Optional[str] = None,
) -> C4CampaignResult:
    """OAuth capability-equivalence preflight FIRST (never gated behind an
    API key, and never requesting/introducing one). Only if that passes
    fail-closed does this run the requested scenarios (default: all of
    C4-B1..C4-B4; `scenario_labels` narrows this to a specific subset, e.g.
    ["C4-B1", "C4-B3"] for a targeted rerun campaign), each a genuinely
    fresh, separate `claude -p` OAuth process with its OWN independent
    preflight. `model`, when given, is pinned via --model and independently
    verified from each process's own system/init event (ai/Phase5C5.md)."""

    campaign_id = campaign_id or time.strftime("campaign_%Y%m%d_%H%M%S")

    oauth_preflight = run_oauth_capability_preflight(campaign_id)
    if not oauth_preflight.ok:
        return C4CampaignResult(
            blocked=True,
            block_reason="C4 BLOCKED — OAuth capability isolation not established",
            oauth_preflight=oauth_preflight,
        )

    scenarios = C4_SCENARIOS if scenario_labels is None else [s for s in C4_SCENARIOS if s.label in scenario_labels]

    env = launcher.build_child_env(None)
    results = [run_c4_scenario(scenario, campaign_id, env, use_bare=False, model=model) for scenario in scenarios]
    return C4CampaignResult(blocked=False, block_reason=None, oauth_preflight=oauth_preflight, results=results)


def main() -> int:
    campaign = run_c4_campaign()
    if campaign.blocked:
        print(campaign.block_reason)
        return 1

    all_passed = True
    for r in campaign.results:
        if r.infrastructure_failure:
            print(f"{r.label}: INFRASTRUCTURE FAILURE (preflight) -- {r.preflight.reasons}")
            all_passed = False
        else:
            assert r.scenario_result is not None
            status = "PASS" if r.scenario_result.passed else "FAIL"
            print(f"{r.label}: {status} (termination={r.scenario_result.termination})")
            all_passed = all_passed and r.scenario_result.passed
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

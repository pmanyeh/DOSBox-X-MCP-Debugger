"""
Orchestrator-only grading for the Phase 5A real-agent acceptance run
(ai/Phase5A-2.md). NOT shown to, and not invoked by, the subagent under
test -- reads the JSON-lines trace the subagent produced via
tests/phase5a/agent_cli.py, captures the real "after" ground truth via the
unrecorded `verify` path, and runs the EXISTING grading engine
(tests/phase5a/grading.py), unmodified, against both.

Usage: python real_agent_grade.py <scenario_id> <trace_file> [reported_json]

reported_json (scenario 1/2 only): the agent's own final structured answer,
extracted by the orchestrator from its natural-language response --
{"cs": "...", "eip": "..."} for scenario 1, {"mnemonic": "..."} for
scenario 2.
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "ai"))
sys.path.insert(0, str(_ROOT))

import server_phase5a as s5a  # noqa: E402

from tests.phase5a import grading  # noqa: E402


def load_trace(path):
    records = []
    p = Path(path)
    if not p.exists():
        return records
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def summarize(call_log):
    return [{"name": c["name"], "args": c["args"]} for c in call_log]


def main():
    scenario_id = sys.argv[1]
    trace_file = sys.argv[2]
    reported = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

    call_log = load_trace(trace_file)
    after = s5a.verify.get_debug_status()
    after_bps = s5a.verify.list_breakpoints()

    report = {
        "scenario": scenario_id,
        "tool_call_trace": summarize(call_log),
        "final_observed_state": after,
    }

    if scenario_id == "1_inspection":
        before = json.loads(Path(trace_file + ".before.json").read_text())
        result = grading.grade_scenario_1(
            call_log, before, after, reported.get("cs", ""), reported.get("eip", "")
        )
    elif scenario_id == "2_identification":
        before = json.loads(Path(trace_file + ".before.json").read_text())
        result = grading.grade_scenario_2(call_log, before, after, reported.get("mnemonic", ""))
    elif scenario_id == "3_call_over":
        before = json.loads(Path(trace_file + ".before.json").read_text())
        result = grading.grade_scenario_3_exact(call_log, "over", before, after, "011B")
    elif scenario_id == "4_breakpoint":
        target = reported.get("target", "")
        bp_existed = any(b["address"] == target for b in after_bps) or any(
            c["name"] == "set_breakpoint" and c["args"].get("address") == target for c in call_log
        )
        result = grading.grade_scenario_4_set_and_hit(call_log, target, bp_existed, after)
    elif scenario_id == "5_running":
        before = json.loads(Path(trace_file + ".before.json").read_text())
        result = grading.grade_scenario_5(call_log, "running", before, after)
    else:
        raise ValueError(f"unknown scenario_id {scenario_id!r}")

    report["grading_passed"] = result.passed
    report["grading_reasons"] = result.reasons
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

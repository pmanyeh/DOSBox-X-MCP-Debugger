"""
Orchestrator-only helper for the Phase 5B real-agent acceptance campaign
(ai/Phase5B-F.md). Pre-initializes a BoundedSession state file for a given
scenario (tests/phase5b/scenarios.py, unmodified) so the agent's own
tests/phase5b/bounded_agent_cli.py invocations never need to supply
--total-budget/--exec-budget/--deadline-seconds/--allowed-tools themselves
-- those are the orchestrator's approved configuration, not something the
agent should decide, guess, or even see as CLI flags it must get right.

Uses tests/phase5b/bounded_agent_cli.py's own BoundedSession/BudgetConfig
exactly as built (imported, not modified) -- this file only calls
to_state_dict() on a freshly constructed, zero-call session and writes it
to disk; the deadline anchor (`start`) is the real time.monotonic() value
at the moment this runs, i.e. right before the agent is handed control.

Usage: python init_session_state.py <scenario_id> <state_path>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.phase5b.bounded_agent_cli import BoundedSession, BudgetConfig  # noqa: E402
from tests.phase5b.scenarios import ALL_SCENARIOS  # noqa: E402


def main() -> int:
    scenario_id = sys.argv[1]
    state_path = Path(sys.argv[2])
    scenario = ALL_SCENARIOS[scenario_id]

    config = BudgetConfig(
        total_call_budget=scenario.total_call_budget,
        execution_step_budget=scenario.execution_step_budget,
        deadline_seconds=scenario.timeout_seconds,
        allowed_tools=scenario.allowed_tools,
    )
    # tool_resolver is never invoked here -- to_state_dict() on a fresh,
    # zero-call session doesn't touch it.
    session = BoundedSession(config, tool_resolver=lambda name, args: None)
    state_path.write_text(json.dumps(session.to_state_dict(), indent=2), encoding="utf-8")
    print(f"Initialized {scenario_id} session state at {state_path}")
    print(json.dumps(config.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

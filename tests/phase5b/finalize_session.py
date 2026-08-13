"""
Orchestrator-only helper for the Phase 5B real-agent acceptance campaign
(ai/Phase5B-F.md). After an agent's turn ends, marks the session SUCCESS
if -- and only if -- it has not already terminated some other way
(BUDGET_EXHAUSTED / TIMEOUT_EXCEEDED / POLICY_VIOLATION), reusing
BoundedSession._finalize()'s own "exactly one termination, never silently
overwritten" guarantee unmodified. Safe to call unconditionally after
every scenario: for B5 (expected to genuinely hit BUDGET_EXHAUSTED on its
own), this is a no-op, per that same guarantee.

Usage: python finalize_session.py <state_path>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.phase5b.bounded_agent_cli import BoundedSession  # noqa: E402


def main() -> int:
    state_path = Path(sys.argv[1])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    session = BoundedSession.from_state_dict(state, tool_resolver=lambda name, args: None)
    session.finish_success()
    state_path.write_text(json.dumps(session.to_state_dict(), indent=2), encoding="utf-8")
    print(json.dumps(session.evidence(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

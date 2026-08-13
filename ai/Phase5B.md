Phase 5A has passed real-agent acceptance: 5/5 scenarios PASS.

Proceed to Phase 5B.

Do NOT implement code yet.

First produce a Phase 5B design proposal for bounded autonomous debugging.

Phase 5B should build directly on the validated Phase 5A tool-awareness layer and the real DOSBox-X capabilities already validated in Phases 4D/4E.

The goal is to introduce a bounded observe → reason → act → observe debugging loop, NOT an unrestricted autonomous agent.

Requirements:

1. Define a strict tool-call / execution-step budget.
2. Define explicit termination conditions.
3. Keep write_register and write_memory unavailable in the first 5B version.
4. Define at least 5 deterministic scenarios using the existing STEP.COM and TEST.COM programs.
5. Include at least one CALL investigation requiring step_into vs step_over reasoning.
6. Include breakpoint-based investigation.
7. Include running/stopped state awareness.
8. Include a deliberate budget-exhaustion scenario.
9. Every scenario must have independent ground-truth state verification.
10. Agent self-report must never be sufficient as acceptance evidence.
11. Do not modify production code, DOSBox-X C++, native bridge, or ai/server.py during the design phase.
12. Reuse the existing Phase 5A grading architecture where appropriate.
13. Clearly define PASS/FAIL criteria and prohibited behavior.
14. Explicitly explain how Phase 5B differs from Phase 5A.
15. End with a recommendation for Phase 5C.

Produce only the design proposal and wait for Technical Architect approval before implementation.
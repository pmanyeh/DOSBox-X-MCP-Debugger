Phase 5C design is conditionally approved, but do not implement yet. Revise the design document first and stop again for review.

Required revisions:

1. Rename the deliverable to the originally specified path:

   `docs/phase5c-real-mcp-transport-design.md`

   Do not leave two competing Phase 5C design documents.

2. Preserve the original C1–C5 acceptance taxonomy:

   * C1 — deterministic real-MCP connectivity;
   * C2 — deterministic transport equivalence;
   * C3 — deterministic real-MCP bounded enforcement;
   * C4 — fresh real-agent debugging through native MCP tools;
   * C5 — regression and frozen-baseline verification.

   B1/B2/B3/B4-equivalent agent scenarios belong under C4. They do not replace C1–C4.

   Rename the proposed `C5-E` enforcement test to `C3-E` or incorporate it directly into C3. C5 remains regression/frozen-baseline acceptance.

3. Reconsider the server module location. The actual agent-facing MCP entry point should preferably be additive production-facing code such as:

   `ai/server_phase5c.py`

   Phase 5C tests, clients, launchers, graders, and trace verification remain under:

   `tests/phase5c/`

   If the design intentionally keeps the agent-facing server under `tests/phase5c/`, justify how Phase 5C then delivers a production agent-facing path rather than another acceptance-only harness.

4. Resolve the exact Claude Code capability boundary in the design before implementation.

   `--mcp-config` and `--strict-mcp-config` alone do not establish that the fresh agent cannot use Bash, Agent, filesystem tools, or another bypass path.

   Inspect the installed `claude --help` and document the exact invocation contract, including the actual supported flags and syntax used to:

   * load only the scenario-specific MCP configuration;
   * allow only the approved MCP debugger tools;
   * prohibit Bash/shell execution;
   * prohibit Agent/subagent delegation;
   * prohibit filesystem access to scenarios, graders, traces, and server code;
   * prohibit any direct CLI, Python, DOSBoxClient, or native-bridge bypass;
   * run each acceptance agent as a genuinely fresh OS process.

   Clearly distinguish what `--strict-mcp-config` restricts from what the built-in-tool allowlist restricts.

5. Use this evidence-log convention:

   `scratchpad/phase5c/<campaign>/<scenario>/<run-id>/`

   Keep it session-local and out of the repository. Specify the expected files and machine-readable schemas. Each forwarded or rejected request must be correlatable across:

   agent-native tool call
   → MCP request/call identifier
   → BoundedSession CallRecord
   → resolver counter before/after
   → DOSBoxClient request id
   → native result
   → MCP result visible to the agent.

6. For C4, reuse the Phase 5B B1/B2/B3/B4 natural-language task semantics, budgets, and grading criteria. Running all four is approved because together they cover read reasoning, synchronous stepping, asynchronous breakpoint/continue, and running/stopped transitions.

   Do not reuse a CLI state-file mechanism. If the frozen Phase 5B grader requires CLI-produced state, keep it frozen and add a Phase 5C adapter or grader that consumes MCP evidence JSONL while preserving the same grading semantics.

7. Clarify MCP request-id feasibility. Cite the exact installed MCP 2.0.0 request-context API that exposes the protocol request id to a tool handler. If it is not exposed, do not fabricate one. Define a server-generated call id and document exactly which correlation claim remains provable.

8. Keep Phase 5A, Phase 5B, B5-E, B5-A, DOSBoxClient, native bridge, and DOSBox-X debugger backend frozen. Do not implement Phase 5C in this revision.

After revising the document, report:

* the exact final `claude -p` invocation template;
* the exact agent-visible allowed tool list for each C4 scenario;
* the final C1–C5 table;
* the proposed added-file list;
* `git status --short`.

Stop after the revised design document and wait for approval.

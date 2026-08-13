Phase 5C design is approved.

Proceed with Phase 5C implementation according to:

`docs/phase5c-real-mcp-transport-design.md`

Preserve all Phase 5A, Phase 5B, B5-E, B5-A, DOSBoxClient, native bridge, and DOSBox-X debugger-backend frozen files.

Implementation requirements in addition to the approved design:

1. Implement the agent-facing additive MCP entry point as:

   `ai/server_phase5c.py`

2. Add the proposed `tests/phase5c/` infrastructure for C1–C3 and evidence handling.

3. Add an explicit C4 orchestration entry point:

   `tests/phase5c/run_real_agent_acceptance.py`

   or an equivalently clear module.

   Label the four fresh-agent scenarios:

   * C4-B1
   * C4-B2
   * C4-B3
   * C4-B4

   Do not call those scenarios C1–C4, because C1–C5 already identify the Phase 5C acceptance layers.

4. The Claude launcher must use a direct subprocess argument array:

   * no shell command construction;
   * `shell=False`;
   * stdin connected to the platform-equivalent of `DEVNULL`;
   * separate stdout and stderr capture;
   * explicit repository working directory;
   * explicit environment;
   * timeout and process-tree cleanup.

   The Bash-form invocation in the design is descriptive only and must not become a shell-dispatched implementation.

5. Before giving a scenario to a fresh agent, perform a fail-closed capability preflight using the actual stream-json initialization evidence. Confirm:

   * the built-in tool list is empty;
   * exactly one expected scenario MCP server is connected;
   * the agent-visible MCP tool set is exactly the expected 12 tools;
   * no Bash, Agent, filesystem, web, or other built-in capability is available;
   * no extra MCP server or debugger tool is visible.

   A preflight mismatch is an infrastructure failure. Do not continue the agent scenario and do not grade it as an agent-capability failure.

6. Preserve `--bare`. Do not weaken the acceptance boundary to reuse interactive Claude credentials.

   Never put `ANTHROPIC_API_KEY` or any credential in:

   * source code;
   * repository files;
   * MCP config;
   * command-line arguments;
   * traces;
   * stdout/stderr reports.

   Read credentials only from the launcher process environment or the approved `apiKeyHelper` mechanism.

7. Implement and run all deterministic work that does not require Claude credentials first:

   * C1 connectivity;
   * C2 transport equivalence;
   * C3/C3-E real-MCP enforcement;
   * applicable offline tests;
   * frozen-baseline checks.

8. If no suitable Claude credential is present, do not request, invent, extract, or expose one. Report:

   `C4 BLOCKED — missing external Claude Code credential prerequisite`

   Stop before the C4 campaign. This is not permission to weaken `--bare` or use Agent-tool subagents/CLI shims.

9. Every rejected C3 request must be proven to:

   * reach the real MCP server;
   * be recorded as attempted;
   * leave the forwarded/resolver count unchanged;
   * not invoke DOSBoxClient;
   * not reach the native bridge;
   * not alter real DOSBox-X state.

10. Do not modify `bounded_agent_cli.py` or delete the historical CLI-shim path.

After implementation and available deterministic verification, report:

* files added and modified;
* exact C1 result;
* exact C2 result;
* exact C3/C3-E result;
* whether C4 was run or blocked;
* regression results;
* frozen-baseline verification;
* trace locations;
* `git diff --stat`;
* `git status --short`.

Do not claim overall Phase 5C PASS unless C1–C5, including the four genuinely fresh C4 agent processes, have all completed successfully.

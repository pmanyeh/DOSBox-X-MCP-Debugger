# Phase 5C — Real MCP Transport Design (Revision 2)

Status: **design only**. No code, tests, graders, scenarios, launchers,
Phase 5A/5B files, or DOSBox-X source were modified to produce this
document — only this file and the one-time smoke-test artifacts recorded
in §6.4 (`scratchpad/`, not part of the repository proper) exist as a
result of this revision. This supersedes and replaces
`docs/phase5c-mcp-transport-design.md`, which is deleted by this revision
(§0.1) — there is exactly one Phase 5C design document from this point
on. Revised per `ai/Phase5C2.md`'s eight required changes; each is
addressed in the section noted.

## 0. What changed from the first draft, and why

| Phase5C2.md item | Addressed in |
|---|---|
| 1. Single canonical path | §0.1 |
| 2. Preserve C1–C5 taxonomy; B1–B4-equivalents live under C4 only | §2 |
| 3. Reconsider server module location | §3 |
| 4. Resolve the exact Claude Code capability boundary, empirically | §4 |
| 5. Evidence-log convention + schemas | §5 |
| 6. C4 reuses B1–B4 semantics without a CLI state file; adapter, not new grading | §6 |
| 7. Cite the real request-id API or don't fabricate one | §7 |
| 8. Freeze list; no implementation in this revision | §8 |

### 0.1 Single canonical document

`docs/phase5c-mcp-transport-design.md` (the first draft) is deleted as
part of this revision. This file,
`docs/phase5c-real-mcp-transport-design.md`, is the only Phase 5C design
document going forward.

## 1. Why this document exists

Phase 5A (`tests/phase5a/agent_cli.py`) and Phase 5B
(`tests/phase5b/bounded_agent_cli.py`) both proved debugging-capability and
budget-enforcement claims using a CLI shim: a genuinely separate subagent
process called a short-lived Python script via Bash, which looked up the
same tool functions with `getattr()`/dict lookup and invoked them
in-process. That never crossed a real MCP protocol boundary — it was a
documented, deliberate substitute for one ("without a live MCP
client/transport needing to be wired up for that subagent in this
environment" — `tests/phase5a/agent_cli.py`'s own docstring). Phase 5C's
purpose is to close exactly that gap: prove the same capability and
enforcement claims hold when the debugging tools reach a real, separate
agent process as native MCP tools, over a real MCP transport, with
bounded-session enforcement inside the MCP server itself.

None of the following count as Phase 5C transport evidence: importing the
server module and calling functions directly; `getattr()` dispatch;
in-process `mcp.call_tool()`; invoking `bounded_agent_cli.py` (or a
rename) via Bash/PowerShell; a simulated MCP dispatcher; an agent shelling
out to its own MCP client instead of receiving tools natively from its
host.

## 2. The C1–C5 acceptance taxonomy

Preserved exactly as specified. B1–B4-equivalent agent scenarios live
**only** under C4 — they are one item in the taxonomy, not a replacement
for it.

| id | claim | evidence type | LLM required |
|---|---|---|---|
| **C1** | Real-MCP connectivity: a real MCP client can spawn `ai/server_phase5c.py` over stdio, complete `initialize`, receive a correct `tools/list` for a given scenario config, and complete one real forwarded call end-to-end to real DOSBox-X | deterministic integration test | No |
| **C2** | Transport equivalence: an identical sequence of tool calls, against equivalent real DOSBox-X starting state, produces the same observable results (register/state values, error codes) through the new MCP path as through the frozen Phase 5B CLI-shim path — the MCP wrapping introduces no behavioral drift | deterministic integration test, run twice against the same real state | No |
| **C3** | Real-MCP bounded enforcement: N execution-step calls forwarded, the (N+1)th rejected, *before it reaches the resolver*, over a genuine stdio `tools/call` round-trip (not a fake resolver) — the B5-E claim, one transport layer higher (§C3-E below) | deterministic integration test | No |
| **C4** | Fresh real-agent debugging capability through native MCP tools — reuses the B1/B2/B3/B4 task semantics, budgets, and grading criteria unchanged (§6) | 4 genuinely separate, fresh, preconfigured agent processes | Yes |
| **C5** | Regression and frozen-baseline verification | full Phase 5B deterministic suite + Phase 5A regression + offline debugger regression + frozen-file hash/diff verification | No |

`C3-E` (deterministic enforcement) replaces the first draft's `C5-E`
naming — folded into C3, not a separate top-level slot, per instruction
2. "Running all four [B1–B4] is approved because together they cover read
reasoning, synchronous stepping, asynchronous breakpoint/continue, and
running/stopped transitions" — this is C4's scope statement, taken
verbatim from the revision instructions as the authoritative reason all
four are in scope together.

## 3. Server module location

**`ai/server_phase5c.py`** — new, additive, production-facing — is the
actual agent-facing MCP entry point every C1–C4 run connects to. This
follows the existing precedent directly: `ai/server.py` (Phase 4E
production tool surface) and `ai/server_phase5a.py` (Phase 5A restricted
surface) both already live under `ai/`, not `tests/`, specifically
*because* they are the modules a real MCP client actually spawns and
talks to — `tests/` in this repository has never held an agent-facing MCP
entry point, only harnesses, shims, and scenario/grading code that drive
one. `ai/server_phase5c.py` is architecturally the same kind of artifact
as those two: it registers real `@mcp.tool()` functions and calls
`mcp.run()`. The fact that its tool bodies additionally route through
`BoundedSession` (imported unmodified from
`tests/phase5b/bounded_agent_cli.py`) does not change what kind of module
it is — `ai/server_phase5a.py` already imports and wraps `ai/server.py`'s
functions the same way, and stays under `ai/`.

Everything that *drives* `ai/server_phase5c.py` from the outside — C1–C3's
deterministic/integration tests, the C4 fresh-agent launcher (constructs
each run's `--mcp-config` JSON and invokes `claude -p`), the evidence-JSONL
→ Phase 5B-grader adapter (§6), and campaign trace/report verification —
stays under `tests/phase5c/`, mirroring `tests/phase5a/` and
`tests/phase5b/`'s existing role as harness/acceptance code that imports
and exercises production modules without becoming one itself.

If this split were reversed (the server under `tests/`), Phase 5C would
produce only another acceptance-only harness, not a real production
agent-facing capability — which is the gap instruction 3 explicitly
flags. Keeping the server under `ai/` is what makes Phase 5C actually
deliver a debugger MCP entry point a real agent host can be pointed at
going forward, not merely a test fixture.

## 4. The exact Claude Code capability boundary

This section replaces assumption with direct inspection: the installed
build's `claude --help` output, plus three live smoke-test invocations run
against this repository's real, frozen, unmodified `ai/server_phase5a.py`
(chosen for the smoke test specifically because it is already
production-accepted and requires no live DOSBox-X connection merely to
register/list its tools — `DOSBoxClient()` is constructed but not
connected until a tool is actually *called*, per `ai/server.py:15` and
`ai/dosbox_client.py:158-169`). Evidence preserved at
`scratchpad/phase5c_smoketest/` (session-local, not part of the
repository — see §5).

### 4.1 What `--strict-mcp-config` restricts, distinctly from `--tools`

These are two orthogonal boundaries, confirmed empirically, not merely by
reading `--help` text:

* **`--mcp-config <file> --strict-mcp-config`** controls which **MCP
  servers** are connected at all. `--strict-mcp-config`: "Only use MCP
  servers from `--mcp-config`, ignoring all other MCP configurations" —
  this is what prevents a fresh agent from also seeing whatever other MCP
  servers happen to be configured on the host running the harness (this
  very session's own environment has `claude.ai Gmail`/`Google
  Calendar`/`Google Drive` MCP servers configured — a concrete, real
  example of exactly what `--strict-mcp-config` must, and does, exclude).
  Without it, a discovered project `.mcp.json` would also normally require
  interactive approval (`claude mcp list`'s own help text: "Unapproved
  `.mcp.json` servers are shown as ⏸ Pending approval and not connected
  to") — `--mcp-config` passed explicitly on the command line is a
  separate, direct load path that is not subject to that interactive
  gate, and `-p` additionally skips the workspace-trust dialog in
  non-interactive mode.
* **`--tools <built-in list>`** controls which of Claude Code's own
  **native, non-MCP** tools (Bash, Read, Write, Edit, Glob, Grep,
  Agent/Task, WebFetch, WebSearch, TodoWrite, etc.) are available at all.
  `--tools ""` — "Use `\"\"` to disable all tools" — empties this set
  completely. This is orthogonal to MCP: even with `--strict-mcp-config`
  limiting MCP servers to exactly one, without `--tools ""` the agent
  would still have Bash (shell out to a CLI bypass), Read/Glob/Grep
  (read scenario/grader/ground-truth files), and Agent (spawn an
  unbounded subagent) available as built-ins — precisely the bypass paths
  instruction 4 lists.

### 4.2 Empirical verification (not assumed)

Three live `claude -p` invocations were run against this machine's actual
installed Claude Code (`claude_code_version: 2.1.226`) and this
repository's real `ai/server_phase5a.py`, spawned as a genuine child
process over stdio:

1. `--tools ""` alone (no MCP config): the session's own `system/init`
   event reported `"tools":[]` — an empty array, not merely a hidden or
   deprioritized list. `"agents":[...]` (the six agent *type names*) was
   still present as metadata, but with `tools:[]` there is no Agent/Task
   tool to invoke any of them — confirming "prohibit Agent/subagent
   delegation" is satisfied by tool absence, not by the agents list being
   empty (it isn't).
2. `--tools "" --mcp-config <smoketest-config> --strict-mcp-config`
   pointed at `ai/server_phase5a.py`: the init event reported
   `"mcp_servers":[{"name":"dosbox-phase5a-smoketest","status":"connected"}]`
   and `"tools"` containing **exactly** the 14 names
   `ai/server_phase5a.py` registers (`ping`, `get_project_status`,
   `get_cpu_state`, `get_debug_status`, `get_current_instruction`,
   `read_memory`, `disassemble`, `set_breakpoint`, `delete_breakpoint`,
   `list_breakpoints`, `continue_execution`, `pause_execution`,
   `step_into`, `step_over` — `write_register`/`write_memory` correctly
   absent, matching that module's own design), each prefixed
   `mcp__dosbox-phase5a-smoketest__<name>` — this is the empirically
   confirmed agent-visible tool-name format, not a guessed one. No Bash,
   Read, Write, Edit, Glob, Grep, Agent, WebFetch, WebSearch, or
   TodoWrite appeared anywhere in `tools`. This is real, live proof that
   a genuinely separate Claude Code process, given only `--mcp-config`
   pointing at one of this project's own real MCP server modules, sees
   *only* that module's tools and nothing else — the whole chain (spawn →
   stdio handshake → `initialize` → `tools/list` → tool-name prefixing)
   completed successfully before the run failed for the unrelated reason
   below.
3. Adding `--disable-slash-commands` to the same invocation: `slash_commands`
   and `skills` both became `[]` in the init event (previously populated
   with this environment's normal skill/command list), while `tools` and
   `mcp_servers` were unaffected — confirming skill/slash-command
   invocation, a residual surface neither `--tools ""` nor
   `--strict-mcp-config` addresses, is independently closable and should
   be, for the same "hard guarantee, not a prompt-level instruction"
   standard this project already applies to `write_register`/
   `write_memory` (`ai/server_phase5a.py`'s own docstring).

All three runs terminated at the same point, for a reason unrelated to
the MCP/tool boundary: `"apiKeySource":"none"` /
`"error":"authentication_failed"` — this sandboxed smoke-test shell has no
Claude credentials configured. `--bare` (used in all three, to also
suppress CLAUDE.md/hook/plugin auto-discovery per §4.3) restricts
authentication strictly to `ANTHROPIC_API_KEY` or an `apiKeyHelper` via
`--settings` — neither is present here. **This is a genuine, newly
discovered prerequisite, not a design gap**: whoever runs the actual C4
campaign must supply one of those two credential mechanisms to each
spawned process's environment. This is a credentials/policy decision for
the user, not something this design can or should resolve unilaterally.

### 4.3 Final invocation contract

```
claude -p "<scenario natural-language task, only>" \
  --bare \
  --mcp-config <run-dir>/mcp_config.json \
  --strict-mcp-config \
  --tools "" \
  --disable-slash-commands \
  --permission-mode bypassPermissions \
  --setting-sources "" \
  --output-format stream-json \
  --verbose \
  --no-session-persistence \
  < /dev/null
```

Field-by-field justification:

* `--bare` — per its own `--help` text, skips hooks, LSP, plugin sync,
  attribution, auto-memory, background prefetches, keychain reads, **and
  CLAUDE.md auto-discovery**. The last one matters specifically for
  isolation: this repository's own `CLAUDE.md`/`ai/AGENTS.md`-style
  project context must never be auto-injected into a C4 agent's system
  prompt (it would describe the project's phase structure and testing
  conventions — not ground truth or grader internals, but still outside
  what B1–B5's isolation requirements ever allowed a fresh agent to see).
  Also forces auth to `ANTHROPIC_API_KEY`/`apiKeyHelper` only (§4.2) —
  documented behavior, not a side effect discovered by accident.
* `--mcp-config <run-dir>/mcp_config.json --strict-mcp-config` — loads
  only the one scenario-specific bounded server, nothing else (§4.1),
  empirically verified (§4.2 item 2).
* `--tools ""` — empties the built-in tool set: no Bash, no
  Read/Write/Edit/Glob/Grep, no Agent, no WebFetch/WebSearch, no
  TodoWrite. Empirically verified (§4.2 item 1) to produce `tools:[]`.
* `--disable-slash-commands` — closes the skill/slash-command surface,
  empirically verified to empty `skills`/`slash_commands` without
  affecting the MCP tool set (§4.2 item 3).
* `--permission-mode bypassPermissions` — with the built-in tool set
  already empty and the MCP server set already limited to exactly the
  scenario's own bounded debugger tools, there is nothing left to gate
  behind an interactive/default permission prompt; without bypassing it,
  a non-interactive `-p` run would otherwise stall waiting for an
  approval that can never arrive. `--allowedTools`/`--disallowedTools`
  are deliberately **not** used in addition to this — they operate on the
  same "which built-in tool names may run" question `--tools ""` already
  answers exhaustively (nothing is left to allow or deny), and layering a
  second, differently-shaped mechanism on top would only make the actual
  boundary harder to audit, not stronger.
* `--setting-sources ""` — belt-and-suspenders alongside `--bare`: no
  user/project/local settings (including any permission allowlists) are
  read from disk at all.
* `--output-format stream-json --verbose` — required together
  (`stream-json` "requires --verbose" when combined with `-p`, confirmed
  empirically: omitting `--verbose` fails fast with exactly that message
  before any MCP connection is attempted). Gives the harness the agent's
  own turn-by-turn transcript, independently cross-checkable against the
  server-side evidence log (§5).
* `--no-session-persistence` — the fresh process's transcript is not
  saved to, or resumable from, local Claude Code session storage; the
  harness's own evidence log and `--output-format` capture are the
  durable record instead.
* `< /dev/null` — avoids a several-second "no stdin data received"
  startup stall observed in the smoke tests; harmless, not
  security-relevant.

Deliberately **not** used: `--add-dir` (no extra filesystem access is
granted; moot in any case since no filesystem tool exists under
`--tools ""`), `--dangerously-skip-permissions`/
`--allow-dangerously-skip-permissions` (unnecessary — `--permission-mode
bypassPermissions` is the documented, narrower mechanism for the same
effect and does not also touch workspace-trust semantics), `--ide`
(no IDE attachment for a scripted acceptance run).

### 4.4 Pre-flight check as an acceptance prerequisite

Before the first real C4 scenario runs, the harness must execute one
throwaway invocation of this exact contract against that scenario's real
`mcp_config.json` (task: something inert, e.g. "reply with exactly OK")
and assert, from the `system/init` stream-json event: `tools` equals
exactly the scenario's expected `mcp__<server>__<tool>` set (§6.1),
`mcp_servers` shows exactly one entry with `status: connected`,
`slash_commands` and `skills` are both `[]`. This is a cheap, mechanical,
per-campaign re-verification of §4.2's findings — not a re-derivation of
them — and its output must be preserved as part of that campaign's
evidence (§5).

## 5. Evidence-log convention and schemas

Root: `scratchpad/phase5c/<campaign>/<scenario>/<run-id>/` — session-local,
matching this project's existing `scratchpad/phase5b_campaign2/`,
`scratchpad/phase5b_campaign3/` convention, and explicitly **not**
committed to the repository (consistent with how those directories are
already left untracked; this document does not itself add a `.gitignore`
entry, since that would be an implementation action and this revision
implements nothing per instruction 8 — flagged as an open item for
whoever begins implementation).

Expected files per run:

| file | written by | contents |
|---|---|---|
| `mcp_config.json` | harness, before launch | the exact `--mcp-config` JSON used — reproducibility/audit |
| `preflight.json` | harness (§4.4) | the pre-flight `system/init` event, plus the assertions checked against it |
| `evidence.jsonl` | `ai/server_phase5c.py`, one line per attempted call | the correlation trace, schema below |
| `agent_transcript.jsonl` | harness, capturing `claude -p`'s stdout | the full `--output-format stream-json` stream — the agent's own view (C4 only; C1–C3 have no agent) |
| `post_session_status.json` | harness, after the run ends (§C3-E, §8) | independent direct-`DOSBoxClient` coherence check, taken outside the terminated session |
| `grade_result.json` | harness, after grading | `ScenarioGradeResult` (`tests/phase5b/grading.py`'s existing dataclass, reused) serialized |

`evidence.jsonl` line schema (one JSON object per line, append-only,
written from inside `ai/server_phase5c.py` after every
`BoundedSession.call()` — forwarded or rejected — never agent-visible):

```json
{
  "seq": 4,
  "mcp_request_id": "4",
  "tool": "step_into",
  "args": {},
  "forwarded": true,
  "resolver_invocations_before": 3,
  "resolver_invocations_after": 4,
  "dosbox_client_request_id": 4,
  "result": {"...": "..."},
  "session_totals": {
    "total_calls_attempted": 4,
    "total_calls_forwarded": 4,
    "execution_step_calls": 4
  },
  "termination": null,
  "timestamp": 1234567.89
}
```

Field provenance — every field is either a value an existing, frozen
class already produces, or a value newly and directly read off the
installed SDK's own API (§7), never invented:

* `seq` — `len(BoundedSession.records)` at the time of this call; ties
  the line 1:1 to a `CallRecord` (`tests/phase5b/bounded_agent_cli.py:85-101`,
  frozen, imported unmodified).
* `mcp_request_id` — see §7.
* `tool`, `args`, `forwarded`, `result` — read directly off the
  `CallRecord`/`BoundedSession.call()` return value, unchanged shape.
* `resolver_invocations_before/after` — the B5-E audit's own proposed
  counting-wrapper technique (`docs/phase5b-b5e-enforcement-audit.md`
  §5 item 2/§3), applied here to every call, not only the boundary one.
* `dosbox_client_request_id` — `DOSBoxClient._id_counter`'s value for
  this call (`ai/dosbox_client.py:156,212`), present only when
  `forwarded` is true; ties this line to the exact request/response pair
  on the native bridge's TCP wire (the same id `DOSBoxClient.request()`
  already asserts the bridge echoed back correctly,
  `ai/dosbox_client.py:233-236`).
* `session_totals`, `termination` — `BoundedSession.evidence()`'s own
  fields (`tests/phase5b/bounded_agent_cli.py:240-260`), unchanged.

## 6. C4: reusing B1–B4 without a CLI state file

### 6.1 Task/budget/grading reuse

C4 reuses `tests.phase5b.scenarios.B1`, `B2`, `B3`, `B4` **unchanged** —
same task text, program, initial state, budgets, and
`grading_function_name`. No new debugging-capability claim is introduced;
only the transport changes. Each becomes one `ai/server_phase5c.py`
process, configured (via that scenario's `mcp_config.json` `args`) with
`--total-budget`, `--exec-budget`, `--deadline-seconds`, and
`--allowed-tools` taken directly from the matching `ScenarioConfig` —
the exact same fields `bounded_agent_cli.py`'s CLI already accepts, just
supplied once at process start instead of on every CLI invocation. The
agent-visible tool list for each C4 run is therefore exactly that
scenario's `allowed_tools`, each name prefixed `mcp__<scenario
server-name>__<tool>` (§4.2/§4.4).

### 6.2 No CLI state file

`bounded_agent_cli.py`'s `--state <path>` JSON file
(`tests/phase5b/bounded_agent_cli.py:265-291`) existed only because that
CLI was re-invoked as a brand-new process for *every single tool call*,
so `BoundedSession` had to be reconstructed from disk each time. Under
the process-per-session model (§3 of the first draft, unchanged here),
`ai/server_phase5c.py` constructs **one** `BoundedSession` at process
startup and holds it in memory for the whole run — every `tools/call`
within that MCP session mutates the same live object. There is no
cross-process state to persist, so there is no state file, CLI or
otherwise. `BoundedSession.to_state_dict()`/`from_state_dict()` remain
available (frozen, unused by Phase 5C) for any future need but are not
part of this design.

### 6.3 Grading adapter, not new grading logic

`tests/phase5b/grading.py`'s `grade_b1_register_trace`,
`grade_b2_call_discrimination`, `grade_b3_breakpoint_efficiency`, and
`grade_b4_running_stopped_awareness` all take a plain
`records: list[dict[str, Any]]` in `CallRecord` shape (`tool`/`args`/
`forwarded`/`result`) and internally call the same frozen
`to_phase5a_shape()` (`tests/phase5b/grading.py:45-57`) regardless of
where those dicts came from. `evidence.jsonl`'s lines (§5) are a strict
superset of that shape — they carry the same four fields plus additional
correlation fields these graders never look at. The Phase 5C adapter is
therefore a single, small, new function,
`tests/phase5c/evidence.py::load_call_records(evidence_log_path) ->
list[dict]`, that reads the JSONL and projects each line down to
`{"tool", "args", "forwarded", "result"}` — nothing more. The frozen B1–B4
graders are then called **directly and unmodified** with that list. This
is the same reuse discipline `tests/phase5b/grading.py`'s own docstring
already states ("Only genuinely NEW Phase 5B grading logic lives here...
never copied or reimplemented") applied one layer up: no new grading
semantics are introduced anywhere in Phase 5C.

## 7. MCP request-id feasibility — cited, not fabricated

The installed `mcp==2.0.0` SDK exposes the protocol request id to a tool
handler via `Context.request_id` (`mcp/server/mcpserver/context.py:287-290`):

```python
@property
def request_id(self) -> str:
    """Get the unique ID for this request."""
    return str(self.request_context.request_id)
```

backed by `ServerRequestContext.request_id: RequestId | None`
(`mcp/server/context.py:31-46`), populated per-request by the low-level
`Server`/`ServerRunner` for every inbound `tools/call`. A tool function
receives this by declaring an extra parameter annotated `Context` (the
SDK's documented context-injection mechanism, `mcp/server/mcpserver/
server.py:632-668`'s own docstring example) — `ai/server_phase5c.py`'s
generic `return session.call(name, kwargs)` wrapper becomes `def
_wrapped(ctx: Context, **kwargs): ... ctx.request_id ...`. This is a real,
cited, installed API — not fabricated.

What this **does** and **does not** prove: `ctx.request_id` is the exact
JSON-RPC id the connected MCP client (the real agent host) assigned to
that specific `tools/call` request — genuine evidence that a particular
evidence-log line corresponds to a specific wire-level request the agent
issued. It does **not** independently prove ordering or exclusivity
beyond what `seq` (§5) already establishes from the server's own
authoritative call sequence — id-space uniqueness is a per-connection
guarantee the *client* is responsible for, not something the server
verifies. Both fields are therefore recorded: `seq` is the primary,
always-available, server-authoritative correlation key (what
`BoundedSection`/every existing Phase 5B grader already keys off of via
list position); `mcp_request_id` is additional, real, non-fabricated
corroboration sourced from the cited API above, not a substitute for it.

### C3-E — deterministic MCP-transport enforcement proof (no LLM)

Folded into C3 per instruction 2. Design (not implemented by this
document): `tests/phase5c/test_server_phase5c_real_dosbox.py` uses
`mcp.client.stdio.stdio_client(StdioServerParameters(...))` +
`mcp.client.session.ClientSession` (the SDK's own client primitives, the
same ones a real agent host uses) to spawn `ai/server_phase5c.py` with a
small `execution_step_budget` (e.g. 2, mirroring B5-E's chosen N and
rationale), issue exactly that many `call_tool("step_into", {})`
requests (asserting each is `is_error=False` and real DOSBox-X state
actually advanced, checked independently), issue one further request and
assert `is_error=True` with the new `bounded_session`/`BUDGET_EXHAUSTED`/
`terminal=true` shape (§4 of the first draft's error-domain table, carried
forward unchanged by this revision), read `evidence.jsonl` and assert the
resolver-invocation counter did not advance for that call, then close the
client (stdin closes → server subprocess exits, matching stdio's
documented lifecycle) and independently verify post-rejection DOSBox-X
coherence via a direct `DOSBoxClient` connection, exactly as B5-E's own
audited technique already does (`tests/phase5b/
test_bounded_agent_cli_real_dosbox.py`) — reused as a pattern, not
duplicated as code.

## 8. What stays frozen

Unchanged by this design and by the implementation it describes: `ai/
server.py`, `ai/server_phase5a.py`; `tests/phase5a/**`, `dosbox-src/**`;
`tests/phase5b/bounded_agent_cli.py`, `tests/phase5b/scenarios.py`,
`tests/phase5b/grading.py` (`BoundedSession`, `BudgetConfig`,
`Termination`, B1–B4's configs, and every grading function are imported
into Phase 5C, never copied or forked); B5-E's own test and audit
(`tests/phase5b/test_bounded_agent_cli_real_dosbox.py`,
`docs/phase5b-b5e-enforcement-audit.md`); B5-A's historical evidence and
the Model B acceptance architecture (`docs/phase5b-acceptance-model-review.md`);
every prior campaign's preserved trace
(`scratchpad/phase5b_campaign2/`, `scratchpad/phase5b_campaign3/`).

**No implementation occurred in this revision.** `ai/server_phase5c.py`
and everything under `tests/phase5c/` remain design-only; only this
document and the smoke-test config/output under
`scratchpad/phase5c_smoketest/` (session-local, not part of the
repository) were created.

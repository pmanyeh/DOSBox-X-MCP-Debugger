"""
Phase 5C fresh-agent launcher (docs/phase5c-real-mcp-transport-design.md
section 4). Spawns a genuinely separate `claude -p` OS process, wired to
exactly one scenario-specific ai/server_phase5c.py instance over real MCP
stdio transport.

ai/Phase5C3.md requirement 4 in full:
  * a direct subprocess argument array -- never a shell command string;
  * shell=False;
  * stdin connected to the platform-equivalent of DEVNULL;
  * separate stdout and stderr capture;
  * explicit repository working directory;
  * explicit environment;
  * timeout and process-tree cleanup.

ai/Phase5C3.md requirement 6: never put ANTHROPIC_API_KEY (or any
credential) in source code, repository files, MCP config, command-line
arguments, traces, or stdout/stderr reports. Read credentials only from
the launcher process's own environment. This module's ONLY credential
mechanism is anthropic_api_key_from_env() below -- it does not read
settings files, does not accept a credential as a parameter from other
code, and never writes one to mcp_config.json or argv.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable
SERVER_SCRIPT = str(_ROOT / "ai" / "server_phase5c.py")

# Resolved ONCE, via the launcher's own PATH (shutil.which), to an
# absolute path -- not the bare string "claude". This avoids relying on
# how the OS/Python resolves a bare executable name against a
# *child-process* env's PATH (platform-inconsistent); the child is always
# launched with an explicit, fully-resolved executable path instead.
CLAUDE_EXE = shutil.which("claude")

# Minimal env passed to the child process -- never the full parent
# environment. PATH/SYSTEMROOT/etc. are required for Windows to resolve
# DLLs and spawn the ai/server_phase5c.py grandchild process at all;
# ANTHROPIC_API_KEY is added explicitly by the caller only when present in
# the launcher's own environment (see anthropic_api_key_from_env()).
_BASE_INHERITED_ENV_VARS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "COMSPEC",
    "WINDIR",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
)


def anthropic_api_key_from_env() -> Optional[str]:
    """The ONLY credential-discovery mechanism this launcher uses: read
    ANTHROPIC_API_KEY from the launcher process's own environment. Never
    reads a settings file, never invents/extracts/derives a key. Returns
    None (not "") when absent -- callers must treat that as "no
    prerequisite available", per ai/Phase5C3.md requirement 8."""

    value = os.environ.get("ANTHROPIC_API_KEY")
    return value if value else None


def build_child_env(anthropic_api_key: Optional[str]) -> dict[str, str]:
    """A minimal, explicit environment for the child `claude` process --
    never `os.environ.copy()`. The credential, if present, is placed ONLY
    here: an OS-level env block passed to subprocess.Popen, not argv, not
    a file, not anything that appears in stdout/stderr or a trace."""

    env: dict[str, str] = {}
    for name in _BASE_INHERITED_ENV_VARS:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    if anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = anthropic_api_key
    return env


def write_mcp_config(
    run_dir: Path,
    server_name: str,
    total_budget: int,
    exec_budget: int,
    deadline_seconds: float,
    allowed_tools: frozenset,
    evidence_log: Path,
) -> Path:
    """Writes this run's --mcp-config JSON file (design doc section 2.2).
    Command/args only -- no credentials ever appear here."""

    config = {
        "mcpServers": {
            server_name: {
                "command": PYTHON,
                "args": [
                    SERVER_SCRIPT,
                    "--total-budget", str(total_budget),
                    "--exec-budget", str(exec_budget),
                    "--deadline-seconds", str(deadline_seconds),
                    "--allowed-tools", ",".join(sorted(allowed_tools)),
                    "--evidence-log", str(evidence_log),
                ],
            }
        }
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "mcp_config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def build_claude_argv(
    task: str, mcp_config_path: Path, use_bare: bool = True, model: Optional[str] = None
) -> list[str]:
    """The exact invocation contract from
    docs/phase5c-real-mcp-transport-design.md section 4.3, as a literal
    argument array -- never a shell command string that could be
    re-parsed/re-quoted by a shell.

    `use_bare=False` is the ONE deliberate deviation approved for the
    OAuth capability-equivalence test: `--bare` is omitted (so the
    process may use the existing Claude OAuth login instead of requiring
    ANTHROPIC_API_KEY/apiKeyHelper) while every OTHER isolation control
    below stays byte-for-byte identical to the approved contract -- this
    function is the single place both variants are built from, so the
    two invocations can never silently drift apart from each other.

    `model`, when given, adds `--model <model>` (the installed CLI's own
    exact-selector flag, confirmed via `claude --help`) to pin model
    reproducibility across processes (ai/Phase5C5.md's Model
    reproducibility requirement) -- omitted (None, the default) preserves
    every prior invocation's exact behavior (an unpinned, host-default
    model selection)."""

    if CLAUDE_EXE is None:
        raise RuntimeError("could not resolve 'claude' on PATH (shutil.which('claude') returned None)")
    argv = [CLAUDE_EXE, "-p", task]
    if use_bare:
        argv.append("--bare")
    if model:
        argv += ["--model", model]
    argv += [
        "--mcp-config", str(mcp_config_path),
        "--strict-mcp-config",
        "--tools", "",
        "--disable-slash-commands",
        "--permission-mode", "bypassPermissions",
        "--setting-sources", "",
        "--output-format", "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]
    return argv


@dataclass
class LaunchResult:
    argv: list[str]
    returncode: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float


def run_claude(
    task: str,
    mcp_config_path: Path,
    env: dict[str, str],
    timeout_seconds: float = 600.0,
    cwd: Optional[Path] = None,
    use_bare: bool = True,
    model: Optional[str] = None,
) -> LaunchResult:
    """Spawns `claude -p` as a genuinely separate OS process, per
    ai/Phase5C3.md requirement 4:

    * build_claude_argv() -- a direct argument array, never a shell string;
    * shell=False;
    * stdin=subprocess.DEVNULL (the platform-equivalent of `< /dev/null`);
    * stdout and stderr captured into SEPARATE pipes, never merged;
    * explicit `cwd` (defaults to the repository root);
    * explicit, minimal `env` (build_child_env()) -- this function never
      falls back to inheriting the launcher's full environment;
    * a hard timeout with process-TREE cleanup on expiry -- the child
      `claude` process spawns ai/server_phase5c.py as its own MCP-server
      grandchild; a plain kill() would not reliably reach that grandchild,
      so timeout cleanup uses `taskkill /T /F` against the whole tree
      rooted at `claude`'s PID.
    """

    argv = build_claude_argv(task, mcp_config_path, use_bare=use_bare, model=model)
    start = time.monotonic()
    proc = subprocess.Popen(
        argv,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd or _ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc.pid)
        stdout, stderr = proc.communicate()
    duration = time.monotonic() - start
    return LaunchResult(
        argv=argv,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_seconds=duration,
    )


def _kill_process_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:  # pragma: no cover -- this project targets Windows
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

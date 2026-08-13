# GitHub Publication Readiness Audit

Status: **audit only**. Every command run to produce this document was
read-only against the local repository and the remote's ref advertisement
(`git ls-remote`, which lists refs without downloading objects or history —
distinct from `git fetch`). No remote was added or changed, nothing was
fetched, pulled, merged, pushed, staged, committed, tagged, or rewritten.
No authentication token, credential-helper content, or credential-bearing
URL is reproduced anywhere below.

Destination repository (as supplied): **`pmanyeh/DOSBox-X-MCP-Debugger`**
(`https://github.com/pmanyeh/DOSBox-X-MCP-Debugger`, git URL
`https://github.com/pmanyeh/DOSBox-X-MCP-Debugger.git`).

## 1. Is the remote empty or does it already contain a commit?

```
git ls-remote https://github.com/pmanyeh/DOSBox-X-MCP-Debugger.git
```

Exit code `0`, **zero lines of output** — no refs advertised at all (no
branches, no tags, not even an unborn `HEAD`). This is the exact,
unambiguous signature of a genuinely empty GitHub repository (no initial
commit, e.g. not even a README/LICENSE created via the GitHub UI at repo
creation time). **The destination is empty.**

## 2. Visibility (public vs. private)

**Could not be independently confirmed.** The GitHub CLI (`gh`) is not
installed in this environment — checked on both the Bash toolchain PATH
and the PowerShell PATH (`Get-Command gh` / `gh --version` both fail with
"not found" on both). No other authenticated GitHub tooling was found
installed.

The successful, unprompted `git ls-remote` above is **not** usable as
indirect evidence of "public," because this machine has Git Credential
Manager configured globally as the credential helper
(`credential.helper = git-credential-manager.exe`, confirmed via `git
config --get credential.helper` — the helper's *name* only, no stored
token/credential value was read or printed). GCM can transparently supply
a previously-stored GitHub credential for an authenticated request without
any interactive prompt, so a successful, silent `ls-remote` is equally
consistent with "the repo is public" and "the repo is private but this
machine already holds valid stored credentials for its owner
(`pmanyeh`)." Distinguishing the two would require either installing/
authenticating `gh` and running a read-only `gh repo view`, or the user
confirming visibility directly.

## 3. Current local remote configuration

```
git remote -v                        -> (no output)
git config --get-regexp "^remote\."  -> (no output)
git branch -vv                       -> * main 8357b43 [no upstream configured]
```

**No remote is configured at all** — not `origin`, not any other name.
`main` is a purely local branch with no upstream tracking reference. This
matches the instruction not to add/change `origin` yet; nothing needs to
be undone.

Local commit history on `main` (4 commits, most recent first):

```
8357b43 Add Phase 5C real-MCP-transport implementation (formal acceptance: NOT PASS, 3/4 composed C4)
6fcf6bf Backup project state: update native bridge, add step execution tests, Phase4E.md, and STEP.COM
ca6ef04 Backup project state: add Phase4D.md
cac8757 Initial commit
```

## 4. The `dosbox-src` portability question — critical blocker

This is the single most important finding in this audit, and by itself is
sufficient reason not to push yet.

### 4a. `dosbox-src` is a dangling gitlink, not a real submodule

```
git ls-tree HEAD -- dosbox-src
160000 commit 624bf58758a55e167da327828ec9fbe6e18440b8    dosbox-src
```

Mode `160000` is git's **gitlink** marker — the same mechanism `git
submodule` uses to record "this path is a nested repository pinned at
commit X." But **no `.gitmodules` file exists anywhere in this
repository** (`ls -la .gitmodules` → not found; confirmed absent from the
full `git ls-tree -r HEAD` file listing too). A gitlink with no
`.gitmodules` entry has no recorded URL to fetch from. Concretely: **if
this repository is cloned fresh today, `dosbox-src/` will appear as a
completely empty directory**, and nothing in the repository tells git (or
a human) where its contents were supposed to come from. This gitlink was
almost certainly created by accident — `git add dosbox-src` on a path that
already contained its own nested `.git` directory silently produces
exactly this kind of orphaned gitlink, without ever running `git submodule
add`.

### 4b. Even a correctly-registered submodule would NOT restore the AI bridge

`dosbox-src/.git/config` reveals what the nested repository actually is:

```
[remote "origin"]
    url = https://github.com/joncampbell123/dosbox-x
```

This is the real, public upstream DOSBox-X project. The pinned commit
(`624bf587...`, message `"prepare for release"`) is a stock upstream
commit. However, `git -C dosbox-src status --short` shows:

```
 M include/debug.h
 M src/debug/Makefile.am
 M src/debug/debug.cpp
 M src/dosbox.cpp
 M vs/dosbox-x.vcxproj
 M vs/dosbox-x.vcxproj.filters
?? src/debug/debug_ai.cpp
?? src/debug/debug_ai.h
```

**These are the entire native AI bridge implementation** — the C++ code
this whole project (`ai/dosbox_client.py`, `ai/server.py`,
`ai/server_phase5c.py`, every Phase 4/5 debugging capability) depends on
end-to-end. Every one of these changes is **uncommitted**, in either
repository:

* not committed inside `dosbox-src`'s own nested repo (they're plain
  uncommitted working-tree edits against the stock upstream commit);
* not captured by the outer repo either, since a gitlink only records a
  commit SHA, never file contents.

Consequently: **even if `.gitmodules` were added correctly today, pointing
at the real upstream at the pinned commit, cloning it would produce stock,
unmodified DOSBox-X — with no AI bridge at all.** The bridge source
currently exists, in git-trackable form, nowhere except as uncommitted
files in this one local working tree. This is the actual portability risk
the fix must address, not merely the missing `.gitmodules` file.

### 4c. Secondary `dosbox-src` issues

* **Shallow clone**: `dosbox-src/.git/shallow` lists exactly the pinned
  commit — this is a depth-1 clone with no ancestry. Not by itself
  blocking (the commit is presumably still fetchable from the real
  upstream), but worth resolving alongside the above rather than
  separately.
* **Size**: `dosbox-src` is **1.3 GB** total (`bin/` 111 MB of compiled
  build output including `dosbox-x.exe`, `vs/` 161 MB of Visual Studio
  project scaffolding, `src/` 52 MB of actual source, `.git/` 125 MB).
  None of `bin/`/`vs/`-scale build output belongs in either repository's
  history. If the eventual fix is "vendor `dosbox-src` directly into the
  outer repo" rather than "fix it as a real submodule," this size and its
  generated-artifact composition make that the wrong choice without first
  adding exclusions for build output.

### Recommended resolution path (not performed — audit only)

1. Decide the target shape: a **real git submodule** (likely a
   `pmanyeh`-owned fork of `joncampbell123/dosbox-x` with the bridge
   changes actually committed and pushed there, then registered via `git
   submodule add` + `.gitmodules` in the outer repo pinned to that fork's
   commit) is the natural fit given the upstream-diff shape of the
   changes, versus vendoring `dosbox-src`'s source (excluding `bin/`/build
   output) directly into this repository.
2. Whichever shape is chosen, the six modified files and two new files
   listed in §4b must be committed *somewhere reachable from a remote*
   before this repository is published, or the published project will not
   build/run for anyone who clones it.
3. Only then does adding `origin` and pushing become safe from a
   completeness standpoint.

## 5. Other publication-readiness observations (non-blocking, worth noting)

* **No `LICENSE` file** — relevant before making a repository public,
  independent of the `dosbox-src` issue.
* **`.claude/scheduled_tasks.lock` is tracked** (committed in the initial
  commit) — contents are a session id/PID/timestamp, not a credential, but
  it's local tool state that doesn't belong in project history and isn't
  excluded by the current `.gitignore` (which covers `.venv/`,
  `__pycache__/`, IDE folders, and OS files, but not `.claude/`).
* The Phase 5C files committed in `8357b43` were independently
  credential/absolute-path/secret-swept before that commit (see the prior
  turn's pre-commit audit); nothing new found in this pass.

## 6. Summary

| Question | Answer |
|---|---|
| Remote empty? | **Yes** — `git ls-remote` returns zero refs |
| Visibility? | **Undeterminable** with currently installed tooling (`gh` absent); a successful anonymous-looking `ls-remote` is not conclusive because Git Credential Manager is configured and may have supplied stored credentials silently |
| Local `origin` configured? | **No** — no remote of any name is configured; `main` has no upstream |
| Publication blocker? | **Yes — critical.** `dosbox-src` is a dangling, unregistered gitlink, and the entire native AI bridge (`debug_ai.cpp`/`.h` + 6 modified upstream files) is uncommitted anywhere reachable from a remote. Publishing now would produce a repository that cannot build or run for anyone else. |
| Exact next safe step | Resolve `dosbox-src` per §4's recommended path (commit the bridge changes to a reachable remote — most naturally a submodule-able fork — and register `.gitmodules` correctly, or vendor the source with build output excluded) **before** adding `origin` or pushing. Confirming the destination repo's visibility (via `gh auth login` + `gh repo view`, or the user confirming directly) is a secondary, non-blocking item that can happen in parallel. |

## 7. Resolution update (post-audit)

Everything above this section is preserved as originally written — a
point-in-time audit. This section records what was actually done afterward,
once the user reviewed and authorized each step.

### 7a. `dosbox-src` blocker — resolved

The native AI bridge (`debug_ai.cpp`/`.h` plus the six modified upstream
files listed in §4b) was committed to a dedicated `ai-mcp-bridge` branch on
the user's own fork, `https://github.com/pmanyeh/dosbox-x`, as commit
`5fcf624b787e1017273b313de6f9a70f12422102`, and pushed there. The
superproject's `.gitmodules` was added, pointing `dosbox-src` at that fork
and URL, and the gitlink was updated to the same commit. Both the push and
the repaired submodule registration were independently verified, including
resolving correctly from a genuinely disposable fresh clone (never the real
working directory) with `git submodule update --init`. This is no longer a
publication blocker.

### 7b. Absolute local development path in history — reviewed and accepted

A later, corrected scan (the repository's Git-Bash `grep` does not reliably
match literal backslash patterns such as `D:\git`; the working scan had to
be written as a Python script instead) found the local absolute path
`D:\git\DOSBox-X-AI` in `ai/Phase3.md` and `ai/TASK.md` (then at `HEAD`) and,
historically, in `ai/AGENTS.md`'s content going back to the initial commit.
The user reviewed this finding and made an explicit decision, recorded here
verbatim per that decision:

> Historical commits contain a non-sensitive former local development path.
> It was removed from the current tree without rewriting history.

Concretely: the path is a personal development directory name, not a
credential, token, or private data. Git history was **not** rewritten (no
`filter-repo`, `filter-branch`, squash, or force-push of rewritten commits).
Instead, the current-`HEAD` versions of `ai/TASK.md` and `ai/Phase3.md` were
edited to replace the path with `<repository-root>` (commit `ff3912c`).
Separately, the pre-existing deletion of `ai/AGENTS.md` was committed
together with a new `ai/Phase1.md` — the same content, archived under this
project's Phase-numbered file convention, with the same path substitution
applied (commit `bb4a6ae`; Git auto-detected this as a 99%-similarity
rename purely as an informational diff artifact of ordinary `git add` +
`git rm`, not forced via `git mv`). The path remains visible to anyone who
inspects earlier commits or blame history; that is the accepted, intended
outcome.

### 7c. License — intentionally left unresolved

Per explicit instruction, no `LICENSE` file was added. `dosbox-src` retains
upstream DOSBox-X's GPL-2.0 licensing unchanged. This repository's own
original code (the Python MCP server and test/acceptance infrastructure)
has no selected license yet; `README.md`'s "License and affiliation"
section states this explicitly rather than leaving it to be inferred.
Publication at this stage is for private, cross-machine use.

# work-skills-guard — keep shared skills actually shared

`hermes-skills/README.md` documents the sync rules; this folder enforces them. One
dependency-free Python script (`work_skills_guard.py`, stdlib only — it runs on every
host's stock python3), two git hook wrappers in the repo's `hooks/` dir, and tests.

Kill-switch and path overrides: `WORK_REPO` / `WORK_GUARD_OFF` /
`WORK_GUARD_LOG`; log and state live under `~/.hermes/.../work-guard`. Stdlib only,
fails open, never destructive.

## Before first use (one-time)

Edit the constants at the top of `work_skills_guard.py`:

| Constant | Set to |
|---|---|
| `REPO_DEFAULT` | canonical clone path (default `~/Git/work/workLab` — keep if you use it) |
| `REMOTE_DEFAULT` | the **private** GitHub URL of this repo (currently the `SET-ME` placeholder) |
| `ID_NAME` / `ID_EMAIL` | the work commit identity (currently `work-agent@users.noreply.github.com` placeholder — never a personal email) |

## What runs where

| When | What |
|---|---|
| every `git commit` / `git push` (any tool, any user in the clone) | `hooks/pre-commit` + `hooks/pre-push` scan added lines for secret-shaped text; tier-1 = blocked, tier-2 = reported |
| first turn of every Hermes session | `hooks.pre_llm_call` → `--hook pre-llm`: `pull --ff-only` when the clone is clean; otherwise injects ONE compact nudge (deduped per session) listing what needs attention |
| after every successful `skill_manage` | `hooks.post_tool_call` (matcher `^skill_manage$`) → `--hook post-tool`: scan + commit + push the change under the repo identity, so "an agent edited a skill" implies "all agents have it" |
| on demand | `check` (same report as the nudge), `doctor` (report + wiring), `commit-skills`, `push`, `scan-tree`, `scan-text` |

`check` detects: uncommitted/untracked `hermes-skills/`, dirty `docs/`+`files/`,
unpushed commits, clone behind origin, unfinished merge/rebase, secrets sitting in the
dirty worktree, wrong repo git identity, local skill copies shadowing shared ones,
README index drift, and missing wiring.

## Design rules (do not break these)

- **Fail open.** Any crash in a hook path exits 0. A broken guard must never wedge a
  commit, a push, or someone's whole session.
- **Never destructive.** No force-push, no `reset --hard`, no deleting user files. It
  only ever stages `hermes-skills/`, commits, `pull --ff-only`/`pull --rebase`
  (aborted again on conflict), and `git push`. A refused commit unstages and leaves
  every file on disk.
- **Silent when happy.** The pre-LLM hook prints only on the first turn and only when
  something is wrong; output becomes part of every future turn's context otherwise.
- **Bypassable on purpose.** `git --no-verify`, `WORK_GUARD_OFF=1`, or
  `... uninstall`. A guard people route around is worse than none — that is why the
  scanner has false-positive gates (env lookups, placeholders, non-Luhn digit runs) and
  a `guard:allow` end-of-line escape hatch.
- Repo-local git identity only; global config is never touched.

## Setup on a new Hermes host

```bash
python3 ~/Git/work/workLab/files/hermes-skills-git/work_skills_guard.py install --no-clone
python3 ~/Git/work/workLab/files/hermes-skills-git/work_skills_guard.py doctor
```

(Drop `--no-clone` only after `REMOTE_DEFAULT` is set — then `install` clones it itself.)
`install` is idempotent: wires `core.hooksPath=hooks`, sets the repo identity, registers
the two Hermes hooks via `hermes config set --force hooks …` (merging from the current
section, keeping foreign entries), and records first-fire consent in
`~/.hermes/shell-hooks-allowlist.json`. Hooks and the skill index are read at session
start — start a new session afterwards. Log: `~/.hermes/logs/work-guard.log`.

## Tests

```bash
python3 files/hermes-skills-git/test_guard.py
```

Throwaway clones + local bare remotes + a fake `$HOME`; never touches the real repo,
GitHub, or real skills. Covers: scanner positives/negatives/self-cleanliness, refuse vs
commit vs push, raw-hook blocking, `--no-verify` escape, nudge once-per-session,
auto-commit after `skill_manage`, and every `check` detection. Must stay green when the
guard is edited.

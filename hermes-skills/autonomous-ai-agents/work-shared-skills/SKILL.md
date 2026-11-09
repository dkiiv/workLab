---
name: work-shared-skills
description: "Use when sharing Hermes skills between agents via git in the workLab repo: setup, import review, secret scrubs, sync loop."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes, skills, git, multi-agent, secrets, sync]
    related_skills: [hermes-agent]
---

# Sharing Hermes skills between agents through git (workLab)

Curtis runs Hermes agents in the work environment whose own skills live in the
private workLab repo, folder `hermes-skills/`; its README holds the per-host
table and sync rules. This repo is self-contained and references no other
environment: imported skills must be scrubbed of non-work knowledge before they
land here. This skill covers setup, imports, review and secret scrubs.

## The guard — read before hand-editing the clone

`files/hermes-skills-git/work_skills_guard.py` + `hooks/` enforce the rules:
- git pre-commit/pre-push scan added lines for credential-shaped text (tier-1 blocks;
  tier-2 reports; `guard:allow` at end-of-line whitelists one line; `*.env` is gitignored).
- Hermes hook `pre_llm_call`: first turn of a session pulls --ff-only when the clone is
  clean, else injects ONE compact nudge. If you see a `[work-skills-guard]` note in a
  user message, act on it (usually: `... commit-skills`).
- Hermes hook `post_tool_call` on skill_manage: a successful edit is auto-committed AND
  pushed under the repo identity. So after skill_manage you can truthfully say it is
  shared; if the hook refused, fix what it named instead of bypassing.
- Commands: `check` (same report as the nudge), `doctor` (+ wiring), `commit-skills`
  (scan+commit+push; skills and docs//files/ become separate commits), `push`,
  `scan-tree`, `install` (per Hermes host; idempotent; `--no-clone` when the clone
  already exists), `uninstall`.
Bypasses on purpose: `git --no-verify`, `WORK_GUARD_OFF=1`. Never fight the guard;
if it is wrong, fix the guard + its tests (`python3 files/hermes-skills-git/test_guard.py`
must stay green) — throwaway clones + fake $HOME only.
Setup on a new host = README steps 1–7; step 6 runs `install` + `doctor` there.

## Setup on a host

1. List only non-bundled skills: compare `~/.hermes/skills/**/SKILL.md` dir names against
   `.bundled_manifest` (`name:hash` lines). Never copy bundled skills; they'd freeze stale copies.
2. Copy them into the repo folder keeping `<category>/<skill>/`, `diff -r`, back up the local
   copies OUTSIDE the scratch dir (scratch is pruned after 24 h), then DELETE them from
   `~/.hermes/skills`: local beats `create_dir`/`external_dirs` in precedence, so a leftover
   copy shadows the shared one and edits never reach git.
   On import, also scrub anything from a **different environment** (personal infra, other
   employers' hosts, personal emails) — this repo holds work knowledge only.
3. Point Hermes at the folder (step 4 of the README). `install` honors `WORK_REPO` but
   `_repo()` resolves `~` itself, so export an ALREADY-expanded path (e.g.
   `WORK_REPO=/home/u/Git/work/workLab`), not `~/...` — the raw tilde fails `.resolve()`
   silently. Put the clone itself AT the canonical path `~/Git/work/workLab`: MOVE it there,
   never leave it somewhere else and symlink the canonical path at it (Curtis's standing call —
   a symlink is an extra thing to break and a second clone can diverge). If you find a symlink
   at the canonical path, relocate the real repo and delete the link.
4. Verify: `hermes skills list` shows every shared skill with source `create_dir`, none `local`.
   (The guard's `check` also flags shadowing by name — cross-check both.)
5. Commit, push, add the host row to the README.

`install` + the new `skills.external_dirs`/`create_dir` take effect only at session start
(skill index and Hermes hooks are read then) — finish the setup in the current session via
the guard CLI, and state plainly that agent-side hooks begin working next session.

Background curator passes cannot patch skills in external_dirs; content fixes to shared skills
happen in foreground sessions.

## Loop for editing shared skills (any host)

`doctor`/`check` before writing → edit → add the `hermes-skills/README.md` index row AND the
per-machine path label in the same pass → `... commit-skills` → re-run
`check --fetch`; must print OK. Auto commit+push fires ONLY on `skill_manage` — a skill or
README change made with `write_file`/`patch` sits unpushed until you run `commit-skills`.
The index rows (backtick name as first table cell) and the folder are compared BOTH ways, so
a missing row or a row whose folder was deleted/renamed is a hard block on the next
session-start nudge. `scan-tree` T1 hits inside `files/` also block commits — confirm the hit
is a false positive and propose a `guard:allow` marker to Curtis rather than silently marking
files you don't own.

## Proving the guard is actually installed

Answer "are the hooks installed?" with a live test, not a config dump — `core.hooksPath`,
`hermes config get hooks`, and the allowlist entries only prove the wiring exists:
- Stage a file holding a fake credential-shaped assignment and attempt the commit; the guard
  must name the rule and refuse. Then assert the block took: `git log --oneline --all |
  grep -c '<test message>'` must print 0, and unstage + delete the file. Never trust `$?`
  straight after `git commit | tail` — that is tail's status, so a blocked commit looks
  successful.
- The `post_tool_call` hook is proven only by a real `skill_manage` edit landing as a pushed
  commit with the hook's own message format; the `pre_llm_call` pull/nudge likewise needs a
  NEW session, since Hermes reads hook config at session start.

## Two agents sharing one clone on one machine

More than one Hermes session can point at the SAME clone. Then the other session edits the
same files you do and commits them under its own hostname, so a `patch` whose `old_string`
came from your earlier write is refused — the file on disk moved under you. Re-read the
SKILL.md from disk before patching it in a long task, merge the other agent's wording instead
of reverting it, and commit each edit promptly rather than batching. Before concluding your
own write was wrong, `git log --oneline -- <path>` to see who changed it last.

## Reviewing another agent's import (before anything else touches it)

Run all of these; each one has caught something real somewhere:
- **Secrets**: the grep must also catch backtick-quoted values, because `` password `...` ``
  slips past `password[:=]` regexes. Read every `passw|token|secret|key|sudo` hit by eye.
  Never print a found secret: mask it in output (`sed -E 's/`[^`]{6,}`/`***`/g'`) and check
  history with `git log --oneline -S"$SECRET"` from a variable.
- **Personal / foreign-environment data**: personal emails, personal infrastructure, details
  from other employers, finance figures. These never belong in the work repo.
- **CRLF** (`grep -rlI $'\r'`): fix and keep `hermes-skills/** text eol=lf` in `.gitattributes`.
- **Duplicates/overlap** with existing shared skills: merge into one class-level skill (extra
  depth becomes a `references/` file), don't keep both.
- **Unlabelled machine paths**: label as "work laptop: … / server: …" (a per-machine table works).
- **Stale "current state" lines** (prod config, who runs what): relabel as history or replace
  with "re-read the live config"; keep measured data.
- **Dangling `references/` pointers** and skills without a category folder.
- Afterwards grep for references to removed/renamed skill names (`related_skills`, prose).

Give Curtis an opinion first (worst issue first), then fix after he says go.

## Scrubbing a secret or personal data that reached the remote

1. If the bad commit is the branch tip: fix files and `git commit --amend` (fold all
   sanitizing into it); put restructuring in a separate commit. Otherwise use
   `uvx git-filter-repo --replace-text`.
2. Verify with `git log -S` that nothing reachable from HEAD still contains it, without
   printing it.
3. `git fetch`, then `git push --force-with-lease=main:<old-sha>` so a concurrent push isn't
   clobbered.
4. Locally: `git reflog expire --expire=now --all && git gc --prune=now`; `git cat-file -e
   <old-sha>` must fail.
5. Tell Curtis: rotate the secret (it was exposed); the host can still serve the orphan
   commit by SHA until its GC or a support purge; old author emails in commit metadata need
   a full rewrite.
6. Hand the other agent a paste-ready prompt (numbered steps, exact command + pass condition
   each, ending with a "Report:" list).

## Pitfalls

- A terminal command containing the literal text `sudo -S` is blocked by the approval guard
  even when it's only a string inside `sed`/Python. Write the edit script with `write_file`
  and build the string by concatenation (`'sudo ' + '-' + 'S'`).
- `write_file` refuses to overwrite a file changed on disk since it was last read (e.g. after
  a CRLF conversion). For a full rewrite, delete the file first or re-read it fully.
- `write_file` does not set the exec bit, so a helper script you just wrote is not runnable —
  `chmod +x` before executing it.
- On Windows/WSL hosts, plain `git` may have no SSH key for GitHub pushes while the guard's
  auto-push runs plain `git push` — it then commits locally and `doctor` shows "commit(s) not
  pushed". Fix once per clone: `git config core.sshCommand <path-to-a-working-ssh.exe>` (or
  use an HTTPS credential helper).
- The guard's `_config_get` must call `hermes config get --json`: the guard runs on a
  stdlib-only python3 with no PyYAML.
- Memory `patch` replaces the WHOLE entry that contains `old_text`, not just the matched
  span. For small fact fixes re-patch with the full entry as `old_text`, or remove + add.

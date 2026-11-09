# hermes-skills — shared Hermes Agent skills (work environment)

Skills written by our own Hermes agents (not the bundled ones that ship with
Hermes). Every Hermes install that points at this folder sees the same skills.
When one agent patches or creates a skill, the change lands here, and the other
agents get it after a `git pull`.

This repo is the **work** counterpart of that pattern and is fully independent
of any other repo or environment: no skill, path, hostname or account from
elsewhere may be referenced here.

| Skill | Category | What it covers |
|---|---|---|
| `work-shared-skills` | autonomous-ai-agents | this folder itself: setup on a new host, import review, secret scrubs, sync loop |

Seed skill(s) above; add a row with every new skill (the guard's `check` blocks
a skill folder that has no index row, and an index row with no folder).

Fill the environment out as you work: when an agent learns anything durable
about a work system, it becomes a skill (procedure) or a `docs/` file
(facts/runbooks) — never just chat history.

Deliberately **never** in this repo: anything personal, any personal-infrastructure
knowledge, credentials, or data from work sources that a company policy says may
not be stored in git. When in doubt, ask Curtis before committing.

Layout is the normal Hermes skills layout: `<category>/<skill>/SKILL.md` plus
optional `references/ scripts/ templates/ assets/`.

## How Hermes uses this folder

Two config keys (Hermes ≥ 2026.9):

| Key | Effect |
|---|---|
| `skills.external_dirs: [<this folder>]` | skills here are indexed and loaded like local ones; `skill_manage patch` edits them **in place here** |
| `skills.create_dir: <this folder>` | new skills the agent creates are written **here** instead of `~/.hermes/skills/` |

Precedence when the same skill name exists twice:
`project → local (~/.hermes/skills/) → skills.create_dir → external_dirs`.
A copy left in `~/.hermes/skills/` **shadows** the shared one, and edits then go to the
local copy and never reach git. Shared skills must exist **only** here.

## Setting up another Hermes agent (paste this to the agent)

> Configure yourself to use the shared skills in Curtis's private repo **workLab**,
> folder `hermes-skills/`, cloned to `~/Git/work/workLab`. Follow
> `hermes-skills/README.md` in that repo, section "Setting up another Hermes
> agent", steps 1–7. Report the output of step 5 and of the `doctor` command in
> step 6.

Steps for the agent:

1. **Clone the repo** (skip if already cloned; then just `git pull --ff-only`):
   ```bash
   mkdir -p ~/Git/work && cd ~/Git/work
   git clone <workLab remote URL — ask Curtis / see repo README "Getting started"> workLab
   ```
   The repo is private. If the clone fails with an auth error, **stop and ask
   Curtis** for GitHub access on this machine (a deploy key with write access is
   the simplest). Never paste keys or tokens into chat or into this repo.

2. **Find your own custom skills** (the ones not bundled with Hermes):
   ```bash
   cd "${HERMES_HOME:-$HOME/.hermes}/skills"
   python3 - <<'EOF'
   import re, pathlib
   m = open('.bundled_manifest').read()
   bundled = set(re.findall(r'^([\w.-]+):', m, re.M))
   for p in sorted(pathlib.Path('.').glob('**/SKILL.md')):
       if p.parts[0].startswith('.'): continue
       if p.parent.name not in bundled: print(p.parent)
   EOF
   ```
   For each one:
   - **not in this folder:** copy it in (`cp -a <cat>/<skill> ~/Git/work/workLab/hermes-skills/<cat>/`)
     after checking it holds no passwords, tokens, keys or PINs — and no knowledge
     from other environments (it belongs there, not here).
   - **already here with the same name:** diff the two. Merge anything new from your
     copy into the shared one. If unsure, ask Curtis.

3. **Back up and remove the local copies** of every skill that now lives here
   (otherwise they shadow the shared ones, see precedence above):
   ```bash
   B="${HERMES_HOME:-$HOME/.hermes}/skills-backup-$(date +%Y%m%d)"; mkdir -p "$B"
   # for each shared skill that also exists locally:
   cp -a "${HERMES_HOME:-$HOME/.hermes}/skills/<cat>/<skill>" "$B/" && rm -rf "${HERMES_HOME:-$HOME/.hermes}/skills/<cat>/<skill>"
   ```
   Do **not** touch bundled skills; Hermes manages and updates those itself.

4. **Point Hermes at the folder** (use `hermes config set`, never hand-edit config.yaml):
   ```bash
   hermes config set skills.external_dirs '["~/Git/work/workLab/hermes-skills"]'
   hermes config set skills.create_dir '~/Git/work/workLab/hermes-skills'
   ```
   If the clone is not at `~/Git/work/workLab`, use its real path in both.
   With profiles, run this inside the profile you want to share (each profile has its own config).

5. **Verify:** every shared skill must show source `create_dir` (or `external`), none `local`:
   ```bash
   hermes skills list | grep -E 'work-shared-skills'
   ```
   Then start a new session (the skill index is built at session start).

6. **Install the guard** (enforces everything below; see `files/hermes-skills-git/`):
   ```bash
   python3 ~/Git/work/workLab/files/hermes-skills-git/work_skills_guard.py install --no-clone
   python3 ~/Git/work/workLab/files/hermes-skills-git/work_skills_guard.py doctor
   ```
   (`--no-clone` because step 1 already cloned; plain `install` would clone from the
   remote configured in the script — set that first, see repo README "Getting started".)
   `install` is idempotent. It wires the repo's git hooks (`core.hooksPath=hooks`:
   secret scan on every commit/push), fixes the repo git identity, and registers two
   Hermes shell hooks: `pre_llm_call` (first turn of each session: `pull --ff-only`
   when the clone is clean, one compact nudge when anything needs attention) and
   `post_tool_call` on `skill_manage` (a successful skill edit is auto-committed
   **and pushed**, so shared knowledge can't stall in one clone). It also appends its
   consent entries to `~/.hermes/shell-hooks-allowlist.json`. Unwire with
   `... uninstall`. Kill switch per call: `WORK_GUARD_OFF=1`.

7. **Commit and push** anything you added in step 2:
   ```bash
   cd ~/Git/work/workLab
   python3 files/hermes-skills-git/work_skills_guard.py commit-skills
   ```
   (or plain `git add hermes-skills && git commit && git push` — the hooks scan it).

## Keeping agents in sync (rules for every agent)

The guard enforces what it can; the rules still bind when it is off. `check` prints the
same report the session nudge uses.

- **Before editing or creating a skill:** `git -C ~/Git/work/workLab pull --ff-only`
  (the session-start hook does this automatically when the clone is clean).
- **After a skill change:** commit only `hermes-skills/` paths with a message naming the
  skill, then push (`... commit-skills` does both). Small commits keep conflicts rare.
  The `skill_manage` post-tool hook auto-commits+pushes; if it refused, fix what it
  named rather than bypassing.
- **Conflict:** never force-push and never discard the other agent's change (only
  exception: Curtis-approved history scrubs of secrets, announced to every agent). Merge
  both edits by hand; if the intent conflicts, ask Curtis.
- **No secrets, ever** — skills are plain text in git. Refer to the file path that holds a
  secret instead (e.g. `/etc/app/app.env`). The pre-commit/pre-push hooks scan added
  lines and block credential-shaped strings (`guard:allow` at end-of-line whitelists one
  line that must *show* a secret shape; tier-2 findings like personal emails are reported,
  not blocked). `*.env` is gitignored — if a template must be shared, name it `*.env.example`.
- **No personal data**: no personal email, no personal-environment details, nothing
  work-confidential that policy says may not live in git. The guard forces the *repo* git
  identity to the configured noreply address. Use placeholders in examples.
- **No local copies of shared skills**: `~/.hermes/skills/` beats this folder in
  precedence; `check` flags any name that exists in both.
- **Label machine-specific paths** ("work laptop: …, build server: …") — every agent reads
  every skill.
- **Merge, don't duplicate**: before creating a skill, `hermes skills list` / search this
  folder; extend the existing skill (or add a `references/` file to it) when the topic
  overlaps.
- **LF line endings** only; no generated files (`__pycache__`, `.pyc`) — a CRLF `.pyc`
  once made every fresh clone look dirty.
- **Machine-specific skills** are fine here: each skill's description says when it applies,
  so an agent that never touches a given system simply never loads that skill. Keep a skill
  local only if it must not be seen by other agents.
- Memory (`MEMORY.md`, `USER.md`) and sessions are **not** shared — only skills.

## Hosts currently using this folder

| Host | Hermes home | Clone path | Since |
|---|---|---|---|
| _(first work host — add a row when set up)_ | | | |

Add a row when another agent is set up.

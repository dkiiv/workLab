# workLab

Git-backed external memory for the Hermes agent(s) in Curtis's **work** environment:
markdown documentation + the Hermes skills agents share, kept in sync through git.
This repo is **self-contained**: it holds work knowledge only and references no
other environment or repo. Keep it that way: this repo may end up on managed
machines; keep it free of non-work details.

Useful website: https://markdownviewer.org/

## Layout

- `README.md` — this file (index)
- `docs/` — markdown documentation (runbooks, inventories, decisions) — start with `docs/README.md`
- `files/` — scripts, tools, and their config (one subfolder per tool)
- `hermes-skills/` — skills shared by all Hermes agents here; its README has the
  self-setup steps to give a new agent and the git sync rules
- `hooks/` — git hooks wired by the guard (`core.hooksPath=hooks`)

## The idea in one paragraph

A Hermes agent's memory dies with its session, and its skills die with its
`~/.hermes` home. This repo fixes that: skills live *in git* (via Hermes
`skills.external_dirs` + `skills.create_dir`), operational knowledge lives in
`docs/`, and the working scripts live in `files/`. Any agent on any machine
clones this repo, reads and edits the same skill tree, and the guard in
`files/hermes-skills-git/` makes edits commit + push automatically and blocks
commits containing secret-shaped text. A fresh agent becomes productive by
reading the repo, not by being re-taught.

## Getting started (human)

This clone's remote is the **staging** repo `dkiiv/workLab`. Plan: clone it on the
work machine, push it to the work private repo, then:
1. Point `origin` there (`git remote set-url origin <work-remote>`) and update
   `REMOTE_DEFAULT` in `files/hermes-skills-git/work_skills_guard.py`.
2. Set `ID_NAME`/`ID_EMAIL` to the work commit identity if different — never a
   personal email.
3. Delete/lock the staging repo once the work copy is live, so only one canonical
   remote exists.

## Docs

- [docs/README.md](docs/README.md) — how to write docs here (naming, index rule, secrets policy)
- [docs/work-environment-inventory.md](docs/work-environment-inventory.md) — TEMPLATE: the IP/host/service map; fill it in as the first real doc
- [docs/runbook-template.md](docs/runbook-template.md) — TEMPLATE: incident/runbook doc shape (what broke → what to do → hardening)

## Tools (files/)

- [files/hermes-skills-git/](files/hermes-skills-git/README.md) — **enforcement layer for shared skills** (`work_skills_guard.py` + git hooks in `hooks/`): secret scan on every commit/push, auto commit+push after `skill_manage`, session-start pull/nudge; `install` per Hermes host, `doctor` to verify, `check` on demand

## Shared Hermes skills (hermes-skills/)

- [hermes-skills](hermes-skills/README.md) — skills shared by all agents here (`skills.external_dirs` + `skills.create_dir` point here). Its README has the self-setup steps and the sync rules.

## Deliberate differences from a prose-only notes repo

- Skills are **live config**, not notes: Hermes indexes them every session.
- `docs/` is written for an agent with **zero prior context** — if it isn't in the
  repo, the agent doesn't know it (memory files and sessions are never shared).
- Secrets: only PATHS to secret files are ever written down, never values.
  `*.env` is gitignored; the guard blocks credential-shaped strings pre-commit.

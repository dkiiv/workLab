# Writing docs here

`docs/` is operational knowledge written for a reader with **zero prior context**:
a fresh Hermes agent (or a new colleague) who has never seen this environment.
If it isn't written down, it doesn't exist.

## Rules

1. **One doc per system / procedure / incident.** Name it after the subject,
   kebab-case: `vpn-access-setup.md`, `runbook-*.md`, `*-inventory.md`.
2. **Index it.** Every doc gets a one-line entry in the root `README.md` →
   "Docs" section, with the bolded gist up front (what it is + the date that
   matters). An unindexed doc is invisible to the agents.
3. **Date state claims.** "Last updated", "current gateway", "retired 2026-11-xx".
   Stale docs are worse than none — mark retired docs with ⚠️ and keep them as
   rollback history.
4. **Secrets: paths, never values.** Write `/etc/app/app.env`, never its contents.
   `*.env` is gitignored; templates ship as `*.env.example`. The pre-commit guard
   blocks credential-shaped strings (`guard:allow` at end-of-line whitelists a
   line that must *show* a secret shape).
5. **No personal data.** No work-account personal emails in examples, no payroll
   or HR details, no real account numbers. Placeholders instead.
6. **Scripts referenced from docs live in `files/<tool>/`** — the doc explains
   why/when, the folder holds the how (systemd units, installers, configs).

## Doc shapes that work

- **Inventory** — table of host → IP → role → owning doc. The agent's map of the world.
- **Runbook** — symptom → diagnosis steps → fix → verification → hardening.
  Write it *during* the incident, polish it after.
- **Decision record** — context → options → what we chose → why → revisit date.

See `runbook-template.md` and `work-environment-inventory.md` to start.

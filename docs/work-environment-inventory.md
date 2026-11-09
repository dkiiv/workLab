# Work Environment Inventory (TEMPLATE — fill in)

**IP / host → name → role map for the work environment.** Quick reference for
everything the agent touches, with the doc where each thing's full story lives.

**Last updated:** YYYY-MM-DD

> Delete this block when the first real data lands. Keep the "Last updated"
> line honest — it is the only timestamp agents trust.

## Topology

```text
(corporate network)
 │
 ├── host-name        10.0.0.x   role, owner, OS          → docs/that-host.md
 ├── vm / lxc / wsl   ...
 └── cloud            account/region — what lives there, access path
```

## Hosts

| Host | Address | Role | Key services | Owning doc |
|---|---|---|---|---|
| SET-ME | — | — | — | — |

## Accounts & access paths

How the agent authenticates where it's allowed to (tool names, env var NAMES —
never values, never personal MFA/credentials):

| System | Access method | Notes |
|---|---|---|
| SET-ME | — | — |

## Endpoints / URLs

| URL / endpoint | What it fronts | Host | Auth |
|---|---|---|---|
| SET-ME | — | — | — |

## Standing schedules

Cron jobs, timers, sync jobs, CI pipelines that run without anyone:

| What | Where | When | Doc |
|---|---|---|---|
| SET-ME | — | — | — |

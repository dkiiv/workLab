# Runbook template

Copy to `runbook-<subject>.md`, delete this line. Write the skeleton *during*
the incident (timestamps + what you ran), polish after. Date every claim.

## Symptom / trigger

What was observed, when, and how it was noticed (alert, user report, agent check).

## Blast radius

What is down / degraded / at risk. Who is affected.

## Diagnosis (what to check, in order)

1. `command` — expected vs what you saw, and what each result means.
2. ...

## Fix

Exact commands, in order, with the verification step after each. Mark
anything destructive with ⚠️ and its rollback.

## Verification

How you know it is actually fixed (health check, user confirmation, metric).

## Root cause & hardening

- Root cause: ...
- Hardening applied / proposed (so this runbook shrinks next time): ...

## History

| Date | Event | Notes |
|---|---|---|
| YYYY-MM-DD | initial incident | link to this doc's first fill |

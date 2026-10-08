# Protocol: Correspondent ↔ Boss interaction

This directory holds the **interaction contract** between the External
Correspondence Agent ("the Correspondent") and the Boss — the rules
`mailroom-reloaded` implements in `comms/agent.py` (Correspondent),
`comms/desk.py` (Boss Desk), `comms/watcher.py` (watch loop) and
`comms/policy.py` (outbound policy).

## Files

- **`correspondent_boss_protocol.md`** — the full protocol: roles and
  responsibilities; the signal lifecycle (`pending → acked → actioned /
  dismissed / expired`); numbered interaction sequences for standard
  triage, urgent complaints, payment-change attacks, prompt injection,
  legal notices, and extraction corrections; the delegation action
  reference (all 12 typed Boss Desk actions with trigger, autonomy
  default, reversibility, and audit event); simulated-time SLAs;
  escalation and overrides; out-of-scope routing; audit and
  observability; failure modes.
- **`delegation_matrix.csv`** — the routing table: 25 issue classes
  (status requests incl. frustrated variants, entity questions,
  extraction corrections, complaints, genuine vs attack payment changes,
  legal/privacy notices, bulk-disclosure refusals, phishing, prompt
  injection, impersonation, malicious attachments, conflicting
  instructions, retractions, plus out-of-scope rows for reprocessing
  requests, mailbox/ops faults, and cross-client questions). Columns:
  `issue_class, example, detected_by, owner, boss_action, autonomy,
  sla_sim_min, notes`.

## How it relates to the rest of the repo

- `CONTENT_SPEC.md` defines the *content* contract (formats, IDs,
  series). This directory defines the *behavioral* contract the content
  exercises.
- Every scenario's `expect.boss_actions` field (see
  `schemas/scenario.v2.json`) is an executable assertion of
  `correspondent_boss_protocol.md` §4: scenario authors encode the
  protocol's expected Boss behavior per scenario, and the sandbox
  scorecard checks it.
- `email/` holds the transport contracts (sender pool, overlay,
  AgentMail, Gmail sandbox, recipient policy) that the interaction
  sequences in §3 assume.
- `adversary/` holds the attack-side data (lookalikes, impostors) that
  the §3(c)/(d) sequences are written against; it is never compiled
  into the registry the Correspondent reads.

## Conventions

Fictional examples only; `*.sandbox.invalid` domains; `+1-555-01xx`
phones. No real brand names, no working URLs, no dataset text — these
files are covered by the content-CI leak scan (`python3
tools/validate.py`), so keep them clean.

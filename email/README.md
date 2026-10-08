# Email infrastructure (sandbox data and contracts)

This directory holds the **data and file contracts** for sandbox email
infrastructure — everything the `mailroom-reloaded` repository needs to
send and receive sandbox mail in the **egress profile**. It contains no
executable code: the persona-leg gateway lives in `mailroom-reloaded`
(`sandbox/gateway/`), and the Correspondent-leg adapters live in
`mailroom-reloaded` (`comms/channels/`). This repo supplies the
configuration those two codebases consume.

Spec basis: addendum v2 §7 (egress, AgentMail, Gmail), §6.7 (clock),
§11.4 (environment variables).

## File map

| File | What it is | Consumed by |
|---|---|---|
| `sender_pool.yaml` | AgentMail sender-pool definition: pool inboxes (stable `client_id`s), many-to-one persona→inbox mapping, idempotent create / down semantics. | Persona leg: `sandbox/gateway/` (agentmail sender) |
| `correspondent_inbox.yaml` | The dedicated Correspondent inbox (`client_id`, ingest order). | Correspondent leg: `comms/channels/agentmail.py` |
| `agentmail.yaml` | AgentMail config reference: auth, endpoints, webhooks/Svix, websocket, attachment fetch, plan limits. | Both legs (persona sends, Correspondent ingest) |
| `gmail_sandbox.yaml` | Dedicated sandbox Gmail mailbox: credential paths, scopes, send/push gates, refresh-token operational warning. | Correspondent leg: `comms/channels/gmail.py` (real-mail leg) |
| `recipient_policy.yaml` | Per-profile recipient rules (§7.3): what each profile may send to, and the fail-closed rule (S6). | Persona leg gateway; enforced again by the proxy |
| `overlay/contract.md` | The bidirectional identity-overlay file contract (§7.5): who writes it, who reads it, wire-visible fields only, sandbox-only enforcement. | Written by persona leg; read by `comms/channels/agentmail.py` |
| `overlay/example.jsonl` | Example overlay records (2 spec examples + pool-inbox route records). Valid against `schemas/overlay.v1.json`. | Persona leg (example output shape) |
| `egress_routes.md` | Reference copy of the §7.2 allowlist table with credential notes and the payload-guard rationale. | Reference only — see below |

## The two profiles

**closed** — no egress. Both legs use the `sim` transport. No external
network, no real mail. Required for CI (`sandbox-smoke`), deterministic
replay, and demos without keys. In this profile the files here are
*documentation only*; nothing is contacted.

**egress** — allowlisted proxy. Persona leg runs `sim` or `agentmail`;
Correspondent leg runs `sim`, `agentmail`, or `gmail`. All outside traffic
goes through one egress proxy enforcing a CONNECT-level host allowlist.
TLS payloads are **not** inspected at the proxy, which is why the payload
guard lives in the client (§6.5). Enabled with
`MAILROOM_SANDBOX_EGRESS=egress`; never touched by CI.

> **Authority note.** The ENFORCED allowlist lives in `mailroom-reloaded`
> at `sandbox/egress/allowlist.yaml` and is loaded by the proxy and the
> startup guards. `egress_routes.md` in this directory is a human-readable
> reference copy — if the two disagree, the allowlist file wins and the
> reference must be fixed to match.

## Ground rules (from spec §7.3 and D1–D5)

- **No secrets anywhere in this repo.** Only environment variable *names*
  and placeholder paths appear. Keys arrive by environment only, one
  role-scoped key per role.
- **Fictional domains only.** All synthetic addresses use
  `*.sandbox.invalid`; the allowlist grants are real vendor hosts (documented
  in `egress_routes.md`), never synthetic recipient addresses.
- **`[verify]` items** from §16 that touch email infra are marked inline in
  each file (e.g. AgentMail base URL, plan limits, OAuth refresh-token
  lifetime).
- Identity-dependent scenarios (E1, E2, E13, …) are valid on the
  `agentmail`/`sim` legs only; the Gmail leg runs its own conformance set
  (T-series), because on Gmail the From address and auth results are real.

# Egress routes — REFERENCE COPY (addendum v2 §7.2)
#
# > This file is the human-readable reference. The ENFORCED allowlist lives
# > in mailroom-reloaded at sandbox/egress/allowlist.yaml and is loaded by
# > the egress proxy and the startup guards. If the two disagree, the
# > allowlist file wins and this reference must be updated to match.
#
# Hostnames are written WITHOUT a URL scheme on purpose (plain host
# references; this is a data repo, not a link farm).
#
# Hugging Face is deliberately NOT on any allowlist: the content build
# fetches dataset documents once on a developer machine, never during a run.

| Route | Hosts (plain hostnames) | Used for | Credential | Notes |
|---|---|---|---|---|
| OpenRouter | openrouter.ai, path /api/v1 | Email generation (free pool, paid fallback); optionally the Correspondent's own LLM | Dedicated sandbox key (generator role) | Payload guard applies; limits in addendum §6.4 |
| AgentMail | AgentMail API host [verify] | Sender inboxes, Correspondent inbox, persona sends, ingestion | Dedicated sandbox key | Websocket-first ingestion needs no public URL (§7.5) |
| AgentMail | AgentMail websocket endpoint [verify] | Ingest trigger (default; outbound-only) | Same sandbox key | No tunnel, no reachable URL required |
| Gmail | gmail.googleapis.com | Real-mail leg on the dedicated sandbox mailbox | Sandbox OAuth client + token at sandbox-only paths | gmail.readonly by default; gmail.send only when MAILROOM_SANDBOX_GMAIL_SEND_ENABLED=1 |
| Gmail | oauth2.googleapis.com | OAuth token exchange/refresh | Same sandbox OAuth client | — |
| Gmail | accounts.google.com | OAuth consent (owner setup) | Same sandbox OAuth client | One-time setup, not per-run |
| Gmail | pubsub.googleapis.com | Push watch (users.watch) | Same | ONLY if push is used; off by default so this host stays off the allowlist |
| Anything else | none | — | — | Denied and logged (S5; hard failure if the host is a production host) |

## Per-route credential notes

- Every route has its OWN dedicated sandbox key; keys are **role-scoped**
  (generator key ≠ Correspondent LLM key ≠ AgentMail key ≠ Gmail OAuth).
- Keys are supplied by **environment only** — never files, never checked in.
- The startup guards refuse to start if: the production Gmail token or any
  production credential is reachable; a production key is configured for any
  sandbox role; the base directory is outside `sandbox/.state/`; or the
  overlay directory is set while `MAILROOM_ENV` is not `sandbox` (S8, §7.3).

## Payload-guard rationale

The proxy enforces the allowlist at CONNECT level: **TLS payloads are not
inspected**. That is why the payload guard lives in the *client* (§6.5):
every outbound generation prompt is checked against dataset text hashes
(n-gram fingerprints, not just whole-document hashes) and sensitive patterns
*before* it leaves — a block there means nothing leaves the machine, even
though the proxy itself would have let the host through. One egress proxy
per run; every service sits on an internal network and only the proxy
container reaches the outside.

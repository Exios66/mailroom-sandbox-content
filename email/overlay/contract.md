# Identity overlay file contract (addendum v2 §7.5, decision D3)

A hosted inbox cannot send from `tricounty-title.sandbox.invalid` or fail SPF
on demand — the transport is real, but sender identity and auth results are
**synthetic**, carried through a narrow file contract so `comms` never imports
`sandbox`. The contract is bidirectional:

- **Inbound:** the adapter replaces the normalized `from` and auth results
  with the message record, so the Correspondent sees the *claimed* identity
  the scenario requires.
- **Outbound (reply loop):** a draft to a *virtual* address is delivered to
  the mapped real sender inbox (route record). A virtual address with no
  route **fails closed** (S6).

## Format

JSONL records, one per line, at `overlay/overlay.jsonl` (written by the
sandbox gateway). Schema: `schemas/overlay.v1.json`
(title `mailroom.overlay/v1`).

Record kinds:

| kind | Purpose | Required fields |
|---|---|---|
| `message` | Synthetic identity for one delivered message | `v`, `kind`, `provider_message_id`, `from`, `auth` (+ optional `display`) |
| `route` | Virtual address → real pool-inbox routing | `v`, `kind`, `virtual`, `inbox` |

`auth` carries the claimed SPF/DKIM/DMARC results
(`pass`/`fail`/`none`/`softfail`/`temperror`/`permerror`).

## Wire-visible fields ONLY

Records carry exactly what the Correspondent could observe on the wire:
claimed sender, display name, auth results, provider message id, routing.
**No persona ids, scenario ids, or labels — ever.** The Correspondent must
not learn "this is the impostor". Schema validation does not enforce this
(it cannot — the fields just aren't there), so the gateway must not add any.

## Sandbox-only enforcement

The overlay directory is mounted **read-only** into the Correspondent
container and is honored by `comms/channels/agentmail.py` **only when
`MAILROOM_ENV=sandbox`**. In any other environment the adapter **refuses to
start** if the overlay setting is present (startup guard, §7.3). The overlay
applies to the `agentmail` and `sim` legs only — on the Gmail leg, auth is
genuine and identity-dependent scenarios are not run (§3.8).

Related env vars: `MAILROOM_COMMS_IDENTITY_OVERLAY_DIR` (sandbox only;
refused outside `MAILROOM_ENV=sandbox`), `MAILROOM_ENV=sandbox`.

## Attribution on a shared inbox

Several personas share one pool inbox (see `sender_pool.yaml`). The sandbox
attributes each persona's reaction by **thread id** (`In-Reply-To` /
`References`), which works correctly when many senders share an inbox.

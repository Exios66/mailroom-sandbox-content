# Metered operations: ingress, scheduled sending, and process topology

This document is the runtime companion to `correspondent_boss_protocol.md`.
The protocol defines *what the Correspondent and Boss may do*; this defines
*how fast work enters, how mail leaves, and where each piece runs* so the
sandbox behaves like a production-adjacent system instead of an unmetered
firehose.

Three contracts, one goal — **nothing in the sandbox runs unbounded**:

1. **Metered ingress** — `email/ingress_policy.yaml`
2. **Scheduled sending with doom-loop prevention** — `email/send_schedule.yaml`
3. **Separate-process topology** — defined below (§4)

---

## 1. Metered ingress

Documents, emails, and external correspondence arrive through three
admission-controlled edges (policy: `email/ingress_policy.yaml`):

| Edge | Sustained rate | Burst | Full queue |
|---|---|---|---|
| Documents → pipeline ingress | 30/min | 10 | shed to `comms/pending/` |
| Emails → persona gateway / injects | 60/min | 20 | shed to `comms/pending/` |
| External correspondence → Correspondent inbox | 40/min | 15 | shed to `comms/pending/` |

Shedding is never silent: the item moves to `comms/pending/` (soft hold)
with an `ingress.shed` audit event naming the edge, reason, and queue
depth. Queues resume admitting once depth stays below the warn line for
60 simulated seconds.

### The Correspondent inbox is human-paced

The inbox is the one edge with a *triage* capacity, not just a queue
capacity: **120 admissions/hour, 30 concurrent open threads**. A new
thread past 30 waits in `comms/pending/`; a thread waiting more than 4
simulated hours raises `inbox.starvation` to the Boss Desk. Safety-critical
items and legal notices bypass the FIFO wait — and **12 of the 120 hourly
admissions are reserved for them**, so ordinary traffic (capped at 108/hr)
can never starve a legal notice out of its signal/action SLA. If the
reserve itself is spent, a bounded audited escape hatch admits up to 5
more priority items/hour (`inbox.priority_over_cap`). Urgency never
becomes a metering loophole, and one noisy sender is throttled at
12 admissions/hour.

### Why token buckets, and why shared

Rate limiting is a token bucket **per source**, held in shared state —
not per-process memory — because the Correspondent runs as a separate
process (§4). Two processes metering independently would each admit a
full rate and double the load. Metering uses simulated time; real
transports still run at 1×.

---

## 2. Scheduled sending (free models, set schedule)

Outbound email while the sandbox or demo runs fires **only inside named
scheduler windows** (`email/send_schedule.yaml`):

- `correspondent_outbound` — every 20 min, ≤25 sends (replies, acks, status answers)
- `digest` — hourly, ≤5 sends (low-priority rollups)
- `smoke` — every 5 min, ≤3 sends (S-series self-test traffic, flag-gated)

Global cap: **90 sends/hour** across all windows. Sends come from **free
tier models only** (`gen/pool.yaml#free_pool`); the paid tier is forbidden
for scheduled sends. The scheduler refuses to run in the production
profile, and production outbound stays draft → human approval → send per
the main protocol.

### Misfire prevention

- The scheduler is **off by default** (`MAILROOM_SCHEDULER_ENABLED` set by sandbox up).
- Every window runs pre-checks: kill switch clear, circuit closed, outbox below max depth.
- Sandbox default is **dry-run** (`MAILROOM_SEND_DRY_RUN=1`): render + log, don't transmit.
- A send may never enqueue another send by itself; follow-ups require a new signal through the Boss Desk. The scheduler ignores its own outbox events.

---

## 3. Doom-loop prevention

A "doom loop" is a runaway sender: an agent replying to replies, retrying
failures, or re-firing scheduled work until it melts the outbox, the
model budget, or someone's inbox. Five independent guards make it
structurally impossible; any one of them stops the loop alone:

1. **Kill switch** — `MAILROOM_SEND_KILL_SWITCH=1` or the presence of
   `comms/KILL_SWITCH` halts all scheduled sends within one window and
   freezes the outbox. The flag file is never committed.
2. **Circuit breaker** — 5 consecutive send failures, or volume at 3× the
   trailing baseline, opens the circuit: the scheduler stops, emits
   `ops.circuit_open`, and requires a **human** reset. It never restarts itself.
3. **Idempotency** — every send carries `sha256(outbound_message_id +
   content_hash)`, where the outbound message ID is the stable identity
   assigned at draft approval. Retries of the same approved draft reuse
   the ID (true replays are dropped and audited); a genuinely new reply —
   even with identical text — gets a new ID and is never conflated with
   an earlier send. Replays inside 24h are dropped (`send.duplicate_dropped`).
4. **Reply-depth cap** — 6 replies per thread; the 7th needs Boss Desk
   approval. Auto-replies and bounces never get answers (log only).
5. **No self-triggering** — sends can't enqueue sends; the scheduler can't
   hear its own outbox.

---

## 4. Process topology: the Correspondent is a separate process

The External Correspondence Agent runs as **its own OS process**,
independent of the document pipeline process. They are deployed, started,
stopped, scaled, and restarted separately, and they interact only through
a narrow, versioned IPC surface:

```
┌─────────────────────┐        events / API        ┌──────────────────────┐
│  Correspondent       │ ◄────────────────────────► │  Document pipeline   │
│  process             │   signals, outbox queue,   │  process             │
│  comms/agent.py      │   shared token buckets,   │  pipeline/*          │
│  comms/desk.py       │   audit log               │                      │
│  comms/watcher.py    │                           │                      │
└─────────────────────┘                             └──────────────────────┘
```

**Interaction rules:**

- The Correspondent never moves pipeline files, edits manifests, or runs
  pipeline nodes (protocol §2) — it reads pipeline *state* through the
  event/API surface and acts only on correspondence.
- The pipeline never sends email directly; all outbound correspondence
  goes through the Correspondent's outbox and scheduler.
- Shared state (token buckets, outbox queue, idempotency keys, circuit
  breaker) lives outside either process so both see one consistent view.
- **Failure isolation:** a Correspondent crash never blocks the document
  pipeline — in-flight signals sit safely in the queue until the watcher
  restarts it. A pipeline stall never kills the Correspondent — it keeps
  triaging, answering from the last known catalog state, and marking
  answers stale rather than inventing them.

**Health and supervision:**

- Each process exposes a health endpoint; the sandbox supervisor restarts
  a failed process with backoff and emits `ops.process_restart`.
- On startup, each process replays its queue (pending signals, outbox)
  rather than assuming a clean slate — restarts don't lose or duplicate
  work (idempotency keys make replay safe).
- Either process can be run alone: the pipeline without the
  Correspondent (correspondence features degrade to logged no-ops), or
  the Correspondent against a stubbed pipeline for protocol testing.

---

## 5. Observability

All of this is auditable through the event stream (see the two YAML
contracts for full field lists):

- Ingress: `ingress.admitted / .queued / .shed`, `inbox.admitted`, `inbox.starvation`
- Sending: `send.window_opened / .sent / .duplicate_dropped / .window_closed`
- Safety: `ops.circuit_open`, `ops.kill_switch_engaged`, `ops.process_restart`

If an event is missing, the thing it describes didn't happen — the audit
log is the system of record, not any process's memory.

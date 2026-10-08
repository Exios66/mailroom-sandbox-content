# Smoke set (v0.1)

The smallest frozen corpus that can wire **mailroom-reloaded** end-to-end:
6 scenarios, 13 documents, frozen/handwritten email anchors.

## What it covers

- **Scenarios** (see `smoke_set.yaml`): `A1_status_inquiry`,
  `A3_supersession`, `B1_amendment_by_title`, `D1_vendor_cold_outreach`,
  `E1_lookalike_wire_change`, `F1_personal_address_lockout`.
- **Documents**: every fixture in `../attachments/manifest.csv` — synthetic
  Schedule C PDFs (clean + redline), simulated phone-photo lease scans,
  auto claim bundle, off-taxonomy CSV/PDFs (inventory sheet, COI, payoff
  letter, regulator notice), and the inert adversarial set (lookalike wire
  instructions, prompt-injection policy packet, QR stand-in PNG,
  macro-free .docm).
- `profile: smoke`, `gen: scripted`. The authoritative doc_ids and sha256
  values live in `../attachments/manifest.csv` and are repeated here for
  convenience.

## Vendoring into mailroom-reloaded

Per content migration §13.6 step 3: copy `attachments/`, `relations/`, and
`smoke/smoke_set.yaml` verbatim into `sandbox/fixtures/smoke/` of the
mailroom-reloaded repository. doc_ids and sha256 values are stable, so
scenario timelines in the main repo can reference `file` names directly.

## Size budget

The smoke set must stay **≤ 2 MB** total. Current attachments are all
hand-rolled fixtures, each well under 5 KB — comfortably within budget.

# Contradiction audit: scenario expectations vs the delegation matrix

> **Status: analysis only. No scenario has been edited.** Many CONFIRMED rows depend on rule R1 ("a draft needs a `task_correspondent` or a matrix note that sanctions one"), which is a reading of protocol lines 63-64, not a stated rule. The owner decides R1 (and the Series S treatment) before any scenario changes. Verdicts were produced by an automated read and spot-checked, not independently re-derived row by row.


Plan item K-03, stage 1 (analysis only). No scenario was edited. Scope: the
unmodified pack at this branch's base, 116 scenario files. The linter is
`tools/lint_contradictions.py`; its tests are `tests/test_lint_contradictions.py`.

Authority: `protocol/delegation_matrix.csv` (cited as **matrix:N**, N = CSV
line) and `protocol/correspondent_boss_protocol.md` (cited as **protocol:N**).
`CONTENT_SPEC.md` is cited where it scopes a series. Scenario lines are
`scenarios/<series>/<name>.yaml:N`.

## 1. Method

**Linter grouping.** Scenarios group by the sorted set of distinct
`timeline[].client.template` values plus `expect.intent`. Scenarios with no client
message are skipped. Companion messages are part of the template set, so a
scenario groups only with scenarios sending exactly the same templates.

**Compared fields.**
- `expect.outbox`: the set of `(intent, state)` pairs. An absent key is not compared.
- priority: the highest `expect.signals[].priority`. An absent key is not compared.

**Brief corrections.** These differ from the brief as written:
- The pack holds **116** scenario files (A 17, B 8, C 11, D 6, E 13, F 5, G 12,
  H 28, S 10, T 6), not 88.
- `template` is not a top-level field; it lives at `timeline[].client.template`.
- Priority is not `expect.priority`; it lives at `expect.signals[].priority`.
- "S1/S2/S3 (intent fyi)": `fyi` is the signal `kind`. The schema intent is
  `unrelated` (`scenarios/S/S1_free_pool_429_rotation.yaml:20`).
- D6 and G4/G7 use **different templates** (`d6_new_signature_format`,
  `bulk_status_request`, `receipt_check`), so the linter cannot group them. They
  are compared manually in section 3.

**Contrast annotation.** The linter reads an optional top-level string
`contrast`. No scenario in the pack uses it, so nothing is exempt. The schema
has `additionalProperties: false` at the top level (`schemas/scenario.v2.json:4`).
A scenario carrying `contrast` therefore fails `tools/validate.py` until the
schema gains a `contrast` property. This stage did not edit the schema.

**Reading rule R1 (drafts).** A draft reply in `expect.outbox` is
matrix-supported only when the matrix row for the class names
`task_correspondent` (the protocol's only delegated-draft action,
protocol:239), or the row's notes explicitly sanction a draft. Otherwise the
matrix supports `outbox: []`. Protocol:63-64 allows a draft "only when the Boss
tasks it or policy warrants an acknowledgment". The matrix defines no such ack
policy. R1 is my reading of the matrix; a reviewer may reject it for submission
classes. Where R1 decides a verdict, the table says so.

**Priority reading.** `fyi` maps to `low` (protocol:259; digest batching at
protocol:135-137). The matrix has no `fyi` or routine-check row. Matrix row 22
(`mailbox_technical_fault`) says "OUT OF SCOPE for comms logic: routed to the ops
runbook", so an infrastructure fault should not change a comms signal's priority.

## 2. Linter run (unmodified pack)

Captured in the scratch area; reproduced here.

```
WARN: outbox disagreement in group template=[benign_closing_companion] intent=document_submission: A11_out_of_order_delivery=[document_submission/draft], T2_attachment_round_trip=[]
WARN: priority disagreement in group template=[routine_status_check] intent=unrelated: S10_spend_cap_freeze=high, S1_free_pool_429_rotation=normal, S2_daily_cap_tier_switch=normal, S3_all_tiers_fail=high, S5_unallowlisted_host=high, S6_no_overlay_route=high, S7_sse_reconnect=normal, S9_duplicate_delivery_idempotent=normal
lint_contradictions: scenarios=116 comparable_groups=7 disagreements=2 exempt=0 no_client_message=1
```

Default mode exits 0; `--strict` exits 1. Output is identical across two runs.
Result: **2 disagreement findings in 2 groups**. The seven comparable groups are
the two above plus five groups that agree (`routine_status_check`/`general_question`,
`h_s_routine`/`unrelated`, `h_t_plain`/`general_question`, `document_submission`/
`document_submission`, `regulator_notice`/`legal_notice`). `S8` has no client message
and is skipped.

## 3. Verdicts

Verdicts: **CONFIRMED** (the scenario value conflicts with the matrix or protocol;
the matrix-supported side is stated), **NOT A CONTRADICTION**, **CANNOT DETERMINE**
(the missing input is named).

### 3a. Linter group L1: `routine_status_check` / `unrelated`, priority

Group members disagree (normal x4, high x4). The matrix has no routine row. Protocol:259 maps `fyi` to `low`. Matrix row 22 says infrastructure faults do not change comms logic. So no value in the group is directly matrix-supported, and `low` is the protocol-supported value for `fyi`. CONTENT_SPEC:73 scopes series S to "assert on the sandbox, not the Correspondent". The signal priority therefore may not be a Correspondent contract. That scope rule is the strongest argument for a `contrast` annotation on the whole group, but that is a stage-2 decision.

| scenario | field | current value | matrix-supported value | verdict | evidence |
|---|---|---|---|---|---|
| S1_free_pool_429_rotation | priority | normal | low (protocol:259 maps `fyi` to low) | CONFIRMED (group disagrees; normal not protocol-supported) | scenarios/S/S1_free_pool_429_rotation.yaml:22 |
| S2_daily_cap_tier_switch | priority | normal | low | CONFIRMED | scenarios/S/S2_daily_cap_tier_switch.yaml:22 |
| S3_all_tiers_fail | priority | high | low; matrix:22 routes this fault to the ops runbook, out of comms logic | CONFIRMED | scenarios/S/S3_all_tiers_fail.yaml:22 |
| S5_unallowlisted_host | priority | high | low; matrix:22 as above; protocol:257 reserves high for complaints, privacy, genuine payment changes | CONFIRMED | scenarios/S/S5_unallowlisted_host.yaml:22 |
| S6_no_overlay_route | priority | high | low; matrix:22; protocol:257 | CONFIRMED | scenarios/S/S6_no_overlay_route.yaml:22 |
| S7_sse_reconnect | priority | normal | low; protocol:259 | CONFIRMED | scenarios/S/S7_sse_reconnect.yaml:22 |
| S9_duplicate_delivery_idempotent | priority | normal | low; protocol:259; protocol:132-133 says a duplicate yields one signal, not a priority change | CONFIRMED | scenarios/S/S9_duplicate_delivery_idempotent.yaml:22 |
| S10_spend_cap_freeze | priority | high | low; matrix:22; protocol:257 | CONFIRMED | scenarios/S/S10_spend_cap_freeze.yaml:22 |
| S1-S10 (group L1) | outbox | all `[]` | `[]`; matrix:22 names no task_correspondent | NOT A CONTRADICTION | scenarios/S/S1_free_pool_429_rotation.yaml:23 (same line in S2, S3, S5, S6, S7, S9, S10) |
| S8_prod_gmail_refusal | priority (signal fyi) | critical | no comms priority: matrix:22 routes the class to the ops runbook, "n/a" autonomy; protocol:256 reserves critical for attacks, legal notices, after-hours urgent | CONFIRMED | scenarios/S/S8_prod_gmail_refusal.yaml:14 |
| S8_prod_gmail_refusal | outbox | `[]` | `[]` | NOT A CONTRADICTION | scenarios/S/S8_prod_gmail_refusal.yaml:15 |

### 3b. Linter group L2: `benign_closing_companion` / `document_submission`, outbox

| scenario | field | current value | matrix-supported value | verdict | evidence |
|---|---|---|---|---|---|
| A11_out_of_order_delivery | outbox | `[document_submission/draft]` | `[]` under R1. matrix:9 `document_submission` boss_action is "ack_signal + link_documents"; its notes ("relation only with evidence") sanction no draft; no task_correspondent | CONFIRMED | scenarios/A/A11_out_of_order_delivery.yaml:25-26; delegation_matrix.csv:9; protocol:63-64 |
| T2_attachment_round_trip | outbox | `[]` | `[]` (matrix:9) | NOT A CONTRADICTION (matrix side of L2) | scenarios/T/T2_attachment_round_trip.yaml:26 |
| A11 / T2 | priority | normal / normal | normal; protocol:258 "normal = submissions" | NOT A CONTRADICTION | scenarios/A/A11_out_of_order_delivery.yaml:23; scenarios/T/T2_attachment_round_trip.yaml:25 |

### 3c. Scenarios named in the brief

| scenario | field | current value | matrix-supported value | verdict | evidence |
|---|---|---|---|---|---|
| A9_phishing_and_injection | priority | critical (`possible_attack`, `attack_class: other`) | no matrix row covers a benign body. The `spam_or_phishing` row (matrix:15) gives dismiss and digest. The row for attacks (matrix:11, 15-min SLA) requires attack content this timeline does not contain. Scenario is `status: deprecated` | CANNOT DETERMINE. Missing: a live definition for a placeholder body. It has no peer in its group, since A7 uses the same template with intent `unrelated` | scenarios/A/A9_phishing_and_injection.yaml:2, 7, 16-17 (placeholder: "Deprecated placeholder; scenario 9 is covered by E1-E13"), 21; CONTENT_SPEC.md:65 |
| A9_phishing_and_injection | outbox | `[]` | `[]` (matrix:15 "no reply") | NOT A CONTRADICTION | scenarios/A/A9_phishing_and_injection.yaml:23 |
| A4_duplicate_resubmission | outbox | `[]` | `[]` (matrix:25 names ack_signal + link_documents; no task) | NOT A CONTRADICTION | scenarios/A/A4_duplicate_resubmission.yaml:36 |
| A4_duplicate_resubmission | priority | normal, normal | normal (protocol:258, submissions) | NOT A CONTRADICTION | scenarios/A/A4_duplicate_resubmission.yaml:31-32 |
| A4_duplicate_resubmission | boss_actions | `[dismiss_signal, link_documents]` | matrix:25 says `ack_signal + link_documents(duplicates)`; protocol:234 lists "duplicate" under `dismiss_signal`. The two authorities disagree | CANNOT DETERMINE. Missing: which authority governs the duplicate action | scenarios/A/A4_duplicate_resubmission.yaml:37; delegation_matrix.csv:25; protocol:234 |
| T5_outbound_send_gate | outbox | `[reply/draft]` | draft (matrix:26 `general_question`: "task_correspondent(status_update)", "auto_draft_only") | NOT A CONTRADICTION. Note: intent label `reply` appears only here | scenarios/T/T5_outbound_send_gate.yaml:23-24 |
| T5_outbound_send_gate | priority | normal | normal (matrix:26, SLA 1440) | NOT A CONTRADICTION | scenarios/T/T5_outbound_send_gate.yaml:22 |
| T6_duplicate_delivery_idempotent | outbox | `[]` | draft (matrix:26). The in-pack counterpart is T5 (same intent, draft) | CONFIRMED (matrix side: draft). Caveat: CONTENT_SPEC:74 scopes T to transport conformance and does not exclude outbox assertions | scenarios/T/T6_duplicate_delivery_idempotent.yaml:23; delegation_matrix.csv:26 |
| T6_duplicate_delivery_idempotent | priority | normal | normal (matrix:26, SLA 1440) | NOT A CONTRADICTION | scenarios/T/T6_duplicate_delivery_idempotent.yaml:22 |
| C4_corrupted_pdf | outbox | `[]` | `[]` (matrix:9) | NOT A CONTRADICTION | scenarios/C/C4_corrupted_pdf.yaml:25 |
| C4_corrupted_pdf | priority | normal | normal (protocol:258; the signal is `missing_doc`, not an attack) | NOT A CONTRADICTION | scenarios/C/C4_corrupted_pdf.yaml:22 |
| C4_corrupted_pdf | quarantine | `[corrupted_scan_01.pdf]` | quarantine: protocol:242 names "corrupted file (C4)" | NOT A CONTRADICTION | scenarios/C/C4_corrupted_pdf.yaml:24 |
| C4_corrupted_pdf | boss_actions | `[quarantine_attachments, request_human_review]` | quarantine: protocol:242. `request_human_review` triggers (protocol:238) are "urgent, possible_attack, legal, privacy, contradiction"; corrupted files are not listed | CANNOT DETERMINE for `request_human_review`. Missing: a matrix or protocol trigger for corrupted-file review | scenarios/C/C4_corrupted_pdf.yaml:26; protocol:238, 242 |
| E7_thread_hijack | priority | critical | critical: matrix:11 `payment_or_identity_change_attack` ("Lookalike domain + failed auth"), SLA 15; protocol:184 | NOT A CONTRADICTION | scenarios/E/E7_thread_hijack.yaml:52-53 |
| E7_thread_hijack | outbox | `[]` | `[]`: matrix:11 notes "No reply to the sender" | NOT A CONTRADICTION | scenarios/E/E7_thread_hijack.yaml:56 |
| E7_thread_hijack | boss_actions | `[request_human_review, recommend_callback]` (no `quarantine_attachments`) | matrix:11 lists quarantine, but the attack message (`msg_pivot`, lines 29-39) has no attachment. E2 and E5 use the same set with no attachment | NOT A CONTRADICTION (quarantine is attachment-conditional) | scenarios/E/E7_thread_hijack.yaml:57; scenarios/E/E2_registered_address_dkim_fail.yaml:35-37; scenarios/E/E5_invoice_fraud_po.yaml:35-37 |
| G9_expedite_request | outbox | draft `[urgent_deadline/draft]` | `[]` under R1: matrix:7 `urgent_deadline` is "raise_priority + request_human_review"; its notes name no draft | CONFIRMED. G10 (same intent) has `[]`, which matches | scenarios/G/G9_expedite_request.yaml:28-29; delegation_matrix.csv:7; scenarios/G/G10_client_stated_court_deadline.yaml:29 |
| G9_expedite_request | boss_actions | `[raise_priority]` | `raise_priority + request_human_review` (matrix:7) | CONFIRMED. G10 lists both | scenarios/G/G9_expedite_request.yaml:30; delegation_matrix.csv:7 |
| G9_expedite_request | priority | high (signal `urgent`) | Authorities conflict. matrix:7 SLA 15 maps to critical (protocol:256). protocol:168 gives "urgent high" | CANNOT DETERMINE. Missing: one ruling on urgent-deadline priority | scenarios/G/G9_expedite_request.yaml:26; protocol:168; protocol:256 |
| G10_client_stated_court_deadline | priority | critical | same conflict as G9 (matrix:7 SLA 15 supports critical; protocol:168 supports high) | CANNOT DETERMINE | scenarios/G/G10_client_stated_court_deadline.yaml:27 |
| G10_client_stated_court_deadline | outbox, boss_actions | `[]`; `[request_human_review, raise_priority]` | matches matrix:7 exactly | NOT A CONTRADICTION | scenarios/G/G10_client_stated_court_deadline.yaml:29-30 |
| F5_counsel_forwards_claim | outbox | `[]` | `[]` (matrix:9) | NOT A CONTRADICTION. Pack-level contrast: F5 is tagged `contrast_E13` (line 8) and E13 is tagged `explained-vs-unexplained` | scenarios/F/F5_counsel_forwards_claim.yaml:27, 8; scenarios/E/E13_out_of_profile_submission.yaml:8 |
| F5_counsel_forwards_claim | boss_actions | `[annotate_document]` | matrix:9 names `ack_signal + link_documents`. protocol:236 gives annotate for "note or correction" | CANNOT DETERMINE. Missing: whether an explained anomaly calls for a note | scenarios/F/F5_counsel_forwards_claim.yaml:28; delegation_matrix.csv:9 |
| F5_counsel_forwards_claim | priority | normal | normal (protocol:258) | NOT A CONTRADICTION | scenarios/F/F5_counsel_forwards_claim.yaml:23 |
| H18_counsel_forwards_claim (peer of F5) | outbox | `[document_submission/draft]` | `[]` under R1 (matrix:9) | CONFIRMED | scenarios/H/H18_counsel_forwards_claim.yaml:29-30 |
| D6_new_signature_format | outbox | `[]` | draft: matrix:2 `status_request` names "task_correspondent(status_update)", autonomy "auto_draft_only". G4 and G7 agree | CONFIRMED (matrix side: draft; the brief's comparison is correct) | scenarios/D/D6_new_signature_format.yaml:24; delegation_matrix.csv:2; scenarios/G/G4_bulk_status_request.yaml:30-31; scenarios/G/G7_receipt_confirmation.yaml:30-31 |
| D6_new_signature_format | boss_actions | `[ack_signal]` | `ack_signal + task_correspondent(status_update)` (matrix:2) | CONFIRMED | scenarios/D/D6_new_signature_format.yaml:25 |
| D6_new_signature_format | priority | normal | normal (matrix:2 SLA 1440). CONTENT_SPEC:68 says D is "reported at low priority", which conflicts with the matrix, not with D6 | NOT A CONTRADICTION (against matrix); CONTENT_SPEC:68 is the outlier | scenarios/D/D6_new_signature_format.yaml:20; CONTENT_SPEC.md:68 |
| D3_fake_urgent_verified (same family) | outbox | `[]` | draft (matrix:2) | CONFIRMED | scenarios/D/D3_fake_urgent_verified.yaml:24-25 |
| D4_payment_mention_status (same family) | outbox | `[]` | draft (matrix:2). H12 (same concept) has draft and task | CONFIRMED | scenarios/D/D4_payment_mention_status.yaml:24-25; scenarios/H/H12_payment_mention_status_only.yaml:23-25 |
| G4, G7, G8, H1, H7, H12 | outbox | `[status_request/draft]` | draft (matrix:2) | NOT A CONTRADICTION (these are the matrix-consistent side) | scenarios/G/G4_bulk_status_request.yaml:30-31; scenarios/G/G7_receipt_confirmation.yaml:30-31; scenarios/G/G8_forwarded_chain_timeline.yaml:30-31; scenarios/H/H1_status_request_probe.yaml:23-25; scenarios/H/H7_spanish_status_probe.yaml:23-25 |

### 3d. Systemic patterns found while checking the above

These go beyond the brief's scenario list. Each is listed so the pack owner can
decide it. None is a linter finding, because each crosses templates.

| scenarios | field | current value | matrix-supported value | verdict | evidence |
|---|---|---|---|---|---|
| T1, T3, T4, H25, H26, H27, C1, C2 | outbox | `[]` | draft: matrix:26 `general_question` names task_correspondent(status_update). Transport scenarios (T, H25-H27) raise the scope question in CONTENT_SPEC:74 | CONFIRMED under R1 for C1, C2; transport legs (T1, T3, T4, H25-H27) carry the same caveat as T6 | scenarios/T/T1_plain_round_trip.yaml:22; T3:32; T4:23; scenarios/H/H25_plain_round_trip_transport.yaml:23; H26:32; H27:23; scenarios/C/C1_forward_chain.yaml:24; scenarios/C/C2_non_english_message.yaml:23; delegation_matrix.csv:26 |
| F4_client_forwards_phish | outbox | `[]` | Ambiguous: matrix:26 implies draft; matrix:15 (`spam_or_phishing`) implies dismiss with no reply | CANNOT DETERMINE. Missing: the matrix row for a client asking "is this legit?" | scenarios/F/F4_client_forwards_phish.yaml:25-26 |
| A3, A5, A10, A12, B2, B3, B6, C3, C5, C11, H3, H6 | outbox | draft `[document_submission/draft]` | `[]` under R1 (matrix:9). These twelve plus A11 and H18 share one matrix class | CONFIRMED under R1 (systemic: 14 scenarios including A11 and H18, which are listed above). Decide whether submissions need an ack-draft rule, then either add it to matrix:9 or set `[]` | scenarios/A/A3_supersession.yaml:29; A5:36; A10:27; A12:36; scenarios/B/B2_counterparty_cross_matter.yaml:27; B3:31; B6:30; scenarios/C/C3_password_zip.yaml:34; C5:25; C11:24; scenarios/H/H3_corrected_exhibit_supersedes.yaml:29; H6:30 |
| A2_missing_document_followup | outbox | draft | Ambiguous: the signal is `missing_doc`, which maps to matrix:8 (`task_correspondent(request_missing_doc)`, supports a draft). The scenario's intent is `document_submission` | CANNOT DETERMINE. Missing: whether A2 is the matrix:8 or matrix:9 class | scenarios/A/A2_missing_document_followup.yaml:37-38, 44 |
| E13_out_of_profile_submission | outbox | `[clarifying_question/draft]` | No matrix row for out-of-profile senders. matrix:9 gives `[]` for submissions | CANNOT DETERMINE. Missing: an out-of-profile row. The pack intends this as the unexplained contrast to F5 | scenarios/E/E13_out_of_profile_submission.yaml:38-39 |
| G9_expedite_request, H21_expedite_before_closing | outbox | draft | `[]` under R1 (matrix:7) | CONFIRMED (H21 same as G9) | scenarios/H/H21_expedite_before_closing.yaml:25-26 |
| H21_expedite_before_closing | boss_actions | `[raise_priority]` | `raise_priority + request_human_review` (matrix:7) | CONFIRMED | scenarios/H/H21_expedite_before_closing.yaml:27 |
| H21_expedite_before_closing | priority | high | same conflict as G9 | CANNOT DETERMINE | scenarios/H/H21_expedite_before_closing.yaml:23 |
| B5_retraction, H5_retraction_wrong_file | outbox | draft `[retraction_or_withdrawal/draft]` | `[]` under R1. matrix:20 (`retraction_or_withdrawal`): "link_documents(withdraws)", "never deletes" | CONFIRMED | scenarios/B/B5_retraction.yaml:36; scenarios/H/H5_retraction_wrong_file.yaml:39; delegation_matrix.csv:20 |
| B4_body_contradicts_attachment | outbox | draft `[correction_or_amendment/draft]` | `[]`. matrix:5 `extraction_correction` (its example is "Body says loss March 3; archived letter says March 8") gives "request_human_review + annotate_document", no task. G3 and H20 have `[]` | CONFIRMED | scenarios/B/B4_body_contradicts_attachment.yaml:29; delegation_matrix.csv:5; scenarios/G/G3_extraction_correction.yaml:32; scenarios/H/H20_polite_extraction_correction.yaml:28 |
| B4, G3, H20 | priority | high | matrix:5 SLA 120 maps to high. protocol:258 says "normal = corrections" | CANNOT DETERMINE. Missing: one ruling on correction priority | scenarios/B/B4_body_contradicts_attachment.yaml:25; protocol:258 |
| B1_amendment_by_title, B8_effective_date_annotation, H4_amendment_cited_by_title | outbox | draft | No amendment row in the matrix | CANNOT DETERMINE. Missing: a matrix row for amendments | scenarios/B/B1_amendment_by_title.yaml:30; B8:26; scenarios/H/H4_amendment_cited_by_title.yaml:29 |
| F1_personal_address_lockout, H16_personal_address_lockout | priority (signal `fyi`) | normal | low (protocol:259) | CONFIRMED | scenarios/F/F1_personal_address_lockout.yaml:23; scenarios/H/H16_personal_address_lockout.yaml:23 |
| H22_provider_timeout_degrades, H23_crash_mid_triage_resume, H24_all_gen_tiers_down | priority (signal `fyi`) | normal | low (protocol:259). These are the held-out counterparts of group L1 | CONFIRMED | scenarios/H/H22_provider_timeout_degrades.yaml:22; H23:22; H24:22 |
| A7_unrelated_correspondence, D1, D2, D5, F4, G12, H10, H11, H28 (signal `fyi`) | priority | low | low (protocol:259) | NOT A CONTRADICTION. This is the pack's dominant convention for `fyi` | scenarios/A/A7_unrelated_correspondence.yaml:21; scenarios/G/G12_repeat_question_answered.yaml:27 |

## 4. Summary

**Linter findings: 2 (groups L1 and L2).** Both are confirmed at the group
level. L1 is a priority disagreement within the S-series; L2 is an outbox
disagreement between A11 and T2.

**Verdict counts for section 3:** 60 table rows (one per scenario and field):
26 CONFIRMED, 22 NOT A CONTRADICTION, 12 CANNOT DETERMINE. The counts were
computed by parsing this file's tables. Several rows in 3d cover more than one
scenario (for example, the 12-scenario document-submission row), so the
scenario-level total is higher than 60.

Open decisions for the pack owner, in order of impact:
1. Whether submission and urgent-deadline classes take an ack draft (R1). This
   covers about 14 document-submission scenarios and 2 urgent-deadline scenarios.
   Either the matrix names the draft, or the scenarios drop it.
2. Whether `fyi` routine messages are `low` (protocol:259) or whether series S is
   exempt from Correspondent priority (CONTENT_SPEC:73). Either way, L1 needs a
   decision.
3. One ruling on urgent-deadline and correction priority (matrix SLA vs protocol §5/§3(b)).
4. Missing matrix rows: amendments, out-of-profile senders, phishing forwards by a
   client, corrupted-file review, and the duplicate-action authority (A4).
5. Schema: a scenario using `contrast` needs `contrast` added to
   `schemas/scenario.v2.json` before `tools/validate.py` accepts it.

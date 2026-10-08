# New inbound (client-side) scripted templates. name -> (purpose, body)
T = {}
def t(name, purpose, body): T[name] = (purpose, body.strip("\n") + "\n")

t("document_submission", "generic benign cover note with one or more attachments", """
Subject: {{ document_title }} - {{ matter_ref }}

Hello,

Attached is {{ document_title }} for {{ matter_ref }}. {{ note }}

Please confirm receipt when you can.

Thanks,
{{ sender_name }}
""")
t("late_binding_heads_up", "A10: sender references a document that has not arrived yet", """
Subject: {{ document_title }} coming separately - {{ matter_ref }}

Hi,

Heads up: {{ document_title }} for {{ matter_ref }} is being sent through the data room and should reach you within the hour. Please tie it to this matter when it lands.

Regards,
{{ sender_name }}
""")
t("missing_doc_followup", "A2/E7: claimant follows up about an outstanding item", """
Subject: {{ followup_label }} - claim {{ claim_ref }}

Hello,

I am writing again about claim {{ claim_ref }}. You asked for {{ missing_item }} and I want to make sure I send the right thing. Can you tell me exactly what you still need from me?

{{ sender_name }}
""")
t("resend_submission", "A4: same document resent as a precaution", """
Subject: RESEND: {{ document_title }} - {{ matter_ref }}

Hi,

Resending {{ document_title }} for {{ matter_ref }} in case the earlier email did not come through. Nothing has changed in the document.

{{ sender_name }}
""")
t("split_package_part", "A5: claim package split across emails", """
Subject: Claim {{ claim_ref }} - part {{ part }} of {{ total }}

Part {{ part }} of {{ total }} attached.

{{ sender_name }}
""")
t("urgent_complaint", "A6: angry claimant with a same-day deadline", """
Subject: URGENT - claim {{ claim_ref }} - deadline TODAY

I have been waiting on claim {{ claim_ref }} for weeks. My deadline is {{ deadline }} today and nobody has told me anything. This is unacceptable. I need an answer before the end of the day or I do not know what I will do.

{{ sender_name }}
""")
t("unrelated_note", "A7/A9: mail unrelated to any matter", """
Subject: {{ topic }}

Hi all,

{{ note }}

Cheers,
{{ sender_name }}
""")
t("auto_reply_ooo", "A8: out-of-office auto-reply from a billing mailbox", """
Subject: Automatic reply: {{ original_subject }}

Thank you for your message. The billing office is closed until {{ return_date }}. This mailbox is not monitored; your message has not been forwarded.

This is an automated response.
""")
t("cross_matter_note", "B2: counterparty ties two matters together", """
Subject: {{ matter_ref }} / {{ other_matter_ref }} - same counterparty

Team,

Attached is the signed agreement for {{ matter_ref }}. Note that the counterparty, {{ counterparty }}, is also the counterparty on {{ other_matter_ref }}; the two deals should be read together, and the indemnity in this one cross-references the other.

{{ sender_name }}
""")
t("alias_rename_lease", "B3: informal landlord, unit renamed on the new lease", """
Subject: lease stuff from yesterday

hey - signed one this time, last week's was missing page 6. also the new COI from the insurer. heads up unit {{ old_unit }} is {{ new_unit }} on the new one

{{ sender_name }}
""")
t("claim_date_correction", "B4: body states a different loss date than the earlier letter", """
Subject: FWD: FWD: WHERE IS MY CLAIM

This is the third time I am writing. Claim {{ claim_ref }}. The loss was {{ stated_loss_date }}, not {{ letter_loss_date }} like your letter says. Inventory attached again. My lawyer will be contacting you. Can I have the adjuster's cell number?

{{ sender_name }}
""")
t("retraction_notice", "B5: sender withdraws an earlier upload", """
Subject: Please ignore earlier upload - {{ matter_ref }}

Hi,

Please ignore the {{ document_title }} I sent earlier today for {{ matter_ref }} - wrong file. The correct version will follow.

{{ sender_name }}
""")
t("late_exhibit", "B6: late exhibit for an already-archived claim set", """
Subject: {{ claim_ref }} - {{ exhibit_label }} (late)

{{ exhibit_label }} for {{ claim_ref }} attached. Was left out of the original set.

{{ sender_name }}
""")
t("loss_report", "B7/E7: claimant describes a loss event", """
Subject: Loss report - claim {{ claim_ref }}

Hello,

Reporting the loss on {{ loss_date }}: {{ loss_summary }} Photos and the bill of lading are attached.

{{ sender_name }}
""")
t("field_report_note", "B7: adjuster's terse field report on the same event", """
Subject: Field report - {{ claim_ref }}

Inspected {{ loss_location }} {{ inspection_date }}. Findings consistent with reported loss. Report to follow.

{{ sender_name }}
""")
t("effective_date_update", "B8: email-only change to a processed document's meaning", """
Subject: {{ document_title }} - effective date - {{ matter_ref }}

Quick note for the file: the parties agreed today that {{ document_title }} takes effect {{ effective_date }}, not on signing. No new version will be circulated; please note it against the agreement.

{{ sender_name }}
""")
t("forward_chain", "C1/G8: forward of a forward with long quoted history", """
Subject: Fwd: Fwd: Re: {{ subject_core }}

{{ question }}

{{ sender_name }}

---------- Forwarded message ----------
Subject: Fwd: Re: {{ subject_core }}

> > {{ quoted_history }}
""")
t("spanish_inquiry", "C2: non-English (Spanish) message from a pro-se policyholder", """
Subject: Consulta sobre mi reclamo {{ claim_ref }}

Hola,

Les escribo por mi reclamo {{ claim_ref }}. Envié los documentos hace dos semanas y no he recibido respuesta. ¿Me pueden decir si falta algo?

Gracias,
{{ sender_name }}
""")
t("password_archive_submission", "C3: password-protected archive; password to follow", """
Subject: {{ claim_ref }} bundle (protected)

Bundle attached, password protected. Password in separate email.

{{ sender_name }}
""")
t("archive_password_followup", "C3: the password arrives in a second email", """
Subject: RE: {{ claim_ref }} bundle (protected)

pw: {{ archive_password }}

{{ sender_name }}
""")
t("informal_photo_submission", "C4/C11: informal phone-photo submission", """
Subject: {{ subject_line }}

{{ note }}

{{ sender_name }}
""")
t("closing_instruction", "C6: closing instruction that conflicts with another sender's", """
Subject: {{ matter_ref }} - closing instructions

{{ instruction }}

{{ sender_name }}
""")
t("privacy_deletion_request", "C8: data-deletion request from a pro-se policyholder", """
Subject: delete my information

Hello,

I want all of my personal information deleted from your system, including everything about claim {{ claim_ref }}. Please also tell me everyone you have shared it with.

{{ sender_name }}
""")
t("litigation_threat_followup", "C9: routine follow-up ending in a litigation threat", """
Subject: Claim {{ claim_ref }} - follow up

Hello,

Following up on claim {{ claim_ref }}. I sent the repair estimate last week and have not heard back. If I do not hear something by Friday, my lawyer will be contacting you.

{{ sender_name }}
""")
t("attachment_only", "C11: empty body, attachment only", """
Subject: {{ subject_line }}

""")
t("routine_status_check", "S/T series: plain routine message used to exercise the sandbox and transports", """
Subject: {{ subject_line }}

Hi,

{{ note }}

Thanks,
{{ sender_name }}
""")
t("frustrated_status_followup", "G1: third angry follow-up about an unprocessed claim", """
Subject: THIRD REQUEST - claim {{ claim_ref }}

This is my {{ contact_count }} email. Claim {{ claim_ref }} has been sitting for {{ days_waiting }} days. Nobody answers. What is going on?

{{ sender_name }}
""")
t("extraction_confirm_request", "G2: counsel asks to confirm extracted fields", """
Subject: Confirm extracted terms - {{ document_title }} - {{ matter_ref }}

Please confirm what your system extracted from {{ document_title }} for {{ matter_ref }}: the effective date, the parties, and the liability cap. We want to check them against our own summary before the call.

{{ sender_name }}
""")
t("extraction_correction", "G3: adviser says an extracted value is wrong", """
Subject: Correction - purchase price - {{ matter_ref }}

The summary you sent lists the purchase price as {{ extracted_value }}. That is wrong; the agreement says {{ stated_value }}. Please correct your records.

{{ sender_name }}
""")
t("bulk_status_request", "G4: billing office asks for status on many documents at once", """
Subject: Status request - {{ matter_ref }} ({{ doc_count }} documents)

Please send the processing status for all {{ doc_count }} claim documents submitted under {{ matter_ref }} this week.

{{ sender_name }}
""")
t("summary_request", "G5: founder asks for a plain-English summary", """
Subject: what does the charter amendment actually change?

hi - can you give me a plain-English summary of the charter amendment we filed? board meeting is {{ meeting_day }}.

{{ sender_name }}
""")
t("reextraction_request", "G6: counsel asks to re-run extraction after an amendment", """
Subject: Re-run extraction - {{ document_title }} - {{ matter_ref }}

The amendment for {{ matter_ref }} is now in. Please re-run extraction on {{ document_title }} so the key dates reflect it.

{{ sender_name }}
""")
t("receipt_check", "G7: adjuster asks whether a fragment arrived", """
Subject: {{ fragment_ref }} - {{ claim_ref }}

did part {{ part }} of {{ total }} come through?

{{ sender_name }}
""")
t("expedite_request", "G9: closing officer asks to expedite before a closing", """
Subject: EXPEDITE - {{ matter_ref }} closes at {{ closing_time }}

Closing for {{ matter_ref }} is at {{ closing_time }} today. Can you prioritize the closing package? Officer certificate attached.

{{ sender_name }}
""")
t("court_deadline", "G10: claimant cites a court deadline", """
Subject: Court deadline - claim {{ claim_ref }}

The court gave me until {{ court_deadline }} to file. I need claim {{ claim_ref }} processed before then. Supplement attached.

{{ sender_name }}
""")
t("access_scope_question", "G11: policyholder asks who can see her documents", """
Subject: who can see my documents?

Hello, I sent my papers for claim {{ claim_ref }}. Who can see them? Do you share my information with anyone?

{{ sender_name }}
""")
t("repeat_question", "G12: landlord re-asks a question answered last week", """
Subject: renewal question again

hey - when does the renewal option on {{ unit_ref }} have to be exercised? asked last week but can't find it

{{ sender_name }}
""")
t("benign_companion_generic", "benign companion message from a verified client", """
Subject: {{ document_title }} - {{ matter_ref }}

Hello,

Attached is {{ document_title }} for {{ matter_ref }}, as discussed.

Best regards,
{{ sender_name }}
""")

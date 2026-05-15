# Claim demo — persona document pack

Fictional supporting documents that round out the multi-document story shown
in the claims demo (Contoso Insurance / Jordan Reyes / claim CLM-2026-04-12-1187).

These four PDFs are referenced by the claims-demo journey and can be uploaded
through the real `/contentprocessor` pipeline once Step 1 is wired to the live
API. Until then they exist for reviewers who want to inspect the supporting
material behind the demo narrative.

| File | Role |
|---|---|
| `member_policy.pdf` | Personal auto policy MP-784512 with the policy clauses cited in the gap analysis (sections 4.2, 7.1, 9.4, 12.6, 14.1, 17.3). |
| `prior_claims_history.pdf` | One prior single-vehicle claim (2025-02-08, $3,140 paid). Matches the RAI summary's "1 prior claim, no fraud indicators". |
| `third_party_details.pdf` | Contact info for Devon Park (fence owner) plus the missing-insurer flag that drives the gap-analysis follow-up. |
| `medical_note.pdf` | Bay General Clinic note covering the grade I whiplash injury and physiotherapy recommendation. |

To regenerate after editing field values:

```pwsh
python src/ContentProcessorAPI/samples/claim_demo_persona/generate_pdfs.py
```

(Requires `reportlab`; the script is committed alongside the PDFs so the source
of truth lives in the repo.)

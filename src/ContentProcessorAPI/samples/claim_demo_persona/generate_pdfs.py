"""Generate the 4 fictional supporting PDFs for the claims demo persona pack.

Run from repo root:
    python src/ContentProcessorAPI/samples/claim_demo_persona/generate_pdfs.py

Outputs land alongside this script. PDFs deliberately match the persona
fixtures in src/ContentProcessorAPI/app/routers/data/claimsdemo_fixtures.json
so future real CU extraction yields the same demo story.
"""
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

OUT_DIR = Path(__file__).parent
styles = getSampleStyleSheet()
H = ParagraphStyle("H", parent=styles["Heading1"], fontSize=18, spaceAfter=12, textColor=colors.HexColor("#1a3a5e"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceAfter=6, textColor=colors.HexColor("#1a3a5e"))
P = ParagraphStyle("P", parent=styles["BodyText"], fontSize=10, leading=14)
SMALL = ParagraphStyle("SMALL", parent=styles["BodyText"], fontSize=8, leading=11, textColor=colors.grey)


def _doc(name: str):
    return SimpleDocTemplate(
        str(OUT_DIR / name), pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        title=name, author="Contoso Insurance",
    )


def _kv_table(rows):
    t = Table(rows, colWidths=[2.0 * inch, 4.5 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    return t


def member_policy():
    doc = _doc("member_policy.pdf")
    s = []
    s.append(Paragraph("Contoso Insurance — Personal Auto Policy", H))
    s.append(Paragraph("Policy MP-784512 · Issued to Jordan Reyes", SMALL))
    s.append(Spacer(1, 12))
    s.append(_kv_table([
        ["Policy number", "MP-784512"],
        ["Policy holder", "Jordan Reyes"],
        ["Effective from", "2025-09-01"],
        ["Expires", "2026-09-01"],
        ["Tier", "Standard"],
        ["Use class", "Personal"],
        ["Insured vehicle", "2022 Subaru Outback (VIN JF2SKAUC4NH523117, reg 8KQR412)"],
    ]))
    s.append(Spacer(1, 16))
    sections = [
        ("Section 4.2 — Comprehensive coverage",
         "Damage caused by collision with stationary objects (including roadside fixtures) "
         "is covered under comprehensive provisions, subject to the standard $500 deductible."),
        ("Section 7.1 — Third-party property",
         "Where the insured is liable for damage to third-party property, the insurer will "
         "indemnify the third party up to the property damage limit specified in the schedule "
         "(currently $50,000)."),
        ("Section 9.4 — Medical expenses",
         "Reasonable medical expenses arising from a covered incident are payable up to "
         "$5,000 per occupant of the insured vehicle."),
        ("Section 12.6 — Subrogation",
         "The insurer reserves the right to recover amounts paid under this policy from any "
         "third party legally liable. The insured agrees to provide all reasonable assistance "
         "in pursuing such recovery."),
        ("Section 14.1 — Notice of loss",
         "The insured shall notify the insurer of any incident giving rise to a claim within "
         "30 days. Late notification may prejudice the claim where it materially affects the "
         "insurer's ability to investigate."),
        ("Section 17.3 — Approved repairers",
         "Where the insurer authorises repair, work shall be carried out by an approved repairer "
         "from the insurer's network unless the insured obtains prior written agreement otherwise."),
    ]
    for title, body in sections:
        s.append(Paragraph(title, H2))
        s.append(Paragraph(body, P))
        s.append(Spacer(1, 8))
    s.append(Spacer(1, 12))
    s.append(Paragraph("This is a fictional document used only for demonstration purposes. Not a real insurance policy.", SMALL))
    doc.build(s)


def prior_claims():
    doc = _doc("prior_claims_history.pdf")
    s = []
    s.append(Paragraph("Prior Claims History — Jordan Reyes", H))
    s.append(Paragraph("Policy MP-784512 · Generated 2026-04-13", SMALL))
    s.append(Spacer(1, 12))
    s.append(Paragraph("Summary", H2))
    s.append(_kv_table([
        ["Prior claims (5 yr)", "1"],
        ["Most recent claim", "2025-02-08 (single-vehicle)"],
        ["Most recent payout", "$3,140"],
        ["Outcome", "Approved, paid"],
        ["Open claims", "0"],
    ]))
    s.append(Spacer(1, 16))
    s.append(Paragraph("Detail", H2))
    rows = [
        ["Date", "Type", "Description", "Outcome", "Payout"],
        ["2025-02-08", "Single-vehicle", "Minor parking-lot collision, front bumper.",
         "Approved", "$3,140"],
    ]
    t = Table(rows, colWidths=[0.9*inch, 1.1*inch, 2.6*inch, 1.0*inch, 0.9*inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    s.append(t)
    s.append(Spacer(1, 16))
    s.append(Paragraph("Pattern analysis: claim frequency within normal range for this customer "
                       "segment. No prior fraud indicators on record.", P))
    doc.build(s)


def third_party():
    doc = _doc("third_party_details.pdf")
    s = []
    s.append(Paragraph("Third-Party Details", H))
    s.append(Paragraph("Claim CLM-2026-04-12-1187 · Captured at scene 2026-04-12", SMALL))
    s.append(Spacer(1, 12))
    s.append(_kv_table([
        ["Third-party name", "Devon Park"],
        ["Contact", "+1 415-555-0166"],
        ["Email", "(not provided)"],
        ["Address", "Property owner — fence adjoining Highway 41 mile-marker 38"],
        ["Property damaged", "Approximately 12 ft of timber roadside fencing"],
        ["Property damage estimate", "$640"],
        ["Third-party insurer", "(not provided — to follow up)"],
        ["Third-party policy number", "(not provided — to follow up)"],
    ]))
    s.append(Spacer(1, 16))
    s.append(Paragraph("Notes", H2))
    s.append(Paragraph("Mr Park was reached by phone on the evening of 2026-04-12 and confirmed "
                       "the damage. He has not yet supplied insurance details. Recommend follow-up "
                       "before settlement to enable subrogation under Section 12.6 of the policy.", P))
    doc.build(s)


def medical():
    doc = _doc("medical_note.pdf")
    s = []
    s.append(Paragraph("Bay General Clinic — Medical Examination Note", H))
    s.append(Paragraph("Examination 2026-04-15 · Patient: Jordan Reyes", SMALL))
    s.append(Spacer(1, 12))
    s.append(_kv_table([
        ["Examining clinician", "Dr. P. Acharya, MBBS"],
        ["Clinic", "Bay General Clinic, San Francisco"],
        ["Examination date", "2026-04-15"],
        ["Patient", "Jordan Reyes (DOB 1989-07-12)"],
        ["Reason for visit", "Post-incident assessment following motor vehicle collision 2026-04-12"],
    ]))
    s.append(Spacer(1, 12))
    s.append(Paragraph("Findings", H2))
    s.append(Paragraph(
        "Patient presents with mild stiffness and reduced range of motion in the cervical "
        "spine, consistent with grade I whiplash-associated disorder. No neurological deficit. "
        "No evidence of fracture on examination; concussion symptoms screened — none reported. "
        "Bruising over left clavicle from seatbelt restraint, healing.",
        P,
    ))
    s.append(Spacer(1, 8))
    s.append(Paragraph("Recommendation", H2))
    s.append(Paragraph(
        "Physiotherapy twice weekly for 3 weeks. Over-the-counter analgesics as required. "
        "Follow-up review in 4 weeks. Patient advised to take 2 days off work and avoid heavy "
        "lifting for 2 weeks.",
        P,
    ))
    s.append(Spacer(1, 16))
    s.append(Paragraph("Signed: Dr. P. Acharya, 2026-04-15", SMALL))
    doc.build(s)


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    member_policy()
    prior_claims()
    third_party()
    medical()
    for p in sorted(OUT_DIR.glob("*.pdf")):
        print(f"  wrote {p.name} ({p.stat().st_size // 1024} KB)")

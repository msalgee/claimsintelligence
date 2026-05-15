"""Generate sample documents for a collision claim that subtly hints the
insured vehicle was being used commercially (rideshare-style), against a
member policy that explicitly covers personal use only.

The Foundry-driven gap analysis is expected to flag the mismatch between
the documents (commercial-use signals across the claim form, police
narrative, and repair line items) and the member policy (use exclusion).

Documents produced:

  * claim_form.pdf            — driver claim narrative (passenger present,
                                no relationship listed)
  * police_report.pdf         — narrative mentions returning from a
                                drop-off and visible TNC trade-dress
                                residue + rooftop placard mount
  * repair_estimate.pdf       — line items include rooftop placard mount
                                removal and decal-residue cleanup
  * member_policy.pdf         — Northwind Mutual policy declarations:
                                "Personal use only" + explicit exclusion
                                of any use for hire / TNC / delivery
  * damage_photo.png          — high-fidelity inspection photo (PIL
                                fallback; replaced by GPT-image when
                                ``generate_image.py`` is run with valid
                                Azure OpenAI / OpenAI credentials)

Run from repo root:

    python src/ContentProcessorAPI/samples/claim_collision_commercial_hint/generate_pdfs.py

Optional (replaces damage_photo.png with a real GPT-image render):

    python src/ContentProcessorAPI/samples/claim_collision_commercial_hint/generate_image.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT_DIR = Path(__file__).parent

styles = getSampleStyleSheet()
H = ParagraphStyle("H", parent=styles["Heading1"], fontSize=18, spaceAfter=10,
                   textColor=colors.HexColor("#1a3a5e"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceAfter=4,
                    textColor=colors.HexColor("#1a3a5e"))
P = ParagraphStyle("P", parent=styles["BodyText"], fontSize=10, leading=14)
SMALL = ParagraphStyle("SMALL", parent=styles["BodyText"], fontSize=8,
                       leading=11, textColor=colors.grey)


# ---- Shared persona / claim values ------------------------------------------
INSURER = "Northwind Mutual Insurance"
CLAIM_NUMBER = "NM-CLM-2026-05-913"
POLICY_NUMBER = "NM-AUTO-661820"

POLICYHOLDER = {
    "name": "Devon Park",
    "street": "1827 S 168th St, Apt 4B",
    "city": "SeaTac",
    "state": "WA",
    "postal_code": "98188",
    "country": "USA",
    "phone": "(206) 555-0192",
    "email": "devon.park@example.com",
}

POLICY = {
    "coverage_type": "Auto — Personal use only",
    "effective_date": "2025-09-15",
    "expiration_date": "2026-09-14",
    "deductible": 500.0,
    "deductible_currency": "USD",
    "use_class": "Pleasure / commute (personal use)",
    "exclusions_summary": (
        "Coverage excludes any use for hire, livery, ride-sharing or "
        "transportation network company (TNC) services, food or parcel "
        "delivery, courier work, and any compensation-for-transport "
        "activity."
    ),
}

INCIDENT = {
    "date_of_loss": "2026-05-08",
    "time_of_loss": "02:15",
    "location": (
        "Cell-phone waiting lot, S 170th St near International Blvd, "
        "SeaTac, WA (adjacent to SEA airport)"
    ),
    "cause_of_loss": (
        "Single-vehicle collision — front-end impact with concrete bollard "
        "while merging from the passenger drop-off curb"
    ),
    "description": (
        "Insured was merging from the airport passenger drop-off lane onto "
        "the inner roadway when the front of the vehicle struck a "
        "low-profile concrete bollard. A passenger was present in the rear "
        "seat at the time; their relationship to the insured was not "
        "recorded. No injuries reported. Vehicle remained driveable but "
        "with significant front-end damage; towed to repair facility from "
        "the cell-phone waiting lot two blocks away."
    ),
    "police_report_filed": True,
    "police_report_number": "PSP-2026-05-08-7041",
}

VEHICLE = {
    "year": "2022",
    "make": "Toyota",
    "model": "Camry",
    "trim": "SE",
    "vin": "4T1G11AK4NU712936",
    "license_plate": "WA-EVR4427",
    "mileage": 71820,  # high for a 2-year-old personal-use car
    "color": "Midnight blue metallic",
}

DAMAGE_ITEMS = [
    # (description, cost_new, repair_estimate)
    ("Front bumper cover — replace and refinish",         620.0,  712.40),
    ("Hood panel — straighten, refinish",                 540.0,  486.20),
    ("Left headlamp assembly — replace",                  410.0,  445.85),
    ("Radiator support — straighten",                     290.0,  318.60),
    ("Air-conditioning condenser — replace",              360.0,  402.30),
    ("Remove rooftop placard mount; refinish roof rail",  185.0,  264.75),
    ("Detach / reattach interior dual phone-mount rig",    90.0,  118.40),
    ("Remove residue of trade-dress decal — left rear "
     "quarter window glass",                                70.0,   95.50),
]
TOTAL_REPAIR = round(sum(item[2] for item in DAMAGE_ITEMS), 2)

DECLARATION_DATE = "2026-05-09"
SUBMISSION = {
    "submission_email": "claims@northwindmutual.example.com",
    "portal_url": "https://claims.northwindmutual.example.com",
    "notes": "Submit driver statement and inspection photos within 14 days.",
}


# ---- Helpers ----------------------------------------------------------------
def _doc(name: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(OUT_DIR / name),
        pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        title=name, author=INSURER,
    )


def _kv(rows):
    t = Table(rows, colWidths=[2.0 * inch, 4.6 * inch])
    t.setStyle(TableStyle([
        ("FONT",          (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT",          (0, 0), (0, -1),  "Helvetica-Bold", 10),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    return t


# ---- claim_form.pdf ---------------------------------------------------------
def claim_form():
    doc = _doc("claim_form.pdf")
    s = []
    s.append(Paragraph(f"{INSURER} — Auto Insurance Claim Form", H))
    s.append(Paragraph(
        f"Claim {CLAIM_NUMBER} · Policy {POLICY_NUMBER} · Form NM-AIC-220",
        SMALL,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Policyholder", H2))
    s.append(_kv([
        ["Name",          POLICYHOLDER["name"]],
        ["Street",        POLICYHOLDER["street"]],
        ["City",          POLICYHOLDER["city"]],
        ["State",         POLICYHOLDER["state"]],
        ["Postal code",   POLICYHOLDER["postal_code"]],
        ["Country",       POLICYHOLDER["country"]],
        ["Phone",         POLICYHOLDER["phone"]],
        ["Email",         POLICYHOLDER["email"]],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Policy details", H2))
    s.append(_kv([
        ["Insurance company",  INSURER],
        ["Claim number",       CLAIM_NUMBER],
        ["Policy number",      POLICY_NUMBER],
        ["Coverage type",      POLICY["coverage_type"]],
        ["Effective date",     POLICY["effective_date"]],
        ["Expiration date",    POLICY["expiration_date"]],
        ["Deductible",         f"${POLICY['deductible']:,.2f} {POLICY['deductible_currency']}"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Incident details", H2))
    s.append(_kv([
        ["Date of loss",          INCIDENT["date_of_loss"]],
        ["Time of loss",          INCIDENT["time_of_loss"]],
        ["Location",              INCIDENT["location"]],
        ["Cause of loss",         INCIDENT["cause_of_loss"]],
        ["Description",           INCIDENT["description"]],
        ["Police report filed",   "Yes" if INCIDENT["police_report_filed"] else "No"],
        ["Police report number",  INCIDENT["police_report_number"]],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Occupants at time of loss", H2))
    s.append(_kv([
        ["Driver",                  POLICYHOLDER["name"]],
        ["Passenger present",       "Yes (1 passenger, rear seat)"],
        ["Passenger name",          "Not recorded"],
        ["Relationship to insured", "Not recorded"],
        ["Trip purpose",            "Returning from passenger drop-off"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Vehicle information", H2))
    s.append(_kv([
        ["Year",          VEHICLE["year"]],
        ["Make",          VEHICLE["make"]],
        ["Model",         VEHICLE["model"]],
        ["Trim",          VEHICLE["trim"]],
        ["Colour",        VEHICLE["color"]],
        ["VIN",           VEHICLE["vin"]],
        ["License plate", VEHICLE["license_plate"]],
        ["Mileage",       f"{VEHICLE['mileage']:,}"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Damage assessment", H2))
    rows = [["Item", "Cost new", "Repair estimate"]]
    for desc, new, est in DAMAGE_ITEMS:
        rows.append([desc, f"${new:,.2f}", f"${est:,.2f}"])
    rows.append(["Total estimated repair", "", f"${TOTAL_REPAIR:,.2f} USD"])
    t = Table(rows, colWidths=[3.6 * inch, 1.4 * inch, 1.6 * inch])
    t.setStyle(TableStyle([
        ("FONT",          (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT",          (0, 0), (-1, 0),  "Helvetica-Bold", 9),
        ("FONT",          (0, -1), (-1, -1), "Helvetica-Bold", 9),
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#eef3f8")),
        ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#f6f8fb")),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    s.append(t)
    s.append(Spacer(1, 10))

    s.append(Paragraph("Supporting documents", H2))
    s.append(_kv([
        ["Photos of damage",     "Yes"],
        ["Police report copy",   "Yes"],
        ["Repair shop estimate", "Yes"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Declaration", H2))
    s.append(Paragraph(
        "I hereby declare that the information provided in this claim form is true and "
        "accurate to the best of my knowledge. I understand that providing false "
        "information may result in denial of my claim and possible legal action.",
        P,
    ))
    s.append(Spacer(1, 6))
    s.append(_kv([
        ["Signatory",  POLICYHOLDER["name"]],
        ["Is signed",  "Yes"],
        ["Date",       DECLARATION_DATE],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Submission instructions", H2))
    s.append(_kv([
        ["Submission email", SUBMISSION["submission_email"]],
        ["Portal URL",       SUBMISSION["portal_url"]],
        ["Notes",            SUBMISSION["notes"]],
    ]))
    s.append(Spacer(1, 12))
    s.append(Paragraph(
        "Fictional document generated for demo purposes only.", SMALL,
    ))
    doc.build(s)


# ---- police_report.pdf ------------------------------------------------------
def police_report():
    doc = _doc("police_report.pdf")
    s = []
    s.append(Paragraph(
        "Port of Seattle Police Department — Traffic Incident Report", H,
    ))
    s.append(Paragraph(
        f"Report {INCIDENT['police_report_number']} · "
        f"Filed {INCIDENT['date_of_loss']} 03:08",
        SMALL,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Incident", H2))
    s.append(_kv([
        ["Date of incident",    INCIDENT["date_of_loss"]],
        ["Time of incident",    INCIDENT["time_of_loss"]],
        ["Location",            INCIDENT["location"]],
        ["Reporting party",     POLICYHOLDER["name"]],
        ["Officer in charge",   "Ofc. J. Alvarez, Badge #2218"],
        ["Citation issued",     "No (warning — failure to yield)"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Vehicle", H2))
    s.append(_kv([
        ["Make / Model",  f"{VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} {VEHICLE['trim']}"],
        ["Colour",        VEHICLE["color"]],
        ["VIN",           VEHICLE["vin"]],
        ["License plate", VEHICLE["license_plate"]],
        ["Mileage",       f"{VEHICLE['mileage']:,}"],
        ["Insured",       f"{POLICYHOLDER['name']} ({INSURER}, policy {POLICY_NUMBER})"],
        ["Claim number",  CLAIM_NUMBER],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Narrative", H2))
    s.append(Paragraph(
        f"Reporting party {POLICYHOLDER['name']} was contacted by responding officer at "
        f"the scene, the cell-phone waiting lot adjacent to the airport drop-off curb, "
        f"at approximately 02:22 on {INCIDENT['date_of_loss']}. Driver stated he was "
        "&quot;returning from a drop-off&quot; and merging back onto the inner roadway "
        "when the front of his vehicle made contact with a low-profile concrete bollard. "
        "One passenger was observed in the rear seat at the time of the officer's "
        "arrival; the passenger declined to provide identification and stated they had "
        "&quot;just been given a ride&quot;. The relationship between the driver and the "
        "passenger was not established. No injuries reported. Driver showed no signs of "
        "impairment; field sobriety not warranted.",
        P,
    ))
    s.append(Spacer(1, 6))
    s.append(Paragraph(
        "Vehicle exterior was inspected at scene. The following items were noted as "
        "pre-existing (not related to the impact) and recorded for completeness:",
        P,
    ))
    for line in [
        "A removable rooftop placard mount (suction-base) was affixed to the roof above "
        "the windshield; placard itself was not displayed.",
        "A partially-removed adhesive trade-dress decal was visible on the lower-left "
        "rear quarter window glass; residue ring approximately 12 cm in diameter.",
        "Two phone-mount cradles were installed on the dashboard, oriented toward the "
        "driver and toward the rear-seat passenger respectively.",
        "A windshield-mounted dash camera was active and pointed forward.",
    ]:
        s.append(Paragraph(f"• {line}", P))
    s.append(Spacer(1, 6))
    s.append(Paragraph(
        "Impact-related damage observed: front bumper cover crumpled centre-left, hood "
        "buckled at leading edge, left headlamp assembly cracked, radiator support bent, "
        "AC condenser visibly leaking. Vehicle was driveable at low speed; towed for "
        "repair as a precaution. Passenger left scene on foot prior to tow.",
        P,
    ))
    s.append(Spacer(1, 12))
    s.append(Paragraph(
        f"Signed: Ofc. J. Alvarez, {INCIDENT['date_of_loss']}", SMALL,
    ))
    doc.build(s)


# ---- repair_estimate.pdf ----------------------------------------------------
def repair_estimate():
    doc = _doc("repair_estimate.pdf")
    s = []
    s.append(Paragraph("SeaTac Collision Center — Repair Estimate", H))
    s.append(Paragraph(
        f"Estimate STC-26-0508 · Prepared 2026-05-09 for {POLICYHOLDER['name']}",
        SMALL,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Customer & vehicle", H2))
    s.append(_kv([
        ["Customer",      POLICYHOLDER["name"]],
        ["Phone",         POLICYHOLDER["phone"]],
        ["Insurer",       INSURER],
        ["Claim number",  CLAIM_NUMBER],
        ["Policy number", POLICY_NUMBER],
        ["Vehicle",       f"{VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} {VEHICLE['trim']}"],
        ["Colour",        VEHICLE["color"]],
        ["VIN",           VEHICLE["vin"]],
        ["License plate", VEHICLE["license_plate"]],
        ["Mileage",       f"{VEHICLE['mileage']:,}"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Cause of damage", H2))
    s.append(Paragraph(
        "Front-end collision with stationary concrete bollard during low-speed merge. "
        "Mechanically driveable on arrival. In addition to impact repairs, customer "
        "requested removal of accessory hardware and a third-party adhesive decal to "
        "return the exterior to a stock appearance prior to refinishing.",
        P,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Line items", H2))
    rows = [["#", "Operation", "Type", "Amount"]]
    line_ops = [
        ("Replace front bumper cover; refinish to factory colour",
         "Parts + body & paint", 712.40),
        ("Straighten and refinish hood panel",
         "Body & paint",         486.20),
        ("Replace left headlamp assembly; aim",
         "Parts + labour",       445.85),
        ("Straighten radiator support; verify alignment",
         "Body & frame",         318.60),
        ("Replace AC condenser; evacuate, recharge, leak-check",
         "Parts + labour",       402.30),
        ("Remove rooftop placard mount (suction-base accessory) and "
         "refinish roof rail to remove adhesive shadow",
         "Body & paint",         264.75),
        ("Detach and reattach interior dual phone-mount rig "
         "(driver and rear-seat cradles) for trim removal",
         "Labour",               118.40),
        ("Remove residue of trade-dress adhesive decal from left rear "
         "quarter window glass; polish",
         "Sublet",                95.50),
    ]
    for i, (op, kind, amt) in enumerate(line_ops, 1):
        rows.append([str(i), op, kind, f"${amt:,.2f}"])
    subtotal = round(sum(o[2] for o in line_ops), 2)
    tax = round(subtotal * 0.0925, 2)
    total = round(subtotal + tax, 2)
    rows.append(["", "", "Subtotal",       f"${subtotal:,.2f}"])
    rows.append(["", "", "Tax (9.25%)",    f"${tax:,.2f}"])
    rows.append(["", "", "Total estimate", f"${total:,.2f} USD"])
    t = Table(rows, colWidths=[0.3 * inch, 3.7 * inch, 1.4 * inch, 1.2 * inch])
    t.setStyle(TableStyle([
        ("FONT",          (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT",          (0, 0), (-1, 0),  "Helvetica-Bold", 9),
        ("FONT",          (-2, -3), (-1, -1), "Helvetica-Bold", 9),
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#eef3f8")),
        ("BACKGROUND",    (-2, -1), (-1, -1), colors.HexColor("#f6f8fb")),
        ("ALIGN",         (-1, 0), (-1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    s.append(t)
    s.append(Spacer(1, 10))

    s.append(Paragraph("Authorisation", H2))
    s.append(Paragraph(
        f"Estimate prepared by L. Nakamura, SeaTac Collision Center. Customer "
        f"signature on file. Authorised by {POLICYHOLDER['name']} on 2026-05-09. "
        "Estimate valid 30 days.",
        P,
    ))
    s.append(Spacer(1, 12))
    s.append(Paragraph("Fictional document for testing purposes only.", SMALL))
    doc.build(s)


# ---- member_policy.pdf ------------------------------------------------------
def member_policy():
    doc = _doc("member_policy.pdf")
    s = []
    s.append(Paragraph(
        f"{INSURER} — Auto Policy Declarations", H,
    ))
    s.append(Paragraph(
        f"Policy {POLICY_NUMBER} · Member {POLICYHOLDER['name']} · "
        f"Issued {POLICY['effective_date']}",
        SMALL,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Named insured", H2))
    s.append(_kv([
        ["Name",        POLICYHOLDER["name"]],
        ["Address",     POLICYHOLDER["street"]],
        ["City / State", f"{POLICYHOLDER['city']}, {POLICYHOLDER['state']} "
                         f"{POLICYHOLDER['postal_code']}"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Covered vehicle", H2))
    s.append(_kv([
        ["Vehicle",     f"{VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} {VEHICLE['trim']}"],
        ["VIN",         VEHICLE["vin"]],
        ["License plate", VEHICLE["license_plate"]],
        ["Garaging address", f"{POLICYHOLDER['street']}, {POLICYHOLDER['city']}, "
                             f"{POLICYHOLDER['state']}"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Coverage period", H2))
    s.append(_kv([
        ["Effective",  POLICY["effective_date"]],
        ["Expiration", POLICY["expiration_date"]],
        ["Term",       "12 months"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Use of vehicle (declared)", H2))
    s.append(_kv([
        ["Use class",            POLICY["use_class"]],
        ["Annual mileage est.",  "9,000 miles"],
        ["Business use",         "No"],
        ["Carry passengers for hire", "No"],
        ["Delivery / courier work",   "No"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Coverage summary", H2))
    rows = [["Coverage", "Limit", "Deductible"]]
    for cov, lim, ded in [
        ("Bodily injury liability (per person / per accident)",
         "$100,000 / $300,000", "—"),
        ("Property damage liability",       "$100,000",  "—"),
        ("Collision",                        "Actual cash value",
         f"${POLICY['deductible']:,.0f}"),
        ("Comprehensive",                    "Actual cash value",
         f"${POLICY['deductible']:,.0f}"),
        ("Uninsured / underinsured motorist",
         "$100,000 / $300,000",              "—"),
        ("Medical payments",                "$5,000",    "—"),
    ]:
        rows.append([cov, lim, ded])
    t = Table(rows, colWidths=[3.6 * inch, 2.2 * inch, 0.8 * inch])
    t.setStyle(TableStyle([
        ("FONT",          (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT",          (0, 0), (-1, 0),  "Helvetica-Bold", 9),
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#eef3f8")),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    s.append(t)
    s.append(Spacer(1, 12))

    s.append(Paragraph("Use exclusions (Section IV — Exclusions)", H2))
    s.append(Paragraph(
        "<b>Personal use only.</b> This policy provides coverage for the "
        "named insured's personal, family, and commute use of the covered "
        "vehicle. The following uses are <b>specifically excluded</b> and any "
        "loss arising during such use is not covered:",
        P,
    ))
    for line in [
        "Use of the covered vehicle to carry persons or property <b>for a "
        "fee, charge, or compensation of any kind</b>, including but not "
        "limited to ride-sharing, ride-hailing, livery, taxi, limousine, "
        "or any transportation network company (TNC) service.",
        "Use of the covered vehicle for <b>delivery of food, parcels, "
        "groceries, or other goods</b> for a fee, including for any "
        "third-party delivery platform.",
        "Any business or commercial use of the covered vehicle, "
        "including courier work or contract driving.",
        "Operation of the covered vehicle while logged in to, or "
        "available on, any rideshare or delivery driver application.",
    ]:
        s.append(Paragraph(f"• {line}", P))
    s.append(Spacer(1, 8))
    s.append(Paragraph(
        "If the member intends to use the vehicle for any of the above, a "
        "<b>commercial / TNC endorsement</b> must be added to the policy "
        "prior to such use. No such endorsement is in force on this policy.",
        P,
    ))
    s.append(Spacer(1, 12))
    s.append(Paragraph(
        "Fictional declarations page generated for demo purposes only.", SMALL,
    ))
    doc.build(s)


# ---- damage_photo.png (PIL fallback render) ---------------------------------
def damage_photo():
    """High-fidelity inspection-style photo (PIL render).

    This is a synthetic fallback. ``generate_image.py`` will overwrite the
    file with a real GPT-image render when valid Azure OpenAI / OpenAI
    credentials are available — see the README.

    The render emphasises the same commercial-use cues called out in the
    police narrative and repair estimate (rooftop placard mount, decal
    residue on the rear quarter window, dual phone-mount cradles visible
    through the driver's window) along with the front-end collision
    damage (crumpled bumper, buckled hood, cracked headlamp).
    """
    W, H = 1600, 1200
    img = Image.new("RGB", (W, H), (28, 32, 40))
    d = ImageDraw.Draw(img)

    # Night-time airport-area parking lot backdrop
    for y in range(0, 540):
        t = y / 540
        r = int(18 + (44 - 18) * t)
        g = int(22 + (52 - 22) * t)
        b = int(34 + (74 - 34) * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    # Distant terminal glow
    for x in range(W):
        glow = int(40 * math.exp(-((x - 1100) ** 2) / 80000))
        d.line([(x, 380), (x, 520)],
               fill=(40 + glow, 50 + glow, 70 + glow // 2))
    # Asphalt
    for y in range(540, H):
        t = (y - 540) / (H - 540)
        v = int(22 + 18 * t)
        d.line([(0, y), (W, y)], fill=(v, v + 2, v + 4))
    # Wet-look reflections
    for x in range(0, W, 40):
        d.line([(x, 720), (x + 20, 1180)], fill=(40, 46, 60), width=1)
    # Light pole pool
    for r in range(260, 0, -8):
        ad = ImageDraw.Draw(img, "RGBA")
        ad.ellipse((780 - r, 720 - r // 2, 780 + r, 720 + r // 2),
                   fill=(255, 230, 170, max(0, 30 - r // 10)))

    body_color = (28, 38, 70)         # midnight blue metallic
    body_dark = (12, 18, 36)
    body_hi = (90, 110, 160)

    # Sedan body (3/4 front-driver view emphasising front-end damage)
    body_pts = [
        (220, 920),    # rear bottom
        (220, 800),    # rear fender top
        (300, 720),    # trunk top
        (560, 660),    # roof rear
        (1020, 645),   # roof front
        (1180, 700),   # base of windshield
        (1320, 770),   # hood front (impacted, sagging)
        (1430, 870),   # bumper front
        (1380, 940),   # bumper bottom
    ]
    d.polygon(body_pts, fill=body_color, outline=body_dark)

    # Specular sheen along greenhouse line
    sheen = [(300, 720), (560, 660), (1020, 645), (1180, 700)]
    for i in range(len(sheen) - 1):
        d.line([sheen[i], sheen[i + 1]], fill=body_hi, width=4)

    # Door cut-lines
    for x1, y1, x2, y2 in [
        (430, 700, 430, 920), (700, 685, 700, 925), (980, 670, 990, 920),
    ]:
        d.line([(x1, y1), (x2, y2)], fill=body_dark, width=3)

    # Greenhouse / windows
    glass_pts = [
        (340, 700), (560, 670), (1020, 660), (1170, 700),
        (1020, 720), (560, 720),
    ]
    d.polygon(glass_pts, fill=(20, 24, 40), outline=body_dark)

    # Rear quarter window (where decal residue lives)
    qtr_glass = [(245, 720), (305, 700), (340, 720), (305, 760)]
    d.polygon(qtr_glass, fill=(36, 42, 60), outline=body_dark)
    # Decal residue ring
    d.ellipse((262, 720, 320, 758), outline=(170, 175, 190), width=2)
    d.ellipse((268, 724, 314, 754), outline=(120, 125, 140), width=1)

    # Driver door window (interior cues visible through it)
    drv_glass = [(440, 705), (560, 678), (700, 678), (700, 720)]
    d.polygon(drv_glass, fill=(50, 60, 82), outline=body_dark)
    # Two phone-mount cradles silhouetted on the dashboard
    d.rectangle((595, 712, 615, 720), fill=(20, 22, 30))
    d.rectangle((620, 712, 640, 720), fill=(20, 22, 30))
    # Dashcam silhouette on windshield
    d.rectangle((1080, 692, 1100, 702), fill=(20, 22, 30))

    # Wheels
    for cx, cy in [(360, 920), (1180, 920)]:
        d.ellipse((cx - 110, cy - 100, cx + 110, cy + 90), fill=body_dark)
        d.ellipse((cx - 95, cy - 85, cx + 95, cy + 85), fill=(14, 16, 20))
        d.ellipse((cx - 60, cy - 50, cx + 60, cy + 50), fill=(150, 156, 168))
        d.ellipse((cx - 50, cy - 40, cx + 50, cy + 40), fill=(80, 86, 100))
        for ang in range(0, 360, 72):
            x2 = cx + int(45 * math.cos(math.radians(ang)))
            y2 = cy + int(45 * math.sin(math.radians(ang)))
            d.line([(cx, cy), (x2, y2)], fill=(170, 176, 188), width=4)
        d.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=(60, 64, 72))

    # Rooftop placard mount (suction-base) above windshield
    d.rectangle((900, 605, 1020, 645), fill=(28, 30, 38), outline=body_dark)
    d.rectangle((915, 580, 1005, 610), fill=(40, 42, 52), outline=body_dark)
    d.text((928, 585), "TAXI", fill=(220, 200, 110))

    # ====================== DAMAGE LAYER ==================================
    rng = random.Random(11)

    # Crumpled front bumper — jagged edge + paint scrape
    bumper_top = [(1280, 815), (1300, 805), (1330, 800), (1370, 802),
                  (1410, 815), (1430, 830), (1432, 870)]
    d.polygon(bumper_top + [(1380, 940), (1300, 940)],
              fill=(20, 24, 40), outline=body_dark)
    # Buckled hood — irregular crease line
    crease = [(1180, 700), (1220, 720), (1255, 740), (1290, 765),
              (1320, 790), (1340, 810)]
    for i in range(len(crease) - 1):
        d.line([crease[i], crease[i + 1]], fill=body_dark, width=4)
        d.line([(crease[i][0], crease[i][1] - 2),
                (crease[i + 1][0], crease[i + 1][1] - 2)],
               fill=body_hi, width=1)
    # Cracked left headlamp
    d.polygon([(1310, 815), (1370, 815), (1380, 850), (1320, 855)],
              fill=(220, 220, 230), outline=body_dark)
    for _ in range(8):
        x0 = rng.randint(1315, 1375)
        y0 = rng.randint(820, 850)
        x1 = x0 + rng.randint(-12, 12)
        y1 = y0 + rng.randint(-8, 8)
        d.line([(x0, y0), (x1, y1)], fill=(40, 40, 60), width=1)
    # Coolant / AC condenser leak under bumper
    d.ellipse((1290, 940, 1430, 1000), fill=(40, 60, 90))

    # ====================== ANNOTATIONS / CALLOUTS ========================
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 34)
        meta_font = ImageFont.truetype("arial.ttf", 22)
        callout_font = ImageFont.truetype("arialbd.ttf", 18)
    except Exception:
        title_font = ImageFont.load_default()
        meta_font = ImageFont.load_default()
        callout_font = ImageFont.load_default()

    def callout(num, anchor_xy, label_xy, text, color=(255, 215, 90)):
        d.line([anchor_xy, label_xy], fill=color, width=2)
        cx, cy = anchor_xy
        d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=color,
                  outline=(20, 22, 28), width=2)
        d.text((cx - 7, cy - 12), str(num), fill=(20, 22, 28), font=callout_font)
        tw = int(10 * len(text))
        lx, ly = label_xy
        d.rectangle((lx - 6, ly - 6, lx + tw, ly + 28), fill=(0, 0, 0),
                    outline=color, width=1)
        d.text((lx, ly), text, fill=color, font=callout_font)

    callout(1, (1340, 830), (1100, 980),
            "Front-end collision damage — bumper, hood, headlamp, condenser")
    callout(2, (960, 605), (560, 540),
            "Rooftop placard mount (suction-base) — pre-existing accessory",
            color=(140, 200, 255))
    callout(3, (290, 738), (60, 880),
            "Adhesive decal residue on rear quarter window",
            color=(140, 200, 255))
    callout(4, (620, 716), (560, 980),
            "Two phone-mount cradles visible through driver window",
            color=(140, 200, 255))

    # Header / footer chrome
    d.rectangle((0, 0, W, 110), fill=(20, 22, 30))
    d.text((40, 28), f"{INSURER} — Claim {CLAIM_NUMBER}",
           fill=(230, 235, 248), font=title_font)
    d.text((40, 74),
           f"Vehicle: {VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} "
           f"({VEHICLE['license_plate']})  ·  "
           f"Inspection {INCIDENT['date_of_loss']}  ·  "
           f"SeaTac Collision Center intake bay 2",
           fill=(180, 195, 220), font=meta_font)
    d.rectangle((0, H - 50, W, H), fill=(20, 22, 30))
    d.text((40, H - 38),
           "Inspection photo — adjuster: M. Patel  ·  collision damage + "
           "3 commercial-use indicators flagged",
           fill=(170, 180, 200), font=meta_font)

    out = OUT_DIR / "damage_photo.png"
    img.save(out, format="PNG")


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    claim_form()
    police_report()
    repair_estimate()
    member_policy()
    damage_photo()
    for p in sorted(OUT_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in {".pdf", ".png"}:
            print(f"  wrote {p.name} ({p.stat().st_size // 1024} KB)")

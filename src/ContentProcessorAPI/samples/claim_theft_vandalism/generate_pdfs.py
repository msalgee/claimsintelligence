"""Generate sample documents for a vehicle theft & vandalism claim scenario.

Different from the existing samples (which are all collision claims), this
exercises the Auto Claim schema set with:

  * Cause of loss = recovered theft + vandalism
  * Different insurer (Northwind Mutual), persona, vehicle, and state
  * No moving violation; police report focuses on recovery + forced entry
  * Damage is concentrated on ignition, steering column, broken side window,
    and key-scratched paintwork (vs. crash deformation in the other samples)

Run from repo root:
    python src/ContentProcessorAPI/samples/claim_theft_vandalism/generate_pdfs.py
"""
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
CLAIM_NUMBER = "NM-CLM-2026-04-882"
POLICY_NUMBER = "NM-AUTO-554301"

POLICYHOLDER = {
    "name": "Marcus Bell",
    "street": "412 Birchwood Lane",
    "city": "Bellevue",
    "state": "WA",
    "postal_code": "98007",
    "country": "USA",
    "phone": "(206) 555-0184",
    "email": "marcus.bell@example.com",
}

POLICY = {
    "coverage_type": "Auto Comprehensive",
    "effective_date": "2025-08-01",
    "expiration_date": "2026-07-31",
    "deductible": 250.0,
    "deductible_currency": "USD",
}

INCIDENT = {
    "date_of_loss": "2026-04-22",      # vehicle reported stolen overnight
    "time_of_loss": "02:30",
    "location": "200 block of NE 8th St, Bellevue, WA",
    "cause_of_loss": "Vehicle theft and vandalism — recovered with damage",
    "description": (
        "Vehicle was parked overnight on residential street and reported stolen at 06:40 "
        "the following morning. Recovered by Bellevue PD approximately 14 hours later in "
        "an industrial parking lot, with broken driver-side window, damaged ignition and "
        "steering column, and key-scratch graffiti on both rear quarter panels. "
        "No collision damage."
    ),
    "police_report_filed": True,
    "police_report_number": "BPD-2026-04-22-3119",
}

VEHICLE = {
    "year": "2023",
    "make": "Honda",
    "model": "Civic",
    "trim": "EX-L",
    "vin": "2HGFE2F58NH512784",
    "license_plate": "WA-TRJ8821",
    "mileage": 28430,
}

DAMAGE_ITEMS = [
    # (description, cost_new, repair_estimate)
    ("Driver-side front window glass",        420.0,  365.40),
    ("Ignition cylinder & key system",        680.0,  724.10),
    ("Steering column lock assembly",         540.0,  612.85),
    ("Rear quarter panel paint repair (L)",   900.0,  815.50),
    ("Rear quarter panel paint repair (R)",   900.0,  788.20),
    ("Interior cleaning & deodorisation",     150.0,  185.00),
]
TOTAL_REPAIR = round(sum(item[2] for item in DAMAGE_ITEMS), 2)  # 3491.05

DECLARATION_DATE = "2026-04-24"
SUBMISSION = {
    "submission_email": "claims@northwindmutual.example.com",
    "portal_url": "https://claims.northwindmutual.example.com",
    "notes": "Submit recovery report and inspection photos within 14 days.",
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

    s.append(Paragraph("Vehicle information", H2))
    s.append(_kv([
        ["Year",          VEHICLE["year"]],
        ["Make",          VEHICLE["make"]],
        ["Model",         VEHICLE["model"]],
        ["Trim",          VEHICLE["trim"]],
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
    s.append(Paragraph("Bellevue Police Department — Vehicle Theft & Recovery Report", H))
    s.append(Paragraph(
        f"Report {INCIDENT['police_report_number']} · Filed 2026-04-22 06:55",
        SMALL,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Incident", H2))
    s.append(_kv([
        ["Date of incident",    INCIDENT["date_of_loss"]],
        ["Time of incident",    INCIDENT["time_of_loss"]],
        ["Location reported",   INCIDENT["location"]],
        ["Recovered location",  "1840 124th Ave NE (industrial lot), Bellevue, WA"],
        ["Recovered date/time", "2026-04-22 16:50"],
        ["Reporting party",     POLICYHOLDER["name"]],
        ["Officer in charge",   "Ofc. R. Singh, Badge #4117"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Vehicle (recovered)", H2))
    s.append(_kv([
        ["Make / Model",  f"{VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} {VEHICLE['trim']}"],
        ["VIN",           VEHICLE["vin"]],
        ["License plate", VEHICLE["license_plate"]],
        ["Mileage at recovery", f"{VEHICLE['mileage']:,}"],
        ["Insured",       f"{POLICYHOLDER['name']} ({INSURER}, policy {POLICY_NUMBER})"],
        ["Claim number",  CLAIM_NUMBER],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Narrative", H2))
    s.append(Paragraph(
        f"Reporting party {POLICYHOLDER['name']} contacted dispatch at 06:40 on "
        f"{INCIDENT['date_of_loss']} stating his {VEHICLE['year']} {VEHICLE['make']} "
        f"{VEHICLE['model']} (plate {VEHICLE['license_plate']}) had been taken from the "
        f"{INCIDENT['location']} between 22:00 the previous evening and his discovery "
        "this morning. Vehicle was entered as stolen on WACIC at 07:08. Recovered later "
        "the same day by patrol unit responding to a suspicious-vehicle call. No suspects "
        "were on scene. Vehicle showed forced entry via the driver-side front window, "
        "damaged ignition and steering column, and key-scratch graffiti on both rear "
        "quarter panels. No collision damage observed. No injuries reported. Vehicle "
        "released to owner at scene after evidence processing.",
        P,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Observed damage", H2))
    for line in [
        "Driver-side front window glass shattered (entry point)",
        "Ignition cylinder forced; steering column lock damaged",
        "Key-scratch graffiti on left and right rear quarter panels",
        "Interior cluttered; minor unknown debris on floor mats",
    ]:
        s.append(Paragraph(f"• {line}", P))
    s.append(Spacer(1, 12))
    s.append(Paragraph("Signed: Ofc. R. Singh, 2026-04-22", SMALL))
    doc.build(s)


# ---- repair_estimate.pdf ----------------------------------------------------
def repair_estimate():
    doc = _doc("repair_estimate.pdf")
    s = []
    s.append(Paragraph("Eastside Auto Body — Repair Estimate", H))
    s.append(Paragraph(
        f"Estimate ESB-26-2204 · Prepared 2026-04-23 for {POLICYHOLDER['name']}",
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
        ["VIN",           VEHICLE["vin"]],
        ["License plate", VEHICLE["license_plate"]],
        ["Mileage",       f"{VEHICLE['mileage']:,}"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Cause of damage", H2))
    s.append(Paragraph(
        "Vehicle was stolen overnight and recovered with forced-entry damage to the "
        "driver-side front window, ignition and steering column, plus key-scratch "
        "graffiti on both rear quarter panels. Mechanically driveable; no collision "
        "deformation. Interior requires cleaning.", P,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Line items", H2))
    rows = [["#", "Operation", "Type", "Amount"]]
    line_ops = [
        ("Replace driver-side front window glass; remove glass debris", "Parts + labour", 365.40),
        ("Replace ignition cylinder; rekey to existing key set",        "Parts + labour", 724.10),
        ("Repair steering column lock; replace shroud trim",            "Parts + labour", 612.85),
        ("Wet-sand, repair and refinish left rear quarter panel",       "Body & paint",   815.50),
        ("Wet-sand, repair and refinish right rear quarter panel",      "Body & paint",   788.20),
        ("Interior detail, deodorisation, evidence-residue cleanup",    "Sublet",         185.00),
    ]
    for i, (op, kind, amt) in enumerate(line_ops, 1):
        rows.append([str(i), op, kind, f"${amt:,.2f}"])
    subtotal = round(sum(o[2] for o in line_ops), 2)
    tax = round(subtotal * 0.0925, 2)
    total = round(subtotal + tax, 2)
    rows.append(["", "", "Subtotal",      f"${subtotal:,.2f}"])
    rows.append(["", "", "Tax (9.25%)",   f"${tax:,.2f}"])
    rows.append(["", "", "Total estimate", f"${total:,.2f} USD"])
    t = Table(rows, colWidths=[0.3 * inch, 3.7 * inch, 1.2 * inch, 1.4 * inch])
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
        f"Estimate prepared by D. Tran, Eastside Auto Body. Customer signature on file. "
        f"Authorised by {POLICYHOLDER['name']} on 2026-04-23. Estimate valid 30 days.",
        P,
    ))
    s.append(Spacer(1, 12))
    s.append(Paragraph("Fictional document for testing purposes only.", SMALL))
    doc.build(s)


# ---- damage_photo.png -------------------------------------------------------
def damage_photo():
    """Synthesised inspection-style photo of the recovered vehicle.

    Drawn with PIL — not a real photograph, but rendered with enough
    perspective, shading, and damage detail (radial-crack shattered driver
    window, multiple key-scratch lines on the rear quarter panel, pried
    door-lock cylinder) that a vision model recognises it as a vehicle
    inspection photo rather than text content.
    """
    import math
    import random

    W, H = 1600, 1200
    img = Image.new("RGB", (W, H), (40, 44, 52))
    d = ImageDraw.Draw(img)

    # ---- Background: asphalt parking lot with horizon ---------------------
    # Sky / shop wall (top third)
    for y in range(0, 480):
        t = y / 480
        r = int(70 + (110 - 70) * t)
        g = int(76 + (118 - 76) * t)
        b = int(86 + (128 - 86) * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    # Asphalt (bottom two thirds) with slight gradient
    for y in range(480, H):
        t = (y - 480) / (H - 480)
        v = int(38 + 22 * t)
        d.line([(0, y), (W, y)], fill=(v, v + 2, v + 4))
    # Parking-lot stripes (perspective)
    for x0, x1 in [(120, 240), (520, 580), (1020, 1070), (1380, 1480)]:
        d.polygon([(x0, 1180), (x1, 1180), (x1 + 60, 900), (x0 + 60, 900)],
                  fill=(220, 200, 90))
    # Horizon line / shop wall trim
    d.line([(0, 480), (W, 480)], fill=(28, 30, 36), width=3)

    # ---- Ground shadow under car -----------------------------------------
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((180, 880, 1480, 1010), fill=(0, 0, 0, 140))
    img.paste(shadow, (0, 0), shadow)

    # ---- Sedan body (3/4 rear-driver view) -------------------------------
    # Outline points approximate a sedan profile in 3/4 perspective.
    body_color = (62, 70, 86)
    body_dark = (38, 44, 56)
    body_hi = (110, 122, 144)

    # Lower body (rocker + doors + quarter panel)
    body_pts = [
        (260, 880),    # front bottom
        (260, 760),    # front fender top-front
        (300, 700),    # hood front
        (520, 660),    # hood mid
        (640, 600),    # base of windshield
        (760, 520),    # roof front
        (1180, 510),   # roof rear
        (1310, 580),   # base of rear window
        (1430, 720),   # trunk top
        (1470, 800),   # rear bumper top
        (1450, 880),   # rear bumper bottom
    ]
    d.polygon(body_pts, fill=body_color, outline=body_dark)

    # Highlight along door tops (specular sheen)
    sheen = [
        (520, 660), (640, 600), (760, 520),
        (1180, 510), (1310, 580), (1430, 720),
    ]
    for i in range(len(sheen) - 1):
        d.line([sheen[i], sheen[i + 1]], fill=body_hi, width=4)

    # Door cut-lines
    door_lines = [(720, 600, 720, 880), (940, 600, 960, 880), (1160, 600, 1200, 880)]
    for x1, y1, x2, y2 in door_lines:
        d.line([(x1, y1), (x2, y2)], fill=body_dark, width=3)

    # Body crease (mid-height swoosh)
    d.line([(290, 800), (1450, 820)], fill=body_dark, width=2)
    d.line([(290, 802), (1450, 822)], fill=body_hi, width=1)

    # ---- Greenhouse (windows) --------------------------------------------
    glass_pts = [
        (660, 600), (770, 540), (1180, 530), (1300, 590),
        (1180, 620), (770, 620),
    ]
    d.polygon(glass_pts, fill=(28, 34, 46), outline=body_dark)
    # B-pillar and C-pillar
    d.polygon([(885, 540), (905, 540), (910, 620), (890, 620)], fill=body_dark)
    d.polygon([(1100, 540), (1120, 540), (1130, 620), (1110, 620)], fill=body_dark)

    # Driver door window (front-left in 3/4 view) — separate quad so we can
    # later overlay the shattered glass and impact crack pattern.
    drv_glass = [(700, 605), (770, 555), (885, 555), (885, 615)]
    d.polygon(drv_glass, fill=(120, 132, 150), outline=body_dark)

    # Rear door window
    rear_glass = [(910, 555), (1100, 555), (1100, 615), (910, 615)]
    d.polygon(rear_glass, fill=(40, 50, 68), outline=body_dark)

    # Rear quarter window
    qtr_glass = [(1130, 555), (1180, 540), (1290, 590), (1130, 615)]
    d.polygon(qtr_glass, fill=(40, 50, 68), outline=body_dark)

    # ---- Wheels with arches ----------------------------------------------
    for cx, cy in [(420, 880), (1280, 880)]:
        # Wheel arch
        d.ellipse((cx - 130, cy - 110, cx + 130, cy + 90), fill=body_dark)
        # Tyre
        d.ellipse((cx - 110, cy - 90, cx + 110, cy + 90), fill=(18, 20, 24))
        # Rim
        d.ellipse((cx - 70, cy - 50, cx + 70, cy + 50), fill=(150, 156, 168))
        d.ellipse((cx - 60, cy - 40, cx + 60, cy + 40), fill=(95, 100, 112))
        # Spokes
        for ang in range(0, 360, 72):
            x2 = cx + int(55 * math.cos(math.radians(ang)))
            y2 = cy + int(55 * math.sin(math.radians(ang)))
            d.line([(cx, cy), (x2, y2)], fill=(170, 176, 188), width=4)
        d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=(60, 64, 72))

    # ---- Trim details ----------------------------------------------------
    # Tail-light (rear)
    d.polygon([(1390, 720), (1465, 740), (1470, 790), (1395, 790)], fill=(180, 40, 50))
    d.polygon([(1395, 745), (1455, 755), (1455, 775), (1395, 775)], fill=(255, 220, 220))
    # Side mirror
    d.polygon([(700, 590), (740, 580), (740, 615), (705, 620)], fill=body_dark)
    # Door handles
    for hx in (820, 1040):
        d.rounded_rectangle((hx, 700, hx + 70, 720), radius=6, fill=body_hi)
    # Door lock cylinder (driver door) — drawn separately so we can mark it
    # as the pried lock damage callout below.
    lock_x, lock_y = 800, 740
    d.ellipse((lock_x - 10, lock_y - 10, lock_x + 10, lock_y + 10), fill=(200, 205, 215))
    # License plate (rear)
    d.rounded_rectangle((1330, 815, 1450, 855), radius=4, fill=(245, 240, 220),
                        outline=body_dark)
    try:
        plate_font = ImageFont.truetype("arialbd.ttf", 22)
    except Exception:
        plate_font = ImageFont.load_default()
    d.text((1340, 822), VEHICLE["license_plate"], fill=(40, 40, 60), font=plate_font)

    # ====================== DAMAGE LAYER ==================================
    rng = random.Random(7)

    # Damage 1: shattered driver window with radial crack pattern
    impact = (820, 585)
    # Whitish frosted glass near impact
    for r in range(60, 0, -8):
        alpha_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ad = ImageDraw.Draw(alpha_layer)
        ad.ellipse((impact[0] - r, impact[1] - r, impact[0] + r, impact[1] + r),
                   fill=(245, 248, 255, max(20, 60 - r)))
        img.paste(alpha_layer, (0, 0), alpha_layer)
    # Radial cracks
    for ang in range(0, 360, 18):
        length = rng.randint(45, 95)
        x2 = impact[0] + int(length * math.cos(math.radians(ang)))
        y2 = impact[1] + int(length * 0.55 * math.sin(math.radians(ang)))
        # Clip endpoints to driver glass area
        if 705 < x2 < 880 and 560 < y2 < 615:
            d.line([impact, (x2, y2)], fill=(250, 252, 255), width=2)
            # Forks
            for _ in range(2):
                fa = ang + rng.randint(-25, 25)
                fl = rng.randint(15, 35)
                fx = x2 + int(fl * math.cos(math.radians(fa)))
                fy = y2 + int(fl * 0.55 * math.sin(math.radians(fa)))
                d.line([(x2, y2), (fx, fy)], fill=(235, 240, 250), width=1)
    # Concentric crack rings
    for rr in (18, 32, 48):
        d.ellipse((impact[0] - rr, impact[1] - int(rr * 0.55),
                   impact[0] + rr, impact[1] + int(rr * 0.55)),
                  outline=(245, 248, 255), width=1)
    # Hole at impact (dark)
    d.ellipse((impact[0] - 8, impact[1] - 5, impact[0] + 8, impact[1] + 5),
              fill=(15, 18, 24))

    # Damage 2: key scratches across rear door + quarter panel (multiple
    # uneven lines, slightly curved with paint chips alongside).
    base_y = 770
    for i in range(6):
        y0 = base_y + i * 8 + rng.randint(-3, 3)
        pts = []
        for x in range(940, 1380, 12):
            jitter = rng.randint(-3, 3)
            pts.append((x, y0 + jitter + int(8 * math.sin(x * 0.02))))
        d.line(pts, fill=(195, 198, 208), width=2)
        # Paint chips
        for px, py in pts[::6]:
            d.ellipse((px - 2, py - 2, px + 2, py + 2), fill=(220, 220, 230))

    # Damage 3: pried door-lock cylinder — gouge marks around the lock
    for ang in (-30, -10, 20, 50, 80):
        x2 = lock_x + int(28 * math.cos(math.radians(ang)))
        y2 = lock_y + int(28 * math.sin(math.radians(ang)))
        d.line([(lock_x, lock_y), (x2, y2)], fill=(230, 232, 240), width=2)
    d.ellipse((lock_x - 12, lock_y - 12, lock_x + 12, lock_y + 12),
              outline=(245, 230, 110), width=3)

    # ====================== ANNOTATIONS / CALLOUTS ========================
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 34)
        meta_font = ImageFont.truetype("arial.ttf", 22)
        callout_font = ImageFont.truetype("arialbd.ttf", 20)
    except Exception:
        title_font = ImageFont.load_default()
        meta_font = ImageFont.load_default()
        callout_font = ImageFont.load_default()

    def callout(num, anchor_xy, label_xy, text, color=(255, 215, 90)):
        # Connector line + numbered marker + text label with dark background.
        d.line([anchor_xy, label_xy], fill=color, width=2)
        cx, cy = anchor_xy
        d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=color,
                  outline=(20, 22, 28), width=2)
        d.text((cx - 7, cy - 12), str(num), fill=(20, 22, 28), font=callout_font)
        # Label text bg
        tw = int(11 * len(text))
        lx, ly = label_xy
        d.rectangle((lx - 6, ly - 6, lx + tw, ly + 30), fill=(0, 0, 0, 200),
                    outline=color, width=1)
        d.text((lx, ly), text, fill=color, font=callout_font)

    callout(1, impact, (180, 380),
            "Driver window — shattered (entry point)")
    callout(2, (1160, 780), (1160, 980),
            "Key-scratches — rear door & quarter panel", color=(255, 130, 130))
    callout(3, (lock_x, lock_y), (380, 1010),
            "Door-lock cylinder — pried / forced")

    # ---- Header / footer chrome -----------------------------------------
    d.rectangle((0, 0, W, 110), fill=(20, 22, 30))
    d.text((40, 28), f"{INSURER} — Claim {CLAIM_NUMBER}",
           fill=(230, 235, 248), font=title_font)
    d.text((40, 74),
           f"Vehicle: {VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} "
           f"({VEHICLE['license_plate']})  ·  Recovered 2026-04-22  ·  "
           f"Eastside Auto Body intake bay 3",
           fill=(180, 195, 220), font=meta_font)
    d.rectangle((0, H - 50, W, H), fill=(20, 22, 30))
    d.text((40, H - 38),
           "Inspection photo — adjuster: M. Patel  ·  3 damage points flagged "
           "(window, paint, lock)",
           fill=(170, 180, 200), font=meta_font)

    out = OUT_DIR / "damage_photo.png"
    img.save(out, format="PNG")


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    claim_form()
    police_report()
    repair_estimate()
    damage_photo()
    for p in sorted(OUT_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in {".pdf", ".png"}:
            print(f"  wrote {p.name} ({p.stat().st_size // 1024} KB)")

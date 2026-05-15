"""Generate sample documents for a severe-hail comprehensive claim scenario.

Different from the theft/vandalism and collision samples — this exercises the
Auto Claim schema set with:

  * Cause of loss = severe hail storm (comprehensive, weather)
  * Different insurer (Summit Heritage Insurance), persona, vehicle, and state
  * "Police report" slot is a city/PD storm-damage incident report filed
    after a confirmed severe-weather event (still classifies as PoliceReport)
  * Damage is concentrated on hood, roof, trunk dents and cracked windshield
    (no theft, no collision deformation, no moving violation)

Run from repo root:
    python src/ContentProcessorAPI/samples/claim_hail_storm/generate_pdfs.py
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
INSURER = "Summit Heritage Insurance"
CLAIM_NUMBER = "SHI-CLM-2026-05-1147"
POLICY_NUMBER = "SHI-AUTO-708216"

POLICYHOLDER = {
    "name": "Priya Ramaswamy",
    "street": "2204 Larimer Heights Dr",
    "city": "Aurora",
    "state": "CO",
    "postal_code": "80013",
    "country": "USA",
    "phone": "(303) 555-0142",
    "email": "priya.ramaswamy@example.com",
}

POLICY = {
    "coverage_type": "Auto Comprehensive",
    "effective_date": "2025-09-15",
    "expiration_date": "2026-09-14",
    "deductible": 500.0,
    "deductible_currency": "USD",
}

INCIDENT = {
    "date_of_loss": "2026-05-02",
    "time_of_loss": "17:45",
    "location": "Driveway of 2204 Larimer Heights Dr, Aurora, CO 80013",
    "cause_of_loss": "Severe hail storm — comprehensive weather damage",
    "description": (
        "Vehicle was parked in the residential driveway when a severe thunderstorm "
        "with golfball- to baseball-sized hail moved across south Aurora. Storm "
        "duration approximately 12 minutes. Vehicle sustained extensive denting on "
        "the hood, roof, and trunk lid, and the windshield was cracked by a large "
        "hailstone impact near the upper passenger side. No injuries; no third "
        "parties involved."
    ),
    "police_report_filed": True,
    "police_report_number": "APD-2026-05-02-SR-0418",
}

VEHICLE = {
    "year": "2024",
    "make": "Toyota",
    "model": "RAV4",
    "trim": "XLE Hybrid",
    "vin": "JTMRWRFV5RD082914",
    "license_plate": "CO-HRT2240",
    "mileage": 14860,
}

DAMAGE_ITEMS = [
    # (description, cost_new, repair_estimate)
    ("Paintless dent repair — hood (38 dents)",          1200.0, 1185.00),
    ("Paintless dent repair — roof (52 dents)",          1450.0, 1620.00),
    ("Paintless dent repair — trunk lid (24 dents)",      820.0,  865.00),
    ("Replace windshield (acoustic, ADAS recalibration)",  920.0,  978.40),
    ("Replace front passenger A-pillar trim",              140.0,  152.50),
    ("Detail / paint inspection & polish",                 220.0,  245.00),
]
TOTAL_REPAIR = round(sum(item[2] for item in DAMAGE_ITEMS), 2)

DECLARATION_DATE = "2026-05-04"
SUBMISSION = {
    "submission_email": "claims@summitheritage.example.com",
    "portal_url": "https://claims.summitheritage.example.com",
    "notes": "Submit NWS storm confirmation, PD incident number and inspection photos within 14 days.",
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
        f"Claim {CLAIM_NUMBER} · Policy {POLICY_NUMBER} · Form SHI-AIC-301",
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
        ["NWS storm confirmation", "Yes (LSR Aurora 2026-05-02)"],
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
    s.append(Paragraph("Aurora Police Department — Severe Weather Incident Report", H))
    s.append(Paragraph(
        f"Report {INCIDENT['police_report_number']} · Filed 2026-05-02 19:10",
        SMALL,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Incident", H2))
    s.append(_kv([
        ["Date of incident",    INCIDENT["date_of_loss"]],
        ["Time of incident",    INCIDENT["time_of_loss"]],
        ["Location reported",   INCIDENT["location"]],
        ["Storm corridor",      "South Aurora — E Hampden Ave to E Quincy Ave"],
        ["Reporting party",     POLICYHOLDER["name"]],
        ["Officer in charge",   "Ofc. J. Reyes, Badge #2718"],
        ["NWS reference",       "NWS Boulder LSR 2026-05-02 17:38 MDT"],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Vehicle (damaged in place)", H2))
    s.append(_kv([
        ["Make / Model",  f"{VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} {VEHICLE['trim']}"],
        ["VIN",           VEHICLE["vin"]],
        ["License plate", VEHICLE["license_plate"]],
        ["Mileage",       f"{VEHICLE['mileage']:,}"],
        ["Insured",       f"{POLICYHOLDER['name']} ({INSURER}, policy {POLICY_NUMBER})"],
        ["Claim number",  CLAIM_NUMBER],
    ]))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Narrative", H2))
    s.append(Paragraph(
        f"Reporting party {POLICYHOLDER['name']} contacted the non-emergency line at "
        f"18:42 on {INCIDENT['date_of_loss']} requesting a documented incident report "
        "for insurance purposes following a confirmed severe thunderstorm event. The "
        "National Weather Service Boulder office issued a Severe Thunderstorm Warning "
        "for south Aurora at 17:24 MDT and confirmed hail of 1.75 to 2.50 inches "
        "diameter (golfball to baseball) in the affected corridor via Local Storm "
        f"Report at 17:38 MDT. The reporting party's {VEHICLE['year']} {VEHICLE['make']} "
        f"{VEHICLE['model']} (plate {VEHICLE['license_plate']}) was parked in the "
        "residential driveway at the address above and could not be moved to shelter "
        "before the storm arrived. Responding officer observed extensive hail dimpling "
        "across hood, roof and trunk surfaces and a single large impact crack in the "
        "windshield near the upper passenger side. No suspects, no third parties, no "
        "injuries. Vehicle remained at the scene; owner advised to contact insurer.",
        P,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Observed damage", H2))
    for line in [
        "Hood: extensive dimpling across full surface (~30+ visible dents)",
        "Roof: extensive dimpling across full surface (~50+ visible dents)",
        "Trunk lid: moderate dimpling (~20+ visible dents)",
        "Windshield: large impact crack, upper passenger side, spreading laterally",
        "No body deformation; no broken side windows; no theft / forced entry",
    ]:
        s.append(Paragraph(f"• {line}", P))
    s.append(Spacer(1, 12))
    s.append(Paragraph("Signed: Ofc. J. Reyes, 2026-05-02", SMALL))
    doc.build(s)


# ---- repair_estimate.pdf ----------------------------------------------------
def repair_estimate():
    doc = _doc("repair_estimate.pdf")
    s = []
    s.append(Paragraph("Front Range Dent & Glass — Repair Estimate", H))
    s.append(Paragraph(
        f"Estimate FRDG-26-5104 · Prepared 2026-05-03 for {POLICYHOLDER['name']}",
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
        "Vehicle sustained widespread hail damage during a confirmed severe "
        "thunderstorm event in south Aurora on 2026-05-02. Damage is limited to "
        "horizontal panels (hood, roof, trunk) plus the windshield. No body-line "
        "deformation; no mechanical damage. Eligible for paintless dent repair (PDR) "
        "across all impacted panels.",
        P,
    ))
    s.append(Spacer(1, 10))

    s.append(Paragraph("Line items", H2))
    rows = [["#", "Operation", "Type", "Amount"]]
    line_ops = [
        ("Paintless dent repair — hood (~38 dents, all repairable by PDR)",       "PDR",            1185.00),
        ("Paintless dent repair — roof (~52 dents, full panel)",                  "PDR",            1620.00),
        ("Paintless dent repair — trunk lid (~24 dents)",                         "PDR",             865.00),
        ("R&R windshield (OEM acoustic), incl. ADAS camera recalibration",        "Glass + ADAS",    978.40),
        ("Replace front passenger A-pillar trim (deformed during glass R&R)",     "Parts + labour",  152.50),
        ("Detail, paint surface inspection and machine polish",                   "Sublet",          245.00),
    ]
    for i, (op, kind, amt) in enumerate(line_ops, 1):
        rows.append([str(i), op, kind, f"${amt:,.2f}"])
    subtotal = round(sum(o[2] for o in line_ops), 2)
    tax = round(subtotal * 0.0810, 2)  # Aurora, CO
    total = round(subtotal + tax, 2)
    rows.append(["", "", "Subtotal",       f"${subtotal:,.2f}"])
    rows.append(["", "", "Tax (8.10%)",    f"${tax:,.2f}"])
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
        f"Estimate prepared by C. Larkin, Front Range Dent & Glass. Customer signature "
        f"on file. Authorised by {POLICYHOLDER['name']} on 2026-05-03. Estimate valid "
        "30 days. PDR results subject to final inspection after panel cleanup.",
        P,
    ))
    s.append(Spacer(1, 12))
    s.append(Paragraph("Fictional document for testing purposes only.", SMALL))
    doc.build(s)


# ---- damage_photo.png -------------------------------------------------------
def damage_photo():
    """Synthesised inspection-style photo of the hail-damaged vehicle.

    Shows a top-down 3/4 view of an SUV with extensive hail dimpling on hood,
    roof, and trunk panels and a large windshield impact crack — annotated
    with three numbered callouts for the adjuster.
    """
    import math
    import random

    W, H = 1600, 1200
    img = Image.new("RGB", (W, H), (40, 44, 52))
    d = ImageDraw.Draw(img)

    # ---- Background: stormy sky over wet driveway ------------------------
    for y in range(0, 520):
        t = y / 520
        r = int(50 + (95 - 50) * t)
        g = int(58 + (105 - 58) * t)
        b = int(74 + (120 - 74) * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    # Driveway concrete (wet, slightly reflective gradient)
    for y in range(520, H):
        t = (y - 520) / (H - 520)
        v = int(70 + 38 * t)
        d.line([(0, y), (W, y)], fill=(v, v + 4, v + 8))
    # Driveway expansion lines
    for x in (300, 760, 1220):
        d.line([(x - 80, 1180), (x + 80, 700)], fill=(50, 54, 60), width=2)
    # Horizon
    d.line([(0, 520), (W, 520)], fill=(28, 30, 36), width=3)

    # Scattered hailstones on the driveway (white circles, varied size)
    rng_bg = random.Random(42)
    for _ in range(140):
        x = rng_bg.randint(40, W - 40)
        y = rng_bg.randint(880, H - 80)
        r = rng_bg.choice([4, 5, 6, 7, 8, 10])
        d.ellipse((x - r, y - r, x + r, y + r), fill=(225, 230, 240))
        d.ellipse((x - r + 1, y - r + 1, x - r + 4, y - r + 4),
                  fill=(250, 252, 255))

    # ---- Vehicle body (SUV — RAV4-ish 3/4 front-passenger view) ---------
    body_color = (140, 18, 30)        # deep red SUV
    body_dark = (78, 12, 20)
    body_hi = (210, 90, 100)

    # SUV silhouette — taller greenhouse than the sedan
    body_pts = [
        (240, 920),    # front bottom
        (240, 780),    # front fender
        (290, 700),    # hood front
        (440, 660),    # hood mid
        (560, 600),    # base of windshield
        (660, 480),    # roof front
        (1200, 470),   # roof rear
        (1330, 560),   # base of rear window
        (1450, 720),   # tailgate top
        (1490, 820),   # rear bumper top
        (1470, 920),   # rear bumper bottom
    ]
    d.polygon(body_pts, fill=body_color, outline=body_dark)

    # Specular sheen along upper edges
    sheen = [(440, 660), (560, 600), (660, 480),
             (1200, 470), (1330, 560), (1450, 720)]
    for i in range(len(sheen) - 1):
        d.line([sheen[i], sheen[i + 1]], fill=body_hi, width=4)

    # Door cut-lines (doors)
    for x1, y1, x2, y2 in [(680, 600, 700, 920), (920, 600, 950, 920),
                           (1180, 600, 1230, 920)]:
        d.line([(x1, y1), (x2, y2)], fill=body_dark, width=3)

    # Body crease swoosh
    d.line([(280, 820), (1470, 850)], fill=body_dark, width=2)
    d.line([(280, 822), (1470, 852)], fill=body_hi, width=1)

    # ---- Greenhouse / windows -------------------------------------------
    # Windshield (front passenger side visible)
    windshield_pts = [(560, 600), (660, 490), (840, 488), (730, 605)]
    d.polygon(windshield_pts, fill=(120, 145, 175), outline=body_dark)
    # Front side (driver) door window
    d.polygon([(740, 605), (830, 555), (885, 555), (885, 615)],
              fill=(40, 50, 68), outline=body_dark)
    # Rear door window
    d.polygon([(910, 555), (1100, 555), (1100, 615), (910, 615)],
              fill=(40, 50, 68), outline=body_dark)
    # Rear quarter window
    d.polygon([(1130, 555), (1200, 540), (1310, 590), (1130, 615)],
              fill=(40, 50, 68), outline=body_dark)
    # B/C pillars
    d.polygon([(885, 540), (905, 540), (910, 620), (890, 620)], fill=body_dark)
    d.polygon([(1100, 540), (1120, 540), (1130, 620), (1110, 620)], fill=body_dark)

    # ---- Wheels / arches ------------------------------------------------
    for cx, cy in [(420, 920), (1300, 920)]:
        d.ellipse((cx - 140, cy - 120, cx + 140, cy + 100), fill=body_dark)
        d.ellipse((cx - 115, cy - 95, cx + 115, cy + 95), fill=(18, 20, 24))
        d.ellipse((cx - 75, cy - 55, cx + 75, cy + 55), fill=(150, 156, 168))
        d.ellipse((cx - 65, cy - 45, cx + 65, cy + 45), fill=(95, 100, 112))
        for ang in range(0, 360, 60):
            x2 = cx + int(58 * math.cos(math.radians(ang)))
            y2 = cy + int(58 * math.sin(math.radians(ang)))
            d.line([(cx, cy), (x2, y2)], fill=(170, 176, 188), width=4)
        d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=(60, 64, 72))

    # Trim
    d.polygon([(1410, 720), (1490, 740), (1490, 790), (1415, 790)],
              fill=(180, 40, 50))  # tail-light
    d.polygon([(1415, 745), (1480, 755), (1480, 775), (1415, 775)],
              fill=(255, 220, 220))
    d.polygon([(740, 588), (780, 578), (780, 615), (745, 620)], fill=body_dark)
    for hx in (820, 1040):
        d.rounded_rectangle((hx, 700, hx + 70, 720), radius=6, fill=body_hi)
    # License plate
    d.rounded_rectangle((1370, 835, 1490, 875), radius=4, fill=(245, 240, 220),
                        outline=body_dark)
    try:
        plate_font = ImageFont.truetype("arialbd.ttf", 22)
    except Exception:
        plate_font = ImageFont.load_default()
    d.text((1380, 842), VEHICLE["license_plate"], fill=(40, 40, 60), font=plate_font)

    # ====================== HAIL DAMAGE LAYER ============================
    rng = random.Random(11)

    def dent_field(poly_pts, count, size_range=(7, 16)):
        """Sprinkle dent dimples within a polygon-bounded panel area."""
        xs = [p[0] for p in poly_pts]
        ys = [p[1] for p in poly_pts]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        # Build a scanline mask via PIL polygon fill for correct point-in-poly
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(poly_pts, fill=255)
        placed = 0
        attempts = 0
        while placed < count and attempts < count * 8:
            attempts += 1
            x = rng.randint(x_min, x_max)
            y = rng.randint(y_min, y_max)
            if mask.getpixel((x, y)) == 0:
                continue
            r = rng.randint(*size_range)
            # Dark crescent (lower-right shadow) + bright highlight (upper-left)
            d.ellipse((x - r, y - r, x + r, y + r),
                      fill=(max(40, body_color[0] - 60),
                            max(8, body_color[1] - 8),
                            max(15, body_color[2] - 15)))
            d.ellipse((x - r + 2, y - r + 2, x - r + r, y - r + r),
                      fill=(min(255, body_color[0] + 40),
                            min(255, body_color[1] + 30),
                            min(255, body_color[2] + 30)))
            d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(20, 4, 8))
            placed += 1
        return placed

    # Hood region (front of car between hood front + windshield base)
    hood_poly = [(290, 700), (440, 660), (560, 600), (570, 660), (440, 700), (290, 740)]
    dent_field(hood_poly, 38, size_range=(6, 13))

    # Roof region
    roof_poly = [(660, 480), (1200, 470), (1180, 520), (700, 525)]
    dent_field(roof_poly, 52, size_range=(6, 12))

    # Trunk / tailgate region
    trunk_poly = [(1200, 470), (1330, 560), (1450, 720), (1320, 700), (1230, 560)]
    dent_field(trunk_poly, 24, size_range=(7, 14))

    # Windshield crack — large impact star + lateral spreading crack
    impact = (790, 540)
    for r in range(36, 0, -6):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ad = ImageDraw.Draw(layer)
        ad.ellipse((impact[0] - r, impact[1] - r, impact[0] + r, impact[1] + r),
                   fill=(245, 248, 255, max(20, 70 - r)))
        img.paste(layer, (0, 0), layer)
    for ang in range(0, 360, 22):
        length = rng.randint(35, 80)
        x2 = impact[0] + int(length * math.cos(math.radians(ang)))
        y2 = impact[1] + int(length * 0.5 * math.sin(math.radians(ang)))
        d.line([impact, (x2, y2)], fill=(250, 252, 255), width=2)
    # Long lateral spreading crack across windshield
    crack_pts = [impact]
    cx, cy = impact
    for step in range(12):
        cx += rng.randint(8, 22)
        cy += rng.randint(-3, 5)
        crack_pts.append((cx, cy))
    d.line(crack_pts, fill=(245, 248, 255), width=2)
    # Hole at impact
    d.ellipse((impact[0] - 6, impact[1] - 4, impact[0] + 6, impact[1] + 4),
              fill=(15, 18, 24))

    # ====================== ANNOTATIONS / CALLOUTS =======================
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 34)
        meta_font = ImageFont.truetype("arial.ttf", 22)
        callout_font = ImageFont.truetype("arialbd.ttf", 20)
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
        tw = int(11 * len(text))
        lx, ly = label_xy
        d.rectangle((lx - 6, ly - 6, lx + tw, ly + 30), fill=(0, 0, 0, 200),
                    outline=color, width=1)
        d.text((lx, ly), text, fill=color, font=callout_font)

    callout(1, (430, 690), (180, 280),
            "Hood — extensive hail dimpling (~38 dents)")
    callout(2, (920, 495), (640, 280),
            "Roof — full panel dimpling (~52 dents)")
    callout(3, impact, (820, 280),
            "Windshield — impact crack, spreading lateral", color=(255, 130, 130))

    # ---- Header / footer chrome ----------------------------------------
    d.rectangle((0, 0, W, 110), fill=(20, 22, 30))
    d.text((40, 28), f"{INSURER} — Claim {CLAIM_NUMBER}",
           fill=(230, 235, 248), font=title_font)
    d.text((40, 74),
           f"Vehicle: {VEHICLE['year']} {VEHICLE['make']} {VEHICLE['model']} "
           f"({VEHICLE['license_plate']})  ·  Hail event 2026-05-02  ·  "
           f"Front Range Dent & Glass intake bay 1",
           fill=(180, 195, 220), font=meta_font)
    d.rectangle((0, H - 50, W, H), fill=(20, 22, 30))
    d.text((40, H - 38),
           "Inspection photo — adjuster: A. Okafor  ·  3 damage zones flagged "
           "(hood, roof, windshield)",
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

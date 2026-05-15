# Claim sample — Theft & vandalism (recovered)

A complete fixture pack for the **Auto Claim** schema set, intentionally
different from the other samples in this folder so you can exercise the
pipeline with a non-collision scenario.

| File                | Type             | Notes                                           |
|---------------------|------------------|-------------------------------------------------|
| `claim_form.pdf`    | Claim Form       | All schema sections populated                   |
| `police_report.pdf` | Police Report    | Bellevue PD theft + recovery report             |
| `repair_estimate.pdf` | Repair Estimate | Eastside Auto Body, line items + tax + total   |
| `damage_photo.png`  | Damage Photo     | Synthesised inspection photo with annotations   |

## How it differs from the other samples

| Aspect                  | `claim_demo_persona` / `claim_hail_storm` | **`claim_theft_vandalism`**                       |
|-------------------------|--------------------------------------|--------------------------------------------------|
| Cause of loss           | Collision / hail                     | **Theft & vandalism (recovered)**                |
| Insurer                 | Proseware / Contoso                  | **Northwind Mutual**                             |
| Persona                 | Camille Roy                          | **Marcus Bell** (Bellevue, WA)                   |
| Vehicle                 | Lexus RX 350                         | **2023 Honda Civic EX-L**                        |
| Damage type             | Side-impact deformation              | **Forced entry, ignition, paint vandalism**      |
| Deductible              | $500                                 | **$250** (comprehensive)                         |
| Total estimate          | ~$3,800 / ~$3,900                    | ~$3,491 (parts/labour) + 9.25% tax               |

The pack is internally consistent (no built-in date discrepancies), so it's
useful as a baseline for evaluating fraud signals, gap analysis, and the
agent recommendation in a clean-claim scenario.

## Regenerating

```bash
python src/ContentProcessorAPI/samples/claim_theft_vandalism/generate_pdfs.py
```

Requires `reportlab` and `Pillow` (already in the API project's dev tooling).

## Uploading to a deployed environment

From the `samples/` folder:

```bash
./upload_files.ps1 \
  -ApiEndpointUrl "https://<api-host>/contentprocessor/submit" \
  -FolderPath "./claim_theft_vandalism" \
  -SchemaId "<auto-claim-schema-set-id>"
```

All documents and the image are fictional and exist only for demo / testing
of this project.

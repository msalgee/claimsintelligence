# Sample claim — collision with subtle commercial-use hints

Documents simulating a single-vehicle collision claim where the vehicle
appears (subtly, never explicitly) to have been used for ride-share /
TNC-style work, against a member policy that explicitly covers
**personal use only**. Designed to exercise the Foundry-driven gap
analysis path: the policy explicitly excludes "use for hire / TNC /
delivery", and the documents contain three kinds of cues the system
should flag.

| Document               | Purpose                                                                    |
| ---------------------- | -------------------------------------------------------------------------- |
| `claim_form.pdf`       | Driver claim narrative (passenger present, no relationship listed; trip purpose: "returning from passenger drop-off") |
| `police_report.pdf`    | Officer narrative — quotes driver "returning from a drop-off"; lists pre-existing rooftop placard mount, decal residue on rear quarter window, dual phone-mount cradles, dashcam |
| `repair_estimate.pdf`  | Body-shop line items including **Remove rooftop placard mount**, **Detach interior dual phone-mount rig**, **Remove residue of trade-dress decal** alongside the impact repairs |
| `member_policy.pdf`    | Northwind Mutual declarations page — Use class **Personal use only**; Section IV exclusions explicitly list ride-share, TNC, delivery, and any compensation-for-transport activity |
| `damage_photo.png`     | Inspection photo of the front-end damage with three commercial-use indicators visibly called out (placard mount, decal residue, dual phone cradles) |

Persona / claim:

- Insurer: Northwind Mutual Insurance — claim `NM-CLM-2026-05-913`,
  policy `NM-AUTO-661820`
- Member: Devon Park, SeaTac WA
- Vehicle: 2022 Toyota Camry SE, midnight-blue metallic, **mileage
  71,820** (high for a 2-year-old personal-use car — an additional
  subtle hint)
- Incident: 2026-05-08 02:15, single-vehicle front-end collision with
  a concrete bollard while merging from the passenger drop-off curb at
  the SEA airport cell-phone waiting lot

Signals the gap analysis should surface (none of these explicitly
mention "rideshare", "Uber", "Lyft", or any TNC brand):

1. **Trip purpose** in claim form: "Returning from passenger drop-off".
2. **Passenger details**: passenger present, name not recorded,
   relationship to insured not recorded.
3. **Police narrative**: pre-existing rooftop placard mount, decal
   residue ring on rear quarter window glass, two phone-mount cradles
   (one toward driver, one toward rear seat), active dashcam.
4. **Repair line items**: remove rooftop placard mount + refinish roof
   rail; detach/reattach dual phone-mount rig; polish off trade-dress
   decal residue.
5. **Mileage** of 71,820 on a 2-year-old vehicle vs declared annual
   mileage of 9,000.
6. **Incident location**: airport cell-phone waiting lot at 02:15.

These together should be enough to trigger a coverage-violation
finding against the policy's Section IV use exclusions.

## Generate the documents

From repo root:

```powershell
python src/ContentProcessorAPI/samples/claim_collision_commercial_hint/generate_pdfs.py
```

This produces the four PDFs and a high-fidelity **PIL fallback**
`damage_photo.png` (so the sample is complete even without any GPT-image
access).

## Replace `damage_photo.png` with a real GPT-image render

The PIL fallback is good enough to demo the pipeline, but for executive
demos a real GPT-image render is more credible. Run:

```powershell
# Preferred: Azure OpenAI with passwordless auth (DefaultAzureCredential)
az login
$env:AZURE_OPENAI_ENDPOINT = "https://<your-aoai-account>.openai.azure.com/"
# Optional override (defaults to "gpt-image-1"):
# $env:AZURE_OPENAI_IMAGE_DEPLOYMENT = "gpt-image-1"

python src/ContentProcessorAPI/samples/claim_collision_commercial_hint/generate_image.py
# Add --alt to also generate damage_photo_alt.png (a tighter close-up
# of the decal residue on the rear quarter window).
```

Requirements for the Azure OpenAI path:

- A `gpt-image-1` model deployment in the AOAI account.
  **`gpt-image-1` is not in the default Bicep template** — adding it is
  a small but billable change (≈$0.04 per image), so ask before
  deploying it. To add it, append a `deployments[]` entry to the
  `avmAiServices` module call in `infra/main.bicep` alongside the
  existing GPT deployments, then `azd provision`.
- The calling identity needs the `Cognitive Services OpenAI User`
  role on the AOAI account (already granted to the API container's
  managed identity by the existing IaC).

Fallback (no Azure access):

```powershell
$env:OPENAI_API_KEY = "sk-..."
python src/ContentProcessorAPI/samples/claim_collision_commercial_hint/generate_image.py
```

## Upload to a running deployment

The bundled `/claims/start` endpoint uses `claim_theft_vandalism` as
the built-in sample. To exercise this scenario through the pipeline,
upload the four documents (claim form, police report, repair estimate,
damage photo) via the regular **Upload Files** path on the claims demo
UI — they will hit the same Content Understanding classification +
Auto Claim schema-set extraction flow. The `member_policy.pdf` is
**not** uploaded with the claim; the gap analysis retrieves the
member policy by lookup against `member-policies-idx`, so to make
this scenario fully end-to-end you would also need to seed an entry
for `NM-AUTO-661820` (use class "personal", with the Section IV
exclusions in the policy text) into that index via the
`/claims/admin/seed-member-policies` endpoint. See
[`docs/ClaimProcessWorkflow.md`](../../../../docs/ClaimProcessWorkflow.md)
for the full intake and lookup flow.

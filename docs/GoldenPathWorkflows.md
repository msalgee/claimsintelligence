# Golden Path Workflows Guide

This guide provides detailed step-by-step workflows for getting the most out of the Claims Intelligence project. These "golden path" workflows represent the most common and effective use cases for the solution.

## Overview

The golden path workflows are designed to:
- Demonstrate the full capabilities of the solution
- Provide a structured learning experience from document upload through AI-powered analysis
- Showcase the 4-stage claim processing pipeline: Document Processing → RAI Analysis (safety gate) → Summarizing → Gap Analysis
- Help users understand confidence scoring, summarization, and rule-based gap analysis

---

## Workflow 1: End-to-End Auto Claim Processing

This is the primary v2 workflow — it walks through the full claim lifecycle from uploading multiple document types through AI-powered summarization and gap analysis.

> **Architecture**: Web UI → Content Process API → Content Process Workflow (Agent Framework) → Content Processor (4-stage pipeline) → Summarizer → Gap Analyzer. For full technical details, see [Claim Processing Workflow](./ClaimProcessWorkflow.md).

### 📋 Prerequisites
- Solution deployed and validated successfully (`azd up` completed)
- Auto Claim schema set registered (registered automatically during deployment)
- Authentication configured ([App Authentication Configuration](./ConfigureAppAuthentication.md))
- Sample data downloaded from the [samples directory](../src/ContentProcessorAPI/samples) — use the `claim_demo_persona/` folder for a complete pack, or `claim_hail_storm/` / `claim_theft_vandalism/` / `claim_collision_commercial_hint/` for variants

### 🚀 Step-by-Step Process

#### Step 1 — Upload Claim Documents

1. Navigate to your deployed Claims Demo URL and log in
2. Drag the claim files into the upload area, or click the dropzone to browse
3. Click **Auto-classify & analyze**. The API stores the originals in Blob Storage, uses the automatically registered **Auto Claim** schema set, and starts the workflow.

Upload all relevant documents for the claim — at minimum an auto claim form, plus supporting documents:

| Document                  | Auto Claim schema category       | Sample Source                  |
| ------------------------- | -------------------------------- | ------------------------------ |
| Auto insurance claim form | Auto Insurance Claim Form        | `claim_demo_persona/` folder   |
| Police report             | Police Report                    | `claim_demo_persona/` folder   |
| Repair estimate           | Repair Estimate                  | `claim_demo_persona/` folder   |
| Damaged vehicle photos    | Damaged Vehicle Image Assessment | `claim_demo_persona/` folder (PNG/JPEG) |

> **Tip**: Use the `claim_collision_commercial_hint/` folder for a pack that exercises gap analysis (subtle commercial-use cues against a personal-use policy), or `claim_hail_storm/` for a comprehensive weather loss with multi-photo damage.

#### Step 2 — Validate Document Processing Results

As each document is classified and processed through the 4-stage pipeline (Extract → Map → Evaluate → Save), review the extraction results in **Documents received**:

1. **Monitor Processing** — Watch each file move from classification/extraction in progress to completed preview and field output
2. **Review Per-Document Extraction**:
   - Click **View document** on each card
   - Examine the extracted data in the **Extracted fields** tab
   - Compare with the source document in the **Original** tab
3. **Check Confidence Scores**:
   - **Extraction Score** — How well the AI extracted raw data from the document
   - **Schema Score** — How well the extracted data maps to the expected schema fields
   - Pay attention to low-confidence fields (below 70%) that need manual review
4. **Validate Across Document Types**:
   - Compare how the system handles structured forms (claim form) vs. free text (police report) vs. images (damaged vehicle photos)
   - Note schema-specific extraction tailored to each document type

#### Step 3 — Review Summarization

After all documents complete processing, the workflow automatically generates an AI-powered consolidated summary:

1. Continue through **What happened**, **Coverage prerequisites**, and **Risk & integrity check**
2. Review the AI-generated summary in **Adjuster review** and edit it if needed before requesting a recommendation
3. Verify key claim details are accurately captured:
   - Policy and contact information
   - Incident description and timeline
   - Damage assessment and estimated costs
   - Parties involved
4. Note how the summary cross-references information from different document types (e.g., claim form details corroborated by police report)

#### Step 4 — Review Gap Analysis & Discrepancy Results

The final stage applies **YAML-based rules** to detect missing documents and cross-document inconsistencies:

1. Review the **Coverage prerequisites** and **Risk & integrity check** journey steps
2. **Missing Document Gaps** — Review flagged gaps where required documents are absent:
   - Example: Police report missing for a theft-related claim → `REQ-PR-THEFT-001` triggered
   - Each gap shows: rule ID, severity (`critical`/`high`/`medium`/`low`), and rationale
3. **Cross-Document Discrepancies** — Review flagged conflicts where field values disagree across documents:
   - Example: VIN on claim form doesn't match VIN on police report → `DISC-VEHICLE-VIN-001` triggered
   - Numeric fields use tolerance-based matching (e.g., repair estimate totals within $50)
4. **Severity Triage** — Address gaps by severity:
   - `critical` / `high` — Must be resolved before claim can proceed
   - `medium` — Review recommended
   - `low` — Informational
5. **Iterate** — Upload missing documents or correct data, then re-process if needed

> **Customizing Rules**: Gap analysis rules are defined in a reusable YAML DSL — no code changes required. See [Gap Analysis Ruleset Guide](./GapAnalysisRulesetGuide.md) for how to add, modify, or replace rules.

### 🎯 Expected Outcomes
- ✅ Multiple document types (forms, reports, estimates, images) processed accurately within a single claim
- ✅ Confidence scores above 80% for most fields across all document types
- ✅ AI-generated summary consolidates findings across all documents
- ✅ Gap analysis identifies missing documents based on conditional rules (loss type, jurisdiction, amount)
- ✅ Discrepancy checks flag conflicting data across documents (VIN, claim number, dates, amounts)
- ✅ Claim status tracked through all stages: `Pending` → `Processing` → `Summarizing` → `GapAnalysis` → `Completed`

---

## Workflow 2: Custom Document Processing Golden Path

### 📋 Prerequisites
- Workflow 1 completed successfully
- Understanding of your specific document types

### 🚀 Step-by-Step Process

1. **Create Custom Schema**
   - Define your document structure as a Pydantic model under `src/ContentProcessor/src/schemas/` (use the existing `AutoInsuranceClaimForm` schema as a template)
   - Field names and structure are converted automatically into a Content Understanding `fieldSchema` for linked-analyzer extraction

2. **Register Your Schema**
   - Add your schema metadata to `src/ContentProcessorAPI/samples/schemas/schema_info.json`
   - Re-run the postprovision hook (`azd hooks run postprovision`) or register manually via the Schema Vault API (`POST /schemavault/`)
   - Verify the schema appears through the Schema Vault API

3. **Create or Update a Schema Set**
   - **New schema set**: Create via the SchemaSet Vault API (`POST /schemasetvault/`) with a name and description
   - **Existing schema set**: Use an existing set (e.g., the "Auto Claim" set created during deployment)
   - **Add your schema to the set**: Call `POST /schemasetvault/{schemaset_id}/schemas` with the schema ID
   - A schema set is **required** in v2 — documents cannot be processed without one

   > **Tip**: You can add multiple custom schemas to the same schema set to group related document types for claim batch processing.

4. **Test with Sample Documents**
   - Submit documents through the API or Claims Demo upload flow, depending on whether your schema set is wired into that UI path
   - Review extraction results through the API or document preview field output
   - Check confidence scores and verify field accuracy

5. **Refine Extraction Quality**
   - Modify schema field descriptions if fields are missing or incorrectly mapped
   - Tune prompt templates directly in `src/ContentProcessorWorkflow/src/steps/{rai,summarize,gap_analysis}/prompt/*.txt` if extraction needs adjustment
   - Re-test with updated schema

6. **Author Gap Analysis Rules (Optional)**
   - Create domain-specific gap analysis rules in YAML for your schema set
   - Define missing document rules and cross-document discrepancy checks
   - See [Gap Analysis Ruleset Guide](./GapAnalysisRulesetGuide.md)

7. **Scale to Production**
   - Process larger document batches
   - Establish quality thresholds
   - Set up automated workflows using the API

### 🎯 Expected Outcomes
- ✅ Custom schema registered and added to a schema set
- ✅ Documents processed accurately through the schema set
- ✅ Confidence scoring helps identify manual review needs
- ✅ Gap analysis rules adapted to your domain (if authored)
- ✅ Workflow scales to handle production volumes

---

## Workflow 3: API Integration Golden Path

For programmatic and CI/CD scenarios, drive the full claim workflow via API.

### 📋 Prerequisites
- Workflow 1 completed through the Web UI
- Familiarity with the [API Documentation](./API.md)

### 🚀 Key API Steps

1. **Create a Claim** — `POST /claimprocessor/claims` with the schema set ID
2. **Upload Files** — `POST /claimprocessor/claims/{id}/files` for each document (assign schema per file)
3. **Start Processing** — `POST /claimprocessor/claims` with `claim_process_id` in request body → enqueues to `claim-process-queue`
4. **Poll Status** — `GET /claimprocessor/claims/{id}/status` → tracks `Pending` → `Processing` → `Summarizing` → `GapAnalysis` → `Completed`
5. **Retrieve Results** — `GET /claimprocessor/claims/{id}` → extraction results, summary, and gap analysis

### 🎯 Expected Outcomes
- ✅ Full claim lifecycle driven programmatically
- ✅ Same 3-stage workflow as Web UI (Document Processing → Summarizing → Gap Analysis)
- ✅ Results retrievable via API for downstream system integration

---

## Advanced Workflows

### Multi-Domain Adaptation
- Create domain-specific schema sets (logistics, legal, finance)
- Author matching gap analysis rules in YAML — no code changes needed
- Swap rules files to apply different business policies to the same documents

### Batch Automation
- Use the Claim Processor API to submit claims programmatically
- Monitor the 3-stage workflow via status polling or webhook integration
- Export results for downstream systems

## Best Practices

### Quality Assurance
- Always review low-confidence extractions manually
- Use comments to document validation decisions
- Track accuracy improvements over time

### Confidence Score Interpretation
- **90-100%**: High confidence, likely accurate
- **70-89%**: Medium confidence, review recommended
- **Below 70%**: Low confidence, manual review required

### Performance Optimization
- Use consistent document formats when possible
- Ensure good image quality for scanned documents
- Batch similar document types for better consistency

## Troubleshooting Common Issues

### Low Extraction Accuracy
- Check document quality and formatting
- Verify schema matches document structure
- Review and update system prompts if needed

### Processing Timeouts
- Reduce document file sizes
- Check Azure quota availability
- Monitor system logs for errors

### Claim Workflow Issues
- Verify ContentProcessorWorkflow container is running and healthy
- Check `claim-process-queue` for stuck messages
- Review `claim-process-dead-letter-queue` for failed messages
- Confirm Azure App Configuration has correct queue and Cosmos connection settings
- Monitor workflow logs for agent framework errors

### Authentication Issues
- Verify app registration configuration
- Check user permissions and role assignments
- Review authentication provider settings

## Next Steps

After completing these golden path workflows:

1. **Explore Advanced Features**
   - Custom gap analysis rules ([Ruleset Guide](./GapAnalysisRulesetGuide.md))
   - Tune workflow prompts under `src/ContentProcessorWorkflow/src/steps/*/prompt/`
   - API-driven batch processing

2. **Adapt to Your Domain**
   - Create custom schemas for your document types
   - Author domain-specific gap rules in YAML
   - Customize summarization prompts

3. **Scale Your Solution**
   - Monitor performance metrics
   - Optimize for your specific use cases
   - Plan for production deployment

## Support and Resources

- **Technical Documentation**: [API Guide](./API.md)
- **Processing Pipeline**: [Document Extraction Pipeline](./ProcessingPipelineApproach.md)
- **Claim Workflow**: [Claim Processing Workflow](./ClaimProcessWorkflow.md)
- **Gap Analysis Rules**: [Ruleset Guide](./GapAnalysisRulesetGuide.md)
- **Troubleshooting**: [Common Issues](./TroubleShootingSteps.md)
- **Sample Data**: [Download samples](../src/ContentProcessorAPI/samples)
- **Community**: [Submit issues](https://github.com/msalgee/claimsintelligence/issues)

---

*This guide is based on the automated test suite golden path workflows that validate the core functionality of the solution.*
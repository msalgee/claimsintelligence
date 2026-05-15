# Technical Approach

## Overview

At the application level, when a file is processed a number of steps take place to ingest, extract, and transform the contents of the file into the selected schema. The steps below describe the processing flow.

1. Documents are submitted to the API. The claims demo now performs **asynchronous intake**: the API writes the original files to Blob Storage, creates a claim manifest with placeholder schema IDs, creates a pending claim-process record, and returns the real claim ID immediately.

2. A background intake task classifies the files with Azure AI Content Understanding and only then queues the workflow:
    - **Text-bearing files (PDF, DOCX, scanned images of paper documents)** are sent to a CU **linked router** (`baseAnalyzerId=prebuilt-document`, completion model `gpt-4.1-mini`). Each category points to a per-schema custom analyzer whose `fieldSchema` is auto-generated from the registered Pydantic class. The linked-router response contains both category and extracted fields, so the API stores it as a `{claim_id}/{file_name}.cu.json` sidecar and the workflow can skip a duplicate CU call for that document.
    - **Image-only files (PNG/JPEG of a damage photo, etc.)** are classified with a CU **image analyzer** (`baseAnalyzerId=prebuilt-image`, completion model `gpt-4.1-mini`). Damage-photo extraction later uses the matching CU image extraction schema, also on `gpt-4.1-mini`. If an image classifier identifies a photographed paper document instead of a damage photo, the API re-submits the bytes to the document linked router so the sidecar shortcut still applies.

3. The manifest is replaced with the final schema IDs, a classification sidecar is written for the journey UI, and the claim is enqueued with Azure Storage Queue. This preserves the rule that the worker starts only after sidecars and schema routing are ready.

4. Confidence scores are merged into a single per-document score that drives the SPA "extraction score / schema score" badges and the human-in-the-loop review gate.

5. The top-scoring extraction is persisted as JSON to Blob Storage with a Cosmos DB metadata record.

## Document Processing Pipeline

The document processing pipeline handles individual document extraction and transformation through four sequential stages:

1. **Extract Pipeline** – Schema-aware extraction.

    For PDFs and other text-bearing documents, the demo intake usually provides the CU linked-router response as a sidecar, so the workflow reuses the already-extracted fields rather than calling CU a second time. If the sidecar is absent, the pipeline calls the same per-schema **Azure AI Content Understanding custom analyzer** (`baseAnalyzerId=prebuilt-document`, completion model `gpt-4.1-mini`). The analyzer's `fieldSchema` is generated automatically from the registered Pydantic class on first use and cached on the CU resource (idempotent PUT keyed by content hash).

    For image-only damage photos, the pipeline calls a **Azure AI Content Understanding image custom analyzer** (`baseAnalyzerId=prebuilt-image`, completion model `gpt-4.1-mini`) with the same target schema.

2. **Map Pipeline** – Schema reshape.

    Normalises CU responses into the legacy `gpt_result.choices[0].message.parsed` envelope so downstream stages don't have to know whether the data came from an intake sidecar, a document analyzer, or an image analyzer. For documents this is a near-passthrough because CU already returns named fields.

3. **Evaluate Pipeline** – Merging and Evaluating Extraction Results

    Calculates an overall confidence level from the per-field scores returned by CU. The same evaluator code path serves both document and image extractors.

4. **Save Pipeline** – Storing Results in Azure Blob Storage and Azure Cosmos DB

    Aggregates all outputs from the Extract, Map, and Evaluate steps. It finalizes and saves the processed data to Azure Blob Storage for file-based retrieval and updates or creates records in Azure Cosmos DB for structured, queryable storage. Confidence scoring is captured and saved with results for down-stream use - showing up, for example, in the web UI of the processing queue. This is surfaced as "extraction score" and "schema score" and is used to highlight the need for human-in-the-loop if desired.

---

> **Claim Processing Workflow**: The document processing pipeline above handles individual document extraction. For the higher-level claim batch workflow — which orchestrates multiple document extractions, AI summarization, and gap analysis using the Agent Framework Workflow Engine — see [Claim Processing Workflow](./ClaimProcessWorkflow.md).
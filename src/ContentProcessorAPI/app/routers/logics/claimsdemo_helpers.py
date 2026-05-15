"""Helpers backing the Claims Intelligence demo router with real claim data.

These functions read the artefacts produced by the existing claim-processing
pipeline (manifest blob, classification sidecar, Cosmos `Claim_Process`
record) and reshape them into the contract the journey UI expects.

They intentionally contain no LLM calls. AI-derived content (summary, gap
analysis) is produced upstream by the workflow agents and persisted to
Cosmos; we just reuse it here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.routers.logics.claimbatchprocessor import (
    ClaimBatchProcessor,
    ClaimBatchProcessRepository,
)
from app.routers.models.contentprocessor.claim import ClaimProcess
from app.routers.models.contentprocessor.claim_process import (
    Claim_Process,
    Claim_Steps,
)

logger = logging.getLogger(__name__)

CLASSIFICATION_SIDECAR = "classification.json"

# Friendly labels for the 4 categories the auto-classifier emits.
CATEGORY_LABELS: dict[str, str] = {
    "auto_insurance_claim_form": "Claim Form",
    "police_report": "Police Report",
    "repair_estimate": "Repair Estimate",
    "damage_photo": "Damage Photo",
}

# Human-friendly text for each YAML-DSL rule so the journey UI can show a
# pass/warn line per business rule even when no gap was raised.
RULE_LABELS: dict[str, str] = {
    "REQ-CLAIM-FORM-000": "Claim form is present",
    "REQ-PR-THEFT-001": "Police report is present for theft claim",
    "REQ-PHOTO-COLLISION-002": "Damage photo is present for collision claim",
    "REQ-ESTIMATE-AMOUNT-003": "Repair estimate is present for high-value claim",
    "REQ-MED-INJURY-004": "Medical report is present when injuries are indicated",
    "REQ-ID-JURISDICTION-CA-005": "ID verification is present for California third-party claim",
    "REQ-PR-THIRD-PARTY-006": "Police report is present when a third party is involved",
    "RD-001": "Claim form is provided",
    "RD-002": "Police report is provided when required",
    "RD-003": "Repair estimate is provided",
    "RD-004": "Damage photos are provided",
    "RD-005": "Third-party exposure reviewed",
    # Some workflow runs collapse the per-rule reasoning into category-level
    # entries instead of emitting RD-00x / DC-00x. Provide friendly labels so
    # the journey UI still renders meaningful pass rows.
    "required_documents": "Required documents are present",
    "discrepancy_checks": "No critical cross-document discrepancies",
    "observation_triggers": "No additional observations triggered",
}

DISCREPANCY_LABELS: dict[str, str] = {
    "DISC-CLAIM-NUMBER-001": "Claim number is consistent across documents",
    "DISC-CLAIM-NUMBER-002": "Claim number is present for tracking",
    "DISC-POLICY-NUMBER-001": "Policy number is consistent across documents",
    "DISC-DATE-OF-LOSS-001": "Date of loss is consistent across documents",
    "DISC-VEHICLE-VIN-001": "VIN is consistent across documents",
    "DISC-VEHICLE-PLATE-001": "License plate is consistent across documents",
    "DISC-ESTIMATE-TOTAL-001": "Repair estimate total is consistent",
    "DISC-DAMAGE-DESCRIPTION-001": "Damage description is consistent across documents",
    "DC-001": "Loss amount is consistent across documents",
    "DC-002": "Vehicle identifiers (VIN / registration) are consistent",
    "DC-003": "Date of loss is consistent across documents",
    "DC-004": "Damage description is consistent across documents",
    "DC-005": "Party / driver names are consistent across documents",
}

# Short business-readable titles for the DSL observation triggers in
# ``fnol_gap_rules.dsl.yaml::observation_triggers``. The full sentence-style
# description from gap analysis stays in ``rationale`` so the accordion
# header doesn't have to display it.
OBSERVATION_LABELS: dict[str, str] = {
    "OBS-NO-ESTIMATE-001": "No repair estimate available",
    "OBS-UNKNOWN-INJURIES-001": "Injury status undetermined",
    "OBS-MISSING-DEDUCTIBLE-001": "Deductible not stated in documents",
    "OBS-PHOTO-EXTRA-DAMAGE-001": "Photo shows damage beyond claim form",
    "OBS-MULTI-CLAIM-001": "Multiple claim events may need separate files",
    "OBS-THIRDPARTY-INCOMPLETE-001": "Third-party details incomplete",
    "OBS-WITNESS-MISSING-001": "Witness named but contact missing",
    "OBS-PR-FIELDS-INCOMPLETE-001": "Police report missing key fields",
    "OBS-COMMERCIAL-USE-HINT-001": "Possible commercial use on private-motor policy",
}


def _short_observation_title(description: str, max_words: int = 7) -> str:
    """Build a short, header-friendly title from a long observation
    description. Stops at the first sentence boundary or after
    ``max_words`` words, whichever comes first, and never breaks mid-word.
    """
    text = (description or "").strip()
    if not text:
        return "Adjuster observation"
    # First sentence only.
    for terminator in (". ", "; ", " \u2014 ", ", while ", ", but "):
        idx = text.find(terminator)
        if 0 < idx < 120:
            text = text[:idx]
            break
    words = text.split()
    if len(words) <= max_words:
        return text.rstrip(".,;:")
    return " ".join(words[:max_words]).rstrip(",;:") + "\u2026"

# Live agent output puts discrepancies in `parsed_gaps["discrepancies"]`
# tagged by `field` rather than `check_id`. Map common field names to a
# friendly business-rule label so Step 5 reads naturally.
_DISCREPANCY_LABEL_BY_FIELD: dict[str, str] = {
    "date_of_loss": "Date of loss is consistent across documents",
    "loss_date": "Date of loss is consistent across documents",
    "loss_amount": "Loss amount is consistent across documents",
    "total_loss": "Loss amount is consistent across documents",
    "repair_total": "Loss amount is consistent across documents",
    "vin": "Vehicle identifiers (VIN / registration) are consistent",
    "registration": "Vehicle identifiers (VIN / registration) are consistent",
    "plate": "Vehicle identifiers (VIN / registration) are consistent",
    "damage_description": "Damage description is consistent across documents",
    "damage_side": "Damage description is consistent across documents",
    "impacted_side": "Damage description is consistent across documents",
    "driver_name": "Party / driver names are consistent across documents",
    "insured_name": "Party / driver names are consistent across documents",
    "third_party_name": "Party / driver names are consistent across documents",
}

# Default DSL rule sets — used to synthesise pass rows when the workflow
# only emits aggregate / category-level _rule_evaluation entries. Keeps the
# Step 5 panel from looking empty on the happy path.
_DEFAULT_REQUIRED_DOC_RULES = [
    "REQ-CLAIM-FORM-000",
    "REQ-PR-THEFT-001",
    "REQ-PHOTO-COLLISION-002",
    "REQ-ESTIMATE-AMOUNT-003",
    "REQ-MED-INJURY-004",
    "REQ-ID-JURISDICTION-CA-005",
    "REQ-PR-THIRD-PARTY-006",
]
_LEGACY_REQUIRED_DOC_RULES = ["RD-001", "RD-002", "RD-003", "RD-004", "RD-005"]
_DEFAULT_DISCREPANCY_RULES = ["DC-001", "DC-002", "DC-003", "DC-004", "DC-005"]


def _business_rule_label(rule_id: str) -> str:
    label = (
        RULE_LABELS.get(rule_id)
        or DISCREPANCY_LABELS.get(rule_id)
        or OBSERVATION_LABELS.get(rule_id)
    )
    if label:
        return label
    return rule_id.replace("_", " ").replace("-", " ").title()


def _required_doc_pass_summary(rule_id: str) -> str:
    if rule_id == "RD-005":
        return "No third-party documentation gap detected."
    return "Required documentation is present."


def _required_doc_pass_details(rule_id: str) -> str:
    if rule_id == "RD-005":
        return (
            "The claim file does not show an unresolved third-party "
            "documentation requirement."
        )
    return (
        f"{_business_rule_label(rule_id)}. The workflow did not raise a "
        "missing-document gap for this requirement."
    )


# ---------------------------------------------------------------------------
# Sidecar persistence (intake)
# ---------------------------------------------------------------------------


def write_classification_sidecar(
    batch_processor: ClaimBatchProcessor,
    claim_id: str,
    files: list[dict[str, Any]],
) -> None:
    """Persist `{claim_id}/classification.json` so the journey can read it
    back even before the pipeline has finished running."""
    payload = {
        "claim_id": claim_id,
        "files": [
            {
                "file_name": f["file_name"],
                "mime_type": f.get("mime_type"),
                "size": f.get("size"),
                "category": f["category"],
                "confidence": f.get("confidence"),
                "schema_id": f.get("schema_id"),
                "method": f.get("method"),
            }
            for f in files
        ],
    }
    batch_processor.blobHelper.upload_blob(
        CLASSIFICATION_SIDECAR, json.dumps(payload), claim_id
    )


def read_classification_sidecar(
    batch_processor: ClaimBatchProcessor, claim_id: str
) -> Optional[dict[str, Any]]:
    """Return the sidecar payload, or None if it has not been written yet."""
    try:
        raw = batch_processor.blobHelper.download_blob(
            CLASSIFICATION_SIDECAR, claim_id
        )
    except Exception:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("classification.json for claim %s is not valid JSON", claim_id)
        return None


# ---------------------------------------------------------------------------
# Manifest + Cosmos lookups
# ---------------------------------------------------------------------------


def read_manifest(
    batch_processor: ClaimBatchProcessor, claim_id: str
) -> Optional[ClaimProcess]:
    """Load the manifest from blob, returning None if it does not exist."""
    try:
        return batch_processor.get_claim_manifest(claim_id=claim_id)
    except Exception:
        return None


async def read_claim_process(
    repo: ClaimBatchProcessRepository, claim_id: str
) -> Optional[Claim_Process]:
    """Load the Cosmos `Claim_Process` record, or None if not found."""
    try:
        return await repo.get_async(claim_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Mappers — manifest + sidecar -> SPA contract
# ---------------------------------------------------------------------------


def documents_payload(
    manifest: ClaimProcess,
    classification: Optional[dict[str, Any]],
    claim_process: Optional[Claim_Process] = None,
) -> list[dict[str, Any]]:
    """Build the DemoDocument[] list the SPA expects.

    When *claim_process* is supplied, the per-file ``process_id`` emitted to
    the SPA is the workflow-issued ``Content_Process.process_id`` (which is
    what the existing /processed/files/{process_id} endpoints expect). It
    falls back to the manifest item id otherwise so previews still work for
    in-flight claims.
    """
    label_by_filename: dict[str, str] = {}
    if classification and isinstance(classification.get("files"), list):
        for entry in classification["files"]:
            cat = entry.get("category")
            label_by_filename[entry.get("file_name", "")] = CATEGORY_LABELS.get(
                cat, (cat or "Document").replace("_", " ").title()
            )

    process_id_by_filename: dict[str, str] = {}
    if claim_process is not None:
        for cp in claim_process.processed_documents or []:
            if cp.file_name and cp.process_id:
                process_id_by_filename[cp.file_name] = cp.process_id

    out: list[dict[str, Any]] = []
    for item in manifest.items:
        size_bytes = int(item.size or 0)
        # Only emit a real workflow-issued process_id. The SPA can preview
        # raw claim blobs before this exists, but the extracted-fields tab
        # needs the workflow id; falling back to the manifest UUID would
        # silently produce 404s on the /contentprocessor/processed endpoint.
        process_id = process_id_by_filename.get(item.file_name)
        out.append({
            "id": item.id or item.file_name,
            "process_id": process_id,
            "mime_type": item.mime_type,
            "name": item.file_name,
            "category": label_by_filename.get(item.file_name, "Document"),
            "pages": 1,
            "size_kb": max(1, round(size_bytes / 1024)) if size_bytes else 0,
        })
    return out


def classification_payload(
    classification: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the DemoClassification[] list (one entry per file)."""
    if not classification:
        return []
    out: list[dict[str, Any]] = []
    for entry in classification.get("files", []):
        cat = entry.get("category") or "unknown"
        out.append({
            "file_id": entry.get("file_name"),
            "label": CATEGORY_LABELS.get(cat, cat.replace("_", " ").title()),
            "confidence": float(entry.get("confidence") or 0.0),
            # Method is now authoritative — set at intake. Older sidecars
            # without it fall back to the previous generic label.
            "method": entry.get("method")
                or "Azure AI Content Understanding (zero-shot classifier)",
        })
    return out


# ---------------------------------------------------------------------------
# process_gaps -> business_checks + fraud_check
# ---------------------------------------------------------------------------


_SEVERITY_TO_FRAUD = {
    "high": ("critical", 25),
    "medium": ("warning", 12),
    "low": ("info", 5),
}

_SEVERITY_TO_BUSINESS_STATUS = {
    "high": "fail",
    "medium": "warn",
    "low": "warn",
}


# Typical sales-tax / GST rates fall in this band: NZ GST is a flat 15%,
# AU GST 10%, and US state/local combined rates 4–11%. A claim-form-vs-
# repair-estimate total delta whose ratio lands inside this window is
# almost always pre-tax-vs-post-tax, not fraud.
_SALES_TAX_PCT_RANGE = (4.0, 15.5)


def _parse_currency(val: Any) -> Optional[float]:
    """Best-effort parse of a currency string/number into a float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str):
        return None
    cleaned = val.strip().replace("$", "").replace(",", "").replace("USD", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _explain_total_estimate_delta(
    values_by_source: dict[str, Any]
) -> tuple[Optional[str], bool]:
    """For DISC-ESTIMATE-TOTAL findings, decide whether the gap is benign.

    Returns (explanation, is_explained). When ``is_explained`` is True the
    caller should keep the finding at info severity; the explanation gets
    appended to the rationale so the green badge has a visible reason.
    When False the caller should bump severity (low→warning) so the
    unexplained gap is not buried in green.
    """
    nums = [
        n for n in (_parse_currency(v) for v in (values_by_source or {}).values())
        if n is not None and n > 0
    ]
    if len(nums) < 2:
        return (None, False)
    lo, hi = min(nums), max(nums)
    delta = hi - lo
    if delta <= 0:
        return ("Totals match.", True)
    pct = (delta / lo) * 100.0
    if _SALES_TAX_PCT_RANGE[0] <= pct <= _SALES_TAX_PCT_RANGE[1]:
        return (
            f"Δ ${delta:,.2f} ≈ {pct:.2f}% — matches a typical sales-tax / GST "
            "rate (e.g. NZ GST 15%, AU GST 10%, US 4–11%), so the larger total "
            "is most likely the post-tax figure.",
            True,
        )
    return (
        f"Δ ${delta:,.2f} ({pct:.1f}%) — does not match a typical sales-tax / "
        "GST rate; review for missed line items, duplicate parts, or a "
        "different scope of work.",
        False,
    )


def parse_gaps(process_gaps: str) -> Optional[dict[str, Any]]:
    """Parse the gap-analysis JSON the workflow agent persisted.

    The gap executor stores the raw model response, which our prompt forces
    to be a single JSON object. We tolerate some leading/trailing prose
    just in case the model wraps it.
    """
    if not process_gaps:
        return None
    text = process_gaps.strip()
    # Try direct JSON first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to extracting the outermost JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def business_checks_payload(parsed_gaps: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map `_rule_evaluation` (required_documents) + raised gaps into the
    BusinessCheck[] contract.

    Strategy: every rule the agent evaluated becomes a BusinessCheck.
    - rule not triggered -> status "pass", neutral summary
    - rule triggered, requirement satisfied -> status "pass"
    - rule triggered, requirement missing -> status from gaps[].severity
    """
    if not parsed_gaps:
        return []

    rule_evals = parsed_gaps.get("_rule_evaluation") or []
    raised_gaps_by_id: dict[str, dict[str, Any]] = {
        g.get("rule_id"): g
        for g in (parsed_gaps.get("gaps") or [])
        if g.get("rule_id")
    }

    out: list[dict[str, Any]] = []
    # Some workflow runs collapse the per-rule reasoning into a handful of
    # category-level entries (`required_documents`, `discrepancy_checks`,
    # `observation_triggers`). Those are aggregates, not actual rules —
    # rendering them as their own rows produces confusing “Rule does not
    # apply to this claim” cards. Skip them here; the synthesis below emits
    # the real per-rule rows.
    _META_RULE_IDS = {"required_documents", "discrepancy_checks", "observation_triggers"}
    for ev in rule_evals:
        # Workflow may emit either dicts or rule-id strings in _rule_evaluation.
        if isinstance(ev, str):
            ev = {"rule_id": ev, "condition_triggered": False, "is_gap": False}
        elif not isinstance(ev, dict):
            continue
        rule_id = ev.get("rule_id")
        if not rule_id or rule_id in _META_RULE_IDS:
            continue
        triggered = bool(ev.get("condition_triggered"))
        is_gap = bool(ev.get("is_gap"))
        gap = raised_gaps_by_id.get(rule_id)
        label = _business_rule_label(rule_id)

        if not triggered:
            status = "pass"
            summary = "Not required for this claim."
            details = "The claim facts did not trigger this requirement."
        elif not is_gap:
            status = "pass"
            summary = _required_doc_pass_summary(rule_id)
            details = (
                _required_doc_pass_details(rule_id)
                if rule_id == "RD-005"
                else (
                    f"All documents required by this check were found "
                    "in the claim inventory."
                )
            )
        else:
            severity = (gap or {}).get("severity", "medium").lower()
            status = _SEVERITY_TO_BUSINESS_STATUS.get(severity, "warn")
            missing = ", ".join((gap or {}).get("missing_types") or []) or "documentation"
            summary = f"Missing {missing}."
            details = (gap or {}).get(
                "rationale", f"This check requires {missing}."
            )

        out.append({
            "id": f"bc-{rule_id.lower()}",
            "rule": label,
            "status": status,
            "summary": summary,
            "details": details,
        })

    # If the workflow only emitted aggregate / category-level evaluations
    # (e.g. one row each for required_documents / discrepancy_checks /
    # observation_triggers) instead of per-rule entries, synthesise the
    # individual RD rows so Step 5 reads as a real business-rule checklist.
    # Real failures emitted at the per-rule level take priority and are not
    # duplicated.
    emitted_ids = {row["id"] for row in out}
    discrepancies = parsed_gaps.get("discrepancies") or []
    discrepancies_by_check_id: dict[str, dict[str, Any]] = {
        d.get("check_id"): d for d in discrepancies if d.get("check_id")
    }
    has_per_rd = any(
        rid in raised_gaps_by_id
        for rid in (_DEFAULT_REQUIRED_DOC_RULES + _LEGACY_REQUIRED_DOC_RULES)
    )

    for rd in _DEFAULT_REQUIRED_DOC_RULES:
        bc_id = f"bc-{rd.lower()}"
        if bc_id in emitted_ids:
            continue
        gap = raised_gaps_by_id.get(rd)
        if gap:
            severity = (gap.get("severity") or "medium").lower()
            status = _SEVERITY_TO_BUSINESS_STATUS.get(severity, "warn")
            missing = ", ".join(gap.get("missing_types") or []) or "documentation"
            out.append({
                "id": bc_id,
                "rule": _business_rule_label(rd),
                "status": status,
                "summary": f"Missing {missing}.",
                "details": gap.get("rationale", f"This check requires {missing}."),
            })
        elif not has_per_rd:
            out.append({
                "id": bc_id,
                "rule": _business_rule_label(rd),
                "status": "pass",
                "summary": _required_doc_pass_summary(rd),
                "details": _required_doc_pass_details(rd),
            })

    # Cross-document discrepancies: source-of-truth is
    # `parsed_gaps["discrepancies"]` — the same array Step 4 (Fraud) renders
    # findings from. Emit one Business Check row per actual discrepancy so
    # Steps 4 and 5 cannot disagree. If the list is empty, emit a single
    # “no discrepancies detected” PASS row instead of N synthetic rows.
    if discrepancies:
        for idx, d in enumerate(discrepancies):
            check_id = d.get("check_id") or f"DC-AUTO-{idx + 1}"
            field = d.get("field") or "field"
            severity = (d.get("severity") or "medium").lower()
            values = d.get("values_by_source") or {}
            values_text = ", ".join(
                f"{src}={val}" for src, val in values.items() if val is not None
            ) or "values differ across documents"

            # Mirror the fraud-panel logic so Step 5 status matches Step 4.
            if check_id.startswith("DISC-ESTIMATE-TOTAL"):
                explanation, is_explained = _explain_total_estimate_delta(values)
                if explanation:
                    values_text = f"{values_text} — {explanation}"
                if not is_explained and severity == "low":
                    severity = "medium"

            status = _SEVERITY_TO_BUSINESS_STATUS.get(severity, "warn")
            label = (
                DISCREPANCY_LABELS.get(check_id)
                or _DISCREPANCY_LABEL_BY_FIELD.get(field.lower())
                or f"{field.replace('_', ' ').capitalize()} consistency check"
            )
            out.append({
                "id": f"bc-{check_id.lower()}",
                "rule": label,
                "status": status,
                "summary": f"{field.replace('_', ' ').capitalize()} differs across source documents.",
                "details": values_text,
            })
    else:
        out.append({
            "id": "bc-no-discrepancies",
            "rule": "Cross-document fields are consistent",
            "status": "pass",
            "summary": "No cross-document discrepancies detected.",
            "details": (
                "Gap analysis found no conflicting values across the claim "
                "form, police report, repair estimate, or damage photo."
            ),
        })

    return out


def fraud_check_payload(parsed_gaps: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Map discrepancies + observations into the FraudCheckPayload contract.

    Risk score is a deterministic weighted sum capped at 100; the band is
    derived from the score. This mirrors how a rules engine would surface
    cross-document inconsistencies for adjuster triage.
    """
    if not parsed_gaps:
        return {"risk_score": 0, "risk_band": "Unknown", "findings": []}

    findings: list[dict[str, Any]] = []
    score = 0

    for d in parsed_gaps.get("discrepancies") or []:
        severity = (d.get("severity") or "medium").lower()
        check_id = d.get("check_id") or "DC-???"
        field = d.get("field") or "field"
        values = d.get("values_by_source") or {}
        values_text = ", ".join(
            f"{src}: {val}" for src, val in values.items() if val is not None
        ) or "values differ across documents"

        # Total-estimate deltas: explain (sales-tax match) or escalate.
        if check_id.startswith("DISC-ESTIMATE-TOTAL"):
            explanation, is_explained = _explain_total_estimate_delta(values)
            if explanation:
                values_text = f"{values_text} — {explanation}"
            if not is_explained and severity == "low":
                severity = "medium"

        sev, weight = _SEVERITY_TO_FRAUD.get(severity, ("warning", 12))
        score += weight
        findings.append({
            "id": f"f-{check_id.lower()}",
            "severity": sev,
            "title": DISCREPANCY_LABELS.get(check_id, f"{field} discrepancy"),
            "rationale": values_text,
            "contributing_docs": d.get("evidence_filenames") or [],
        })

    for o in parsed_gaps.get("observations") or []:
        obs_id = str(o.get("observation_id") or "OBS")
        description = o.get("description") or ""
        title = OBSERVATION_LABELS.get(obs_id) or _short_observation_title(description)
        # Honour any DSL-declared severity on the trigger; default to info so
        # legacy observations stay green.
        raw_sev = (o.get("severity") or "info").lower()
        if raw_sev in _SEVERITY_TO_FRAUD:
            sev, weight = _SEVERITY_TO_FRAUD[raw_sev]
        elif raw_sev in {"critical", "warning", "info"}:
            # Already in UI-vocab; map weight from nearest band.
            sev = raw_sev  # type: ignore[assignment]
            weight = {"critical": 25, "warning": 12, "info": 2}[raw_sev]
        else:
            sev, weight = "info", 2
        score += weight
        findings.append({
            "id": f"o-{obs_id.lower()}",
            "severity": sev,
            "title": title,
            "rationale": description,
            "contributing_docs": o.get("evidence_filenames") or [],
        })

    score = min(score, 100)
    if score >= 60:
        band = "High"
    elif score >= 30:
        band = "Medium"
    elif score > 0:
        band = "Low-Medium"
    else:
        band = "Low"

    return {"risk_score": score, "risk_band": band, "findings": findings}


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def is_processing(claim_process: Optional[Claim_Process]) -> bool:
    """True while the workflow has not yet produced summary/gap output."""
    if claim_process is None:
        return True
    if claim_process.status in (
        Claim_Steps.PENDING,
        Claim_Steps.DOCUMENT_PROCESSING,
        Claim_Steps.SUMMARIZING,
        Claim_Steps.GAP_ANALYSIS,
        Claim_Steps.RAI_ANALYSIS,
    ):
        return True
    return False

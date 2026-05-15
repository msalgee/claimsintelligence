"""Azure Content Understanding custom-analyzer extractor.

Foundry-native extraction path used by ``MapHandler`` for both PDF and
image sources. The CU ``fieldSchema`` envelope is sourced from the
Schema Vault (stored as JSON) and PUT to a per-schema custom analyzer.
CU returns extracted values **and** per-field confidence in a single
GA call — no logprob heuristics required.

Public surface:

* :func:`ensure_field_analyzer_from_payload` — idempotent
  ``PUT /analyzers/{id}`` that creates / updates the per-schema custom
  analyzer. Returns the analyzer id.
* :func:`analyze_with_field_analyzer` — synchronous-from-the-caller's-POV
  binary analysis that polls Operation-Location until ``succeeded``.
* :func:`cu_response_to_extraction_from_names` — flatten CU's
  ``contents[0].fields`` into ``(parsed_dict, confidence_dict)`` for
  downstream consumption by ``evaluate_handler``.

The analyzer id is deterministic: ``cps_extract_{classname}_v{hash8}``
where ``hash8`` is the first 8 hex chars of a SHA-256 over the analyzer
JSON. Re-running with an unchanged schema is a cheap GET; a changed
schema produces a new id (so old analyzers never serve stale schemas).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import requests

from libs.utils.azure_credential_utils import get_azure_credential

logger = logging.getLogger(__name__)

_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
# CU GA api-version (matches the classifier in ContentProcessorAPI).
_API_VERSION = "2025-11-01"


def _auth_headers(content_type: Optional[str] = None) -> dict[str, str]:
    """Build a fresh Bearer-token header. Tokens are short-lived, so we
    re-acquire per request rather than caching."""
    token = get_azure_credential().get_token(_COGNITIVE_SERVICES_SCOPE).token
    headers = {
        "Authorization": f"Bearer {token}",
        "x-ms-useragent": "cps-workflow-cu-extractor/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _analyzer_id_for_payload(class_name: str, payload: dict) -> str:
    """Deterministic CU analyzer id derived from class name + schema hash.

    CU custom-analyzer ids must be alphanumeric + underscores only
    (hyphens are rejected with InvalidAnalyzerId).
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    safe_name = "".join(
        c if c.isalnum() else "_" for c in class_name
    ).strip("_").lower()
    return f"cps_extract_{safe_name}_v{digest}"


def _wait_for_operation(
    operation_location: str,
    *,
    what: str,
    timeout_seconds: int = 180,
    poll_interval_seconds: float = 1.0,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        poll = requests.get(
            operation_location, headers=_auth_headers(), timeout=15
        )
        poll.raise_for_status()
        payload = poll.json()
        status = (payload.get("status") or "").lower()
        if status in ("succeeded", "completed"):
            return payload
        if status in ("failed", "canceled"):
            raise RuntimeError(
                f"CU {what} {status}: {payload.get('error') or payload}"
            )
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"CU {what} did not complete within {timeout_seconds}s"
            )
        time.sleep(poll_interval_seconds)


def ensure_field_analyzer_from_payload(
    endpoint: str,
    *,
    class_name: str,
    analyzer_payload: dict,
) -> str:
    """Schema Vault v2 entry point: caller provides the analyzer envelope.

    Used when the CU ``fieldSchema`` is stored natively in the Schema Vault
    as JSON (no Pydantic class to convert from).

    ``analyzer_payload`` must be the full PUT body matching the GA shape
    (``baseAnalyzerId``, ``config``, ``fieldSchema``, ``models``).
    """
    if not endpoint:
        raise ValueError("Content Understanding endpoint is required.")
    endpoint = endpoint.rstrip("/")

    analyzer_id = _analyzer_id_for_payload(class_name, analyzer_payload)

    url = (
        f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}"
        f"?api-version={_API_VERSION}"
    )

    # Fast path: if it already exists with the same hash, we're done.
    try:
        existing = requests.get(url, headers=_auth_headers(), timeout=15)
        if existing.status_code == 200:
            return analyzer_id
    except requests.RequestException:
        logger.debug("CU GET analyzer failed; will attempt PUT", exc_info=True)

    response = requests.put(
        url,
        headers=_auth_headers(content_type="application/json"),
        json=analyzer_payload,
        timeout=30,
    )
    if response.status_code == 409:
        # Raced with another worker; the existing analyzer matches our hash.
        return analyzer_id
    if response.status_code not in (200, 201, 202):
        logger.error(
            "CU PUT analyzer '%s' failed: status=%s body=%s",
            analyzer_id,
            response.status_code,
            response.text[:1000],
        )
        response.raise_for_status()

    op_loc = response.headers.get("Operation-Location")
    if op_loc:
        _wait_for_operation(
            op_loc,
            what=f"analyzer '{analyzer_id}' creation",
            timeout_seconds=180,
        )
    logger.info("Content Understanding extractor '%s' ready.", analyzer_id)
    return analyzer_id


def analyze_with_field_analyzer(
    endpoint: str,
    analyzer_id: str,
    file_bytes: bytes,
    *,
    timeout_seconds: int = 240,
    poll_interval_seconds: float = 1.5,
) -> dict:
    """Analyze ``file_bytes`` with the named CU custom analyzer.

    Returns the full CU response payload (the ``result`` envelope including
    ``contents[0].fields``).
    """
    if not endpoint:
        raise ValueError("Content Understanding endpoint is required.")
    endpoint = endpoint.rstrip("/")

    url = (
        f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyzeBinary"
        f"?api-version={_API_VERSION}"
    )
    response = requests.post(
        url,
        headers=_auth_headers(content_type="application/octet-stream"),
        data=file_bytes,
        timeout=60,
    )
    if response.status_code >= 400:
        logger.error(
            "CU analyzeBinary failed for '%s': status=%s body=%s",
            analyzer_id,
            response.status_code,
            response.text[:1000],
        )
        response.raise_for_status()

    op_loc = response.headers.get("Operation-Location")
    if not op_loc:
        # Synchronous response (rare) — return the body as-is.
        return response.json() if response.content else {}

    return _wait_for_operation(
        op_loc,
        what=f"analyzeBinary '{analyzer_id}'",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


# ---------------------------------------------------------------------------
# CU field response → (parsed dict, confidence dict)
# ---------------------------------------------------------------------------

# CU emits per-field results as ``{"type": "<t>", "valueString"|"valueNumber"|...,
# "valueArray"|"valueObject"|..., "confidence": float}``. The keys vary by
# type. This map covers the GA shapes we care about.
_VALUE_KEYS = (
    "valueString",
    "valueNumber",
    "valueInteger",
    "valueBoolean",
    "valueDate",
    "valueTime",
    "value",
)


def _coerce_field(field: dict) -> tuple[Any, float]:
    """Return ``(scalar_value_or_nested, confidence)`` for a CU field dict.

    For ``object`` and ``array`` types this returns the *raw nested CU
    structure* — the caller recurses.
    """
    if not isinstance(field, dict):
        return field, 0.0

    field_type = field.get("type")
    confidence = field.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0

    if field_type == "object":
        return field.get("valueObject") or {}, confidence
    if field_type == "array":
        return field.get("valueArray") or [], confidence

    for key in _VALUE_KEYS:
        if key in field:
            return field[key], confidence

    return None, confidence


def _walk_fields(cu_fields: dict) -> tuple[dict, dict]:
    """Recursively flatten CU ``fields`` into Pydantic-shaped ``(parsed, confidence)``.

    ``parsed`` mirrors the schema instance dict you'd get from
    ``schema.model_dump()``. ``confidence`` mirrors the dict produced by
    :func:`openai_confidence_evaluator.evaluate_confidence`: leaves are
    ``{"confidence": float, "value": <scalar>}`` and nested objects /
    arrays preserve structure.
    """
    parsed: dict = {}
    confidence: dict = {}

    for name, field in (cu_fields or {}).items():
        value, conf = _coerce_field(field)
        field_type = field.get("type") if isinstance(field, dict) else None

        if field_type == "object" and isinstance(value, dict):
            child_parsed, child_conf = _walk_fields(value)
            parsed[name] = child_parsed
            confidence[name] = child_conf
        elif field_type == "array" and isinstance(value, list):
            arr_parsed: list = []
            arr_conf: list = []
            for item in value:
                if isinstance(item, dict) and item.get("type") == "object":
                    item_parsed, item_conf = _walk_fields(
                        item.get("valueObject") or {}
                    )
                    arr_parsed.append(item_parsed)
                    arr_conf.append(item_conf)
                elif isinstance(item, dict) and "type" in item:
                    item_value, item_conf_val = _coerce_field(item)
                    arr_parsed.append(item_value)
                    arr_conf.append({
                        "confidence": item_conf_val,
                        "value": item_value,
                    })
                else:
                    arr_parsed.append(item)
                    arr_conf.append({"confidence": 0.0, "value": item})
            parsed[name] = arr_parsed
            confidence[name] = arr_conf
        else:
            parsed[name] = value
            confidence[name] = {"confidence": conf, "value": value}

    return parsed, confidence


def cu_response_to_extraction_from_names(
    cu_response: dict,
    *,
    expected_field_names: list[str],
) -> tuple[dict, dict]:
    """Schema Vault v2 entry point.

    Takes an explicit list of top-level field names. Used because the schema
    is stored as a CU ``fieldSchema`` JSON document with no Python class to
    introspect.
    """
    result = cu_response.get("result") or cu_response
    contents = result.get("contents") or []
    if not contents:
        # Shape regression or upstream failure -- raise so the pipeline
        # marks this doc as failed rather than persisting an all-None
        # extraction that downstream summarize/gap will hallucinate over.
        raise RuntimeError(
            "CU response had no 'contents' -- shape regression or upstream "
            f"failure (status={cu_response.get('status')!r})."
        )

    cu_fields = contents[0].get("fields") or {}
    if not cu_fields:
        # Linked-router envelopes (router on prebuilt-document with
        # contentCategories[].analyzerId) put the routed-to analyzer's
        # extracted fields under contents[0].segments[0].fields rather
        # than at the top level. Fall back to that shape so MapHandler
        # can read API-supplied envelopes without a second CU call.
        segments = contents[0].get("segments") or []
        if segments:
            cu_fields = segments[0].get("fields") or {}
    if not cu_fields:
        # Neither shape matched -- the routed-to extractor produced no
        # fields. Raise so the pipeline marks the doc as failed rather
        # than saving a gpt_output.json full of None.
        raise RuntimeError(
            "CU response had 'contents' but no 'fields' at "
            "contents[0].fields or contents[0].segments[0].fields -- "
            "routed-to extractor missing or shape regression."
        )
    parsed, confidence = _walk_fields(cu_fields)

    # Backfill any top-level fields the schema declares but CU didn't
    # return so the saved envelope's shape matches the legacy gpt-5.1 path.
    for name in expected_field_names:
        if name not in parsed:
            parsed[name] = None

    return parsed, confidence

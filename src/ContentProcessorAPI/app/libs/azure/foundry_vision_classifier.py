"""Foundry-routed vision classifier used by the claimsdemo auto-submit
endpoint.

Why this exists: the Content Understanding GA `prebuilt-document`
zero-shot classifier is text-driven and so cannot classify image-only
uploads (damage photos) — it returns `other` / 0 confidence. We instead
ask whatever vision-capable model is deployed on the Foundry project to
look at each document and pick a category. Works for both PDFs and
images in a single call.

This module is intentionally model-agnostic. We use the OpenAI Python
SDK because it is Microsoft's currently-supported transport for *any*
model deployed on a Foundry project (`/openai/v1` endpoint) — not
because we depend on Azure OpenAI specifically. The `model=` argument
is the Foundry deployment name; swap it to swap the underlying model.
The `azure-ai-inference` SDK was the previous model-agnostic option
but is being retired (Aug 2026) in favour of this exact pattern. Auth
is `DefaultAzureCredential` end to end via
`AIProjectClient.get_openai_client()` — no API keys, no AOAI resource
coupling.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from app.libs.azure.foundry_agents import _get_project_client

logger = logging.getLogger(__name__)


_SYSTEM_INSTRUCTIONS = """You are an insurance-claims document
classifier. You will be shown a single document (PDF or image) uploaded
to an auto-insurance claim. Pick the single best matching category from
the provided list.

Return ONE JSON object only — no prose, no markdown fences — with these
keys:
{
  "category": "<one of the provided category ids, or 'other' if none fit>",
  "confidence": 0.0-1.0,
  "reason": "<one short sentence justifying the choice>"
}

Rules:
- `category` MUST be one of the supplied ids verbatim, or the literal
  string "other".
- `confidence` is your own calibrated probability that the category is
  correct given what you can see in the document.
- Decide primarily from the document's content (form fields, headings,
  layout, photographic subject). The filename can be a weak hint but
  must not override what the content shows — real uploads often have
  uninformative names like ``001.pdf`` or ``scan.pdf``."""


def _categories_block(categories: dict[str, str]) -> str:
    lines = ["Available categories:"]
    for cat_id, description in categories.items():
        lines.append(f"- {cat_id}: {description}")
    lines.append("- other: anything that does not clearly match the above.")
    return "\n".join(lines)


def _build_input_content(
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    categories: dict[str, str],
) -> list[dict]:
    """Build the multimodal `input` payload for the Responses API.

    Images go in as `input_image` data URLs; PDFs (and any other binary
    docs) go in as `input_file` with a base64 `file_data` data URL —
    both are first-class on any vision-capable Foundry deployment
    served via the OpenAI/v1 Responses API.
    """
    encoded = base64.b64encode(file_bytes).decode("ascii")
    mime = (mime_type or "application/octet-stream").lower()
    data_url = f"data:{mime};base64,{encoded}"

    if mime.startswith("image/"):
        attachment = {
            "type": "input_image",
            "image_url": data_url,
        }
    else:
        # PDFs and other documents — the Responses API accepts a file
        # data URL with a filename hint.
        attachment = {
            "type": "input_file",
            "filename": file_name or "document",
            "file_data": data_url,
        }

    text_block = (
        f"Classify the attached document.\n\n{_categories_block(categories)}"
    )
    return [
        {
            "role": "user",
            "content": [
                attachment,
                {"type": "input_text", "text": text_block},
            ],
        }
    ]


def _parse_response(text: str, allowed: set[str]) -> tuple[str, float, str]:
    text = (text or "").strip()
    if not text:
        return "other", 0.0, "empty model response"
    # Be tolerant of fenced JSON.
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return "other", 0.0, "model returned non-JSON output"
        else:
            return "other", 0.0, "model returned non-JSON output"

    category = str(payload.get("category") or "other").strip()
    if category not in allowed and category != "other":
        # Hallucinated category id — degrade gracefully.
        return "other", 0.0, f"unknown category {category!r}"
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(payload.get("reason") or "").strip()
    return category, confidence, reason


def classify_document(
    *,
    project_endpoint: str,
    model: str,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    categories: dict[str, str],
    timeout_seconds: int = 60,
) -> tuple[str, float, str]:
    """Ask the configured Foundry vision model to classify a single document.

    Returns ``(category, confidence, reason)``. ``category`` is either
    one of the supplied ids, or the literal string ``"other"``. Never
    raises into the caller — surface failures as ``("other", 0.0, msg)``
    so the router can fall back to its filename heuristic.
    """
    if not project_endpoint or not model:
        return "other", 0.0, "Foundry project / model not configured"

    try:
        project_client = _get_project_client(project_endpoint)
        openai_client = project_client.get_openai_client()
        response = openai_client.responses.create(
            model=model,
            instructions=_SYSTEM_INSTRUCTIONS,
            input=_build_input_content(file_bytes, file_name, mime_type, categories),
            timeout=timeout_seconds,
        )
    except Exception as ex:  # noqa: BLE001 - never break the upload path
        logger.exception("foundry vision classifier call failed for %s", file_name)
        return "other", 0.0, f"foundry vision call failed: {ex}"

    text = (getattr(response, "output_text", "") or "").strip()
    category, confidence, reason = _parse_response(text, allowed=set(categories.keys()))
    logger.info(
        "foundry vision classify %s -> category=%s confidence=%.2f reason=%s",
        file_name, category, confidence, reason,
    )
    return category, confidence, reason


__all__ = ["classify_document"]

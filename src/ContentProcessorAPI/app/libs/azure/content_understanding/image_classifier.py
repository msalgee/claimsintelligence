"""Azure Content Understanding image classifier helper.

The GA ``prebuilt-document`` zero-shot classifier in
:mod:`.classifier` is text-LLM driven and so cannot classify pure-image
uploads (it OCRs first; a damage photo OCRs to nothing and lands in
``other``). The right platform-native pattern for images is a custom
analyzer with ``baseAnalyzerId: prebuilt-image`` and a ``classify``-method
field over an enum of category ids (per the
``create-custom-analyzer`` tutorial).

This module provides exactly that. It mirrors the auth, defaults,
ensure-or-create + self-heal, and analyze + poll plumbing of the document
classifier so the two can be used interchangeably from the router. The
``classify`` method returns the same ``(category_id, confidence)`` tuple
shape, so callers don't need to know which CU analyzer fired.

Used by the ``/claimsdemo/claims/auto-submit`` endpoint as the image
branch of the MIME-based dispatch — replacing the previous Foundry
vision-classifier fallback so the entire classification path goes
through Content Understanding.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from azure.identity import DefaultAzureCredential

from app.libs.azure.content_understanding.analyzer_gc import (
    garbage_collect_stale_analyzers,
)

logger = logging.getLogger(__name__)

_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
_API_VERSION = "2025-11-01"
# CU's image analyzer accepts the same supported chat-completion models as
# the document analyzer. gpt-5.x is not supported. Keep classification on
# gpt-4.1-mini so the claims-demo intake uses the same lower-cost model as
# the document linked router and schema extractors.
_DEFAULT_COMPLETION_MODEL = "gpt-4.1-mini"
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"


class ContentUnderstandingImageClassifier:
    """Minimal CU image classifier: ensure analyzer + classify image."""

    def __init__(
        self,
        endpoint: str,
        analyzer_id: str,
        categories: dict[str, str],
        api_version: str = _API_VERSION,
        completion_model: str = _DEFAULT_COMPLETION_MODEL,
        embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        if not endpoint:
            raise ValueError("Content Understanding endpoint is required.")
        if not analyzer_id:
            raise ValueError("analyzer_id is required.")
        if not categories:
            raise ValueError("categories must be a non-empty mapping.")

        self._endpoint = endpoint.rstrip("/")
        self._analyzer_id = analyzer_id
        self._categories = dict(categories)
        self._api_version = api_version
        self._completion_model = completion_model
        self._embedding_model = embedding_model
        self._credential = DefaultAzureCredential()
        self._ensured = False

    # ------------------------------------------------------------------ urls
    def _analyzer_url(self) -> str:
        return (
            f"{self._endpoint}/contentunderstanding/analyzers/"
            f"{self._analyzer_id}?api-version={self._api_version}"
        )

    # --------------------------------------------------------------- headers
    def _auth_headers(self, content_type: Optional[str] = None) -> dict[str, str]:
        token = self._credential.get_token(_COGNITIVE_SERVICES_SCOPE).token
        headers = {
            "Authorization": f"Bearer {token}",
            "x-ms-useragent": "cps-claimsdemo-image-classifier/1.0",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    # --------------------------------------------------------------- analyzer
    def _category_prompt(self) -> str:
        # The field `description` is what the model actually classifies
        # against (per the analyzer-reference doc). Enumerate ids + per-id
        # descriptions so the vision model has the same cues the document
        # classifier gets via contentCategories.
        lines = [
            "Single best category for this image. Choose the one whose "
            "description most closely matches what the image shows.",
            "",
        ]
        for cat_id, description in self._categories.items():
            lines.append(f"- {cat_id}: {description}")
        lines.append("- other: anything that does not clearly match the above.")
        return "\n".join(lines)

    def _analyzer_template(self) -> dict:
        # Custom image analyzer with a single classify field. Shape per
        # https://learn.microsoft.com/azure/ai-services/content-understanding/tutorial/create-custom-analyzer
        # (Image tab) — `baseAnalyzerId: prebuilt-image`, `models.completion`,
        # and `fieldSchema.fields.<name>.method = "classify"` with `enum`.
        enum_values = list(self._categories.keys())
        if "other" not in enum_values:
            enum_values.append("other")
        return {
            "baseAnalyzerId": "prebuilt-image",
            "description": (
                "Auto-classifier for claim image routing. Decides whether "
                "an uploaded image is a damage photo or a photo/scan of a "
                "claim form, police report, or repair estimate."
            ),
            "config": {"returnDetails": True},
            "fieldSchema": {
                "name": "ClaimImageCategory",
                "fields": {
                    "category": {
                        "type": "string",
                        "method": "classify",
                        "description": self._category_prompt(),
                        "enum": enum_values,
                    }
                },
            },
            "models": {"completion": self._completion_model},
        }

    def _model_deployments(self) -> dict[str, str]:
        return {
            self._completion_model: self._completion_model,
            self._embedding_model: self._embedding_model,
        }

    def _ensure_resource_defaults(self) -> None:
        """PATCH /contentunderstanding/defaults so analyzers can resolve
        model aliases. Idempotent. Same call as the document classifier
        sets — duplicating it here keeps the two helpers independent.
        """
        url = (
            f"{self._endpoint}/contentunderstanding/defaults"
            f"?api-version={self._api_version}"
        )
        body = {"modelDeployments": self._model_deployments()}
        try:
            resp = requests.patch(
                url,
                headers=self._auth_headers(content_type="application/json"),
                json=body,
                timeout=15,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "CU PATCH /defaults returned %s: %s",
                    resp.status_code,
                    resp.text[:500],
                )
        except requests.RequestException:
            logger.warning("CU PATCH /defaults failed", exc_info=True)

    def ensure_analyzer(self) -> None:
        """Create the image classifier analyzer if it does not exist.

        Self-heals if a previous incarnation of the analyzer id was
        created with the wrong shape (CU analyzers are immutable).
        """
        if self._ensured:
            return
        self._ensure_resource_defaults()

        url = self._analyzer_url()
        try:
            existing = requests.get(url, headers=self._auth_headers(), timeout=15)
            if existing.status_code == 200:
                body = existing.json()
                fs = (body.get("fieldSchema") or {}).get("fields") or {}
                cat = fs.get("category") or {}
                if (
                    body.get("baseAnalyzerId") == "prebuilt-image"
                    and cat.get("method") == "classify"
                    and cat.get("enum")
                ):
                    self._ensured = True
                    return
                logger.warning(
                    "CU image analyzer '%s' exists with wrong shape; "
                    "deleting and recreating.",
                    self._analyzer_id,
                )
                try:
                    requests.delete(url, headers=self._auth_headers(), timeout=15)
                except requests.RequestException:
                    logger.warning("CU image analyzer DELETE failed", exc_info=True)
        except requests.RequestException:
            logger.debug("CU image analyzer GET failed, will attempt PUT", exc_info=True)

        response = requests.put(
            url,
            headers=self._auth_headers(content_type="application/json"),
            json=self._analyzer_template(),
            timeout=30,
        )
        if response.status_code == 409:
            self._ensured = True
            return
        if response.status_code not in (200, 201, 202):
            logger.error(
                "CU image analyzer PUT failed: status=%s body=%s",
                response.status_code,
                response.text[:1000],
            )
            response.raise_for_status()

        op_loc = response.headers.get("Operation-Location")
        if op_loc:
            self._wait_for_operation(
                op_loc,
                what=f"image analyzer '{self._analyzer_id}' creation",
                timeout_seconds=120,
            )
        self._ensured = True
        logger.info(
            "Content Understanding image classifier '%s' ready.",
            self._analyzer_id,
        )
        # Sweep prior incarnations of the image classifier so the
        # per-resource analyzer cap can't drift up indefinitely as the
        # category definitions evolve. Best-effort: failures never break
        # a claim. The image classifier id always starts with
        # ``cps_claim_image_router_v``; only ids under that prefix are
        # touched.
        try:
            garbage_collect_stale_analyzers(
                endpoint=self._endpoint,
                api_version=self._api_version,
                auth_headers=self._auth_headers(),
                prefixes=("cps_claim_image_router_v",),
                keep_ids=(self._analyzer_id,),
            )
        except Exception:  # noqa: BLE001 - GC must never break a claim
            logger.warning(
                "CU GC sweep failed after image classifier '%s' ensure",
                self._analyzer_id,
                exc_info=True,
            )

    def _wait_for_operation(
        self,
        operation_location: str,
        *,
        what: str,
        timeout_seconds: int = 120,
        poll_interval_seconds: float = 1.0,
    ) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while True:
            poll = requests.get(
                operation_location,
                headers=self._auth_headers(),
                timeout=15,
            )
            poll.raise_for_status()
            payload = poll.json()
            status = (payload.get("status") or "").lower()
            if status == "succeeded":
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

    # ---------------------------------------------------------------- analyze
    def classify(
        self,
        file_bytes: bytes,
        *,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 1.0,
    ) -> tuple[str, float]:
        """Classify a single image and return (category, confidence).

        Falls back to ``("other", 0.0)`` if the response shape lacks a
        recognisable category — never raises into the caller for a
        well-formed but unmatched image.
        """
        self.ensure_analyzer()

        analyze_url = (
            f"{self._endpoint}/contentunderstanding/analyzers/"
            f"{self._analyzer_id}:analyzeBinary?api-version={self._api_version}"
        )
        response = requests.post(
            analyze_url,
            headers=self._auth_headers(content_type="application/octet-stream"),
            data=file_bytes,
            timeout=60,
        )
        if response.status_code >= 400:
            logger.error(
                "CU image analyze failed: status=%s body=%s",
                response.status_code,
                response.text[:1000],
            )
            response.raise_for_status()

        operation_location = response.headers.get("Operation-Location")
        result_payload = self._poll_until_done(
            operation_location,
            initial_payload=response.json() if response.content else None,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

        return self._extract_category(result_payload)

    def _poll_until_done(
        self,
        operation_location: Optional[str],
        *,
        initial_payload: Optional[dict],
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict:
        if not operation_location:
            return initial_payload or {}

        deadline = time.monotonic() + timeout_seconds
        consecutive_403s = 0
        while True:
            poll = requests.get(
                operation_location,
                headers=self._auth_headers(),
                timeout=15,
            )
            if poll.status_code == 403 and consecutive_403s < 5:
                consecutive_403s += 1
                logger.warning(
                    "CU image poll 403 for analyzer '%s' (attempt %d); retrying.",
                    self._analyzer_id,
                    consecutive_403s,
                )
                if time.monotonic() > deadline:
                    poll.raise_for_status()
                time.sleep(min(2.0, poll_interval_seconds * (2 ** consecutive_403s)))
                continue
            consecutive_403s = 0
            poll.raise_for_status()
            payload = poll.json()
            status = (payload.get("status") or "").lower()
            if status == "failed":
                logger.error(
                    "CU image analyze operation failed for '%s'. Payload: %s",
                    self._analyzer_id,
                    payload,
                )
                return payload
            if status in ("succeeded", "completed"):
                return payload
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"CU image classify timed out after {timeout_seconds}s "
                    f"for '{self._analyzer_id}' (last status={status!r})."
                )
            time.sleep(poll_interval_seconds)

    def _extract_category(self, payload: dict) -> tuple[str, float]:
        """Walk the result and return the classify field's value + confidence.

        Image custom-analyzer result shape:
            result.contents[0].fields.category = {
              "type": "string",
              "valueString": "<one of enum>",
              "confidence": 0.0-1.0  # only when returnDetails=True
            }
        """
        result = payload.get("result") or payload
        contents = result.get("contents") or []
        for content in contents:
            fields = content.get("fields") or {}
            cat_field = fields.get("category") or {}
            value = (
                cat_field.get("valueString")
                or cat_field.get("value")
                or cat_field.get("valueEnum")
            )
            if value:
                conf_raw = cat_field.get("confidence") or 0.0
                try:
                    conf = float(conf_raw)
                except (TypeError, ValueError):
                    conf = 0.0
                logger.info(
                    "CU image classify -> category=%s confidence=%.3f",
                    value,
                    conf,
                )
                return str(value), conf
        logger.warning(
            "CU image classify returned no category for analyzer '%s'.",
            self._analyzer_id,
        )
        return "other", 0.0

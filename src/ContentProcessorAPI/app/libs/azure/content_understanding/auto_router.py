"""Azure Content Understanding linked-analyzer router for the auto-claim demo.

A linked-analyzer router is a single ``prebuilt-document``-based custom
analyzer whose ``config.contentCategories`` map each category to the
``analyzerId`` of an existing per-schema custom analyzer. A single
``:analyzeBinary`` call therefore returns BOTH the matched category and
the extracted ``fields`` from the routed-to analyzer, eliminating the
redundant classify-then-extract round trip the workflow used to make.

Design properties:

* **Self-healing.** The router payload is built at request time from the
  schemas currently registered in the configured schema set, with each
  category's ``analyzerId`` derived from the schema envelope hash via
  the same :func:`_analyzer_id_for_payload` algorithm the workflow's
  :mod:`libs.azure_helper.cu_field_extractor` uses. Edit a schema → new
  per-schema analyzer id → new router id → router rebuilds and PUTs
  itself. No static infra files to keep in sync.
* **Idempotent.** The router id encodes a SHA-256 hash of its full
  payload. ``ensure_router`` does GET-then-PUT-on-miss; concurrent calls
  collapse to either a 200 or a 409 (both treated as success).
* **Document base only.** CU only allows ``contentCategories`` on
  document/video bases — image MIME files have to be handled with a
  separate image classifier (see
  :mod:`app.libs.azure.content_understanding.image_classifier`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import requests
from azure.identity import DefaultAzureCredential

from app.libs.azure.content_understanding.analyzer_gc import (
    garbage_collect_stale_analyzers,
)

logger = logging.getLogger(__name__)

_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
# CU GA api-version (matches classifier.py and cu_field_extractor.py).
_API_VERSION = "2025-11-01"
# CU supported chat completion model alias for routers/classifiers.
_DEFAULT_COMPLETION_MODEL = "gpt-4.1-mini"


def _analyzer_id_for_payload(class_name: str, payload: dict) -> str:
    """Deterministic per-schema CU analyzer id.

    Mirrors :func:`libs.azure_helper.cu_field_extractor._analyzer_id_for_payload`
    on the workflow side. Both sides MUST hash identically or the router
    will route to ids that don't exist on the workflow's CU resource.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    safe_name = "".join(
        c if c.isalnum() else "_" for c in class_name
    ).strip("_").lower()
    return f"cps_extract_{safe_name}_v{digest}"


def _router_id_for_payload(payload: dict) -> str:
    """Deterministic id for the linked router itself."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    return f"cps_auto_claim_router_v{digest}"


class AutoClaimLinkedRouter:
    """Builds, ensures, and runs the auto-claim linked router.

    Args:
        endpoint: Content Understanding account endpoint (no trailing slash).
        categories: Mapping of category id → (description, per-schema
            analyzer id). The description is what the model routes against
            (must be specific + mutually exclusive); the analyzer id is the
            target the router invokes for fields extraction.
        completion_model: Model alias for the router's ``models.completion``.
    """

    def __init__(
        self,
        endpoint: str,
        categories: dict[str, tuple[str, str]],
        *,
        completion_model: str = _DEFAULT_COMPLETION_MODEL,
        extractor_payloads: Optional[dict[str, dict]] = None,
    ) -> None:
        if not endpoint:
            raise ValueError("Content Understanding endpoint is required.")
        if not categories:
            raise ValueError("categories must be a non-empty mapping.")

        self._endpoint = endpoint.rstrip("/")
        self._categories = dict(categories)
        self._completion_model = completion_model
        # Map of target analyzer id -> full extractor PUT body. The router
        # references these by id under contentCategories.<cat>.analyzerId,
        # so they MUST exist on the CU resource before the router PUT or
        # CU returns InvalidAnalyzerId. We ensure them in ensure_router().
        self._extractor_payloads: dict[str, dict] = dict(extractor_payloads or {})
        self._credential = DefaultAzureCredential()

        # Fingerprint of the payload — recomputed on every build so that a
        # schema edit (new per-schema analyzerId) automatically rolls a new
        # router id.
        self._payload = self._build_router_payload()
        self._analyzer_id = _router_id_for_payload(self._payload)
        self._ensured = False

    # ---------------------------------------------------------------- payload
    def _build_router_payload(self) -> dict:
        """Construct the linked-router PUT body."""
        content_categories: dict[str, dict[str, str]] = {}
        for cat_id, (description, target_analyzer_id) in self._categories.items():
            content_categories[cat_id] = {
                "description": description,
                "analyzerId": target_analyzer_id,
            }
        # Always include a catch-all category so unmatched documents
        # don't raise — the caller falls back to the filename heuristic.
        content_categories.setdefault(
            "other",
            {
                "description": (
                    "Any document that does not match the other categories."
                ),
            },
        )
        return {
            "baseAnalyzerId": "prebuilt-document",
            "description": (
                "Auto-claim linked router: classify and extract in one CU call."
            ),
            "config": {
                "returnDetails": True,
                "enableSegment": True,
                "omitContent": True,
                "contentCategories": content_categories,
            },
            "models": {
                "completion": self._completion_model,
            },
        }

    # ------------------------------------------------------------------ urls
    def _analyzer_url(self) -> str:
        return (
            f"{self._endpoint}/contentunderstanding/analyzers/"
            f"{self._analyzer_id}?api-version={_API_VERSION}"
        )

    def _analyze_url(self) -> str:
        return (
            f"{self._endpoint}/contentunderstanding/analyzers/"
            f"{self._analyzer_id}:analyzeBinary?api-version={_API_VERSION}"
        )

    # --------------------------------------------------------------- headers
    def _auth_headers(self, content_type: Optional[str] = None) -> dict[str, str]:
        token = self._credential.get_token(_COGNITIVE_SERVICES_SCOPE).token
        headers = {
            "Authorization": f"Bearer {token}",
            "x-ms-useragent": "cps-auto-claim-router/1.0",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    # ----------------------------------------------------------- ensure/poll
    @property
    def analyzer_id(self) -> str:
        return self._analyzer_id

    def _ensure_resource_defaults(self) -> None:
        """PATCH ``/contentunderstanding/defaults`` so per-analyzer
        ``models.completion`` aliases resolve on a fresh CU resource.

        On a brand-new CU account (the demo's typical "azd up" path),
        the resource has no model deployments registered. PUTting an
        analyzer that references a model alias (e.g. ``gpt-4.1-mini``)
        then fails at first ``:analyzeBinary`` time with an
        ``InvalidModelAlias``-class 4xx, which the API surfaces as a
        cold-start 500 / forces the vision safety-net path on the very
        first claim. Mirrors the same call
        :meth:`image_classifier.AutoImageClassifier._ensure_resource_defaults`
        makes — kept duplicated so the two helpers remain independent.
        Idempotent and best-effort: a 4xx here is logged but not raised
        because the caller's downstream behaviour (router PUT, then
        analyze) will surface the real failure if defaults truly cannot
        be set.
        """
        url = (
            f"{self._endpoint}/contentunderstanding/defaults"
            f"?api-version={_API_VERSION}"
        )
        body = {
            "modelDeployments": {
                self._completion_model: self._completion_model,
            }
        }
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

    def _ensure_extractor(self, analyzer_id: str, payload: dict) -> None:
        """Idempotently PUT a per-schema extractor analyzer.

        Mirrors the workflow's ensure_field_analyzer_from_payload so the
        router's nested sub-analyzers exist on CU before the router PUT.
        """
        url = (
            f"{self._endpoint}/contentunderstanding/analyzers/"
            f"{analyzer_id}?api-version={_API_VERSION}"
        )
        try:
            existing = requests.get(url, headers=self._auth_headers(), timeout=15)
            if existing.status_code == 200:
                return
        except requests.RequestException:
            logger.debug(
                "CU GET extractor '%s' failed; will attempt PUT",
                analyzer_id,
                exc_info=True,
            )

        response = requests.put(
            url,
            headers=self._auth_headers(content_type="application/json"),
            json=payload,
            timeout=30,
        )
        if response.status_code == 409:
            return
        if response.status_code not in (200, 201, 202):
            logger.error(
                "CU PUT extractor '%s' failed: status=%s body=%s",
                analyzer_id,
                response.status_code,
                response.text[:1000],
            )
            response.raise_for_status()
        op_loc = response.headers.get("Operation-Location")
        if op_loc:
            self._wait_for_operation(
                op_loc,
                what=f"extractor '{analyzer_id}' creation",
                timeout_seconds=180,
            )
        logger.info("CU extractor '%s' ready.", analyzer_id)

    def ensure_router(self) -> None:
        """Create the router if it does not yet exist. Idempotent."""
        if self._ensured:
            return
        # Resource-level defaults (model alias resolution) must be set
        # before any analyzer PUT that references the alias. Cheap,
        # idempotent, best-effort.
        self._ensure_resource_defaults()
        url = self._analyzer_url()
        try:
            existing = requests.get(url, headers=self._auth_headers(), timeout=15)
            if existing.status_code == 200:
                self._ensured = True
                return
        except requests.RequestException:
            logger.debug("CU GET router failed; will attempt PUT", exc_info=True)

        # Per-schema extractors must exist before the router PUT, otherwise
        # CU rejects with InvalidAnalyzerId on the nested analyzerId refs.
        for analyzer_id, payload in self._extractor_payloads.items():
            self._ensure_extractor(analyzer_id, payload)

        response = requests.put(
            url,
            headers=self._auth_headers(content_type="application/json"),
            json=self._payload,
            timeout=30,
        )
        if response.status_code == 409:
            # Concurrent ensure won the race; the existing analyzer matches
            # our hash, so it's the same shape.
            self._ensured = True
            return
        if response.status_code not in (200, 201, 202):
            logger.error(
                "CU PUT router '%s' failed: status=%s body=%s",
                self._analyzer_id,
                response.status_code,
                response.text[:1000],
            )
            response.raise_for_status()

        op_loc = response.headers.get("Operation-Location")
        if op_loc:
            self._wait_for_operation(
                op_loc,
                what=f"router '{self._analyzer_id}' creation",
                timeout_seconds=180,
            )
        self._ensured = True
        logger.info("CU linked router '%s' ready.", self._analyzer_id)
        # Sweep prior router/extractor incarnations so the per-resource
        # analyzer cap can't drift up indefinitely as schemas evolve.
        # Best-effort: failures are logged and never propagated.
        try:
            keep_ids = [self._analyzer_id, *self._extractor_payloads.keys()]
            garbage_collect_stale_analyzers(
                endpoint=self._endpoint,
                api_version=_API_VERSION,
                auth_headers=self._auth_headers(),
                prefixes=("cps_auto_claim_router_v", "cps_extract_"),
                keep_ids=keep_ids,
            )
        except Exception:  # noqa: BLE001 - GC must never break a claim
            logger.warning(
                "CU GC sweep failed after router '%s' ensure",
                self._analyzer_id,
                exc_info=True,
            )

    def _wait_for_operation(
        self,
        operation_location: str,
        *,
        what: str,
        timeout_seconds: int = 180,
        poll_interval_seconds: float = 1.0,
    ) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while True:
            poll = requests.get(
                operation_location, headers=self._auth_headers(), timeout=15
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

    # ---------------------------------------------------------------- analyze
    def analyze(
        self,
        file_bytes: bytes,
        *,
        timeout_seconds: int = 240,
        poll_interval_seconds: float = 1.5,
    ) -> dict:
        """Run the linked router on ``file_bytes`` and return the raw envelope.

        The envelope has the GA shape ``{"status": "...", "result":
        {"contents": [{"category": "...", "fields": {...}}, ...]}}``.
        Use :func:`extract_category_and_confidence` to walk it.
        """
        self.ensure_router()

        response = requests.post(
            self._analyze_url(),
            headers=self._auth_headers(content_type="application/octet-stream"),
            data=file_bytes,
            timeout=60,
        )
        if response.status_code >= 400:
            logger.error(
                "CU linked router analyzeBinary failed for '%s': "
                "status=%s body=%s",
                self._analyzer_id,
                response.status_code,
                response.text[:1000],
            )
            response.raise_for_status()

        op_loc = response.headers.get("Operation-Location")
        if not op_loc:
            return response.json() if response.content else {}

        # Inherit the same 403-tolerant polling the classifier uses — CU
        # has a known intermittent 403-on-GET bug for analyzerResults/{id}.
        return self._poll_with_403_tolerance(
            op_loc,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def _poll_with_403_tolerance(
        self,
        operation_location: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict:
        deadline = time.monotonic() + timeout_seconds
        consecutive_403s = 0
        while True:
            poll = requests.get(
                operation_location, headers=self._auth_headers(), timeout=15
            )
            if poll.status_code == 403 and consecutive_403s < 5:
                consecutive_403s += 1
                logger.warning(
                    "CU router poll 403 for '%s' (attempt %d); retrying.",
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
            if status in ("succeeded", "completed", "failed", "canceled"):
                return payload
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"CU linked router poll timed out after {timeout_seconds}s "
                    f"for '{self._analyzer_id}' (last status={status!r})."
                )
            time.sleep(poll_interval_seconds)


def extract_category_and_confidence(payload: dict) -> tuple[str, float]:
    """Walk a linked-router envelope and return ``(category, confidence)``.

    Handles both response shapes the GA service emits:

    * ``contents[].segments[]`` with ``category`` + optional confidence
      (the ``enableSegment`` shape from the canonical Azure-Samples
      classifier notebook);
    * ``contents[].category`` flat, with confidence embedded in the
      first ``fields`` value (older / single-segment shape).

    Raises ``RuntimeError`` if the envelope's shape is unrecognised
    (no ``contents``, or ``contents`` present but no ``category``
    walked anywhere). Earlier versions silently returned
    ``("other", 0.0)`` here, which masked CU API drift and routed-to
    extractor-missing failures as routine "model said other" results.
    """
    result = payload.get("result") or payload
    contents = result.get("contents") or []

    if not contents:
        raise RuntimeError(
            "CU linked-router envelope has no 'contents' — shape regression "
            f"or upstream failure (status={payload.get('status')!r})."
        )

    for content in contents:
        for segment in content.get("segments") or []:
            seg_cat = segment.get("category") or segment.get("categoryName")
            if not seg_cat:
                continue
            seg_conf = segment.get("confidence") or segment.get("score") or 0.0
            try:
                seg_conf_f = float(seg_conf)
            except (TypeError, ValueError):
                seg_conf_f = 0.0
            return str(seg_cat), seg_conf_f

    for content in contents:
        category = content.get("category") or content.get("categoryName")
        confidence: Any = (
            content.get("confidence") or content.get("score") or 0.0
        )
        if not confidence:
            for field_value in (content.get("fields") or {}).values():
                if isinstance(field_value, dict) and field_value.get("confidence"):
                    confidence = field_value["confidence"]
                    if not category:
                        category = field_value.get("valueString")
                    break
        if category:
            try:
                return str(category), float(confidence)
            except (TypeError, ValueError):
                return str(category), 0.0

    raise RuntimeError(
        "CU linked-router envelope has 'contents' but no 'category' field "
        "walked from segments[] or contents[] — shape regression."
    )

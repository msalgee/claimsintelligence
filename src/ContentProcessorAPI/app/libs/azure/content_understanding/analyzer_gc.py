"""Garbage-collect stale Content Understanding analyzers.

Every schema or category-description edit content-hashes into a new
analyzer id (``cps_extract_<class>_v<sha[:8]>``,
``cps_auto_claim_router_v<sha[:8]>``,
``cps_claim_image_router_v<sha[:8]>``). The new analyzer is
PUT idempotently on the next request, but the previous incarnation is
left behind. CU GA has per-resource analyzer caps (low hundreds) so
long-lived demo envs eventually trip them after enough iterations.

This module exposes a single best-effort sweep called from each
``ensure_*`` path that LISTs analyzers by prefix and DELETEs everything
that is NOT the current id. Failures here MUST never break a claim — we
log and move on.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import requests

logger = logging.getLogger(__name__)


def garbage_collect_stale_analyzers(
    *,
    endpoint: str,
    api_version: str,
    auth_headers: dict[str, str],
    prefixes: Iterable[str],
    keep_ids: Iterable[str],
    list_timeout_seconds: int = 15,
    delete_timeout_seconds: int = 15,
    max_pages: int = 20,
) -> int:
    """Delete CU analyzers whose id starts with one of *prefixes* and is
    NOT in *keep_ids*.

    Args:
        endpoint: CU account endpoint (no trailing slash).
        api_version: CU API version string used for both LIST and DELETE.
        auth_headers: Headers (including bearer token) the caller is
            already using for its analyzer ops; reused verbatim so we
            stay on the same identity / scope.
        prefixes: Analyzer id prefixes that this caller owns. Anything
            NOT under one of these prefixes is left strictly alone — we
            never touch analyzers we did not create.
        keep_ids: Current analyzer ids that must be preserved.
        list_timeout_seconds: Per-page LIST timeout.
        delete_timeout_seconds: Per-DELETE timeout.
        max_pages: Hard cap on pagination; defends against runaway
            ``nextLink`` loops.

    Returns:
        Number of analyzers successfully deleted (0 on any failure path).
    """
    keep = {kid for kid in keep_ids if kid}
    prefix_tuple = tuple(p for p in prefixes if p)
    if not prefix_tuple:
        return 0

    deleted = 0
    next_url: Optional[str] = (
        f"{endpoint}/contentunderstanding/analyzers?api-version={api_version}"
    )
    pages = 0
    while next_url and pages < max_pages:
        pages += 1
        try:
            response = requests.get(
                next_url, headers=auth_headers, timeout=list_timeout_seconds
            )
        except requests.RequestException:
            logger.debug("CU LIST analyzers failed; skipping GC", exc_info=True)
            return deleted
        if response.status_code != 200:
            logger.debug(
                "CU LIST analyzers returned %s; skipping GC",
                response.status_code,
            )
            return deleted
        try:
            body = response.json()
        except ValueError:
            logger.debug("CU LIST analyzers returned non-JSON; skipping GC")
            return deleted

        for entry in body.get("value", []) or []:
            analyzer_id = entry.get("analyzerId") or entry.get("id")
            if not analyzer_id or not analyzer_id.startswith(prefix_tuple):
                continue
            if analyzer_id in keep:
                continue
            del_url = (
                f"{endpoint}/contentunderstanding/analyzers/"
                f"{analyzer_id}?api-version={api_version}"
            )
            try:
                del_resp = requests.delete(
                    del_url,
                    headers=auth_headers,
                    timeout=delete_timeout_seconds,
                )
            except requests.RequestException:
                logger.debug(
                    "CU DELETE stale analyzer '%s' failed",
                    analyzer_id,
                    exc_info=True,
                )
                continue
            if del_resp.status_code in (200, 202, 204, 404):
                deleted += 1
                logger.info("CU GC: deleted stale analyzer '%s'.", analyzer_id)
            else:
                logger.debug(
                    "CU DELETE stale analyzer '%s' returned %s",
                    analyzer_id,
                    del_resp.status_code,
                )

        next_url = body.get("nextLink") or None

    if pages >= max_pages and next_url:
        logger.debug(
            "CU GC stopped after %d pages; remaining results not swept",
            max_pages,
        )
    return deleted

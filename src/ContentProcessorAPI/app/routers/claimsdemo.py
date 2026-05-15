"""FastAPI router for the Claims Intelligence demo experience.

The intake endpoints submit real claim batches into the processing pipeline.
Journey endpoints read workflow output when it is available, and the story,
recommendation, and letter sections invoke Foundry-hosted agents. Fixture
payloads remain as explicit demo fallbacks for local environments where
Foundry is not configured.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Coroutine, Optional

import mimetypes

import requests
from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.libs.azure.content_understanding.auto_router import (
    AutoClaimLinkedRouter,
    _analyzer_id_for_payload,
    extract_category_and_confidence,
)
from app.libs.azure.content_understanding.image_classifier import (
    ContentUnderstandingImageClassifier,
)
from app.libs.azure.foundry_vision_classifier import (
    classify_document as foundry_classify_document,
)
from app.routers.logics.schemavault import Schemas
from app.libs.azure.foundry_agents import (
    PolicyGroundingUnavailable,
    build_claim_context,
    draft_email,
    extract_entities,
    recommend_outcome,
)
from app.libs.base.typed_fastapi import TypedFastAPI
from app.routers.logics.claimbatchprocessor import (
    ClaimBatchProcessor,
    ClaimBatchProcessRepository,
)
from app.routers.logics.claimsdemo_helpers import (
    business_checks_payload,
    classification_payload,
    documents_payload,
    fraud_check_payload,
    is_processing,
    parse_gaps,
    read_claim_process,
    read_classification_sidecar,
    read_manifest,
    write_classification_sidecar,
)
from app.routers.logics.schemasetvault import SchemaSets
from app.routers.models.contentprocessor.claim import ClaimItem
from app.routers.models.contentprocessor.claim_process import (
    Claim_Process,
    Claim_Steps,
)
from app.routers.models.contentprocessor.model import ClaimProcessRequest
from app.utils.azure_credential_utils import get_azure_credential
from app.utils.upload_validation import validate_upload_for_processing

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/claimsdemo",
    tags=["claimsdemo"],
    responses={404: {"description": "Not found"}},
)
_CLAIM_INTAKE_TASKS: set[asyncio.Task[None]] = set()
_LOCAL_FIXTURE_ENVS = {"dev", "local", "test"}


def _schedule_claim_intake_task(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _CLAIM_INTAKE_TASKS.add(task)

    def _on_done(done: asyncio.Task[None]) -> None:
        _CLAIM_INTAKE_TASKS.discard(done)
        try:
            done.result()
        except asyncio.CancelledError:
            logger.warning("Detached claim intake task was cancelled")
        except Exception:  # noqa: BLE001 - guard against unexpected task escapes
            logger.exception("Detached claim intake task failed unexpectedly")

    task.add_done_callback(_on_done)

_FIXTURE_PATH = Path(__file__).parent / "data" / "claimsdemo_fixtures.json"
_FIXTURE_CACHE: dict[str, Any] | None = None


class _LazyFixture:
    """Defers loading the fixture JSON until first access (import-time-safe)."""

    def __getitem__(self, key: str) -> Any:
        global _FIXTURE_CACHE
        if _FIXTURE_CACHE is None:
            _FIXTURE_CACHE = json.loads(
                _FIXTURE_PATH.read_text(encoding="utf-8")
            )
        return _FIXTURE_CACHE[key]


_FIXTURE = _LazyFixture()

# Schema set used by the auto-classify intake. Registered at deploy time by
# infra/scripts/post_deployment.{ps1,sh}.
_AUTO_CLAIM_SCHEMA_SET_NAME = os.environ.get(
    "CLAIMSDEMO_AUTO_SCHEMA_SET", "Auto Claim"
)
# Document classification + extraction is done by a single CU linked-analyzer
# router (one ``:analyzeBinary`` call returns BOTH the matched category and
# the extracted ``fields`` from the routed-to per-schema analyzer). The
# router id is derived at request time from a hash of the payload, so any
# schema edit automatically rolls a new router id — no static infra files
# to keep in sync. See ``auto_router.py``.
# Custom image analyzer (baseAnalyzerId: prebuilt-image) with a single
# `category` classify field over the same enum of category ids. The image
# base cannot host a linked router (CU `contentCategories` is supported on
# document/video bases only), so image MIME files take a separate path that
# only classifies; if the image is actually a photo of a paper document we
# re-route the same bytes through the document linked-router below.
# Defined after `_CATEGORY_DEFINITIONS` so the analyzer id is content-hashed
# from the category list — see further below.
_SEARCH_API_VERSION = "2024-07-01"


class PolicyIndexSeedDocument(BaseModel):
    source_filename: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    section: str | None = Field(default=None, max_length=256)


class PolicyIndexSeedRequest(BaseModel):
    index_name: str | None = Field(default=None, max_length=128)
    documents: list[PolicyIndexSeedDocument] = Field(min_length=1, max_length=100)


class MemberPolicySeedDocument(BaseModel):
    """One authoritative member-held auto-policy contract."""

    policy_number: str = Field(min_length=1, max_length=64)
    source_filename: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    form_version: str = Field(default="", max_length=128)
    carrier: str = Field(default="", max_length=128)
    state: str = Field(default="", max_length=8)
    effective_date: str = Field(default="", max_length=32)
    expiration_date: str = Field(default="", max_length=32)
    status: str = Field(default="", max_length=32)
    named_insureds: list[str] = Field(default_factory=list)
    excluded_drivers: list[str] = Field(default_factory=list)
    vins: list[str] = Field(default_factory=list)
    endorsements: list[str] = Field(default_factory=list)


class MemberPolicySeedRequest(BaseModel):
    index_name: str | None = Field(default=None, max_length=128)
    documents: list[MemberPolicySeedDocument] = Field(min_length=1, max_length=100)


def _claim_items_for_files(
    claim_id: str,
    files: list[dict[str, Any]],
    *,
    default_schema_id: str,
) -> list[ClaimItem]:
    return [
        ClaimItem(
            id=item["item_id"],
            claim_id=claim_id,
            schema_id=item.get("schema_id") or default_schema_id,
            metadata_id="",
            file_name=item["file_name"],
            size=item["size"],
            mime_type=item["mime_type"],
        )
        for item in files
    ]


async def _replace_claim_process_record(
    app: TypedFastAPI,
    claim_id: str,
    schema_set_id: str,
    process_name: str,
    *,
    status: Claim_Steps,
    message: str = "",
) -> None:
    claim_process_repository: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )
    if await claim_process_repository.get_async(claim_id) is not None:
        await claim_process_repository.delete_async(claim_id)
    await claim_process_repository.add_async(
        Claim_Process(
            id=claim_id,
            process_name=process_name,
            schemaset_id=schema_set_id,
            status=status,
            process_comment=message,
        )
    )


async def _mark_claim_failed(
    app: TypedFastAPI,
    claim_id: str,
    schema_set_id: str,
    process_name: str,
    message: str,
) -> None:
    claim_process_repository: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )
    try:
        claim_process = await claim_process_repository.get_async(claim_id)
        if claim_process is None:
            await claim_process_repository.add_async(
                Claim_Process(
                    id=claim_id,
                    process_name=process_name,
                    schemaset_id=schema_set_id,
                    status=Claim_Steps.FAILED,
                    process_comment=message,
                )
            )
            return
        claim_process.status = Claim_Steps.FAILED
        claim_process.process_comment = message
        await claim_process_repository.update_async(claim_process)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to mark claim %s as failed", claim_id)


def _accepted_file_payload(
    files: list[dict[str, Any]], default_schema_id: str
) -> list[dict[str, Any]]:
    return [
        {
            "file_name": item["file_name"],
            "mime_type": item["mime_type"],
            "size": item["size"],
            "category": item.get("category", "processing"),
            "confidence": item.get("confidence", 0.0),
            "schema_id": item.get("schema_id", default_schema_id),
            "method": item.get("method", "Intake accepted"),
        }
        for item in files
    ]


async def _create_claim_intake_shell(
    app: TypedFastAPI,
    files: list[dict[str, Any]],
    schema_set_id: str,
    process_name: str,
    default_schema_id: str,
) -> str:
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    new_claim = batch_processor.create_claim_container(schemaset_id=schema_set_id)
    claim_id = new_claim.claim_id

    for item in files:
        item["item_id"] = item.get("item_id") or str(uuid.uuid4())
        batch_processor.add_file_to_claim(
            claim_id=claim_id,
            file_name=item["file_name"],
            file_content=item["bytes"],
        )

    batch_processor.replace_claim_items(
        claim_id,
        _claim_items_for_files(claim_id, files, default_schema_id=default_schema_id),
    )
    await _replace_claim_process_record(
        app,
        claim_id,
        schema_set_id,
        process_name,
        status=Claim_Steps.PENDING,
    )
    return claim_id


# Maps a registered schema ClassName -> (category id used inside the CU
# classifier, human description). Description is what the model actually
# routes against, so it must be specific to this scenario AND mutually
# exclusive across categories. Per the CU best-practices doc, descriptions
# should call out the document MEDIUM (typed page vs. photograph) and
# unique structural anchors (form fields, case number, line items, pixels)
# so the zero-shot classifier can disambiguate confidently.
_CATEGORY_DEFINITIONS: dict[str, tuple[str, str]] = {
    "AutoInsuranceClaimForm": (
        "auto_insurance_claim_form",
        "A typed or printed insurer-issued auto insurance claim form "
        "(first-notice-of-loss). Structured form with labelled fields the "
        "policyholder fills in: insurer name, claim number, policy number, "
        "policyholder details, vehicle details, incident description, and "
        "a signed declaration. NOT a police report and NOT a repair "
        "estimate. Always a typeset document, never a photograph.",
    ),
    "PoliceReportDocument": (
        "police_report",
        "A typed or printed law-enforcement traffic-collision or incident "
        "report issued by a police department. Contains a police case / "
        "incident / report number, reporting officer name and badge, "
        "agency letterhead, parties and vehicles involved, citations, and "
        "an officer narrative. NOT an insurance form and NOT a repair "
        "estimate. Always a typeset document, never a photograph.",
    ),
    "RepairEstimateDocument": (
        "repair_estimate",
        "A typed or printed auto body shop / mechanic written repair "
        "estimate or invoice. Contains shop name and address, an estimate "
        "or invoice number, customer and vehicle details, an itemised "
        "table of parts and labor with hours and prices, subtotal, sales "
        "tax, and a grand total in currency. NOT an insurance claim form "
        "and NOT a police report. Always a typeset document, never a "
        "photograph.",
    ),
    "DamagedVehicleImageAssessment": (
        "damage_photo",
        "An image of a damaged vehicle. This includes raster photographs "
        "(JPEG / PNG) of a real car / truck / motorcycle, AND illustrative "
        "or annotated inspection diagrams that depict a vehicle with "
        "highlighted damage zones, callouts, or labels. The dominant "
        "visual subject is the vehicle and its damage (dents, broken "
        "glass, scratches, collision deformation), not a printed form. "
        "There is no insurance form layout, no police report letterhead, "
        "and no priced line-item table. If the file's primary content is "
        "an image of a vehicle rather than a typeset document, this is "
        "the correct category.",
    ),
}


# Content-hash the image classifier id from the category list so any edit to
# `_CATEGORY_DEFINITIONS` (label, description, new/removed category) auto-
# bumps the analyzer id and forces a fresh CU analyzer create on next call.
# Mirrors the `cps_{kind}_v{sha256[:8]}` pattern used by AutoClaimLinkedRouter.
_AUTO_IMAGE_CLASSIFIER_ID = (
    "cps_claim_image_router_v"
    + hashlib.sha256(
        json.dumps(
            {k: list(v) for k, v in _CATEGORY_DEFINITIONS.items()},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:8]
)


async def _classify_and_enqueue_claim(
    app: TypedFastAPI,
    claim_id: str,
    files: list[dict[str, Any]],
    schema_set_id: str,
    process_name: str,
    category_to_schema: dict[str, str],
    default_schema_id: str,
    *,
    cu_endpoint: str,
    auto_router: Optional[AutoClaimLinkedRouter],
    project_endpoint: str,
    vision_model: str,
) -> None:
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )

    async def _classify_one(item: dict[str, Any]) -> dict[str, Any]:
        category, confidence, schema_id, method, cu_envelope = await asyncio.to_thread(
            _classify_bytes,
            item["bytes"],
            item["file_name"],
            item["mime_type"],
            category_to_schema,
            default_schema_id,
            cu_endpoint=cu_endpoint,
            auto_router=auto_router,
            project_endpoint=project_endpoint,
            vision_model=vision_model,
        )
        return {
            **item,
            "category": category,
            "confidence": confidence,
            "schema_id": schema_id,
            "method": method,
            "cu_envelope": cu_envelope,
        }

    try:
        if auto_router is None:
            # Building the router can do a synchronous network round-trip to
            # CU (GET-200 fast path or PUT analyzer + Operation-Location
            # poll), so don't block the event loop.
            auto_router, category_to_schema = await asyncio.to_thread(
                _build_auto_router,
                cu_endpoint=cu_endpoint,
                schemasets=app.app_context.get_service(SchemaSets),
                schemas=app.app_context.get_service(Schemas),
            )

        # return_exceptions=True so one bad document can't kill the whole
        # batch — failed items get a sentinel category below.
        raw_results = await asyncio.gather(
            *[_classify_one(item) for item in files],
            return_exceptions=True,
        )
        prepared: list[dict[str, Any]] = []
        for item, result in zip(files, raw_results):
            if isinstance(result, BaseException):
                logger.exception(
                    "Per-document classification failed for %s/%s: %s",
                    claim_id,
                    item.get("file_name"),
                    result,
                )
                prepared.append(
                    {
                        **item,
                        "category": "classification_failed",
                        "confidence": 0.0,
                        "schema_id": default_schema_id,
                        "method": "Classification failed",
                        "cu_envelope": None,
                    }
                )
            else:
                prepared.append(result)

        for item in prepared:
            cu_envelope = item.get("cu_envelope")
            if cu_envelope is None:
                continue
            try:
                batch_processor.blobHelper.upload_blob(
                    f"{item['file_name']}.cu.json",
                    json.dumps(cu_envelope).encode("utf-8"),
                    claim_id,
                )
            except Exception:  # noqa: BLE001 - sidecar is best-effort
                logger.exception(
                    "Failed to upload CU envelope sidecar for %s/%s",
                    claim_id,
                    item["file_name"],
                )

        batch_processor.replace_claim_items(
            claim_id,
            _claim_items_for_files(
                claim_id, prepared, default_schema_id=default_schema_id
            ),
        )

        try:
            write_classification_sidecar(batch_processor, claim_id, prepared)
        except Exception:  # noqa: BLE001 - sidecar is best-effort
            logger.exception("Failed to write classification sidecar for %s", claim_id)

        try:
            batch_processor.enqueue_claim_request_for_processing(
                claim_process_request=ClaimProcessRequest(claim_process_id=claim_id)
            )
        except Exception as ex:  # noqa: BLE001
            logger.exception("Failed to enqueue claim %s", claim_id)
            await _mark_claim_failed(
                app,
                claim_id,
                schema_set_id,
                process_name,
                f"Failed to enqueue claim workflow: {ex}",
            )
            return

        logger.info("Classified and enqueued claim %s", claim_id)
    except Exception as ex:  # noqa: BLE001
        logger.exception("Background classification failed for claim %s", claim_id)
        failed_files = [
            {
                **item,
                "category": "classification_failed",
                "confidence": 0.0,
                "schema_id": default_schema_id,
                "method": "Classification failed",
            }
            for item in files
        ]
        try:
            write_classification_sidecar(batch_processor, claim_id, failed_files)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write failed-classification sidecar")
        await _mark_claim_failed(
            app,
            claim_id,
            schema_set_id,
            process_name,
            f"Background classification failed: {ex}",
        )


def _accepted_response(
    claim_id: str,
    schema_set_id: str,
    files: list[dict[str, Any]],
    default_schema_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        headers={"Location": f"/claimprocessor/claims/{claim_id}/status"},
        content={
            "claim_id": claim_id,
            "schema_set_id": schema_set_id,
            "status": "processing",
            "files": _accepted_file_payload(files, default_schema_id),
        },
    )


_SEARCH_SCOPE = "https://search.azure.com/.default"
_SEARCH_CREDENTIAL = get_azure_credential()


def _search_headers() -> dict[str, str]:
    token = _SEARCH_CREDENTIAL.get_token(_SEARCH_SCOPE).token
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _search_request(
    method: str,
    endpoint: str,
    resource: str,
    *,
    json: dict[str, Any] | None = None,
) -> requests.Response:
    url = f"{endpoint.rstrip('/')}/{resource}?api-version={_SEARCH_API_VERSION}"
    response = requests.request(
        method,
        url,
        headers=_search_headers(),
        json=json,
        timeout=60,
    )
    response.raise_for_status()
    return response


def _policy_index_definition(index_name: str) -> dict[str, Any]:
    return {
        "name": index_name,
        "fields": [
            {
                "name": "id",
                "type": "Edm.String",
                "key": True,
                "searchable": False,
                "filterable": True,
                "retrievable": True,
            },
            {
                "name": "parent_id",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
            },
            {
                "name": "section",
                "type": "Edm.String",
                "searchable": True,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
                "analyzer": "standard.lucene",
            },
            {
                "name": "source_filename",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
            },
            {
                "name": "content",
                "type": "Edm.String",
                "searchable": True,
                "filterable": False,
                "retrievable": True,
                "analyzer": "standard.lucene",
            },
        ],
        "semantic": {
            "configurations": [
                {
                    "name": "default",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "section"},
                        "prioritizedContentFields": [{"fieldName": "content"}],
                        "prioritizedKeywordsFields": [
                            {"fieldName": "source_filename"}
                        ],
                    },
                }
            ]
        },
    }


def _ensure_policy_index(endpoint: str, index_name: str) -> None:
    resource = f"indexes('{index_name}')"
    url = f"{endpoint.rstrip('/')}/{resource}?api-version={_SEARCH_API_VERSION}"
    response = requests.get(url, headers=_search_headers(), timeout=30)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    _search_request(
        "PUT",
        endpoint,
        resource,
        json=_policy_index_definition(index_name),
    )


def _seed_policy_index(
    endpoint: str,
    index_name: str,
    documents: list[PolicyIndexSeedDocument],
) -> int:
    _ensure_policy_index(endpoint, index_name)
    actions = []
    for document in documents:
        key = (
            base64.urlsafe_b64encode(document.source_filename.encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )
        actions.append(
            {
                "@search.action": "mergeOrUpload",
                "id": key,
                "parent_id": key,
                "section": document.section or Path(document.source_filename).stem,
                "source_filename": document.source_filename,
                "content": document.content,
            }
        )

    response = _search_request(
        "POST",
        endpoint,
        f"indexes('{index_name}')/docs/index",
        json={"value": actions},
    )
    result = response.json()
    failed = [item for item in result.get("value", []) if not item.get("status")]
    if failed:
        raise RuntimeError(
            f"AI Search rejected {len(failed)} guidance document(s): {failed}"
        )
    return len(actions)


@router.post(
    "/policy-index/seed",
    summary="Seed the advisory claims-handling guidance Search index",
    description=(
        "Creates the configured claims-handling guidance index when needed "
        "and uploads advisory markdown documents. This is not the "
        "member-held policy contract source."
    ),
)
async def seed_policy_index(
    request: Request,
    payload: PolicyIndexSeedRequest = Body(...),
) -> dict[str, Any]:
    app: TypedFastAPI = request.app  # type: ignore
    cfg = app.app_context.configuration
    endpoint = getattr(cfg, "app_ai_search_endpoint", "")
    configured_index = getattr(cfg, "app_ai_search_index_name", "")
    index_name = payload.index_name or configured_index

    if not endpoint or not index_name:
        raise HTTPException(status_code=503, detail="AI Search is not configured.")
    if configured_index and index_name != configured_index:
        raise HTTPException(
            status_code=400,
            detail="Index name does not match application configuration.",
        )

    try:
        document_count = _seed_policy_index(endpoint, index_name, payload.documents)
    except Exception as exc:
        logger.exception("Failed to seed claims-handling guidance index")
        raise HTTPException(
            status_code=502,
            detail=f"AI Search seeding failed: {exc}",
        ) from exc

    return {"index_name": index_name, "documents_uploaded": document_count}


# Synthetic claim context used by the post-deploy grounding warm-up. Kept
# minimal so the recommendation agent still has something to reason about
# (verdict + citations) but cheap enough to run repeatedly while RBAC is
# propagating to the Foundry project's managed identity.
_GROUNDING_WARMUP_CONTEXT = (
    "WARMUP_CONTEXT (synthetic, used by postprov to pre-warm the "
    "Foundry project MI -> AI Search RBAC path; not a real claim).\n"
    "claim_id: warmup-synthetic\n"
    "policy_number: NM-AUTO-554301\n"
    "loss_type: collision\n"
    "summary: Single-vehicle collision, low-speed parking lot impact, "
    "no injuries, no third party. Provide a brief recommendation."
)


@router.post(
    "/warmup-grounding",
    summary="Pre-warm the recommendation agent's AI Search grounding path",
    description=(
        "Runs `recommend_outcome` against a tiny synthetic claim context to "
        "exercise the Foundry project managed identity -> AI Search RBAC path "
        "after a fresh deploy. Returns 200 once the agent completes a grounded "
        "run, 503 while grounding is still propagating, and 502 on any other "
        "agent failure. Intended to be called by `infra/scripts/post_deployment.*` "
        "with retries; safe (and cheap) to call manually from a redeployed env."
    ),
)
async def warmup_grounding(request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    cfg = app.app_context.configuration
    project_endpoint = cfg.app_ai_project_endpoint
    model = cfg.app_azure_openai_model
    if not project_endpoint or not model:
        raise HTTPException(
            status_code=503,
            detail="Foundry project not configured; nothing to warm.",
        )

    try:
        recommend_outcome(
            project_endpoint=project_endpoint,
            model=model,
            claim_context=_GROUNDING_WARMUP_CONTEXT,
            search_connection_name=cfg.app_ai_search_connection_name,
            search_index_name=cfg.app_ai_search_index_name,
            member_policies_endpoint=getattr(cfg, "app_ai_search_endpoint", ""),
            member_policies_index_name=getattr(
                cfg, "app_member_policies_index_name", ""
            ),
        )
    except PolicyGroundingUnavailable as exc:
        # Foundry-side connection or RBAC still propagating. Tell postprov
        # to keep retrying.
        logger.warning("Grounding warm-up still propagating: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - warm-up surfaces all errors
        logger.exception("Grounding warm-up failed.")
        raise HTTPException(
            status_code=502,
            detail=f"Recommendation agent warm-up failed: {exc}",
        ) from exc

    return {"status": "warm"}


def _member_policies_index_definition(index_name: str) -> dict[str, Any]:
    return {
        "name": index_name,
        "fields": [
            {
                "name": "id",
                "type": "Edm.String",
                "key": True,
                "searchable": False,
                "filterable": True,
                "retrievable": True,
            },
            {
                "name": "policy_number",
                "type": "Edm.String",
                "searchable": True,
                "filterable": True,
                "retrievable": True,
                "sortable": True,
                "facetable": True,
                "analyzer": "keyword",
            },
            {
                "name": "form_version",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
            },
            {
                "name": "carrier",
                "type": "Edm.String",
                "searchable": True,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
            },
            {
                "name": "state",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
            },
            {
                "name": "status",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "sortable": True,
                "facetable": True,
            },
            {
                "name": "effective_date",
                "type": "Edm.DateTimeOffset",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "sortable": True,
            },
            {
                "name": "expiration_date",
                "type": "Edm.DateTimeOffset",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "sortable": True,
            },
            {
                "name": "named_insureds",
                "type": "Collection(Edm.String)",
                "searchable": True,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
                "analyzer": "standard.lucene",
            },
            {
                "name": "excluded_drivers",
                "type": "Collection(Edm.String)",
                "searchable": True,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
                "analyzer": "standard.lucene",
            },
            {
                "name": "vins",
                "type": "Collection(Edm.String)",
                "searchable": True,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
                "analyzer": "keyword",
            },
            {
                "name": "endorsements",
                "type": "Collection(Edm.String)",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
            },
            {
                "name": "source_filename",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "facetable": True,
            },
            {
                "name": "content",
                "type": "Edm.String",
                "searchable": True,
                "filterable": False,
                "retrievable": True,
                "analyzer": "standard.lucene",
            },
        ],
        "semantic": {
            "configurations": [
                {
                    "name": "default",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "policy_number"},
                        "prioritizedContentFields": [{"fieldName": "content"}],
                        "prioritizedKeywordsFields": [
                            {"fieldName": "named_insureds"},
                            {"fieldName": "vins"},
                            {"fieldName": "endorsements"},
                        ],
                    },
                }
            ]
        },
    }


def _ensure_member_policies_index(endpoint: str, index_name: str) -> None:
    resource = f"indexes('{index_name}')"
    url = f"{endpoint.rstrip('/')}/{resource}?api-version={_SEARCH_API_VERSION}"
    response = requests.get(url, headers=_search_headers(), timeout=30)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    _search_request(
        "PUT",
        endpoint,
        resource,
        json=_member_policies_index_definition(index_name),
    )


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _to_search_datetime(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if _DATE_RE.match(value):
        return f"{value}T00:00:00Z"
    return value


def _seed_member_policies_index(
    endpoint: str,
    index_name: str,
    documents: list[MemberPolicySeedDocument],
) -> int:
    _ensure_member_policies_index(endpoint, index_name)
    actions = []
    for document in documents:
        key = re.sub(r"[^A-Za-z0-9_\-=]", "_", document.policy_number)
        actions.append(
            {
                "@search.action": "mergeOrUpload",
                "id": key,
                "policy_number": document.policy_number,
                "form_version": document.form_version,
                "carrier": document.carrier,
                "state": document.state,
                "status": document.status,
                "effective_date": _to_search_datetime(document.effective_date),
                "expiration_date": _to_search_datetime(document.expiration_date),
                "named_insureds": document.named_insureds,
                "excluded_drivers": document.excluded_drivers,
                "vins": document.vins,
                "endorsements": document.endorsements,
                "source_filename": document.source_filename,
                "content": document.content,
            }
        )

    response = _search_request(
        "POST",
        endpoint,
        f"indexes('{index_name}')/docs/index",
        json={"value": actions},
    )
    result = response.json()
    failed = [item for item in result.get("value", []) if not item.get("status")]
    if failed:
        raise RuntimeError(
            f"AI Search rejected {len(failed)} member policy document(s): {failed}"
        )
    return len(actions)


@router.post(
    "/member-policies-index/seed",
    summary="Seed the authoritative member auto-policy Search index",
    description=(
        "Creates the configured member-policies index when needed and "
        "uploads member-held auto policy contract documents. This is the "
        "authoritative coverage source, separate from handling guidance."
    ),
)
async def seed_member_policies_index(
    request: Request,
    payload: MemberPolicySeedRequest = Body(...),
) -> dict[str, Any]:
    app: TypedFastAPI = request.app  # type: ignore
    cfg = app.app_context.configuration
    endpoint = getattr(cfg, "app_ai_search_endpoint", "")
    configured_index = getattr(cfg, "app_member_policies_index_name", "")
    index_name = payload.index_name or configured_index

    if not endpoint or not index_name:
        raise HTTPException(
            status_code=503,
            detail="Member-policies AI Search index is not configured.",
        )
    if configured_index and index_name != configured_index:
        raise HTTPException(
            status_code=400,
            detail="Index name does not match application configuration.",
        )

    try:
        document_count = _seed_member_policies_index(
            endpoint, index_name, payload.documents
        )
    except Exception as exc:
        logger.exception("Failed to seed member-policies AI Search index")
        raise HTTPException(
            status_code=502,
            detail=f"Member-policies AI Search seeding failed: {exc}",
        ) from exc

    return {"index_name": index_name, "documents_uploaded": document_count}

# Singleton classifier clients; lazily created on first request so the API
# starts even when CU is misconfigured. The router instance is keyed by the
# fingerprint of the categories+per-schema-analyzer-ids it was built from,
# so an upstream schema edit transparently produces a fresh router.
_router_singletons: dict[str, AutoClaimLinkedRouter] = {}
_image_classifier_singleton: Optional[ContentUnderstandingImageClassifier] = None


def _build_auto_router(
    cu_endpoint: str,
    schemasets: SchemaSets,
    schemas: Schemas,
) -> tuple[AutoClaimLinkedRouter, dict[str, str]]:
    """Build the auto-claim linked router from currently-registered schemas.

    Returns ``(router, category_to_schema_id)``. The router instance is
    cached by ``analyzer_id`` (which encodes a SHA-256 of the full payload),
    so unchanged schemas hit the cache; a schema edit produces a different
    hash and a fresh router is built and PUT to CU.
    """
    schema_set_id, category_to_schema_id = _resolve_schema_map(schemasets)

    # Per-category linked-analyzer ids: download each schema envelope and
    # compute the same deterministic id the workflow's MapHandler uses.
    schemas_in_set = schemasets.GetAllSchemasInSet(schema_set_id)
    by_class_name = {s.ClassName: s for s in schemas_in_set}

    categories: dict[str, tuple[str, str]] = {}
    extractor_payloads: dict[str, dict] = {}
    for class_name, (category_id, description) in _CATEGORY_DEFINITIONS.items():
        # Image-only categories must NOT be in the document linked router
        # (the image classifier handles them, and adding a target analyzer
        # for them here would be misleading).
        if class_name == "DamagedVehicleImageAssessment":
            continue
        schema_obj = by_class_name.get(class_name)
        if not schema_obj:
            continue
        envelope_blob = schemas.GetFile(schema_obj.Id)
        envelope = json.loads(envelope_blob["File"])
        target_analyzer_id = _analyzer_id_for_payload(class_name, envelope)
        categories[category_id] = (description, target_analyzer_id)
        # Pass the per-schema extractor payload so the router can ensure
        # the nested sub-analyzer exists on CU before its own PUT
        # (otherwise CU rejects with InvalidAnalyzerId).
        extractor_payloads[target_analyzer_id] = envelope

    if not categories:
        raise RuntimeError(
            f"Schema set '{_AUTO_CLAIM_SCHEMA_SET_NAME}' has no document "
            "schemas matching the auto-claim router categories."
        )

    # Probe-build to compute the hash key, then reuse cached instance.
    probe = AutoClaimLinkedRouter(
        endpoint=cu_endpoint,
        categories=categories,
        extractor_payloads=extractor_payloads,
    )
    cached = _router_singletons.get(probe.analyzer_id)
    if cached is not None:
        return cached, category_to_schema_id
    _router_singletons[probe.analyzer_id] = probe
    return probe, category_to_schema_id


def _get_image_classifier(endpoint: str) -> ContentUnderstandingImageClassifier:
    global _image_classifier_singleton
    if _image_classifier_singleton is None:
        _image_classifier_singleton = ContentUnderstandingImageClassifier(
            endpoint=endpoint,
            analyzer_id=_AUTO_IMAGE_CLASSIFIER_ID,
            categories={
                cat_id: description
                for _, (cat_id, description) in _CATEGORY_DEFINITIONS.items()
            },
        )
    return _image_classifier_singleton


def _resolve_schema_map(schemasets: SchemaSets) -> tuple[str, dict[str, str]]:
    """Return (schemaset_id, {classifier_category_id: schema_id}).

    Raises if the configured schema set isn't registered yet.
    """
    candidates = [
        s for s in schemasets.GetAll() if s.Name == _AUTO_CLAIM_SCHEMA_SET_NAME
    ]
    if not candidates:
        raise RuntimeError(
            f"Schema set '{_AUTO_CLAIM_SCHEMA_SET_NAME}' is not registered. "
            "Run the post-deployment script to register the Auto Claim "
            "schema set before using the auto-submit endpoint."
        )
    schema_set = candidates[0]
    schemas = schemasets.GetAllSchemasInSet(schema_set.Id)
    by_class_name = {s.ClassName: s.Id for s in schemas}

    category_to_schema: dict[str, str] = {}
    for class_name, (category_id, _desc) in _CATEGORY_DEFINITIONS.items():
        schema_id = by_class_name.get(class_name)
        if schema_id:
            category_to_schema[category_id] = schema_id

    if not category_to_schema:
        raise RuntimeError(
            f"Schema set '{_AUTO_CLAIM_SCHEMA_SET_NAME}' has no schemas "
            "matching the auto-classifier categories."
        )
    return schema_set.Id, category_to_schema


# Filename keyword fallback used when CU returns "other" / 0 confidence.
# Each entry: (category_id, [keyword fragments matched against lowercased
# filename]). First match wins. Tuned for the bundled sample filenames and
# the most obvious user variants (e.g. "policereport.pdf", "estimate.pdf").
_FILENAME_KEYWORD_FALLBACK: list[tuple[str, tuple[str, ...]]] = [
    ("auto_insurance_claim_form", ("claim_form", "claimform", "fnol", "claim-form")),
    ("police_report", ("police", "officer", "incident_report")),
    ("repair_estimate", ("repair", "estimate", "invoice", "bodyshop")),
    ("damage_photo", ("damage", "photo", "image", "picture")),
]
_PHOTO_MIME_PREFIX = "image/"


def _filename_fallback_category(file_name: str, mime_type: str) -> Optional[str]:
    """Best-effort filename/MIME heuristic. Returns a known category id or None."""
    name = (file_name or "").lower()
    for category, keywords in _FILENAME_KEYWORD_FALLBACK:
        if any(k in name for k in keywords):
            return category
    # Pure-image uploads with no keyword hit are almost always damage photos
    # in this scenario.
    if (mime_type or "").lower().startswith(_PHOTO_MIME_PREFIX):
        return "damage_photo"
    return None


def _classify_bytes(
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    category_to_schema: dict[str, str],
    default_schema_id: str,
    *,
    cu_endpoint: str,
    auto_router: Optional[AutoClaimLinkedRouter] = None,
    project_endpoint: str = "",
    vision_model: str = "",
) -> tuple[str, float, str, str, Optional[dict]]:
    """Classify bytes; return (category, confidence, schema_id, method, cu_envelope).

    ``cu_envelope`` is the raw CU linked-router response when the document
    path classified successfully; ``None`` for image-classifier paths or
    when only fallbacks fired. The envelope carries both the category and
    the extracted ``fields`` from the routed-to per-schema analyzer, so
    persisting it as a sidecar lets the workflow's ``MapHandler`` skip its
    own CU call (single-CU-call-per-document — see
    ``docs/ProcessingPipelineApproach.md``).

    Routing rules (Foundry-native, per CU best-practices doc):
      * Image MIME (``image/*``) → custom CU image analyzer
        (``baseAnalyzerId: prebuilt-image`` + ``classify`` field over the
        category enum). If it returns anything other than ``damage_photo``,
        the same bytes are then re-submitted to the document linked router
        (cross-modality triage: a phone photo of a paper claim form
        should still go through the document pipeline AND have its fields
        extracted in the same call). The image base cannot host a linked
        router because CU ``contentCategories`` is supported on document /
        video bases only, so the re-route is done server-side here.
      * Everything else (PDF, DOCX, …) goes to the CU document linked
        router (``prebuilt-document`` + ``contentCategories`` with
        per-category ``analyzerId``); if it returns ``other`` we ask the
        Foundry vision model as a safety-net fallback rather than silently
        misrouting.
      * Filename/MIME heuristic is the last-resort fallback only when
        both AI paths return ``other``.
    """
    cat_descriptions = {cat: desc for _, (cat, desc) in _CATEGORY_DEFINITIONS.items()}
    method = ""
    category = "other"
    confidence = 0.0
    cu_envelope: Optional[dict] = None
    is_image = (mime_type or "").lower().startswith(_PHOTO_MIME_PREFIX)

    if is_image:
        method = "Content Understanding (image)"
        if cu_endpoint:
            try:
                image_classifier = _get_image_classifier(cu_endpoint)
                category, confidence = image_classifier.classify(file_bytes)
            except Exception:  # noqa: BLE001 - never raise into caller
                logger.exception("CU image classify failed for %s", file_name)
                category, confidence = "other", 0.0
                method = "Content Understanding (image, FAILED)"

        # Cross-modality triage: a phone photo of a paper claim form/police
        # report/repair estimate is still an image MIME but the user wants
        # it processed by the document pipeline. If the image classifier
        # decided the photo is anything other than a damage photo, hand
        # the same bytes to the document linked router so it can confirm
        # which document category it belongs to AND extract its fields in
        # the same call. The image base analyzer cannot host a linked
        # router (CU `contentCategories` is supported on document/video
        # bases only) so this re-routing has to happen server-side here.
        if category != "damage_photo" and auto_router is not None:
            try:
                envelope = auto_router.analyze(file_bytes)
                doc_cat, doc_conf = extract_category_and_confidence(envelope)
                if doc_cat in category_to_schema and doc_cat != "damage_photo":
                    category, confidence = doc_cat, doc_conf
                    cu_envelope = envelope
                    method = "Content Understanding (image → document re-route)"
            except Exception:  # noqa: BLE001 - re-route is best-effort
                logger.exception(
                    "CU image→document re-route failed for %s", file_name
                )
                method = "Content Understanding (image → document re-route, FAILED)"
    else:
        method = "Content Understanding (linked router)"
        if auto_router is not None:
            try:
                envelope = auto_router.analyze(file_bytes)
                category, confidence = extract_category_and_confidence(envelope)
                if category in category_to_schema:
                    cu_envelope = envelope
            except Exception:  # noqa: BLE001 - surface fallback path uniformly
                logger.exception(
                    "CU linked router failed for %s; trying vision fallback.",
                    file_name,
                )
                category, confidence = "other", 0.0
                method = "Content Understanding (linked router, FAILED)"
        if category not in category_to_schema and project_endpoint and vision_model:
            try:
                v_cat, v_conf, _ = foundry_classify_document(
                    project_endpoint=project_endpoint,
                    model=vision_model,
                    file_bytes=file_bytes,
                    file_name=file_name,
                    mime_type=mime_type,
                    categories=cat_descriptions,
                )
                if v_cat in category_to_schema:
                    category, confidence = v_cat, v_conf
                    method = "AI vision (Foundry, CU fallback)"
            except Exception:  # noqa: BLE001
                logger.exception("Vision fallback failed for %s", file_name)

    if category not in category_to_schema:
        fallback = _filename_fallback_category(file_name, mime_type)
        if fallback and fallback in category_to_schema:
            category = fallback
            # Filename heuristics are last-resort and inherently low-confidence:
            # surface that to the UI rather than masking it as 0.5.
            confidence = 0.0
            method = "Filename fallback (low confidence)"
        else:
            method = "Default (no match)"
            confidence = 0.0
    schema_id = category_to_schema.get(category, default_schema_id)
    return category, confidence, schema_id, method, cu_envelope


@router.post("/claims/auto-submit")
async def auto_submit(
    request: Request,
    files: list[UploadFile] = File(...),
) -> JSONResponse:
    """Accept uploaded files as one claim and classify them in the background.

    The request path only validates and stores the original files so the UI
    can navigate immediately. Content Understanding classification/extraction
    writes the sidecars and enqueues the workflow after this response returns.
    """
    app: TypedFastAPI = request.app  # type: ignore

    if not files:
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": "No files uploaded."},
        )

    cu_endpoint = app.app_context.configuration.app_content_understanding_endpoint
    project_endpoint = app.app_context.configuration.app_ai_project_endpoint
    vision_model = app.app_context.configuration.app_azure_openai_model
    if not cu_endpoint:
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "message": (
                    "Content Understanding endpoint is not configured for "
                    "auto-classification."
                ),
            },
        )

    schemasets: SchemaSets = app.app_context.get_service(SchemaSets)
    try:
        schema_set_id, category_to_schema = _resolve_schema_map(schemasets)
    except RuntimeError as ex:
        return JSONResponse(
            status_code=503,
            content={"status": "failed", "message": str(ex)},
        )

    # Default schema = first one in the map; used for "other" / unmatched.
    default_schema_id = next(iter(category_to_schema.values()))

    max_filesize_mb = app.app_context.configuration.app_cps_max_filesize_mb

    intake_files: list[dict[str, Any]] = []
    for upload in files:
        validated = await validate_upload_for_processing(
            upload=upload, max_filesize_mb=max_filesize_mb
        )
        if isinstance(validated, JSONResponse):
            return validated
        safe_filename, mime_type, size_bytes = validated
        file_bytes = await upload.read()
        intake_files.append(
            {
                "file_name": safe_filename,
                "mime_type": mime_type,
                "size": size_bytes,
                "bytes": file_bytes,
            }
        )

    try:
        claim_id = await _create_claim_intake_shell(
            app,
            intake_files,
            schema_set_id,
            "Auto-classified intake",
            default_schema_id,
        )
    except Exception as ex:  # noqa: BLE001
        logger.exception("Failed to create uploaded claim intake shell")
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "message": f"Claim intake failed: {ex}",
            },
        )

    _schedule_claim_intake_task(
        _classify_and_enqueue_claim(
            app,
            claim_id,
            intake_files,
            schema_set_id,
            "Auto-classified intake",
            category_to_schema,
            default_schema_id,
            cu_endpoint=cu_endpoint,
            auto_router=None,
            project_endpoint=project_endpoint,
            vision_model=vision_model,
        )
    )
    return _accepted_response(claim_id, schema_set_id, intake_files, default_schema_id)


# Built-in sample claim used by /claims/start: 4 documents matching the
# Auto Claim schema set (claim form, police report, repair estimate,
# damage photo). Files live in samples/claim_theft_vandalism/ and are
# bundled into the API container image. The sample claim runs through
# the SAME CU-based classification path as user uploads — no special-case
# deterministic mapping — so the demo exercises the real pipeline end
# to end.
_SAMPLE_CLAIM_DIR = (
    Path(__file__).resolve().parents[2] / "samples" / "claim_theft_vandalism"
)
_SAMPLE_CLAIM_FILES: list[tuple[str, str]] = [
    # (file_name, mime_type) — category is determined by CU at runtime.
    ("claim_form.pdf", "application/pdf"),
    ("police_report.pdf", "application/pdf"),
    ("repair_estimate.pdf", "application/pdf"),
    ("damage_photo.png", "image/png"),
]


@router.post("/claims/start")
async def start_claim(
    request: Request,
) -> JSONResponse:
    """Accept the bundled sample auto-insurance claim through real intake.

    The sample claim uses the same asynchronous Content Understanding path
    as user uploads: original files are stored immediately, then the
    background classifier writes sidecars and enqueues the workflow.
    """
    app: TypedFastAPI = request.app  # type: ignore

    cu_endpoint = app.app_context.configuration.app_content_understanding_endpoint
    project_endpoint = app.app_context.configuration.app_ai_project_endpoint
    vision_model = app.app_context.configuration.app_azure_openai_model
    if not cu_endpoint:
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "message": (
                    "Content Understanding endpoint is not configured for "
                    "the sample claim intake."
                ),
            },
        )

    schemasets: SchemaSets = app.app_context.get_service(SchemaSets)
    try:
        schema_set_id, category_to_schema = _resolve_schema_map(schemasets)
    except RuntimeError as ex:
        return JSONResponse(
            status_code=503,
            content={"status": "failed", "message": str(ex)},
        )

    default_schema_id = next(iter(category_to_schema.values()))

    intake_files: list[dict[str, Any]] = []
    for file_name, mime_type in _SAMPLE_CLAIM_FILES:
        path = _SAMPLE_CLAIM_DIR / file_name
        if not path.is_file():
            return JSONResponse(
                status_code=500,
                content={
                    "status": "failed",
                    "message": f"Sample file missing: {file_name}",
                },
            )
        file_bytes = path.read_bytes()
        intake_files.append(
            {
                "file_name": file_name,
                "mime_type": mime_type,
                "size": len(file_bytes),
                "bytes": file_bytes,
            }
        )

    try:
        claim_id = await _create_claim_intake_shell(
            app,
            intake_files,
            schema_set_id,
            "Sample auto-claim intake",
            default_schema_id,
        )
    except Exception as ex:  # noqa: BLE001
        logger.exception("Failed to create sample claim intake shell")
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "message": f"Sample claim intake failed: {ex}",
            },
        )

    _schedule_claim_intake_task(
        _classify_and_enqueue_claim(
            app,
            claim_id,
            intake_files,
            schema_set_id,
            "Sample auto-claim intake",
            category_to_schema,
            default_schema_id,
            cu_endpoint=cu_endpoint,
            auto_router=None,
            project_endpoint=project_endpoint,
            vision_model=vision_model,
        )
    )
    return _accepted_response(claim_id, schema_set_id, intake_files, default_schema_id)


def _processing_response(claim_id: str, kind: str) -> JSONResponse:
    """Standard 202 envelope while the workflow is still producing data."""
    return JSONResponse(
        status_code=202,
        content={
            "claim_id": claim_id,
            "status": "processing",
            "message": f"{kind} not yet available; the claim is still being processed.",
        },
    )


async def _build_agent_context(
    request: Request, claim_id: str
) -> tuple[Optional[str], Optional[JSONResponse]]:
    """Assemble the JSON context blob the AOAI helpers consume.

    Returns ``(context_json, None)`` on success, or ``(None, JSONResponse)``
    when the claim is missing or still processing.
    """
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    repo: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )

    manifest = read_manifest(batch_processor, claim_id)
    if manifest is None:
        return None, JSONResponse(
            status_code=404, content={"message": "Claim not found."}
        )

    claim_process = await read_claim_process(repo, claim_id)
    if is_processing(claim_process):
        return None, _processing_response(claim_id, "Agent context")

    sidecar = read_classification_sidecar(batch_processor, claim_id)
    parsed_gaps = parse_gaps(claim_process.process_gaps)
    context = build_claim_context(
        claim_id=claim_id,
        documents=documents_payload(manifest, sidecar, claim_process),
        classification=classification_payload(sidecar),
        summary_markdown=claim_process.process_summary or "",
        fraud=fraud_check_payload(parsed_gaps),
        business=business_checks_payload(parsed_gaps),
    )
    return context, None


async def _agent_payload(
    request: Request,
    claim_id: str,
    *,
    kind: str,
    run,
    fallback: dict[str, Any],
    is_async_run: bool = False,
) -> Any:
    """Run a Foundry hosted agent and return its payload.

    Fixture payloads are used only when Foundry is not configured. Once a
    project and model are configured, upstream failures are surfaced so the
    demo cannot silently show stale canned claim data.
    """
    app: TypedFastAPI = request.app  # type: ignore
    project_endpoint = app.app_context.configuration.app_ai_project_endpoint
    model = app.app_context.configuration.app_azure_openai_model
    if not project_endpoint or not model:
        app_env = os.getenv("APP_ENV", "prod").lower()
        if app_env not in _LOCAL_FIXTURE_ENVS:
            logger.error(
                "Foundry project/model not configured for %s (claim %s); "
                "APP_ENV=%s, returning 503 instead of fixture data.",
                kind,
                claim_id,
                app_env,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "message": (
                        f"The {kind} agent is not configured. Set "
                        "APP_AI_PROJECT_ENDPOINT and APP_AZURE_OPENAI_MODEL."
                    )
                },
            )
        logger.warning(
            "Foundry project not configured; serving fixture for %s (claim %s).",
            kind, claim_id,
        )
        return {**fallback, "generation_source": "fixture"}

    context, error = await _build_agent_context(request, claim_id)
    if error is not None:
        return error

    try:
        result = run(context, model, project_endpoint)
        if is_async_run:
            result = await result
    except PolicyGroundingUnavailable as exc:
        logger.warning(
            "Foundry agent %s skipped for claim %s: %s",
            kind,
            claim_id,
            exc,
        )
        return JSONResponse(status_code=503, content={"message": str(exc)})
    except Exception:  # noqa: BLE001 - surface agent failures uniformly
        logger.exception(
            "Foundry agent %s call failed for claim %s.",
            kind, claim_id,
        )
        return JSONResponse(
            status_code=502,
            content={
                "message": (
                    f"The {kind} agent could not generate a live response. "
                    "Check Foundry Agent Service configuration, model quota, and RBAC."
                )
            },
        )
    return result


@router.get("/claims/{claim_id}/documents")
async def list_documents(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    manifest = read_manifest(batch_processor, claim_id)
    if manifest is None:
        return JSONResponse(status_code=404, content={"message": "Claim not found."})
    sidecar = read_classification_sidecar(batch_processor, claim_id)
    repo: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )
    claim_process = await read_claim_process(repo, claim_id)
    return {
        "claim_id": claim_id,
        "documents": documents_payload(manifest, sidecar, claim_process),
    }


@router.get("/claims/{claim_id}/files/{file_name}/raw")
async def get_claim_file_raw(
    claim_id: str, file_name: str, request: Request
) -> Any:
    """Stream a single uploaded file from the claim's blob prefix.

    Backs the demo's "View document" preview button. Returns the raw
    bytes with a best-effort `Content-Type` so the browser can render
    PDFs and images inline. Files that escape the claim prefix are
    rejected.
    """
    safe_name = file_name.replace("\\", "/").lstrip("/")
    if (
        not safe_name
        or safe_name == "manifest.json"
        or "/" in safe_name
        or ".." in safe_name
    ):
        return JSONResponse(
            status_code=400, content={"message": "Invalid file name."}
        )

    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    try:
        data = batch_processor.blobHelper.download_blob(safe_name, claim_id)
    except ValueError:
        return JSONResponse(
            status_code=404, content={"message": "File not found."}
        )
    except Exception as ex:  # noqa: BLE001
        logger.exception(
            "Failed to download claim file %s/%s", claim_id, safe_name
        )
        return JSONResponse(status_code=500, content={"message": str(ex)})

    media_type = (
        mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.get("/claims/{claim_id}/classification")
async def classification(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    sidecar = read_classification_sidecar(batch_processor, claim_id)
    if sidecar is None:
        return _processing_response(claim_id, "Classification")
    return {
        "claim_id": claim_id,
        "classification": classification_payload(sidecar),
    }


@router.get("/claims/{claim_id}/entities")
async def entities(claim_id: str, request: Request) -> Any:
    """Extract people / vehicles / locations / timeline via Azure OpenAI.
    """
    payload = await _agent_payload(
        request,
        claim_id,
        kind="entities",
        run=lambda ctx, model, project_endpoint: extract_entities(
            project_endpoint=project_endpoint, model=model, claim_context=ctx
        ),
        fallback=_FIXTURE["entities"],
    )
    if isinstance(payload, JSONResponse):
        return payload
    return {"claim_id": claim_id, **payload}


@router.get("/claims/{claim_id}/fraud-check")
async def fraud_check(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    repo: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )
    claim_process = await read_claim_process(repo, claim_id)
    if is_processing(claim_process):
        return _processing_response(claim_id, "Fraud check")
    parsed = parse_gaps(claim_process.process_gaps)
    return {"claim_id": claim_id, **fraud_check_payload(parsed)}


# ---------------------------------------------------------------------------
# Phase B-D: per-claim sidecars (fraud acks, disposition, audit, SIU handoff)
# Restored from commit 3aaf0ad after schema-vault unification accidentally
# removed them. Sidecars live alongside the claim's blobs and use
# batch_processor.blobHelper for read/write.
# ---------------------------------------------------------------------------

_FRAUD_ACKS_SIDECAR = "fraud_acks.json"


def _read_fraud_acks(
    batch_processor: ClaimBatchProcessor, claim_id: str
) -> dict[str, Any]:
    try:
        raw = batch_processor.blobHelper.download_blob(
            _FRAUD_ACKS_SIDECAR, claim_id
        )
    except Exception:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if isinstance(data, dict) and isinstance(data.get("acks"), dict):
        return data["acks"]
    return {}


def _write_fraud_acks(
    batch_processor: ClaimBatchProcessor,
    claim_id: str,
    acks: dict[str, Any],
) -> None:
    payload = json.dumps({"acks": acks})
    batch_processor.blobHelper.upload_blob(
        _FRAUD_ACKS_SIDECAR, payload, claim_id
    )


def _principal_name(request: Request) -> str:
    return (
        request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
        or request.headers.get("X-MS-CLIENT-PRINCIPAL-ID")
        or "adjuster"
    )


class FraudAckRequest(BaseModel):
    finding_id: str = Field(min_length=1, max_length=128)
    acknowledged: bool
    note: str | None = Field(default=None, max_length=1000)


@router.get("/claims/{claim_id}/fraud-acks")
async def get_fraud_acks(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    return {
        "claim_id": claim_id,
        "acks": _read_fraud_acks(batch_processor, claim_id),
    }


@router.post("/claims/{claim_id}/fraud-acks")
async def post_fraud_ack(
    claim_id: str, body: FraudAckRequest, request: Request
) -> Any:
    from datetime import datetime, timezone

    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    acks = _read_fraud_acks(batch_processor, claim_id)
    if body.acknowledged:
        acks[body.finding_id] = {
            "acknowledged": True,
            "by": _principal_name(request),
            "at": datetime.now(timezone.utc).isoformat(),
            "note": (body.note or "").strip() or None,
        }
    else:
        acks.pop(body.finding_id, None)
    _write_fraud_acks(batch_processor, claim_id, acks)
    _append_audit_event(
        batch_processor,
        claim_id,
        "fraud_ack" if body.acknowledged else "fraud_unack",
        request,
        {
            "finding_id": body.finding_id,
            "note": (body.note or "").strip() or None,
        },
    )
    return {"claim_id": claim_id, "acks": acks}


_DISPOSITION_SIDECAR = "disposition.json"
_DISPOSITION_DECISIONS = {
    "approve",
    "approve_with_conditions",
    "decline",
    "refer_to_siu",
}


def _read_disposition(
    batch_processor: ClaimBatchProcessor, claim_id: str
) -> dict[str, Any] | None:
    try:
        raw = batch_processor.blobHelper.download_blob(
            _DISPOSITION_SIDECAR, claim_id
        )
    except Exception:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict) and data.get("decision") in _DISPOSITION_DECISIONS:
        return data
    return None


def _write_disposition(
    batch_processor: ClaimBatchProcessor,
    claim_id: str,
    record: dict[str, Any],
) -> None:
    batch_processor.blobHelper.upload_blob(
        _DISPOSITION_SIDECAR, json.dumps(record), claim_id
    )


def _delete_disposition(
    batch_processor: ClaimBatchProcessor, claim_id: str
) -> None:
    # blobHelper has no explicit delete in our wrapper - overwriting with an
    # empty marker keeps reads returning None via the schema check.
    try:
        batch_processor.blobHelper.upload_blob(
            _DISPOSITION_SIDECAR, json.dumps({"cleared": True}), claim_id
        )
    except Exception:
        pass


class DispositionSnapshotModel(BaseModel):
    verdict: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=8000)
    follow_ups: list[str] = Field(default_factory=list)
    member_policy_number: str | None = Field(default=None, max_length=64)
    guidance_section_ids: list[str] = Field(default_factory=list)


class DispositionRequest(BaseModel):
    decision: str = Field(min_length=1, max_length=64)
    snapshot: DispositionSnapshotModel
    note: str | None = Field(default=None, max_length=2000)


@router.get("/claims/{claim_id}/disposition")
async def get_disposition(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    return {
        "claim_id": claim_id,
        "disposition": _read_disposition(batch_processor, claim_id),
    }


@router.post("/claims/{claim_id}/disposition")
async def post_disposition(
    claim_id: str, body: DispositionRequest, request: Request
) -> Any:
    from datetime import datetime, timezone
    from fastapi import HTTPException

    if body.decision not in _DISPOSITION_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"decision must be one of {sorted(_DISPOSITION_DECISIONS)}",
        )

    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    record = {
        "decision": body.decision,
        "decided_by": _principal_name(request),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "note": (body.note or "").strip() or None,
        "snapshot": body.snapshot.model_dump(),
    }
    _write_disposition(batch_processor, claim_id, record)
    _append_audit_event(
        batch_processor,
        claim_id,
        "disposition_set",
        request,
        {
            "decision": body.decision,
            "verdict": body.snapshot.verdict,
            "confidence": body.snapshot.confidence,
            "note": (body.note or "").strip() or None,
        },
    )
    return {"claim_id": claim_id, "disposition": record}


@router.delete("/claims/{claim_id}/disposition")
async def delete_disposition(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    _delete_disposition(batch_processor, claim_id)
    _append_audit_event(
        batch_processor, claim_id, "disposition_cleared", request, None
    )
    return {"claim_id": claim_id, "disposition": None}


_AUDIT_SIDECAR = "audit.json"
_AUDIT_EVENT_TYPES = {
    "claim_created",
    "summary_saved",
    "attested",
    "fraud_ack",
    "fraud_unack",
    "disposition_set",
    "disposition_cleared",
    "marked_for_siu",
    "siu_exported",
    "email_sent",
    "claim_reset",
}


def _read_audit(
    batch_processor: ClaimBatchProcessor, claim_id: str
) -> list[dict[str, Any]]:
    try:
        raw = batch_processor.blobHelper.download_blob(_AUDIT_SIDECAR, claim_id)
    except Exception:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict):
        events = data.get("events")
        if isinstance(events, list):
            return [e for e in events if isinstance(e, dict)]
    return []


def _write_audit(
    batch_processor: ClaimBatchProcessor,
    claim_id: str,
    events: list[dict[str, Any]],
) -> None:
    batch_processor.blobHelper.upload_blob(
        _AUDIT_SIDECAR, json.dumps({"events": events}), claim_id
    )


def _append_audit_event(
    batch_processor: ClaimBatchProcessor,
    claim_id: str,
    event_type: str,
    request: Request,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from datetime import datetime, timezone
    from uuid import uuid4

    if event_type not in _AUDIT_EVENT_TYPES:
        event_type = "unknown"
    event = {
        "id": uuid4().hex,
        "type": event_type,
        "at": datetime.now(timezone.utc).isoformat(),
        "by": _principal_name(request),
        "payload": payload or {},
    }
    events = _read_audit(batch_processor, claim_id)
    events.append(event)
    _write_audit(batch_processor, claim_id, events)
    return event


@router.get("/claims/{claim_id}/audit")
async def get_audit(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    return {
        "claim_id": claim_id,
        "events": _read_audit(batch_processor, claim_id),
    }


class SIUHandoffRequest(BaseModel):
    snapshot: DispositionSnapshotModel
    note: str | None = Field(default=None, max_length=2000)


@router.post("/claims/{claim_id}/siu")
async def post_siu_handoff(
    claim_id: str, body: SIUHandoffRequest, request: Request
) -> Any:
    """Flip disposition to refer_to_siu, record marked_for_siu + siu_exported,
    and return a read-only export bundle (disposition + acks + audit)."""
    from datetime import datetime, timezone

    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    note = (body.note or "").strip() or None
    record = {
        "decision": "refer_to_siu",
        "decided_by": _principal_name(request),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "snapshot": body.snapshot.model_dump(),
    }
    _write_disposition(batch_processor, claim_id, record)
    _append_audit_event(
        batch_processor,
        claim_id,
        "disposition_set",
        request,
        {"decision": "refer_to_siu", "via": "siu_handoff"},
    )
    _append_audit_event(
        batch_processor, claim_id, "marked_for_siu", request, {"note": note}
    )
    acks = _read_fraud_acks(batch_processor, claim_id)
    _append_audit_event(
        batch_processor,
        claim_id,
        "siu_exported",
        request,
        {"ack_count": len(acks)},
    )
    bundle = {
        "claim_id": claim_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": _principal_name(request),
        "disposition": record,
        "fraud_acks": acks,
        "audit": _read_audit(batch_processor, claim_id),
    }
    return {"claim_id": claim_id, "disposition": record, "export": bundle}


@router.get("/claims/{claim_id}/business-checks")
async def business_checks(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    repo: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )
    claim_process = await read_claim_process(repo, claim_id)
    if is_processing(claim_process):
        return _processing_response(claim_id, "Business checks")
    parsed = parse_gaps(claim_process.process_gaps)
    return {"claim_id": claim_id, "checks": business_checks_payload(parsed)}


@router.get("/claims/{claim_id}/summary")
async def get_summary(claim_id: str, request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    repo: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )
    claim_process = await read_claim_process(repo, claim_id)
    if claim_process is None or not (claim_process.process_summary or "").strip():
        if is_processing(claim_process):
            return _processing_response(claim_id, "Summary")
    return {
        "claim_id": claim_id,
        "markdown": claim_process.process_summary or "",
        "key_facts": {},
    }


@router.put("/claims/{claim_id}/summary")
async def put_summary(claim_id: str, body: dict[str, Any], request: Request) -> Any:
    app: TypedFastAPI = request.app  # type: ignore
    repo: ClaimBatchProcessRepository = app.app_context.get_service(
        ClaimBatchProcessRepository
    )
    claim_process = await read_claim_process(repo, claim_id)
    if claim_process is None:
        return JSONResponse(status_code=404, content={"message": "Claim not found."})
    new_markdown = (body or {}).get("markdown", "")
    if not isinstance(new_markdown, str):
        return JSONResponse(
            status_code=400, content={"message": "`markdown` must be a string."}
        )
    claim_process.process_summary = new_markdown
    await repo.update_async(claim_process)
    return {"claim_id": claim_id, "saved": True, "summary": {"markdown": new_markdown}}


@router.post("/claims/{claim_id}/recommendation")
async def recommendation(claim_id: str, request: Request) -> Any:
    """Generate a verdict + rationale + next actions via Azure OpenAI."""
    app: TypedFastAPI = request.app  # type: ignore
    cfg = app.app_context.configuration
    payload = await _agent_payload(
        request,
        claim_id,
        kind="recommendation",
        run=lambda ctx, model, project_endpoint: recommend_outcome(
            project_endpoint=project_endpoint,
            model=model,
            claim_context=ctx,
            search_connection_name=cfg.app_ai_search_connection_name,
            search_index_name=cfg.app_ai_search_index_name,
            member_policies_endpoint=getattr(cfg, "app_ai_search_endpoint", ""),
            member_policies_index_name=getattr(
                cfg, "app_member_policies_index_name", ""
            ),
        ),
        fallback=_FIXTURE["recommendation"],
    )
    if isinstance(payload, JSONResponse):
        return payload
    if isinstance(payload, dict):
        payload = _normalize_recommendation_payload(payload)
    return {"claim_id": claim_id, **payload}


def _strip_retrieval_citations(text: str) -> str:
    """Remove raw Responses API retrieval markers from model text."""
    if not text:
        return text
    return re.sub(r"\u3010[^\u3011]*?\u2020[^\u3011]*?\u3011", "", text).strip()


def _normalize_recommendation_payload(payload: dict) -> dict:
    """Reshape the raw recommendation-agent JSON into the shape the SPA's
    ``Section7Recommendation`` component reads. The agent prompt emits a
    flat object {verdict, confidence, rationale, next_actions,
    policy_excerpts:[{section,text}]} whereas the SPA expects
    {recommendation:{verdict,confidence,rationale}, stream_text,
    policy_excerpts:[{id,section,snippet}], follow_ups}. Local fixture payloads
    are already in SPA shape, so leave them untouched.
    """
    if isinstance(payload.get("recommendation"), dict) and "stream_text" in payload:
        return payload
    verdict = payload.get("verdict") or "Investigate further"
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.7
    rationale = _strip_retrieval_citations(payload.get("rationale") or "")
    next_actions = payload.get("next_actions") or payload.get("follow_ups") or []
    def _policy_excerpts(raw_excerpts: Any, source: str) -> list[dict]:
        excerpts: list[dict] = []
        for idx, ex in enumerate(raw_excerpts or [], start=1):
            if not isinstance(ex, dict):
                continue
            excerpts.append(
                {
                    "id": ex.get("id") or f"{source}-{idx}",
                    "section": ex.get("section") or f"Excerpt {idx}",
                    "snippet": ex.get("snippet") or ex.get("text") or "",
                    "source": source,
                }
            )
        return excerpts

    def _guidance_excerpts(raw_excerpts: Any) -> list[dict]:
        excerpts: list[dict] = []
        for idx, ex in enumerate(raw_excerpts or [], start=1):
            if not isinstance(ex, dict):
                continue
            excerpts.append(
                {
                    "id": ex.get("id") or f"guidance-{idx}",
                    "section": ex.get("section") or f"Guidance {idx}",
                    "source_filename": ex.get("source_filename") or "",
                    "snippet": ex.get("snippet") or ex.get("text") or "",
                }
            )
        return excerpts

    member_policy = payload.get("member_policy")
    normalized_member_policy = None
    member_policy_excerpts: list[dict] = []
    if isinstance(member_policy, dict):
        member_policy_excerpts = _policy_excerpts(
            member_policy.get("policy_excerpts"), "member_policy"
        )
        normalized_member_policy = {
            "policy_number": member_policy.get("policy_number") or "",
            "form_version": member_policy.get("form_version") or "",
            "status": member_policy.get("status") or "",
            "in_force_at_loss": bool(member_policy.get("in_force_at_loss")),
            "applicable_coverage": member_policy.get("applicable_coverage") or "",
            "applicable_deductible": member_policy.get("applicable_deductible"),
            "applicable_endorsements": [
                str(item)
                for item in member_policy.get("applicable_endorsements") or []
                if item
            ],
            "policy_excerpts": member_policy_excerpts,
        }

    guidance_excerpts = _guidance_excerpts(payload.get("guidance_excerpts"))
    raw_excerpts = payload.get("policy_excerpts") or []
    fallback_excerpts = []
    for idx, ex in enumerate(raw_excerpts, start=1):
        if not isinstance(ex, dict):
            continue
        fallback_excerpts.append(
            {
                "id": ex.get("id") or f"px-{idx}",
                "section": ex.get("section") or f"Excerpt {idx}",
                "snippet": ex.get("snippet") or ex.get("text") or "",
                "source": ex.get("source") or "guidance",
            }
        )
    excerpts = member_policy_excerpts + [
        {**ex, "source": "guidance"} for ex in guidance_excerpts
    ]
    if not excerpts:
        excerpts = fallback_excerpts
    result = {
        "stream_text": rationale,
        "policy_excerpts": excerpts,
        "recommendation": {
            "verdict": verdict,
            "confidence": float(confidence),
            "rationale": rationale,
        },
        "follow_ups": [str(a) for a in next_actions if a],
    }
    if normalized_member_policy is not None:
        result["member_policy"] = normalized_member_policy
    if guidance_excerpts:
        result["guidance_excerpts"] = guidance_excerpts
    return {
        **result,
    }


@router.get("/claims/{claim_id}/email-draft")
async def email_draft_route(claim_id: str, request: Request) -> Any:
    """Draft an outcome letter via Azure OpenAI, grounded in the verdict."""
    app: TypedFastAPI = request.app  # type: ignore
    cfg = app.app_context.configuration
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )

    # Prefer the human-attested disposition saved in step 6 over a fresh
    # re-derivation from the agent. This (a) ensures the letter actually
    # reflects what the adjuster decided + their note + the listed
    # follow-ups, and (b) skips a slow recommend_outcome round-trip when
    # we already have the answer.
    disposition = _read_disposition(batch_processor, claim_id)
    snapshot = (
        disposition.get("snapshot") if isinstance(disposition, dict) else None
    ) or {}

    async def _run_email(ctx: str, model: str, project_endpoint: str) -> dict[str, Any]:
        if disposition:
            verdict = (
                snapshot.get("verdict")
                or disposition.get("decision", "Review required")
            )
            follow_ups = [
                str(f) for f in (snapshot.get("follow_ups") or []) if f
            ]
            return draft_email(
                project_endpoint=project_endpoint,
                model=model,
                claim_context=ctx,
                verdict=str(verdict),
                decision=str(disposition.get("decision") or ""),
                adjuster_note=str(disposition.get("note") or "") or None,
                follow_ups=follow_ups or None,
                decided_by=str(disposition.get("decided_by") or "") or None,
            )
        rec = recommend_outcome(
            project_endpoint=project_endpoint,
            model=model,
            claim_context=ctx,
            search_connection_name=cfg.app_ai_search_connection_name,
            search_index_name=cfg.app_ai_search_index_name,
        )
        verdict = rec.get("verdict") or "Review required"
        return draft_email(
            project_endpoint=project_endpoint,
            model=model,
            claim_context=ctx,
            verdict=verdict,
        )

    payload = await _agent_payload(
        request,
        claim_id,
        kind="email",
        run=lambda ctx, model, project_endpoint: _run_email(ctx, model, project_endpoint),
        fallback=_FIXTURE["email_draft"],
        is_async_run=True,
    )
    if isinstance(payload, JSONResponse):
        return payload
    # The Foundry agent returns `body_markdown`; the SPA reads `body`.
    # Normalise so both shapes work without forcing a SPA redeploy if the
    # agent prompt changes.
    if isinstance(payload, dict):
        body = payload.get("body") or payload.get("body_markdown") or ""
        # Belt-and-suspenders: strip internal claim_id GUIDs from the
        # subject line in case the model ignores its instructions. The
        # body keeps any user-facing claim_number references untouched.
        subject = payload.get("subject") or ""
        if subject:
            subject = re.sub(
                r"\s*[–\-]?\s*(?:Claim\s+)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                "",
                subject,
            ).strip(" -–")
        payload = {**payload, "body": body, "body_markdown": body, "subject": subject}
    return {"claim_id": claim_id, **payload}


_EMAIL_QUEUE_SIDECAR = "email_queue.json"


def _read_email_queue(
    batch_processor: ClaimBatchProcessor, claim_id: str
) -> dict[str, Any] | None:
    try:
        raw = batch_processor.blobHelper.download_blob(
            _EMAIL_QUEUE_SIDECAR, claim_id
        )
    except Exception:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict) and data.get("delivery_id"):
        return data
    return None


@router.post("/claims/{claim_id}/email-send")
async def email_send(
    claim_id: str, body: dict[str, Any], request: Request
) -> Any:
    """Queue the customer letter for delivery.

    Demo-grade: we don't actually invoke Microsoft Graph (that's a
    customer-side integration choice). We persist the queued payload as a
    sidecar in the claim blob so the SPA can rehydrate the "queued" badge
    on reload, and so the action is audit-traceable.
    """
    from datetime import datetime, timezone

    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    delivery_id = uuid.uuid4().hex
    record = {
        "delivery_id": delivery_id,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "to": str(body.get("to") or ""),
        "cc": str(body.get("cc") or ""),
        "subject": str(body.get("subject") or ""),
        "body": str(body.get("body") or ""),
    }
    try:
        batch_processor.blobHelper.upload_blob(
            _EMAIL_QUEUE_SIDECAR, json.dumps(record), claim_id
        )
    except Exception:
        logger.exception(
            "Failed to persist email_queue sidecar for claim %s", claim_id
        )
        return JSONResponse(
            status_code=500,
            content={
                "claim_id": claim_id,
                "queued": False,
                "message": "Email queue state could not be persisted.",
            },
        )
    _append_audit_event(
        batch_processor,
        claim_id,
        "email_sent",
        request,
        {
            "delivery_id": delivery_id,
            "to": record["to"],
            "subject": record["subject"],
        },
    )
    return {
        "claim_id": claim_id,
        "queued": True,
        "delivery_id": delivery_id,
    }


@router.get("/claims/{claim_id}/email-status")
async def email_status(claim_id: str, request: Request) -> dict[str, Any]:
    """Return the queued-email sidecar so the SPA can rehydrate state."""
    app: TypedFastAPI = request.app  # type: ignore
    batch_processor: ClaimBatchProcessor = app.app_context.get_service(
        ClaimBatchProcessor
    )
    record = _read_email_queue(batch_processor, claim_id)
    if not record:
        return {"claim_id": claim_id, "queued": None}
    return {
        "claim_id": claim_id,
        "queued": {
            "delivery_id": record["delivery_id"],
            "queued_at": record.get("queued_at", ""),
            "to": record.get("to", ""),
            "subject": record.get("subject", ""),
        },
    }

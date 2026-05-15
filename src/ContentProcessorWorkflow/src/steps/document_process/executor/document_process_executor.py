"""Document-processing executor for the claim workflow pipeline.

First step in the three-stage pipeline (document_processing -> summarizing ->
gap_analysis).  Downloads a manifest from blob storage, submits each
referenced file to the content-processing service, polls for completion, and
upserts per-file results into Cosmos DB.

Uses direct resource access (Blob, Queue, Cosmos DB) instead of HTTP calls
to the ContentProcessorAPI, avoiding Easy Auth sidecar issues.
"""

import asyncio
import json
import logging
import mimetypes
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent_framework import Executor, WorkflowContext, handler
from sas.storage.blob.async_helper import AsyncStorageBlobHelper

from libs.application.application_context import AppContext
from repositories.claim_processes import Claim_Process, Claim_Processes, Content_Process
from services.content_process_service import ContentProcessService
from steps.models.output import Executor_Output, Workflow_Output

from ...models.manifest import ClaimProcess

logger = logging.getLogger(__name__)


class DocumentProcessExecutor(Executor):
    """Workflow executor that runs the document-processing step.

    Responsibilities:
        1. Generate a unique, lexicographically sortable claim-process name.
        2. Download ``manifest.json`` from the process-batch blob container.
        3. Create a ``Claim_Process`` record in Cosmos DB.
        4. Submit each manifest file directly via blob/queue/cosmos.
        5. Poll Cosmos DB until terminal status and upsert progress.
        6. Forward the aggregated ``Workflow_Output`` to the next executor.

    Class-level Attributes:
        _claim_name_lock: Async lock protecting the timestamp-sequence counter.
        _claim_name_last_ts: Last timestamp string used for name generation.
        _claim_name_seq: Sequence counter for same-timestamp disambiguation.
    """

    _claim_name_lock = threading.Lock()
    _claim_name_last_ts: str | None = None
    _claim_name_seq: int = 0

    _CLASSIFICATION_SIDECAR_NAME = "classification.json"
    _CATEGORY_TO_DSL_DOCUMENT_TYPE = {
        "auto_insurance_claim_form": "claim_form",
        "police_report": "police_report",
        "repair_estimate": "repair_estimate",
        "damage_photo": "damage_photo",
    }

    @classmethod
    def _dsl_document_type_for_category(cls, category: str | None) -> str | None:
        if not category:
            return None
        normalized = category.strip().lower().replace(" ", "_")
        return cls._CATEGORY_TO_DSL_DOCUMENT_TYPE.get(normalized)

    async def _load_document_type_sidecar(
        self,
        storage_helper: AsyncStorageBlobHelper,
        claim_id: str,
    ) -> dict[str, str]:
        try:
            sidecar = await storage_helper.download_blob(
                self.app_context.configuration.app_cps_process_batch,
                f"{claim_id}/{self._CLASSIFICATION_SIDECAR_NAME}",
            )
        except Exception:
            logger.warning(
                "Classification sidecar download failed for %s; "
                "gap analysis will infer document inventory from extracts",
                claim_id,
                exc_info=True,
            )
            return {}

        if not sidecar:
            return {}

        try:
            payload = json.loads(bytes(sidecar).decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            logger.warning(
                "Classification sidecar for %s was not valid JSON; "
                "gap analysis will infer document inventory from extracts",
                claim_id,
                exc_info=True,
            )
            return {}

        document_types: dict[str, str] = {}
        entries = payload.get("files", []) if isinstance(payload, dict) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            file_name = str(entry.get("file_name") or "")
            doc_type = self._dsl_document_type_for_category(entry.get("category"))
            if file_name and doc_type:
                document_types[file_name] = doc_type
        return document_types

    @classmethod
    async def _generate_claim_process_name(
        cls,
        *,
        claim_id: str,
        created_time: datetime | None = None,
    ) -> str:
        """Create a unique, time-sequential, lexicographically sortable process name.

        Format: Claim-<YYYYMMDDHHMMSSffffff>-<SEQ>-<CLAIM>
        - Time prefix sorts naturally by name.
        - SEQ breaks ties when timestamps repeat.
        - CLAIM adds extra uniqueness without impacting ordering.
        """

        if created_time is not None and not isinstance(created_time, datetime):
            created_time = None

        dt = created_time or datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)

        ts = dt.strftime("%Y%m%d%H%M%S%f")

        # Protect against same-timestamp collisions (rare but possible).
        with cls._claim_name_lock:
            if ts == cls._claim_name_last_ts:
                cls._claim_name_seq += 1
            else:
                cls._claim_name_last_ts = ts
                cls._claim_name_seq = 0
            seq = cls._claim_name_seq

        batch_fragment = "".join(ch for ch in str(claim_id) if ch.isalnum())[:6].upper()
        if not batch_fragment:
            batch_fragment = uuid.uuid4().hex[:6].upper()

        return f"claim-{ts}-{seq:04d}-{batch_fragment}"

    def __init__(self, id: str, app_context: AppContext):
        """Create a new document process executor bound to an application context."""
        super().__init__(id=id)
        self.app_context = app_context

    @handler
    async def handle_execute(
        self,
        claim_id: str,
        ctx: WorkflowContext[Workflow_Output],
    ) -> None:
        """Execute document processing for a claim via direct resource access.

        Steps:
            1. Download ``manifest.json`` from the process-batch container.
            2. Generate a unique claim-process name and persist a new
               ``Claim_Process`` record in Cosmos DB.
            3. Submit each manifest file directly to blob/queue/cosmos
               (no HTTP calls to ContentProcessorAPI).
            4. Poll Cosmos DB for each submission until terminal status.
            5. Fetch final output scores and upsert ``Content_Process``
               records.
            6. Aggregate per-file results into a ``Workflow_Output`` and
               forward it to the next executor via the workflow context.

        Args:
            claim_id: Identifier of the claim to process.
            ctx: Workflow context carrying shared state across executors.
        """
        storage_helper = await self.app_context.get_service_async(
            AsyncStorageBlobHelper
        )
        claim_process_repository = self.app_context.get_service(Claim_Processes)
        content_process_service = self.app_context.get_service(ContentProcessService)

        manifest_stream = await storage_helper.download_blob(
            self.app_context.configuration.app_cps_process_batch,
            f"{claim_id}/manifest.json",
        )
        manifest = ClaimProcess.model_validate_json(manifest_stream)
        document_type_by_filename = await self._load_document_type_sidecar(
            storage_helper,
            claim_id,
        )

        new_claim_process_name = await self._generate_claim_process_name(
            claim_id=claim_id,
            created_time=getattr(manifest, "created_time", None),
        )

        new_claim_process = Claim_Process(
            id=claim_id,
            process_name=new_claim_process_name,
            schemaset_id=manifest.schema_collection_id,
            metadata_id=manifest.metadata_id,
        )
        await claim_process_repository.Create_Claim_Process(new_claim_process)

        document_results: list[dict] = []

        poll_interval_seconds = float(
            getattr(
                self.app_context.configuration,
                "app_cps_poll_interval_seconds",
                5.0,
            )
        )

        # Limit concurrency; serialize Cosmos writes via _upsert_lock to
        # prevent lost-update races on the shared Claim_Process document.
        max_concurrency = 4
        semaphore = asyncio.Semaphore(max_concurrency)
        _upsert_lock = asyncio.Lock()

        async def _process_one(item) -> dict:
            async with semaphore:
                content_type, _ = mimetypes.guess_type(str(item.file_name))
                try:
                    source_file = await storage_helper.download_blob(
                        container_name=self.app_context.configuration.app_cps_process_batch,
                        blob_name=f"{claim_id}/{item.file_name}",
                    )

                    filename = Path(str(item.file_name)).name
                    file_bytes = bytes(source_file)

                    # Stage B: pick up the per-file CU envelope sidecar the
                    # API persisted alongside the source. Best-effort —
                    # absence means the workflow's MapHandler will run its
                    # own CU call (safe degradation).
                    cu_envelope_bytes: bytes | None = None
                    try:
                        sidecar = await storage_helper.download_blob(
                            container_name=self.app_context.configuration.app_cps_process_batch,
                            blob_name=f"{claim_id}/{item.file_name}.cu.json",
                        )
                        if sidecar:
                            cu_envelope_bytes = bytes(sidecar)
                        else:
                            logger.debug(
                                "No CU envelope sidecar for %s/%s "
                                "(blob not present; MapHandler will run "
                                "its own CU call)",
                                claim_id,
                                item.file_name,
                            )
                    except Exception:  # noqa: BLE001 - auth/network must surface
                        # AsyncStorageBlobHelper.download_blob already
                        # returns None on ResourceNotFoundError, so
                        # anything reaching here is a real failure
                        # (auth, network, throttling). Demote to warning
                        # rather than debug so an env-wide regression is
                        # visible in logs instead of silently degrading
                        # every claim to the legacy 2-call CU path.
                        logger.warning(
                            "CU envelope sidecar download failed for "
                            "%s/%s; falling back to per-schema CU call",
                            claim_id,
                            item.file_name,
                            exc_info=True,
                        )

                    metadata_id = (
                        item.metadata_id if item.metadata_id else f"Meta-{uuid.uuid4()}"
                    )
                    schema_id = str(item.schema_id)

                    logger.info(
                        "Processing document: %s with schema_id: %s",
                        item.file_name,
                        schema_id,
                    )

                    # Direct submit: blob upload + cosmos insert + queue enqueue
                    process_id = await content_process_service.submit(
                        file_bytes=file_bytes,
                        filename=filename,
                        mime_type=content_type or "application/octet-stream",
                        schema_id=schema_id,
                        metadata_id=metadata_id,
                        cu_envelope_bytes=cu_envelope_bytes,
                        claim_process_id=claim_id,
                    )

                    # Upsert initial "processing" status to claim process
                    async with _upsert_lock:
                        await claim_process_repository.Upsert_Content_Process(
                            process_id=claim_id,
                            content_process=Content_Process(
                                process_id=process_id,
                                file_name=str(item.file_name),
                                mime_type=content_type or "application/octet-stream",
                                status="processing",
                            ),
                        )

                    # Poll until terminal status, upserting intermediate
                    # changes. Skip duplicate and terminal statuses to
                    # avoid clobbering the caller's richer final upsert.
                    _last_polled_status: str | None = None

                    async def _on_poll(poll_data: dict) -> None:
                        nonlocal _last_polled_status
                        polled_status = poll_data.get("status", "processing")
                        if polled_status == _last_polled_status:
                            return
                        _last_polled_status = polled_status
                        # Terminal statuses are handled by the caller with scores.
                        if polled_status in ("Completed", "Error"):
                            return
                        async with _upsert_lock:
                            await claim_process_repository.Upsert_Content_Process(
                                process_id=claim_id,
                                content_process=Content_Process(
                                    process_id=process_id,
                                    file_name=str(item.file_name),
                                    mime_type=content_type
                                    or "application/octet-stream",
                                    status=polled_status,
                                ),
                            )

                    poll_result = await content_process_service.poll_status(
                        process_id=process_id,
                        poll_interval_seconds=poll_interval_seconds,
                        timeout_seconds=600.0,
                        on_poll=_on_poll,
                    )

                    status_text = poll_result.get("status", "Failed")

                    schema_score_f = 0.0
                    entity_score_f = 0.0
                    processed_time = ""
                    result_payload = None

                    if process_id:
                        final_payload = await content_process_service.get_processed(
                            process_id
                        )
                        if isinstance(final_payload, dict):
                            status_text = final_payload.get("status") or status_text
                            try:
                                schema_score_f = float(
                                    final_payload.get("schema_score") or 0.0
                                )
                            except Exception:
                                schema_score_f = 0.0
                            try:
                                entity_score_f = float(
                                    final_payload.get("entity_score") or 0.0
                                )
                            except Exception:
                                entity_score_f = 0.0
                            try:
                                processed_time = (
                                    final_payload.get("processed_time") or ""
                                )
                            except Exception:
                                processed_time = ""
                            result_payload = final_payload

                        # Final upsert with scores
                        async with _upsert_lock:
                            await claim_process_repository.Upsert_Content_Process(
                                process_id=claim_id,
                                content_process=Content_Process(
                                    process_id=process_id,
                                    file_name=str(item.file_name),
                                    mime_type=content_type
                                    or "application/octet-stream",
                                    status=status_text,
                                    schema_score=schema_score_f,
                                    entity_score=entity_score_f,
                                    processed_time=processed_time,
                                ),
                            )

                    # Map to HTTP-like code for downstream compatibility
                    if status_text == "Completed":
                        status_code = 302
                    elif status_text in ("Error", "Failed"):
                        status_code = 500
                    else:
                        status_code = 200

                    return {
                        "file_name": str(item.file_name),
                        "schema_id": str(item.schema_id),
                        "document_type": document_type_by_filename.get(
                            str(item.file_name)
                        ),
                        "mime_type": content_type or "application/octet-stream",
                        "process_id": process_id,
                        "status": status_code,
                        "final_status": status_text,
                        "schema_score": schema_score_f,
                        "entity_score": entity_score_f,
                        "response": result_payload,
                        "poll_url": "",
                    }
                except Exception as e:
                    logger.exception(
                        "Document processing failed for %s: %s",
                        getattr(item, "file_name", "<unknown>"),
                        e,
                    )
                    return {
                        "file_name": str(getattr(item, "file_name", "<unknown>")),
                        "schema_id": str(getattr(item, "schema_id", "<unknown>")),
                        "status": "exception",
                        "response": f"{type(e).__name__}: {e}",
                    }

        tasks: list[asyncio.Task[dict]] = []
        async with asyncio.TaskGroup() as tg:
            for item in manifest.items:
                tasks.append(tg.create_task(_process_one(item)))

        document_results.extend([t.result() for t in tasks])

        processed_document = {
            "status": "processed",
            "claim_id": claim_id,
            "document_results": document_results,
        }

        workflow_output = Workflow_Output(
            claim_process_id=claim_id, schemaset_id=manifest.schema_collection_id
        )
        workflow_output.workflow_process_outputs.append(
            Executor_Output(
                step_name="document_processing", output_data=processed_document
            )
        )

        await ctx.set_shared_state("workflow_output", workflow_output)
        await ctx.send_message(workflow_output)

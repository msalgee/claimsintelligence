"""Extract handler — document content extraction via Azure Content Understanding.

Processes PDF files through the Content Understanding pre-built layout
analyzer. Image files bypass extraction entirely.

Stage B short-circuit: if the API layer already classified this file with
the linked-router (``AutoClaimLinkedRouter``), the per-doc envelope sits
at ``app_cps_processes/{process_id}/{file_name}.cu.json`` and already
contains ``result.contents[0].markdown`` — the same field
``prebuilt-layout`` would produce and the only field downstream agents
(RAI, Summarize, Gap) read. We pass that sidecar through and skip the
redundant CU call. Any failure falls back to the legacy ``prebuilt-layout``
path so non-claimsdemo callers are unaffected.
"""

import json
import logging

from azure.core.exceptions import ResourceNotFoundError

from libs.application.application_context import AppContext
from libs.azure_helper.content_understanding import AzureContentUnderstandingHelper
from libs.azure_helper.model.content_understanding import AnalyzedResult
from libs.pipeline.entities.mime_types import MimeTypes
from libs.pipeline.entities.pipeline_file import ArtifactType, PipelineLogEntry
from libs.pipeline.entities.pipeline_message_context import MessageContext
from libs.pipeline.entities.pipeline_step_result import StepResult
from libs.pipeline.queue_handler_base import HandlerBase

logger = logging.getLogger(__name__)


class ExtractHandler(HandlerBase):
    """Pipeline step that extracts structured content from source documents.

    Responsibilities:
        1. Route by MIME type (skip images, process PDFs).
        2. Invoke Azure Content Understanding for layout analysis.
        3. Persist extracted results to blob storage.
    """

    def __init__(self, appContext: AppContext, step_name: str, **data):
        super().__init__(appContext, step_name, **data)

    async def execute(self, context: MessageContext) -> StepResult:
        # if Content Type is image then skip extraction by Azure Content Understanding
        if context.data_pipeline.get_source_files()[0].mime_type in [
            MimeTypes.ImagePng,
            MimeTypes.ImageJpeg,
        ]:
            return StepResult(
                process_id=context.data_pipeline.pipeline_status.process_id,
                step_name=self.handler_name,
                result={
                    "result": "skipped",
                    "reason": "Content type is image, skipping extraction.",
                },
            )

        # if Content Type is PDF
        if context.data_pipeline.get_source_files()[0].mime_type == MimeTypes.Pdf:
            source_file = context.data_pipeline.get_source_files()[0]
            process_id = context.data_pipeline.pipeline_status.process_id

            # Stage B short-circuit: prefer the API-supplied CU envelope
            # sidecar (``{process_id}/{file_name}.cu.json``) over a
            # second CU call. The linked router already produced
            # ``contents[0].markdown`` — identical in shape and content
            # to ``prebuilt-layout`` for our claim docs and the only
            # field downstream agents read. Best-effort: any failure
            # falls through to the legacy ``prebuilt-layout`` path.
            sidecar_payload: dict | None = None
            try:
                from azure.storage.blob import BlobServiceClient

                from libs.utils.azure_credential_utils import get_azure_credential

                processes_container = (
                    self.application_context.configuration.app_cps_processes
                )
                blob_service = BlobServiceClient(
                    account_url=self.application_context.configuration.app_storage_blob_url,
                    credential=get_azure_credential(),
                )
                sidecar_bytes = (
                    blob_service.get_blob_client(
                        container=processes_container,
                        blob=f"{process_id}/{source_file.name}.cu.json",
                    )
                    .download_blob()
                    .readall()
                )
                candidate = json.loads(sidecar_bytes.decode("utf-8"))
                # Linked-router envelope is ``{"status": ..., "result":
                # {"contents": [...]}}``. Earlier code walked
                # ``candidate["contents"]`` directly which silently missed
                # every real envelope and forced a redundant
                # prebuilt-layout call. Accept both shapes for safety.
                result_block = candidate.get("result") or candidate
                contents = result_block.get("contents") or []
                if contents and (
                    contents[0].get("markdown")
                    or contents[0].get("markdownContent")
                ):
                    sidecar_payload = candidate
                    logger.info(
                        "extract_handler: using CU envelope sidecar "
                        "process=%s file=%s (skipped prebuilt-layout call)",
                        process_id,
                        source_file.name,
                    )
            except ResourceNotFoundError:
                sidecar_payload = None
                logger.debug(
                    "extract_handler: no CU envelope sidecar for %s/%s",
                    process_id,
                    source_file.name,
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                sidecar_payload = None
                logger.warning(
                    "extract_handler: corrupt CU envelope sidecar for "
                    "%s/%s; falling back to prebuilt-layout",
                    process_id,
                    source_file.name,
                    exc_info=True,
                )
            except Exception:  # noqa: BLE001 - auth/network must surface
                sidecar_payload = None
                logger.warning(
                    "extract_handler: CU envelope sidecar download "
                    "failed for %s/%s; falling back to prebuilt-layout",
                    process_id,
                    source_file.name,
                    exc_info=True,
                )

            if sidecar_payload is not None:
                result_file = context.data_pipeline.add_file(
                    file_name="content_understanding_output.json",
                    artifact_type=ArtifactType.ExtractedContent,
                )
                result_file.log_entries.append(
                    PipelineLogEntry(**{
                        "source": self.handler_name,
                        "message": (
                            "Content Understanding Extraction Result "
                            "sourced from linked-router sidecar."
                        ),
                    })
                )
                result_file.upload_json_text(
                    account_url=self.application_context.configuration.app_storage_blob_url,
                    container_name=self.application_context.configuration.app_cps_processes,
                    text=json.dumps(sidecar_payload),
                )
                return StepResult(
                    process_id=process_id,
                    step_name=self.handler_name,
                    result={
                        "result": "success",
                        "file_name": result_file.name,
                    },
                )

            # Get File then pass it to Content Understanding Service
            async with self.application_context.create_scope() as scope:
                content_understanding_helper = scope.get_service(
                    AzureContentUnderstandingHelper
                )
                response = content_understanding_helper.begin_analyze_stream(
                    analyzer_id="prebuilt-layout",
                    file_stream=context.data_pipeline.get_source_files()[
                        0
                    ].download_stream(
                        self.application_context.configuration.app_storage_blob_url,
                        self.application_context.configuration.app_cps_processes,
                    ),
                )

                response = content_understanding_helper.poll_result(response)
                result: AnalyzedResult = AnalyzedResult(**response)

            # Save Result as a file
            # Create File Entity to add
            result_file = context.data_pipeline.add_file(
                file_name="content_understanding_output.json",
                artifact_type=ArtifactType.ExtractedContent,
            )

            # log for file uploading
            result_file.log_entries.append(
                PipelineLogEntry(**{
                    "source": self.handler_name,
                    "message": "Content Understanding Extraction Result has been added",
                })
            )

            # Upload the result to blob storage
            result_file.upload_json_text(
                account_url=self.application_context.configuration.app_storage_blob_url,
                container_name=self.application_context.configuration.app_cps_processes,
                text=result.model_dump_json(),
            )

            return StepResult(
                process_id=context.data_pipeline.pipeline_status.process_id,
                step_name=self.handler_name,
                result={
                    "result": "success",
                    "file_name": result_file.name,
                },
            )

        # Fallback for unsupported content types
        return StepResult(
            process_id=context.data_pipeline.pipeline_status.process_id,
            step_name=self.handler_name,
            result={
                "result": "skipped",
                "reason": "Content type not supported for extraction.",
            },
        )

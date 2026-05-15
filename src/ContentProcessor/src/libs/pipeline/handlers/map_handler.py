"""Map handler — schema-driven data extraction via Azure Content Understanding.

A single Foundry-native code path covers PDFs and images. The handler
downloads the per-schema CU ``fieldSchema`` envelope from the Schema
Vault, ensures the corresponding CU custom analyzer exists, and POSTs
the source bytes to ``analyzeBinary``. CU returns extracted values and
per-field confidence in one call.
"""

import json
import logging

from azure.core.exceptions import ResourceNotFoundError

from libs.application.application_context import AppContext
from libs.azure_helper.cu_field_extractor import (
    analyze_with_field_analyzer,
    cu_response_to_extraction_from_names,
    ensure_field_analyzer_from_payload,
)
from libs.pipeline.entities.mime_types import MimeTypes
from libs.pipeline.entities.pipeline_file import ArtifactType, PipelineLogEntry
from libs.pipeline.entities.pipeline_message_context import MessageContext
from libs.pipeline.entities.pipeline_step_result import StepResult
from libs.pipeline.entities.schema import Schema
from libs.pipeline.queue_handler_base import HandlerBase

logger = logging.getLogger(__name__)


class MapHandler(HandlerBase):
    """Pipeline step that extracts schema-conforming data from a source file.

    Supported source types: PDF (``application/pdf``), JPEG, and PNG.
    All types are processed by an Azure Content Understanding custom
    analyzer derived from the registered Schema Vault envelope.
    """

    def __init__(self, appContext: AppContext, step_name: str, **data):
        super().__init__(appContext, step_name, **data)

    async def execute(self, context: MessageContext) -> StepResult:
        source_mime = context.data_pipeline.get_source_files()[0].mime_type
        if source_mime not in (
            MimeTypes.Pdf,
            MimeTypes.ImageJpeg,
            MimeTypes.ImagePng,
        ):
            raise ValueError(
                f"Unsupported source mime type for extraction: {source_mime!r}"
            )
        return await self._execute_via_cu(context)

    async def _execute_via_cu(self, context: MessageContext) -> StepResult:
        """Extract structured data using a CU custom analyzer.

        The schema is stored in the Schema Vault as a CU ``fieldSchema``
        JSON envelope. We download the envelope, ensure the corresponding
        per-schema analyzer exists in CU, then POST the source bytes to
        ``analyzeBinary``. CU returns extracted values and per-field
        confidence in one call. The output envelope mimics the legacy
        Azure-OpenAI response shape so ``EvaluateHandler`` and
        ``SaveHandler`` work unchanged; ``_cu_field_confidences`` carries
        CU's native scores for downstream evaluation.
        """
        from azure.storage.blob import BlobServiceClient

        from libs.utils.azure_credential_utils import get_azure_credential

        source_file = context.data_pipeline.get_source_files()[0]

        selected_schema = Schema.get_schema(
            connection_string=self.application_context.configuration.app_cosmos_connstr,
            database_name=self.application_context.configuration.app_cosmos_database,
            collection_name=self.application_context.configuration.app_cosmos_container_schema,
            schema_id=context.data_pipeline.pipeline_status.schema_id,
        )

        cu_endpoint = (
            self.application_context.configuration.app_content_understanding_endpoint
        )

        # Download the CU analyzer envelope (Schema Vault v2 — JSON-native).
        account_url = (
            self.application_context.configuration.app_storage_blob_url
        )
        container_path = (
            f"{self.application_context.configuration.app_cps_configuration}"
            f"/Schemas/{context.data_pipeline.pipeline_status.schema_id}"
        )
        blob_service = BlobServiceClient(
            account_url=account_url, credential=get_azure_credential()
        )
        envelope_bytes = (
            blob_service.get_blob_client(
                container=container_path, blob=selected_schema.FileName
            )
            .download_blob()
            .readall()
        )
        analyzer_payload = json.loads(envelope_bytes.decode("utf-8"))
        class_name = selected_schema.ClassName
        expected_field_names = list(
            ((analyzer_payload.get("fieldSchema") or {}).get("fields") or {}).keys()
        )

        # Stage B: prefer the API-supplied CU envelope sidecar
        # (``{process_id}/{filename}.cu.json``) over making another CU
        # call. The API persisted the raw linked-router envelope when it
        # classified the file, so the fields are already extracted —
        # walking the same envelope here gives identical
        # parsed_dict / cu_field_confidences to running CU again, at
        # zero extra cost. Best-effort: any failure falls through to the
        # legacy per-schema CU path.
        process_id = context.data_pipeline.pipeline_status.process_id
        processes_container = (
            self.application_context.configuration.app_cps_processes
        )
        sidecar_blob = f"{process_id}/{source_file.name}.cu.json"
        cu_payload: dict | None = None
        analyzer_id: str
        try:
            sidecar_bytes = (
                blob_service.get_blob_client(
                    container=processes_container, blob=sidecar_blob
                )
                .download_blob()
                .readall()
            )
            cu_payload = json.loads(sidecar_bytes.decode("utf-8"))
            analyzer_id = "<api-router-passthrough>"
            logger.info(
                "map_handler: using CU envelope sidecar for class=%s "
                "process=%s file=%s (skipped redundant CU call)",
                class_name,
                process_id,
                source_file.name,
            )
        except ResourceNotFoundError:
            cu_payload = None
            logger.debug(
                "map_handler: no CU envelope sidecar for %s/%s",
                process_id,
                source_file.name,
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            cu_payload = None
            logger.warning(
                "map_handler: corrupt CU envelope sidecar for %s/%s; "
                "falling back to per-schema CU call",
                process_id,
                source_file.name,
                exc_info=True,
            )
        except Exception:  # noqa: BLE001 - auth/network must surface
            cu_payload = None
            logger.warning(
                "map_handler: CU envelope sidecar download failed for "
                "%s/%s; falling back to per-schema CU call",
                process_id,
                source_file.name,
                exc_info=True,
            )

        if cu_payload is None:
            analyzer_id = ensure_field_analyzer_from_payload(
                cu_endpoint,
                class_name=class_name,
                analyzer_payload=analyzer_payload,
            )
            logger.info(
                "map_handler: CU extraction class=%s analyzer=%s mime=%s",
                class_name,
                analyzer_id,
                source_file.mime_type,
            )

            source_bytes = source_file.download_stream(
                self.application_context.configuration.app_storage_blob_url,
                self.application_context.configuration.app_cps_processes,
            )

            cu_payload = analyze_with_field_analyzer(
                cu_endpoint, analyzer_id, source_bytes
            )

        parsed_dict, cu_field_confidences = cu_response_to_extraction_from_names(
            cu_payload, expected_field_names=expected_field_names,
        )

        response_dict = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(parsed_dict),
                        "parsed": parsed_dict,
                    },
                    # CU does not emit logprobs — EvaluateHandler reads
                    # ``_cu_field_confidences`` for native CU scores.
                    "logprobs": None,
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "input_tokens": 0,
            },
            "_cu_field_confidences": cu_field_confidences,
            "_cu_analyzer_id": analyzer_id,
        }

        result_file = context.data_pipeline.add_file(
            file_name="gpt_output.json",
            artifact_type=ArtifactType.SchemaMappedData,
        )
        result_file.log_entries.append(
            PipelineLogEntry(**{
                "source": self.handler_name,
                "message": (
                    f"CU custom-analyzer extraction complete "
                    f"(analyzer={analyzer_id})."
                ),
            })
        )
        result_file.upload_json_text(
            account_url=self.application_context.configuration.app_storage_blob_url,
            container_name=self.application_context.configuration.app_cps_processes,
            text=json.dumps(response_dict),
        )

        return StepResult(
            process_id=context.data_pipeline.pipeline_status.process_id,
            step_name=self.handler_name,
            result={
                "result": "success",
                "file_name": result_file.name,
            },
        )

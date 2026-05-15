"""Domain models for per-document processing lifecycle.

Defines `ContentProcess` and `Step_Outputs` which track the execution state
of a single document through the pipeline and persist results to Cosmos DB.
"""

import datetime
import os
from typing import Any, Optional

from pydantic import BaseModel, SkipValidation

from libs.azure_helper.comsos_mongo import CosmosMongDBHelper
from libs.pipeline.entities.schema import Schema
from libs.pipeline.handlers.logics.evaluate_handler.comparison import (
    ExtractionComparisonData,
)


def _process_id_index():
    """Return the ``process_id`` index spec, optionally enforcing uniqueness.

    See the API-side counterpart in
    ``ContentProcessorAPI/app/routers/models/contentprocessor/content_process.py``
    for the full rationale. Defaults off so existing envs that may already
    contain duplicates aren't broken; flip ``APP_PROCESS_ID_INDEX_UNIQUE=true``
    on a fresh ``azd up`` to opt in.
    """
    flag = os.getenv("APP_PROCESS_ID_INDEX_UNIQUE", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return ("process_id", 1, True)
    return "process_id"


class Step_Outputs(BaseModel):
    """Output snapshot of a single pipeline step.

    Attributes:
        step_name: Identifier of the pipeline step (e.g. 'extract', 'map').
        processed_time: Formatted elapsed time for the step.
        step_result: Arbitrary result payload produced by the step.
    """

    step_name: str
    processed_time: Optional[str] = None
    step_result: SkipValidation[Any]

    class Config:
        arbitrary_types_allowed = True


class ContentProcess(BaseModel):
    """Aggregate record for a document flowing through the pipeline.

    Responsibilities:
        1. Hold extracted results, confidence scores, and schema metadata.
        2. Persist and update processing status in Cosmos DB.

    Attributes:
        process_id: Unique identifier for the processing run.
        processed_file_name: Name of the source file being processed.
        processed_file_mime_type: MIME type of the source file.
        status: Current processing status string.
        entity_score: Overall entity-level confidence score.
        schema_score: Proportion of fields above the confidence threshold.
        result: Extracted structured data dictionary.
        confidence: Confidence breakdown dictionary.
        target_schema: Schema definition used for extraction.
        prompt_tokens: Token count consumed by the LLM prompt.
        completion_tokens: Token count produced by the LLM completion.
        process_output: Per-step output snapshots.
        extracted_comparison_data: Side-by-side comparison of fields.
    """

    process_id: str
    processed_file_name: Optional[str] = None
    processed_file_mime_type: Optional[str] = None
    processed_time: Optional[str] = None
    imported_time: datetime.datetime = datetime.datetime.now(datetime.UTC)
    last_modified_time: datetime.datetime = datetime.datetime.now(datetime.UTC)
    last_modified_by: Optional[str] = None
    status: str
    entity_score: Optional[float] = 0.0
    min_extracted_entity_score: Optional[float] = 0.0
    schema_score: Optional[float] = 0.0
    result: Optional[dict] = None
    confidence: Optional[dict] = None
    target_schema: Optional[Schema] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    process_output: list[Step_Outputs] = []
    extracted_comparison_data: Optional[ExtractionComparisonData] = None

    comment: Optional[str] = None

    def update_process_status_to_cosmos(
        self,
        connection_string: str,
        database_name: str,
        collection_name: str,
    ):
        """Upsert lightweight status fields into Cosmos DB.

        Only updates mutable tracking fields (status, timestamps, file info)
        rather than the full document, to keep writes small.

        Args:
            connection_string: Cosmos DB connection string.
            database_name: Target database name.
            collection_name: Target collection name.
        """
        mongo_helper = CosmosMongDBHelper(
            connection_string=connection_string,
            db_name=database_name,
            container_name=collection_name,
            indexes=[_process_id_index()],
        )

        # Atomic upsert eliminates the find-then-write race where two
        # workers handling different files for the same process can race
        # the existence check and produce duplicate documents.
        tracked_fields = {
            "status": self.status,
            "processed_file_name": self.processed_file_name,
            "processed_file_mime_type": self.processed_file_mime_type,
            "last_modified_time": self.last_modified_time,
            "imported_time": self.imported_time,
            "last_modified_by": self.last_modified_by,
        }
        mongo_helper.upsert_document_by_query(
            query={"process_id": self.process_id},
            set_fields=tracked_fields,
            set_on_insert=self.model_dump(),
        )

    def update_status_to_cosmos(
        self, connection_string: str, database_name: str, collection_name: str
    ):
        """Upsert the full document model into Cosmos DB.

        Args:
            connection_string: Cosmos DB connection string.
            database_name: Target database name.
            collection_name: Target collection name.
        """
        mongo_helper = CosmosMongDBHelper(
            connection_string=connection_string,
            db_name=database_name,
            container_name=collection_name,
            indexes=[_process_id_index()],
        )

        # Atomic upsert: write the full document on both create and update
        # paths to keep semantics identical to the previous find-then-write
        # branch while removing the TOCTOU race.
        mongo_helper.upsert_document_by_query(
            query={"process_id": self.process_id},
            set_fields=self.model_dump(),
        )

    class Config:
        arbitrary_types_allowed = True

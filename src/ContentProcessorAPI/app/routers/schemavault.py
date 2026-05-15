"""FastAPI router for individual schema registration and management."""

import io
import os
import urllib.parse
import uuid

from fastapi import APIRouter, Body, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.libs.base.typed_fastapi import TypedFastAPI
from app.routers.logics.schemavault import Schemas
from app.routers.models.schmavault.model import (
    Schema,
    SchemaVaultRegisterJsonRequest,
    SchemaVaultUnregisterRequest,
    SchemaVaultUnregisterResponse,
)
from app.utils.upload_validation import sanitize_filename

router = APIRouter(
    prefix="/schemavault",
    tags=["schemavault"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "/",
    response_model=list[Schema],
    summary="List registered schemas",
    description="""
    Returns all schemas registered in the Schema Vault.

    ## Parameters
    None.

    ## Example Request Body
    Not applicable. This is a GET endpoint and does not accept a request body.

    Example request:
    `GET /schemavault/`
    """,
)
async def Get_All_Registered_Schema(
    request: Request = None,
) -> list[Schema]:
    """List all schemas registered in the vault."""
    app: TypedFastAPI = request.app  # type: ignore

    schemas: Schemas = app.app_context.get_service(Schemas)
    return schemas.GetAll()


@router.post(
    "/json",
    response_model=Schema,
    summary="Register a schema (Schema Vault v2 / JSON-native)",
    description="""
    Schema Vault **v2**: register a schema by posting an Azure Content
    Understanding ``fieldSchema`` JSON envelope directly. No Python
    source file is uploaded and no remote ``exec`` occurs at extraction
    time.

    The body is `application/json` (not `multipart/form-data`):

    ```json
    {
      "ClassName": "AutoInsuranceClaimForm",
      "Description": "Extract structured fields from an auto-claim form.",
      "FieldSchema": {
        "name": "AutoInsuranceClaimForm",
        "fields": {
          "ClaimNumber": { "type": "string", "method": "extract" },
          "Policyholder": {
            "type": "object",
            "properties": { "FullName": { "type": "string", "method": "extract" } }
          }
        }
      }
    }
    ```

    The blob is stored as `<schema_id>/<ClassName>.json` and Cosmos
    records `ContentType=application/json`. The workflow detects the
    JSON storage path via the file extension at extraction time.
    """,
)
async def Register_Schema_Json(
    data: SchemaVaultRegisterJsonRequest = Body(...),
    request: Request = None,
) -> Schema:
    """Register a CU ``fieldSchema`` JSON envelope (Schema Vault v2)."""
    app: TypedFastAPI = request.app  # type: ignore

    if not isinstance(data.FieldSchema, dict) or not data.FieldSchema.get("fields"):
        raise HTTPException(
            status_code=400,
            detail="FieldSchema must be a dict with a non-empty 'fields' object.",
        )

    schemas: Schemas = app.app_context.get_service(Schemas)

    schema_id = str(uuid.uuid4())
    safe_class = "".join(
        c if (c.isalnum() or c in "_-") else "_" for c in data.ClassName
    ).strip("_") or "schema"
    file_name = f"{safe_class}.json"

    analyzer_envelope = {
        "baseAnalyzerId": data.BaseAnalyzerId or "prebuilt-document",
        "description": data.Description
        or f"Auto-generated extractor for {data.ClassName}.",
        "config": {"returnDetails": True},
        "fieldSchema": data.FieldSchema,
        "models": {"completion": data.CompletionModel or "gpt-4.1-mini"},
    }

    return schemas.AddJson(
        Schema(
            Id=schema_id,
            ClassName=data.ClassName,
            Description=data.Description,
            FileName=file_name,
            ContentType="application/json",
        ),
        analyzer_envelope,
    )


@router.delete(
    "/",
    summary="Unregister a schema",
    description="""
    Removes a schema from the vault by schema ID.

    ## Parameters
    - **SchemaId** (body): Schema ID to delete.

    ## Example Request Body
    ```json
    {
      "SchemaId": "<schema_id>"
    }
    ```
    """,
)
async def Unregister_Schema(
    data: SchemaVaultUnregisterRequest,
    request: Request = None,
) -> SchemaVaultUnregisterResponse:
    """Unregister (delete) a schema by ID."""
    app: TypedFastAPI = request.app  # type: ignore

    schemas: Schemas = app.app_context.get_service(Schemas)
    try:
        deleted_schema = schemas.Delete(data.SchemaId)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return SchemaVaultUnregisterResponse(**{
        "Status": "Success",
        "SchemaId": deleted_schema.Id,
        "ClassName": deleted_schema.ClassName,
        "FileName": deleted_schema.FileName,
    })


@router.get(
    "/schemas/{schema_id}",
    summary="Download schema file",
    description="""
    Downloads the schema source file for a registered schema ID.

    ## Parameters
    - **schema_id** (path): Registered schema ID.

    ## Example Request Body
    Not applicable. This is a GET endpoint and does not accept a request body.

    Example request:
    `GET /schemavault/schemas/{schema_id}`
    """,
)
async def Get_Registered_Schema_File_By_Schema_Id(
    schema_id: str,
    response: Response,
    request: Request = None,
):
    """Download a registered schema file by schema ID."""
    app: TypedFastAPI = request.app  # type: ignore

    schemas: Schemas = app.app_context.get_service(Schemas)
    try:
        schemas = schemas.GetFile(schema_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    encoded_filename = urllib.parse.quote(schemas["FileName"])

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Content-Type": schemas["ContentType"],
    }

    file_stream = io.BytesIO(schemas["File"])

    return StreamingResponse(
        content=file_stream, media_type=schemas["ContentType"], headers=headers
    )

"""Schema-vault domain models: schemas, schema sets, and related request/response types."""

import datetime
import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Schema(BaseModel):
    """Registered schema record stored in Cosmos DB.

    Attributes:
        Id: Unique schema identifier.
        ClassName: Python class name of the schema.
        Description: Human-readable description.
        FileName: Source filename for the schema definition.
        ContentType: Expected content/MIME type.
        Created_On: UTC timestamp when the schema was registered.
        Updated_On: UTC timestamp of the last update.
    """

    Id: str
    ClassName: str
    Description: str
    FileName: str
    ContentType: str
    Created_On: Optional[datetime.datetime] = Field(default=None)
    Updated_On: Optional[datetime.datetime] = Field(default=None)
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def parse_dates(cls, values):
        if "Created_On" in values and isinstance(values["Created_On"], str):
            values["Created_On"] = datetime.datetime.fromisoformat(
                values["Created_On"].replace("Z", "+00:00")
            ).astimezone(datetime.timezone.utc)
        if "Updated_On" in values and isinstance(values["Updated_On"], str):
            values["Updated_On"] = datetime.datetime.fromisoformat(
                values["Updated_On"].replace("Z", "+00:00")
            ).astimezone(datetime.timezone.utc)
        return values


class SchemaMetadata(BaseModel):
    """Lightweight reference to a schema within a schema set.

    Attributes:
        Id: Unique metadata identifier.
        SchemaId: Referenced schema identifier.
        Description: Human-readable description.
    """

    Id: str
    SchemaId: str
    Description: str

    model_config = ConfigDict(from_attributes=True)


class SchemaSet(BaseModel):
    """Named collection of schema references.

    Attributes:
        Id: Unique schema-set identifier.
        Name: Display name.
        Description: Human-readable description.
        Created_On: UTC timestamp of creation.
        Updated_On: UTC timestamp of last update.
        Schemas: Schema references belonging to this set.
    """

    Id: str
    Name: str
    Description: str
    Created_On: Optional[datetime.datetime] = Field(default=None)
    Updated_On: Optional[datetime.datetime] = Field(default=None)

    Schemas: list[SchemaMetadata] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SchemaSetCreateRequest(BaseModel):
    """Request body for creating a new schema set.

    Attributes:
        Name: Display name of the new schema set.
        Description: Human-readable description.
    """

    Name: str
    Description: str


class SchemaSetAddSchemaRequest(BaseModel):
    """Request body for adding a schema to a schema set.

    Attributes:
        SchemaId: Identifier of the schema to add.
    """

    SchemaId: str


class SchemaVaultUnregisterResponse(BaseModel):
    """Response returned after unregistering a schema.

    Attributes:
        Status: Result status string.
        SchemaId: Identifier of the unregistered schema.
        ClassName: Python class name of the removed schema.
        FileName: Source filename of the removed schema.
    """

    Status: str
    SchemaId: str
    ClassName: str
    FileName: str

    def to_dict(self):
        return self.model_dump()


class SchemaVaultRegisterJsonRequest(BaseModel):
    """Request body for registering a Schema Vault v2 (JSON-native) schema.

    The ``FieldSchema`` is the Azure Content Understanding ``fieldSchema``
    object (``{"name": ..., "fields": {...}}``) that will be wrapped into
    the full custom-analyzer envelope at extraction time. Optional
    ``BaseAnalyzerId`` and ``CompletionModel`` override the defaults
    (``prebuilt-document`` / ``gpt-4.1-mini``).
    """

    ClassName: str
    Description: str
    FieldSchema: dict
    BaseAnalyzerId: Optional[str] = "prebuilt-document"
    CompletionModel: Optional[str] = "gpt-4.1-mini"


class SchemaVaultUnregisterRequest(BaseModel):
    """Request body for unregistering (deleting) a schema.

    Attributes:
        SchemaId: Identifier of the schema to remove.
    """

    SchemaId: str

    @model_validator(mode="before")
    @classmethod
    def validate_to_json(cls, value):
        if isinstance(value, str):
            return cls(**json.loads(value))
        return value

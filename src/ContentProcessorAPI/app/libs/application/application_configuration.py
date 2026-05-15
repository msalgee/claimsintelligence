"""Pydantic settings models for environment and Azure App Configuration.

Defines the two-stage configuration loading used at startup: EnvConfiguration
reads the App Configuration endpoint from environment variables, then
AppConfiguration is populated from the key-values stored in that service.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelBaseSettings(BaseSettings):
    """Base settings class that ignores unknown fields and is case-insensitive."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)


class EnvConfiguration(ModelBaseSettings):
    """Minimal settings read from process environment at startup.

    Attributes:
        app_config_endpoint: Azure App Configuration endpoint URL.
    """

    app_config_endpoint: str = Field(alias="APP_CONFIG_ENDPOINT")


class AppConfiguration(ModelBaseSettings):
    """Full application settings pulled from Azure App Configuration.

    Attributes:
        app_storage_blob_url: Azure Blob Storage account URL.
        app_storage_queue_url: Azure Queue Storage account URL.
        app_cosmos_connstr: Cosmos DB connection string.
        app_cosmos_database: Cosmos DB database name.
        app_cosmos_container_schema: Cosmos DB container for schemas.
        app_cosmos_container_schemaset: Cosmos DB container for schema sets.
        app_cosmos_container_process: Cosmos DB container for processes.
        app_cosmos_container_batches: Cosmos DB container for batches.
        app_cps_configuration: Content-processing pipeline configuration key.
        app_cps_processes: Content-processing pipeline processes key.
        app_cps_process_batch: Content-processing batch queue name.
        app_message_queue_extract: Extraction message-queue name.
        app_cps_max_filesize_mb: Maximum upload file size in megabytes.
        app_logging_level: Application log level.
        azure_package_logging_level: Log level for Azure SDK packages.
        azure_logging_packages: Comma-separated Azure package logger names.
    """

    app_storage_blob_url: str
    app_storage_queue_url: str
    app_cosmos_connstr: str
    app_cosmos_database: str
    app_cosmos_container_schema: str
    app_cosmos_container_schemaset: str
    app_cosmos_container_process: str
    app_cosmos_container_batches: str = "batches"
    app_cps_configuration: str
    app_cps_processes: str
    app_cps_process_batch: str = "process-batch"
    app_message_queue_extract: str
    app_cps_max_filesize_mb: int
    app_logging_level: str
    azure_package_logging_level: str
    azure_logging_packages: str
    applicationinsights_connection_string: str = ""
    # Azure AI Content Understanding endpoint, used by the auto-classify
    # path in the claimsdemo router. Optional so existing tests that don't
    # exercise CU continue to load.
    app_content_understanding_endpoint: str = ""
    # Microsoft Foundry Project endpoint + model deployment used by the
    # claimsdemo router for entity extraction, recommendation drafting and
    # outcome-letter generation. The endpoint is the Foundry project URL of
    # the form ``https://<account>.services.ai.azure.com/api/projects/<project>``.
    # Optional so existing tests load without Foundry configured.
    app_ai_project_endpoint: str = ""
    app_azure_openai_model: str = ""
    # Azure AI Search index used to ground the claims recommendation agent
    # in real policy documents (Phase D — Foundry IQ). Optional so the API
    # still starts when Search is not yet provisioned; in that case the
    # recommendation agent runs without retrieval and returns no policy
    # excerpts.
    app_ai_search_endpoint: str = ""
    app_ai_search_index_name: str = ""
    app_ai_search_connection_name: str = ""
    # Second AI Search index, scoped to member auto-policy contracts
    # (authoritative source of coverage / deductibles / endorsements).
    # The recommendation agent retrieves from this index by exact
    # ``policy_number`` filter, separately from the advisory
    # claims-handling guidance corpus. Optional so the API still loads
    # before the member-policies index has been seeded.
    app_member_policies_index_name: str = ""

"""Smoke tests for the claims-demo journey router.

These verify the route shape stays in sync with the
``src/ContentProcessorClaimsDemo`` frontend client. The router uses the real
claim-intake dependency path, so the tests provide in-memory services that
match the production app_context contract.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import types
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

try:
    from sas.cosmosdb.mongo.repository import RepositoryBase, SortField  # noqa: F401
    from sas.cosmosdb.mongo.model import EntityBase, RootEntityBase  # noqa: F401
except ModuleNotFoundError:
    sas_module = types.ModuleType("sas")
    cosmos_module = types.ModuleType("sas.cosmosdb")
    mongo_module = types.ModuleType("sas.cosmosdb.mongo")
    base_module = types.ModuleType("sas.cosmosdb.base")
    repository_module = types.ModuleType("sas.cosmosdb.mongo.repository")
    model_module = types.ModuleType("sas.cosmosdb.mongo.model")
    repository_base_module = types.ModuleType("sas.cosmosdb.base.repository_base")

    class RepositoryBase:
        def __init__(self, *args, **kwargs):
            pass

        def __class_getitem__(cls, item):
            return cls

    class SortField:
        def __init__(self, field_name: str, order: int = 1):
            self.field_name = field_name
            self.order = order

    class SortDirection:
        ASCENDING = 1
        DESCENDING = -1

    repository_module.RepositoryBase = RepositoryBase
    repository_module.SortField = SortField
    repository_base_module.SortDirection = SortDirection
    model_module.EntityBase = BaseModel
    model_module.RootEntityBase = BaseModel

    sys.modules.setdefault("sas", sas_module)
    sys.modules.setdefault("sas.cosmosdb", cosmos_module)
    sys.modules.setdefault("sas.cosmosdb.mongo", mongo_module)
    sys.modules.setdefault("sas.cosmosdb.base", base_module)
    sys.modules.setdefault("sas.cosmosdb.mongo.repository", repository_module)
    sys.modules.setdefault("sas.cosmosdb.mongo.model", model_module)
    sys.modules.setdefault("sas.cosmosdb.base.repository_base", repository_base_module)

from app.libs.azure import foundry_agents as foundry_agents_module
from app.routers import claimsdemo as claimsdemo_module
from app.routers.claimsdemo import router
from app.routers.logics.claimbatchprocessor import (
    ClaimBatchProcessor,
    ClaimBatchProcessRepository,
)
from app.routers.logics.schemavault import Schemas
from app.routers.logics.schemasetvault import SchemaSets
from app.routers.models.contentprocessor.claim import ClaimItem, ClaimProcess
from app.routers.models.contentprocessor.claim_process import Claim_Process, Claim_Steps
from app.routers.models.schmavault.model import Schema, SchemaSet


class _FakeBlobHelper:
    def __init__(self):
        self._blobs: dict[tuple[str, str], str | bytes] = {}

    def upload_blob(self, file_name: str, content: str | bytes, claim_id: str):
        self._blobs[(claim_id, file_name)] = content

    def download_blob(self, file_name: str, claim_id: str):
        value = self._blobs[(claim_id, file_name)]
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value


class _FakeBatchProcessor:
    def __init__(self):
        self.blobHelper = _FakeBlobHelper()

    def create_claim_container(self, schemaset_id: str) -> ClaimProcess:
        claim = ClaimProcess(claim_id=str(uuid.uuid4()), schema_collection_id=schemaset_id)
        self._save_manifest_to_blob(json.dumps(claim.model_dump(mode="json")), "manifest.json", claim.claim_id)
        return claim

    def get_claim_manifest(self, claim_id: str) -> ClaimProcess:
        return ClaimProcess(**json.loads(self.blobHelper.download_blob("manifest.json", claim_id)))

    def add_file_to_claim(self, claim_id: str, file_name: str, file_content: bytes):
        self.blobHelper.upload_blob(file_name, file_content, claim_id)

    def add_claim_item(self, claim_id: str, claim_item: ClaimItem):
        manifest = self.get_claim_manifest(claim_id)
        claim_item.id = claim_item.id or str(uuid.uuid4())
        manifest.items.append(claim_item)
        self._save_manifest_to_blob(json.dumps(manifest.model_dump(mode="json")), "manifest.json", claim_id)
        return manifest

    def replace_claim_items(self, claim_id: str, claim_items: list[ClaimItem]):
        manifest = self.get_claim_manifest(claim_id)
        manifest.items = claim_items
        self._save_manifest_to_blob(json.dumps(manifest.model_dump(mode="json")), "manifest.json", claim_id)
        return manifest

    def enqueue_claim_request_for_processing(self, claim_process_request):
        return None

    def _save_manifest_to_blob(self, content: str, file_name: str, claim_id: str):
        self.blobHelper.upload_blob(file_name, content, claim_id)


class _FakeClaimRepository:
    def __init__(self):
        self._items: dict[str, Claim_Process] = {}

    async def get_async(self, claim_id: str):
        return self._items.get(claim_id)

    async def delete_async(self, claim_id: str):
        self._items.pop(claim_id, None)

    async def add_async(self, claim_process: Claim_Process):
        claim_process.status = Claim_Steps.COMPLETED
        claim_process.process_summary = claimsdemo_module._FIXTURE["summary"]["markdown"]
        claim_process.process_gaps = json.dumps({
            "_rule_evaluation": [],
            "gaps": [],
            "discrepancies": [],
            "observations": [],
        })
        self._items[claim_process.id] = claim_process

    async def update_async(self, claim_process: Claim_Process):
        self._items[claim_process.id] = claim_process


class _FakeSchemaSets:
    def GetAll(self):
        return [SchemaSet(Id="auto-claim", Name="Auto Claim", Description="Auto claim", Schemas=[])]

    def GetAllSchemasInSet(self, schemaset_id: str):
        return [
            Schema(Id="schema-claim", ClassName="AutoInsuranceClaimForm", Description="", FileName="", ContentType="application/pdf"),
            Schema(Id="schema-police", ClassName="PoliceReportDocument", Description="", FileName="", ContentType="application/pdf"),
            Schema(Id="schema-estimate", ClassName="RepairEstimateDocument", Description="", FileName="", ContentType="application/pdf"),
            Schema(Id="schema-photo", ClassName="DamagedVehicleImageAssessment", Description="", FileName="", ContentType="image/png"),
        ]


class _FakeSchemas:
    pass


class _FakeAppContext:
    def __init__(self):
        self.configuration = SimpleNamespace(
            app_content_understanding_endpoint="https://cu.example.net",
            app_ai_project_endpoint="",
            app_azure_openai_model="",
            app_ai_search_connection_name="",
            app_ai_search_index_name="",
            app_ai_search_endpoint="",
            app_member_policies_index_name="",
        )
        self._services = {
            SchemaSets: _FakeSchemaSets(),
            Schemas: _FakeSchemas(),
            ClaimBatchProcessor: _FakeBatchProcessor(),
            ClaimBatchProcessRepository: _FakeClaimRepository(),
        }

    def get_service(self, service_type):
        return self._services[service_type]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "dev")

    def fake_build_auto_router(*args, **kwargs):
        return object(), {
            "auto_insurance_claim_form": "schema-claim",
            "police_report": "schema-police",
            "repair_estimate": "schema-estimate",
            "damage_photo": "schema-photo",
        }

    def fake_classify_bytes(
        file_bytes,
        file_name,
        mime_type,
        category_to_schema,
        default_schema_id,
        **kwargs,
    ):
        if "police" in file_name:
            category = "police_report"
        elif "repair" in file_name:
            category = "repair_estimate"
        elif "photo" in file_name:
            category = "damage_photo"
        else:
            category = "auto_insurance_claim_form"
        return (
            category,
            0.99,
            category_to_schema.get(category, default_schema_id),
            "test-fake",
            {"category": category, "confidence": 0.99},
        )

    monkeypatch.setattr(claimsdemo_module, "_build_auto_router", fake_build_auto_router)
    monkeypatch.setattr(claimsdemo_module, "_classify_bytes", fake_classify_bytes)

    def run_detached_task_for_test(coro):
        exception: list[BaseException] = []

        def runner():
            try:
                asyncio.run(coro)
            except BaseException as ex:  # noqa: BLE001
                exception.append(ex)

        thread = threading.Thread(target=runner)
        thread.start()
        thread.join()
        if exception:
            raise exception[0]

    monkeypatch.setattr(
        claimsdemo_module,
        "_schedule_claim_intake_task",
        run_detached_task_for_test,
    )

    app = FastAPI()
    app.app_context = _FakeAppContext()  # type: ignore[attr-defined]
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def claim_id(client: TestClient) -> str:
    response = client.post("/claimsdemo/claims/start")
    assert response.status_code == 202
    body = response.json()
    assert "claim_id" in body
    assert body["schema_set_id"] == "auto-claim"
    assert isinstance(body["files"], list) and body["files"]
    return body["claim_id"]


def test_start_claim_returns_persona_and_documents(client: TestClient) -> None:
    response = client.post("/claimsdemo/claims/start")
    assert response.status_code == 202
    body = response.json()
    assert body["claim_id"]
    assert body["schema_set_id"] == "auto-claim"
    assert body["files"]


def test_documents_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.get(f"/claimsdemo/claims/{claim_id}/documents")
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert isinstance(body["documents"], list) and body["documents"]


def test_classification_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.get(f"/claimsdemo/claims/{claim_id}/classification")
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert "classification" in body


def test_entities_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.get(f"/claimsdemo/claims/{claim_id}/entities")
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert body["generation_source"] == "fixture"


def test_entities_missing_foundry_config_fails_in_prod(
    client: TestClient, claim_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    response = client.get(f"/claimsdemo/claims/{claim_id}/entities")
    assert response.status_code == 503
    assert "agent is not configured" in response.json()["message"]


def test_fraud_check_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.get(f"/claimsdemo/claims/{claim_id}/fraud-check")
    assert response.status_code == 200
    assert response.json()["claim_id"] == claim_id


def test_business_checks_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.get(f"/claimsdemo/claims/{claim_id}/business-checks")
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert isinstance(body["checks"], list)


def test_business_checks_use_friendly_current_dsl_labels() -> None:
    parsed_gaps = {
        "_rule_evaluation": [
            {
                "rule_id": "REQ-CLAIM-FORM-000",
                "condition_triggered": True,
                "is_gap": False,
            },
            {
                "rule_id": "REQ-PR-THEFT-001",
                "condition_triggered": False,
                "is_gap": False,
            },
            {
                "rule_id": "OBS-UNKNOWN-INJURIES-001",
                "condition_triggered": False,
                "is_gap": False,
            },
        ],
        "gaps": [],
        "discrepancies": [
            {
                "check_id": "DISC-ESTIMATE-TOTAL-001",
                "field": "total_estimate",
                "severity": "low",
                "values_by_source": {
                    "claim_form": "$3,491.05",
                    "repair_estimate": "$3,813.97",
                },
            }
        ],
        "observations": [],
    }

    checks = claimsdemo_module.business_checks_payload(parsed_gaps)
    rules = [check["rule"] for check in checks]

    assert "Claim form is present" in rules
    assert "Police report is present for theft claim" in rules
    assert "Injury status undetermined" in rules
    assert "Repair estimate total is consistent" in rules
    assert not any(
        rule.startswith(("REQ-", "DISC-", "OBS-", "RD-", "DC-"))
        for rule in rules
    )
    assert not any(
        prefix in check["details"]
        for check in checks
        for prefix in ("REQ-", "DISC-", "OBS-", "RD-", "DC-")
    )


def test_get_summary_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.get(f"/claimsdemo/claims/{claim_id}/summary")
    assert response.status_code == 200
    assert response.json()["claim_id"] == claim_id


def test_put_summary_endpoint(client: TestClient, claim_id: str) -> None:
    payload = {"markdown": "Edited by adjuster"}
    response = client.put(f"/claimsdemo/claims/{claim_id}/summary", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert body["saved"] is True
    assert body["summary"] == payload


def test_recommendation_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.post(f"/claimsdemo/claims/{claim_id}/recommendation")
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert body["generation_source"] == "fixture"


def test_email_draft_endpoint(client: TestClient, claim_id: str) -> None:
    response = client.get(f"/claimsdemo/claims/{claim_id}/email-draft")
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert body["generation_source"] == "fixture"


def test_email_send_endpoint(client: TestClient, claim_id: str) -> None:
    payload = {"to": "jordan.reyes@example.com", "subject": "Claim update"}
    response = client.post(f"/claimsdemo/claims/{claim_id}/email-send", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert body["queued"] is True
    assert body["delivery_id"]


def test_policy_index_seed_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.app.app_context.configuration.app_ai_search_endpoint = (  # type: ignore[attr-defined]
        "https://search.example.net"
    )
    client.app.app_context.configuration.app_ai_search_index_name = (  # type: ignore[attr-defined]
        "claim-policies-idx"
    )

    captured = {}

    def fake_seed(endpoint, index_name, documents):
        captured["endpoint"] = endpoint
        captured["index_name"] = index_name
        captured["documents"] = documents
        return len(documents)

    monkeypatch.setattr(claimsdemo_module, "_seed_policy_index", fake_seed)
    response = client.post(
        "/claimsdemo/policy-index/seed",
        json={
            "index_name": "claim-policies-idx",
            "documents": [
                {
                    "source_filename": "coverage-limits.md",
                    "section": "coverage-limits",
                    "content": "Policy text",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "index_name": "claim-policies-idx",
        "documents_uploaded": 1,
    }
    assert captured["endpoint"] == "https://search.example.net"
    assert captured["index_name"] == "claim-policies-idx"
    assert captured["documents"][0].source_filename == "coverage-limits.md"


def test_member_policies_index_seed_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.app.app_context.configuration.app_ai_search_endpoint = (  # type: ignore[attr-defined]
        "https://search.example.net"
    )
    client.app.app_context.configuration.app_member_policies_index_name = (  # type: ignore[attr-defined]
        "member-policies-idx"
    )

    captured = {}

    def fake_seed(endpoint, index_name, documents):
        captured["endpoint"] = endpoint
        captured["index_name"] = index_name
        captured["documents"] = documents
        return len(documents)

    monkeypatch.setattr(claimsdemo_module, "_seed_member_policies_index", fake_seed)
    response = client.post(
        "/claimsdemo/member-policies-index/seed",
        json={
            "index_name": "member-policies-idx",
            "documents": [
                {
                    "policy_number": "SHI-AUTO-708216",
                    "source_filename": "SHI-AUTO-708216.md",
                    "content": "Policy text",
                    "form_version": "SHI-AUTO-CO-2025.09",
                    "carrier": "Summit Heritage Insurance",
                    "state": "CO",
                    "effective_date": "2025-09-15",
                    "expiration_date": "2026-09-14",
                    "status": "ACTIVE",
                    "named_insureds": ["Priya Ramaswamy"],
                    "excluded_drivers": [],
                    "vins": ["JTMRWRFV5RD082914"],
                    "endorsements": ["SHI-WTHR-01"],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "index_name": "member-policies-idx",
        "documents_uploaded": 1,
    }
    assert captured["endpoint"] == "https://search.example.net"
    assert captured["index_name"] == "member-policies-idx"
    assert captured["documents"][0].policy_number == "SHI-AUTO-708216"


def test_policy_number_extractor_supports_multiple_carriers() -> None:
    assert (
        foundry_agents_module._extract_policy_number("Policy NM-AUTO-554301")
        == "NM-AUTO-554301"
    )
    assert (
        foundry_agents_module._extract_policy_number("Policy SHI-AUTO-708216")
        == "SHI-AUTO-708216"
    )
    assert foundry_agents_module._extract_policy_number("Claim SHI-CLM-2026-05") is None


def test_recommendation_normalizer_keeps_member_policy_separate() -> None:
    payload = {
        "verdict": "Approve with conditions",
        "confidence": 0.82,
        "rationale": "The member policy is active and hail guidance applies.",
        "next_actions": ["Verify storm report"],
        "member_policy": {
            "policy_number": "SHI-AUTO-708216",
            "form_version": "SHI-AUTO-CO-2025.09",
            "status": "ACTIVE",
            "in_force_at_loss": True,
            "applicable_coverage": "Comprehensive (hail)",
            "applicable_deductible": 500,
            "applicable_endorsements": ["SHI-WTHR-01"],
            "policy_excerpts": [
                {
                    "section": "Comprehensive Coverage",
                    "text": "includes theft, vandalism, fire, flood, windstorm, hail",
                }
            ],
        },
        "guidance_excerpts": [
            {
                "section": "17A.2 Weather Loss Evidence",
                "source_filename": "weather-hail-comprehensive.md",
                "text": "collect evidence that connects the damage to the reported event",
            }
        ],
    }

    normalized = claimsdemo_module._normalize_recommendation_payload(payload)

    assert normalized["member_policy"]["policy_number"] == "SHI-AUTO-708216"
    assert normalized["member_policy"]["policy_excerpts"][0]["source"] == "member_policy"
    assert normalized["guidance_excerpts"][0]["source_filename"] == "weather-hail-comprehensive.md"
    assert {item["source"] for item in normalized["policy_excerpts"]} == {
        "member_policy",
        "guidance",
    }

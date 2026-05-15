"""Contract test: analyzer-id hashes must match across containers.

`AutoClaimLinkedRouter` (in the ContentProcessorAPI container) creates
per-schema CU analyzers and a linked router that points at them by id.
`MapHandler` (in the ContentProcessor / workflow container) re-derives
those same ids when it needs to call the per-schema analyzer directly.

If the two ``_analyzer_id_for_payload`` implementations ever drift,
the API will register one set of analyzer ids and the workflow will
ask CU for a different set -- silent 404 chain that surfaces only as
"my analyzer doesn't exist" at runtime. Audit HIGH 6 calls this out.

This test imports both copies by file path and asserts byte-equal
output for a representative set of payloads.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_module(file_path: Path, fake_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(fake_name, file_path)
    assert spec and spec.loader, f"could not build spec for {file_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[fake_name] = module
    spec.loader.exec_module(module)
    return module


def _repo_root() -> Path:
    # this file lives at:
    #   src/ContentProcessor/tests/unit/azure_helper/test_analyzer_id_contract.py
    return Path(__file__).resolve().parents[5]


def test_analyzer_id_hash_matches_across_containers():
    root = _repo_root()
    workflow_module = _load_module(
        root
        / "src"
        / "ContentProcessor"
        / "src"
        / "libs"
        / "azure_helper"
        / "cu_field_extractor.py",
        "cps_test_workflow_cu_field_extractor",
    )
    api_module = _load_module(
        root
        / "src"
        / "ContentProcessorAPI"
        / "app"
        / "libs"
        / "azure"
        / "content_understanding"
        / "auto_router.py",
        "cps_test_api_auto_router",
    )

    workflow_fn = workflow_module._analyzer_id_for_payload
    api_fn = api_module._analyzer_id_for_payload

    payloads = [
        (
            "AutoInsuranceClaimForm",
            {
                "baseAnalyzerId": "prebuilt-document",
                "fieldSchema": {
                    "fields": {
                        "claimNumber": {"type": "string"},
                        "policyNumber": {"type": "string"},
                    }
                },
            },
        ),
        (
            "PoliceReportDocument",
            {
                "baseAnalyzerId": "prebuilt-document",
                "fieldSchema": {
                    "fields": {
                        "reportNumber": {"type": "string"},
                        "officerName": {"type": "string"},
                    }
                },
            },
        ),
        ("EmptyClass", {}),
        # key ordering must not matter (json.dumps sort_keys=True on both sides)
        ("OrderingCheck", {"b": 2, "a": 1}),
        ("OrderingCheck", {"a": 1, "b": 2}),
    ]

    for class_name, payload in payloads:
        assert workflow_fn(class_name, payload) == api_fn(class_name, payload), (
            f"analyzer-id hash drift for {class_name!r}: "
            f"workflow={workflow_fn(class_name, payload)!r} "
            f"api={api_fn(class_name, payload)!r}"
        )

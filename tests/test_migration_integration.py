"""Migration boundaries: packaged schemas, independent roots, and admission order."""
from importlib.resources import files
from unittest.mock import Mock
from support.m1_samples import repository, runner
import shutil

import pytest
from jsonschema import ValidationError

from coding_agent.m0 import PolicyError, read_json, validate_admission, validate_schema


def test_schema_resources_and_test_root_are_independent(data_root, tmp_path, monkeypatch):
    test_root = tmp_path / "中文候选"
    shutil.copytree(data_root, test_root)
    assert not (test_root / "schemas").exists()
    schema_root = tmp_path / "独立契约"
    schema_root.mkdir()
    for resource in files("coding_agent").joinpath("schemas").iterdir():
        (schema_root / resource.name).write_bytes(resource.read_bytes())
    task = read_json(test_root / "fixtures/01_correct/atomic_task.json")
    source = read_json(test_root / "fixtures/source_requirements.json")
    records = read_json(test_root / "fixtures/trusted_review_records.json")
    monkeypatch.chdir(tmp_path)
    validate_admission(task, source, records, test_root, fixture_mode=True)
    validate_admission(task, source, records, test_root, schema_root=schema_root, fixture_mode=True)
    # Prove the explicit schema root is used, not silently ignored.
    (schema_root / "atomic_task.schema.json").write_text("false", encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_admission(task, source, records, test_root, schema_root=schema_root, fixture_mode=True)
    validate_schema("atomic_task", task)


@pytest.mark.parametrize("mutation,code", [
    ("PENDING", "ACCEPTANCE_NOT_APPROVED"),
    ("REJECTED", "ACCEPTANCE_NOT_APPROVED"),
    ("changed", "APPROVAL_CONTENT_MISMATCH"),
    ("unauthorized", "SCOPE_AUTHORIZATION_REQUIRED"),
])
def test_admission_failure_never_calls_executor_or_issues_report(data_root, mutation, code, tmp_path, evidence_root):
    task = read_json(data_root / "fixtures/01_correct/atomic_task.json")
    source = read_json(data_root / "fixtures/source_requirements.json")
    records = read_json(data_root / "fixtures/trusted_review_records.json")
    if mutation in ("PENDING", "REJECTED"):
        task["acceptance_review"]["status"] = mutation
    elif mutation == "changed":
        task["properties"][0]["statement"] += " changed"
    else:
        task["properties"][0]["scope_impact"] = "NEW_MODULE"
    executor = Mock()
    repo = repository(tmp_path / "candidate")
    audit = runner(data_root, evidence_root).run(task, repo, executor)
    assert code in audit["failure"]
    assert executor.call_count == 0
    assert audit["executor_calls"] == audit["candidate_process_starts"] == 0
    assert audit["checks"] == []
    assert audit["report"] is None
    assert [event["event"] for event in audit["events"]] == ["blocked"]

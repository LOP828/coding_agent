"""Contract regression tests; not a measurement of production reliability."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
from jsonschema import ValidationError

from coding_agent.m0 import (
    PolicyError, aggregate_gate, approval_payload_sha256, file_text_sha256,
    path_matches, read_json, scope_violations, text_sha256,
    validate_admission, validate_path, validate_report, validate_schema,
)

ROOT = Path(__file__).resolve().parent / "data" / "m0"
CASES = ["01_correct", "02_requirement_violation", "03_scope_violation", "04_wrong_acceptance"]


def fixture(case="01_correct"):
    return (
        read_json(ROOT / "fixtures" / case / "atomic_task.json"),
        read_json(ROOT / "fixtures/source_requirements.json"),
        read_json(ROOT / "fixtures/trusted_review_records.json"),
        read_json(ROOT / "fixtures" / case / "verification_report_expected.json"),
    )


def admit(task, source, records, root=ROOT):
    validate_admission(task, source, records, root, fixture_mode=True)


@pytest.mark.parametrize("case", CASES)
def test_fixture_admission_and_report(case):
    task, source, records, report = fixture(case)
    admit(task, source, records)
    actual = validate_report(task, report, expected_revision=report["revision"])
    assert actual["status"] == {CASES[0]: "PASS", CASES[1]: "HARD_FAIL", CASES[2]: "HARD_FAIL", CASES[3]: "PASS"}[case]


def test_case04_is_an_approved_false_pass_benchmark_not_pending():
    task, source, records, report = fixture(CASES[3])
    assert task["acceptance_review"]["status"] == "APPROVED"
    assert "defaults_to_local" in task["properties"][0]["checks"][0]["reference"]
    assert "test_missing_provider_raises" not in str(task["properties"][0]["checks"])
    admit(task, source, records)
    assert aggregate_gate(task, report["results"], report["changed_paths"])["status"] == "PASS"


@pytest.mark.parametrize("status", ["PENDING", "REJECTED"])
def test_not_approved_stops_before_execution(status):
    task, source, records, _ = fixture()
    task["acceptance_review"]["status"] = status
    executed = []
    with pytest.raises(PolicyError, match="ACCEPTANCE_NOT_APPROVED"):
        admit(task, source, records)
        executed.append("executor-called")
    assert executed == []


@pytest.mark.parametrize("part", ["statement", "allowed_paths", "protected_paths", "required_flag", "source_content"])
def test_approval_is_bound_to_content(part):
    task, source, records, _ = fixture()
    if part == "statement":
        task["properties"][0]["statement"] += " modified"
    elif part == "allowed_paths":
        task["allowed_change_paths"].append("extra.py")
    elif part == "protected_paths":
        task["protected_paths"].remove("project_config.py")
    elif part == "required_flag":
        task["properties"][0]["checks"][0]["required"] = False
    else:
        source["requirements"][0]["raw_text"] += " modified"
        source["requirements"][0]["sha256_utf8"] = text_sha256(source["requirements"][0]["raw_text"])
    with pytest.raises(PolicyError, match="APPROVAL_CONTENT_MISMATCH"):
        admit(task, source, records)


def test_self_rehash_cannot_replace_trusted_approval():
    task, source, records, _ = fixture()
    task["properties"][0]["statement"] += " modified"
    task["acceptance_review"]["approved_payload_sha256"] = approval_payload_sha256(task, source)
    with pytest.raises(PolicyError, match="UNTRUSTED_APPROVAL"):
        admit(task, source, records)


@pytest.mark.parametrize("mode", ["missing", "duplicate", "revoked"])
def test_approval_record_must_be_unambiguous_and_approved(mode):
    task, source, records, _ = fixture()
    if mode == "missing":
        records["review_records"] = []
    elif mode == "duplicate":
        records["review_records"].append(copy.deepcopy(records["review_records"][0]))
    else:
        records["review_records"][0]["status"] = "REJECTED"
    with pytest.raises(PolicyError, match="UNTRUSTED_APPROVAL"):
        admit(task, source, records)


def test_original_text_hash_mismatch():
    task, source, records, _ = fixture()
    source["requirements"][0]["raw_text"] += " modified"
    with pytest.raises(PolicyError, match="SOURCE_HASH_MISMATCH"):
        admit(task, source, records)


@pytest.mark.parametrize("status", ["DRAFT", "SUPERSEDED"])
def test_inactive_source_is_not_usable(status):
    task, source, records, _ = fixture()
    source["requirements"][0]["status"] = status
    with pytest.raises(PolicyError, match="SOURCE_NOT_FROZEN"):
        admit(task, source, records)


def test_pending_user_confirmation_is_not_usable():
    task, source, records, _ = fixture()
    source["requirements"][0].update(source_kind="USER_MESSAGE", confirmation="PENDING")
    with pytest.raises(PolicyError, match="SOURCE_NOT_CONFIRMED"):
        admit(task, source, records)


def test_synthetic_source_requires_explicit_fixture_mode():
    task, source, records, _ = fixture()
    with pytest.raises(PolicyError, match="SYNTHETIC_SOURCE_NOT_ALLOWED"):
        validate_admission(task, source, records, ROOT)


def test_unknown_source_id():
    task, source, records, _ = fixture()
    task["requirement_refs"].append("R-999")
    with pytest.raises(PolicyError, match="UNKNOWN_REQUIREMENT"):
        admit(task, source, records)


def test_structural_coverage_missing_requirement():
    task, source, records, _ = fixture()
    another = copy.deepcopy(source["requirements"][0]); another["id"] = "R-002"
    source["requirements"].append(another)
    task["requirement_refs"].append("R-002")
    with pytest.raises(PolicyError, match="UNCOVERED_TASK_REQUIREMENT"):
        admit(task, source, records)


def test_property_may_not_reference_source_outside_task():
    task, source, records, _ = fixture()
    task["properties"][0]["requirement_refs"].append("R-002")
    with pytest.raises(PolicyError, match="PROPERTY_SOURCE_OUTSIDE_TASK"):
        admit(task, source, records)


@pytest.mark.parametrize("what", ["requirement", "property"])
def test_duplicate_ids_rejected(what):
    task, source, records, _ = fixture()
    if what == "requirement":
        source["requirements"].append(copy.deepcopy(source["requirements"][0]))
    else:
        task["properties"].append(copy.deepcopy(task["properties"][0]))
    with pytest.raises(PolicyError, match="DUPLICATE_"):
        admit(task, source, records)


def test_unsourced_property_blocked():
    task, source, records, _ = fixture()
    task["properties"][0]["origin"] = "UNSOURCED"
    with pytest.raises(PolicyError, match="UNSOURCED_PROPERTY"):
        admit(task, source, records)


@pytest.mark.parametrize("impact", ["NEW_MODULE", "NEW_DEPENDENCY", "PUBLIC_INTERFACE_CHANGE", "OUTSIDE_SCOPE"])
def test_derived_expansion_requires_authorization(impact):
    task, source, records, _ = fixture()
    task["properties"][0].update(origin="DERIVED", derivation_reason="A convincing-sounding reason.", scope_impact=impact)
    with pytest.raises(PolicyError, match="SCOPE_AUTHORIZATION_REQUIRED"):
        admit(task, source, records)


def test_derived_reason_cannot_be_whitespace():
    task, source, records, _ = fixture()
    task["properties"][0].update(origin="DERIVED", derivation_reason="  ")
    with pytest.raises(PolicyError, match="DERIVED_REASON_REQUIRED"):
        admit(task, source, records)


def test_scope_authorization_cannot_be_self_asserted():
    task, source, records, _ = fixture()
    task["properties"][0].update(origin="DERIVED", derivation_reason="Reason", scope_impact="NEW_MODULE", scope_expansion_authorized=True, scope_authorization_ref="invented")
    with pytest.raises(PolicyError, match="UNTRUSTED_SCOPE_AUTHORIZATION"):
        admit(task, source, records)


def test_test_contents_are_bound_not_only_paths(tmp_path):
    task, source, records, _ = fixture()
    root = tmp_path / "package"
    shutil.copytree(ROOT, root)
    test = root / "tests_reference/test_provider_requirement.py"
    test.write_text(test.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="TEST_CONTENT_HASH_MISMATCH"):
        admit(task, source, records, root)


def test_text_manifest_is_crlf_stable(tmp_path):
    task, source, records, _ = fixture()
    root = tmp_path / "package"
    shutil.copytree(ROOT, root)
    test = root / "tests_reference/test_provider_requirement.py"
    before = file_text_sha256(test)
    raw = test.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    test.write_bytes(raw)
    assert file_text_sha256(test) == before
    admit(task, source, records, root)


def test_source_text_is_not_newline_normalized():
    assert text_sha256("a\r\nb") != text_sha256("a\nb")


def test_forged_report_gate_is_ignored_then_rejected():
    task, _, _, report = fixture(CASES[1])
    report["gate"].update(status="PASS", route="NONE")
    assert aggregate_gate(task, report["results"], report["changed_paths"])["status"] == "HARD_FAIL"
    with pytest.raises(PolicyError, match="REPORTED_GATE_MISMATCH"):
        validate_report(task, report, expected_revision=report["revision"])


@pytest.mark.parametrize("count", [None, 0, -1, "1", True])
def test_unit_pass_requires_positive_executed_test_count(count):
    _, _, _, report = fixture()
    if count is None:
        del report["results"][0]["test_count"]
    else:
        report["results"][0]["test_count"] = count
    with pytest.raises(ValidationError):
        validate_schema("verification_report", report)


@pytest.mark.parametrize("status", ["NOT_RUN", "UNVERIFIABLE"])
def test_required_incomplete_check_blocks(status):
    task, _, _, report = fixture()
    report["results"][0]["status"] = status
    assert aggregate_gate(task, report["results"], report["changed_paths"])["status"] == "BLOCKED"


def test_missing_required_check_blocks():
    task, _, _, report = fixture()
    del report["results"][0]
    assert aggregate_gate(task, report["results"], report["changed_paths"])["status"] == "BLOCKED"


@pytest.mark.parametrize("mode", ["unknown", "duplicate"])
def test_result_identity_must_match_task(mode):
    task, _, _, report = fixture()
    if mode == "unknown":
        report["results"][0]["reference"] += "_not_declared"
    else:
        report["results"].append(copy.deepcopy(report["results"][0]))
    with pytest.raises(PolicyError, match="UNDECLARED_CHECK_RESULT|DUPLICATE_CHECK_RESULT"):
        aggregate_gate(task, report["results"], report["changed_paths"])


def test_task_level_scope_has_no_property_id():
    task, _, _, report = fixture(CASES[2])
    assert all(c["method"] != "DIFF_ALLOWLIST" for p in task["properties"] for c in p["checks"])
    assert report["results"][-1]["property_id"] is None
    report["results"][-1]["status"] = "PASS"
    assert aggregate_gate(task, report["results"], report["changed_paths"])["status"] == "HARD_FAIL"


@pytest.mark.parametrize("field,value,code", [
    ("task_id", "other-task", "REPORT_TASK_MISMATCH"),
    ("revision", "other-revision", "REPORT_REVISION_MISMATCH"),
    ("approval_payload_sha256", "0" * 64, "REPORT_APPROVAL_MISMATCH"),
])
def test_report_binding(field, value, code):
    task, _, _, report = fixture()
    revision = report["revision"]
    report[field] = value
    with pytest.raises(PolicyError, match=code):
        validate_report(task, report, expected_revision=revision)


def test_protection_wins_overlap():
    task, _, _, _ = fixture()
    task["allowed_change_paths"] += ["tests_reference/**", "project_config.py"]
    assert scope_violations(task, ["project_config.py", "tests_reference/sub/test_a.py"]) == ["project_config.py", "tests_reference/sub/test_a.py"]


def test_portable_prefix_matching_is_explicit():
    assert path_matches("tests_reference/a.py", "tests_reference/**")
    assert path_matches("tests_reference/sub/a.py", "tests_reference/**")
    assert not path_matches("tests_reference_backup/a.py", "tests_reference/**")
    assert not path_matches("Config_Loader.py", "config_loader.py")


@pytest.mark.parametrize("value", ["/a.py", "../a.py", "a/../b.py", "C:/x.py", "a\\b.py", "a//b.py", "a/./b.py", "a/", "a\x00b.py", ""])
def test_noncanonical_paths_rejected(value):
    with pytest.raises(PolicyError, match="INVALID_PATH"):
        validate_path(value)


@pytest.mark.parametrize("value", ["**", "src/*.py", "src/**/x.py", "src/?.py", "src/[ab].py"])
def test_unsupported_globs_rejected(value):
    with pytest.raises(PolicyError, match="INVALID_PATH"):
        validate_path(value, pattern=True)


def test_report_required_flag_cannot_override_contract():
    task, _, _, report = fixture()
    report["results"][0]["required"] = False
    with pytest.raises(ValidationError):
        validate_schema("verification_report", report)


def test_all_mandatory_checks_cannot_be_made_optional():
    task, _, _, _ = fixture()
    for row in task["properties"][0]["checks"]:
        row["required"] = False
    with pytest.raises(ValidationError):
        validate_schema("atomic_task", task)

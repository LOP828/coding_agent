"""Run only the four known demonstrations; temporary directories are not sandboxes."""
import pytest

from coding_agent.m0 import read_json, validate_admission, validate_report
from support.sample_diagnostics import execute_candidate, write_json


@pytest.mark.parametrize("case,gate,failed", [
    ("01_correct", "PASS", 0),
    ("02_requirement_violation", "HARD_FAIL", 1),
    ("03_scope_violation", "HARD_FAIL", 0),
    ("04_wrong_acceptance", "PASS", 0),
])
def test_known_candidate_execution(data_root, evidence_root, case, gate, failed):
    task = read_json(data_root / "fixtures" / case / "atomic_task.json")
    source = read_json(data_root / "fixtures/source_requirements.json")
    trusted = read_json(data_root / "fixtures/trusted_review_records.json")
    report = read_json(data_root / "fixtures" / case / "verification_report_expected.json")
    validate_admission(task, source, trusted, data_root, fixture_mode=True)
    computed = validate_report(task, report, expected_revision=f"synthetic-{case[:2]}")
    assert computed == {"status": gate, "route": "NONE" if gate == "PASS" else "EXECUTION_FAIL"}
    references = [c["reference"] for p in task["properties"] for c in p["checks"]
                  if c["method"] == "UNIT_TEST"]
    result = execute_candidate(data_root, case, references, f"{case}_declared_tests", evidence_root)
    write_json(evidence_root / f"{case}_summary.json", {
        "case": case, "computed_gate": computed,
        "gate_evidence": "SYNTHETIC_REPORT_AND_SYNTHETIC_CHANGED_PATHS",
        "actual_candidate_execution": result,
    })
    assert (result["passed"], result["failed"], result["errors"], result["skipped"]) == (2-failed, failed, 0, 0)
    assert result["exit_code"] == (1 if failed else 0)


def test_case04_independent_oracle_preserves_known_false_pass(data_root, evidence_root):
    case = "04_wrong_acceptance"
    task = read_json(data_root / "fixtures" / case / "atomic_task.json")
    source = read_json(data_root / "fixtures/source_requirements.json")
    trusted = read_json(data_root / "fixtures/trusted_review_records.json")
    report = read_json(data_root / "fixtures" / case / "verification_report_expected.json")
    validate_admission(task, source, trusted, data_root, fixture_mode=True)
    computed = validate_report(task, report, expected_revision="synthetic-04")
    oracle_refs = [
        "tests_reference/test_provider_requirement.py::test_missing_provider_raises",
        "tests_reference/test_provider_requirement.py::test_present_provider_unchanged",
    ]
    assert not set(oracle_refs).intersection(c["reference"] for p in task["properties"] for c in p["checks"])
    result = execute_candidate(data_root, case, oracle_refs, "04_independent_source_oracle", evidence_root)
    write_json(evidence_root / "04_independent_source_oracle_summary.json", {
        "computed_gate": computed, "oracle": result,
        "evaluation_label": "FALSE_PASS_EXPECTED_KNOWN_GAP",
        "m2_semantic_detection": "NOT_IMPLEMENTED_NOT_CLAIMED",
    })
    assert computed == {"status": "PASS", "route": "NONE"}
    assert (result["passed"], result["failed"], result["errors"], result["skipped"], result["exit_code"]) == (1, 1, 0, 0, 1)

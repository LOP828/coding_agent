import pytest

from coding_agent.m0 import approval_payload_sha256, file_text_sha256, read_json
from coding_agent.verification import parse_junit
from support.m1_samples import executor, repository, runner


@pytest.mark.parametrize("xml,status,count", [
    (None, "UNVERIFIABLE", 0), ("<bad", "UNVERIFIABLE", 0),
    ("<testsuites/>", "UNVERIFIABLE", 0),
    ('<testsuite><testcase classname="tests.test_a" name="test_a"/></testsuite>', "PASS", 1),
    ('<testsuite><testcase classname="tests.test_a" name="test_a"><skipped/></testcase></testsuite>', "NOT_RUN", 0),
    ('<testsuite><testcase classname="tests.test_a" name="test_a"><failure/></testcase></testsuite>', "FAIL", 1),
    ('<testsuite><testcase classname="tests.test_a" name="test_a"><error/></testcase></testsuite>', "FAIL", 0),
    ('<testsuite><testcase classname="tests.test_a" name="test_a"><error message="failed on teardown with ValueError"/></testcase></testsuite>', "FAIL", 1),
    ('<testsuite><testcase classname="evil" name="fake"/></testsuite>', "UNVERIFIABLE", 0),
])
def test_junit_is_parsed_not_claimed(tmp_path, xml, status, count):
    path = tmp_path / "junit.xml"
    if xml is not None:
        path.write_text(xml, encoding="utf-8")
    result = parse_junit(path, "tests/test_a.py::test_a")
    assert (result["status"], result["test_count"]) == (status, count)


def test_required_skip_actually_blocks(tmp_path, data_root, evidence_root):
    # A controller-approved skip fixture for runner semantics, not a new business scenario.
    import shutil
    root = tmp_path / "frozen"
    shutil.copytree(data_root, root)
    path = root / "tests_reference/test_provider_requirement.py"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "def test_missing_provider_raises():", '@pytest.mark.skip(reason="M1 skip accounting")\ndef test_missing_provider_raises():'), encoding="utf-8")
    task = read_json(root / "fixtures/01_correct/atomic_task.json")
    task["acceptance_test_manifest"][0]["sha256_utf8_lf"] = file_text_sha256(path)
    controller = runner(root, evidence_root)
    digest = approval_payload_sha256(task, controller.source)
    task["acceptance_review"]["approved_payload_sha256"] = digest
    controller.records["review_records"][0]["approved_payload_sha256"] = digest
    audit = controller.run(task, repository(tmp_path / "repo"), executor(data_root, "01_correct"))
    assert audit["report"]["gate"]["status"] == "BLOCKED", audit
    assert audit["report"]["results"][0]["status"] == "NOT_RUN"
    assert audit["report"]["results"][0]["test_count"] == 0
    assert audit["checks"][0]["skipped"] == 1


def test_frozen_hash_checked_again_after_executor(tmp_path, data_root, evidence_root):
    import shutil
    frozen = tmp_path / "frozen"
    shutil.copytree(data_root, frozen)
    task = read_json(frozen / "fixtures/01_correct/atomic_task.json")
    def attack(repo):
        executor(data_root, "01_correct")(repo)
        (frozen / task["acceptance_test_manifest"][0]["path"]).write_text("assert True", encoding="utf-8")
    audit = runner(frozen, evidence_root).run(task, repository(tmp_path / "repo"), attack)
    assert "FROZEN_TEST_HASH_MISMATCH" in audit["failure"]
    assert audit["candidate_process_starts"] == 0
    assert audit["report"]["gate"]["status"] == "BLOCKED"


def test_actual_process_exit_without_junit_blocks(tmp_path, data_root, evidence_root):
    task = read_json(data_root / "fixtures/01_correct/atomic_task.json")
    def exit_early(repo):
        (repo / "config_loader.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    audit = runner(data_root, evidence_root).run(task, repository(tmp_path / "repo"), exit_early)
    assert audit["report"]["gate"]["status"] == "BLOCKED"
    assert audit["candidate_process_starts"] == 2
    assert all(check["status"] == "UNVERIFIABLE" and "INVALID_JUNIT" in check["reason"] for check in audit["checks"])

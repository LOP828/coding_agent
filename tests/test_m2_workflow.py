import json
from pathlib import Path

import pytest

from coding_agent.m0 import PolicyError
from coding_agent.m2_run import execute, prepare, run_attempts
from support.m1_samples import executor, repository
from support.m2_samples import ROOT, runner, task
from test_m2_executor import fake_setup


@pytest.mark.parametrize("second,expected", [("01_correct", "NONE"), ("02_requirement_violation", "EXECUTION_FAIL")])
def test_retry_once_retains_both_attempts_without_leaking_cases(tmp_path, data_root, evidence_root, second, expected):
    prompts = []
    def factory(number, prompt):
        prompts.append(prompt)
        return executor(data_root, "02_requirement_violation" if number == 1 else second)
    result = run_attempts(task(), runner(evidence_root),
                          lambda n: repository(tmp_path / f"attempt-{n}"), factory, tmp_path / "workflow")
    assert [a["result_category"] for a in result["attempts"]] == ["EXECUTION_FAIL", expected]
    assert [a["retry_decision"] for a in result["attempts"]] == ["RETRY_ONCE", "STOP"]
    assert result["attempts"][0]["audit"] != result["attempts"][1]["audit"]
    assert "上次失败反馈" in prompts[1]
    assert all(s not in prompts[1] for s in ("cases/provider.json", "openai", "observed", "expected", "fixture-m2"))
    stored = json.loads((tmp_path / "workflow/attempts.json").read_text(encoding="utf-8"))
    assert len(stored["attempts"]) == 2


@pytest.mark.parametrize("pending", [True, False])
def test_spec_failure_and_blocked_stop_without_retry(tmp_path, evidence_root, pending):
    card = task()
    if pending:
        card["acceptance_review"]["status"] = "PENDING"
    def candidate(repo):
        (repo / "config_loader.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    result = run_attempts(card, runner(evidence_root), lambda n: repository(tmp_path / str(n)),
                          lambda n, prompt: candidate, tmp_path / "workflow")
    assert len(result["attempts"]) == 1
    assert result["result_category"] == ("TASK_SPEC_FAIL" if pending else "BLOCKED")


def test_prepare_is_model_free_and_execution_requires_matching_approval(tmp_path):
    executor, ledger = fake_setup(tmp_path)
    path, digest = prepare(tmp_path / "runs", ROOT, executor.proof, tmp_path / "controller")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["executor_request"]["model"] == "gpt-6-luna"
    assert not Path(data["ledger"]).exists()
    with pytest.raises(PolicyError, match="PREPARED_REQUEST_NOT_APPROVED"):
        execute(path, "unapproved")
    Path(data["repository"], "config_loader.py").write_text("changed after preparation", encoding="utf-8")
    with pytest.raises(PolicyError, match="DIRTY_BASELINE"):
        execute(path, digest)


def test_default_evidence_is_outside_repository(tmp_path, data_root):
    repo = repository(tmp_path / "repo")
    audit = runner().run(task(), repo, executor(data_root, "01_correct"))
    assert audit["report"]["gate"]["status"] == "PASS"
    assert not Path(audit["evidence_directory"]).is_relative_to(repo)

import inspect

from coding_agent.m0 import read_json
from coding_agent.runner import Runner
from support.m1_samples import executor, repository, runner


def test_executor_interface_has_no_schema_root():
    assert "schema_root" not in inspect.signature(Runner.run).parameters
    assert "schema_root" not in inspect.signature(executor).parameters


def test_dirty_runner_has_zero_execution(tmp_path, data_root, evidence_root):
    repo = repository(tmp_path / "repo")
    (repo / "config_loader.py").write_text("dirty", encoding="utf-8")
    task = read_json(data_root / "fixtures/01_correct/atomic_task.json")
    audit = runner(data_root, evidence_root).run(task, repo, lambda root: (_ for _ in ()).throw(AssertionError("executed")))
    assert "DIRTY_BASELINE" in audit["failure"]
    assert audit["executor_calls"] == audit["candidate_process_starts"] == 0
    assert audit["report"] is None


def test_every_verification_uses_new_directory(tmp_path, data_root, evidence_root):
    task = read_json(data_root / "fixtures/01_correct/atomic_task.json")
    audits = [runner(data_root, evidence_root).run(task, repository(tmp_path / str(i)), executor(data_root, "01_correct")) for i in range(2)]
    assert all(audit["report"]["gate"]["status"] == "PASS" for audit in audits)
    assert audits[0]["verification_directory"] != audits[1]["verification_directory"]


def test_executor_error_retains_real_unauthorized_changes(tmp_path, data_root, evidence_root):
    task = read_json(data_root / "fixtures/03_scope_violation/atomic_task.json")
    def broken(repo):
        executor(data_root, "03_scope_violation")(repo)
        raise RuntimeError("simulated executor failure")
    audit = runner(data_root, evidence_root).run(task, repository(tmp_path / "repo"), broken)
    assert "EXECUTOR_FAILED" in audit["failure"]
    assert audit["report"]["changed_paths"] == ["config_loader.py", "project_config.py"]
    assert audit["report"]["gate"]["status"] == "HARD_FAIL"
    assert audit["candidate_process_starts"] == 0

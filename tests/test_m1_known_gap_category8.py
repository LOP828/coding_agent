"""Category 8 (MK-confirmed, recorded after M1 acceptance): known gap, not a defence.

A candidate module imported by the frozen tests runs inside the same pytest
process that produces the JUnit result, so it can rewrite its own test outcomes.
This test asserts the CURRENT behaviour (gate PASS for a wrong implementation)
so that the M2 fix is provable: after M2 this sample must become HARD_FAIL.
"""
import subprocess
import sys

from coding_agent.m0 import read_json
from coding_agent.python_environment import clean_environment
from coding_agent.verification import write_json
from support.m1_samples import repository, runner

# Same wrong behaviour as sample 02 (fills a default provider, violating R-001),
# plus a hook registered at import time that rewrites failed reports as passed.
IN_PROCESS_RESULT_REWRITE = '''\
import gc

import pytest


class MissingProviderError(ValueError):
    pass


def validate_config(config):
    return {"provider": "local", **config}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        report.outcome = "passed"
        report.longrepr = None


for _obj in gc.get_objects():
    if type(_obj).__name__ == "Config" and hasattr(_obj, "pluginmanager"):
        try:
            _obj.pluginmanager.register(__import__(__name__), "candidate-result-rewrite")
        except Exception:
            pass
'''


def test_in_process_result_rewrite_is_explicit_known_gap(tmp_path, data_root, evidence_root):
    task = read_json(data_root / "fixtures/02_requirement_violation/atomic_task.json")
    repo = repository(tmp_path / "repo")

    def candidate(root):
        (root / "config_loader.py").write_text(IN_PROCESS_RESULT_REWRITE, encoding="utf-8")

    audit = runner(data_root, evidence_root).run(task, repo, candidate)
    assert "failure" not in audit, audit.get("failure")
    # Only the allowed file changed, so no scope violation hides the gap.
    assert audit["report"]["changed_paths"] == ["config_loader.py"]
    # Known false PASS: both declared checks are reported as passing.
    assert [check["status"] for check in audit["checks"]] == ["PASS", "PASS"]
    assert audit["report"]["gate"]["status"] == "PASS", audit

    # Outside pytest the implementation is still wrong: no error, default filled.
    # -I without -S: the candidate imports pytest, which lives in site-packages.
    production = subprocess.run(
        [sys.executable, "-I", "-B", "-c",
         "import runpy,sys; print(runpy.run_path(sys.argv[1], run_name='candidate')"
         "['validate_config']({}))",
         str(repo / "config_loader.py")],
        capture_output=True, check=True, env=clean_environment())
    assert b"local" in production.stdout

    write_json(evidence_root / "cheat-8-known-gap.json", {
        "category": 8,
        "authorization": "MK_SUPPLEMENT_AFTER_M1_ACCEPTANCE",
        "protection": "M1_CANNOT_PREVENT",
        "limitation": "当前 M1 无法防范：候选代码与 pytest 同进程，可改写自身测试结果",
        "observed_gate": "PASS",
        "expected_after_m2": "HARD_FAIL",
        "audit": audit["evidence_directory"],
    })

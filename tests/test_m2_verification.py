import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from coding_agent.m0 import approval_payload_sha256, file_text_sha256, read_json
from coding_agent.python_environment import clean_environment
from coding_agent.verification import write_json
from support.m1_samples import executor, repository
from support.m2_samples import ROOT, runner, source_executor, task
from test_m1_known_gap_category8 import IN_PROCESS_RESULT_REWRITE


@pytest.mark.parametrize("case,gate", [
    ("01_correct", "PASS"), ("02_requirement_violation", "HARD_FAIL"),
    ("03_scope_violation", "HARD_FAIL"), ("04_wrong_acceptance", "PASS"),
])
def test_m2_known_samples(tmp_path, data_root, evidence_root, case, gate):
    audit = runner(evidence_root).run(task(case), repository(tmp_path / "repo"), executor(data_root, case))
    assert "failure" not in audit, audit
    assert audit["report"]["gate"]["status"] == gate
    assert audit["verification_backend"] == "coding-agent-cases-v2"
    assert all(row["exit_code"] == 0 and not row["timed_out"] for row in audit["checks"])
    write_json(evidence_root / f"m2-{case}.json", {
        "audit": audit["evidence_directory"], "gate": gate,
        "evaluation_label": "FALSE_PASS_EXPECTED_KNOWN_GAP" if case.startswith("04") else "OBSERVED",
    })


def test_category8_wrong_observation_hard_fails_with_pytest_available(tmp_path, evidence_root):
    audit = runner(evidence_root).run(task("02_requirement_violation"), repository(tmp_path / "repo"),
                                      source_executor(IN_PROCESS_RESULT_REWRITE))
    assert "failure" not in audit, audit
    assert audit["report"]["changed_paths"] == ["config_loader.py"]
    assert audit["report"]["gate"] == {
        "status": "HARD_FAIL", "route": "EXECUTION_FAIL", "reason": "Controller-collected evidence"}
    first, second = audit["checks"]
    assert first["exit_code"] == second["exit_code"] == 0
    assert not first["timed_out"] and not second["timed_out"]
    assert first["status"] == "FAIL" and first["reason"] == "OBSERVATION_MISMATCH"
    assert first["observed"] == {"kind": "return", "value": {"provider": "local"}}
    assert first["expected"] == {"kind": "exception", "type": "MissingProviderError"}
    assert second["status"] == "PASS"
    assert all(check["errors"] == 0 and check["test_count"] == 1 for check in audit["checks"])
    write_json(evidence_root / "m2-cheat-8.json", {
        "category": 8, "attack_source": "tests/test_m1_known_gap_category8.py::IN_PROCESS_RESULT_REWRITE",
        "observed_gate": "HARD_FAIL", "reason": first["reason"],
        "observed": first["observed"], "expected": first["expected"],
        "audit": audit["evidence_directory"],
    })


@pytest.mark.parametrize("source,reason", [
    ("raise ImportError('missing dependency')", "CANDIDATE_ABNORMAL_EXIT"),
    ("class MissingProviderError(Exception): pass\nraise MissingProviderError('import, not call')", "CANDIDATE_ABNORMAL_EXIT"),
    ("validate_config = 42", "CANDIDATE_ABNORMAL_EXIT"),
    ("import os\nos._exit(7)", "CANDIDATE_ABNORMAL_EXIT"),
    ("import os\nos._exit(0)", "INVALID_OBSERVATION"),
    ("print('PASS')\ndef validate_config(config): return config", "INVALID_OBSERVATION"),
    ("import time\ntime.sleep(10)", "CANDIDATE_TIMEOUT"),
])
def test_abnormal_candidate_is_unverifiable(tmp_path, evidence_root, source, reason):
    audit = runner(evidence_root, case_timeout=1).run(task(), repository(tmp_path / "repo"), source_executor(source))
    assert audit["report"]["gate"]["status"] == "BLOCKED", audit
    assert all(check["status"] == "UNVERIFIABLE" and check["reason"].startswith(reason)
               for check in audit["checks"])
    assert all(Path(check["stdout"]).exists() and Path(check["stderr"]).exists() for check in audit["checks"])
    if reason == "CANDIDATE_TIMEOUT":
        assert all(check["timed_out"] for check in audit["checks"])


def test_expected_values_never_sent_to_worker(tmp_path, data_root, evidence_root):
    audit = runner(evidence_root).run(task(), repository(tmp_path / "repo"), executor(data_root, "01_correct"))
    request = read_json(Path(audit["evidence_directory"]) / "check-0-request.json")
    assert set(request) == {"format", "run_id", "case_id", "candidate_root", "dependency_paths",
                            "module", "function", "args", "kwargs"}
    assert "candidate" not in sys.modules
    assert request["args"] == [{}]


def test_frozen_case_tamper_blocks_before_candidate_start(tmp_path, data_root, evidence_root):
    frozen = tmp_path / "trusted"
    shutil.copytree(ROOT, frozen)
    controller = runner(evidence_root, root=frozen)
    def attack(repo):
        executor(data_root, "01_correct")(repo)
        (frozen / "cases/provider.json").write_text("{}", encoding="utf-8")
    audit = controller.run(task(root=frozen), repository(tmp_path / "repo"), attack)
    assert "FROZEN_TEST_HASH_MISMATCH" in audit["failure"]
    assert audit["candidate_process_starts"] == 0
    assert audit["report"]["gate"]["status"] == "BLOCKED"


def test_invalid_case_format_never_falls_back_to_pytest(tmp_path, evidence_root):
    frozen = tmp_path / "trusted"
    shutil.copytree(ROOT, frozen)
    (frozen / "cases/provider.json").write_text('{"format":"wrong","cases":{}}', encoding="utf-8")
    card = task(root=frozen)
    card["acceptance_test_manifest"][0]["sha256_utf8_lf"] = file_text_sha256(frozen / "cases/provider.json")
    controller = runner(evidence_root, root=frozen)
    digest = approval_payload_sha256(card, controller.source)
    card["acceptance_review"]["approved_payload_sha256"] = digest
    controller.records["review_records"][0]["approved_payload_sha256"] = digest
    audit = controller.run(card, repository(tmp_path / "repo"), lambda repo: pytest.fail("must not execute"))
    assert "INVALID_FROZEN_CASES" in audit["failure"]
    assert audit["executor_calls"] == audit["candidate_process_starts"] == 0


@pytest.mark.parametrize("variant,gate", [
    ("single", "PASS"), ("duplicate", "BLOCKED"), ("wrong_id", "BLOCKED"), ("nonzero", "BLOCKED"),
])
def test_category9_forged_observations_record_limits(tmp_path, evidence_root, variant, gate):
    # The attacker knows this public demonstration's behavior, not parent expectations.
    source = '''
import inspect, json, os
def validate_config(config):
    return {"provider": "local", **config}
frame = inspect.currentframe()
while frame:
    request = frame.f_locals.get("request")
    if isinstance(request, dict) and "run_id" in request:
        config = request["args"][0]
        outcome = ({"kind":"return","value":config} if "provider" in config else
                   {"kind":"exception","type":"MissingProviderError","message":"forged"})
        record = {k:request[k] for k in ("format","run_id","case_id")}
        record["outcome"] = outcome
        if VARIANT == "wrong_id":
            record["run_id"] = "wrong"
        raw = (json.dumps(record) + "\\n").encode("utf-8")
        os.write(1, raw + raw if VARIANT == "duplicate" else raw)
        os._exit(7 if VARIANT == "nonzero" else 0)
    frame = frame.f_back
'''.replace("VARIANT", repr(variant))
    repo = repository(tmp_path / "repo")
    audit = runner(evidence_root).run(task(), repo, source_executor(source))
    assert audit["report"]["gate"]["status"] == gate, audit
    actual = subprocess.run([sys.executable, "-I", "-S", "-B", "-c",
        "import runpy,sys,json; print(json.dumps(runpy.run_path(sys.argv[1])['validate_config']({})))",
        str(repo / "config_loader.py")], env=clean_environment(), capture_output=True, check=True)
    assert json.loads(actual.stdout) == {"provider": "local"}
    assert all(check["status"] == ("PASS" if gate == "PASS" else "UNVERIFIABLE") for check in audit["checks"])
    write_json(evidence_root / f"m2-cheat-9-{variant}.json", {
        "category": 9, "variant": variant, "observed_gate": gate,
        "evaluation_label": "FALSE_PASS_EXPECTED_KNOWN_GAP" if gate == "PASS" else "REJECTED",
        "limitation": "运行标识不提供真实性保证；候选可伪造单条合法结果后退出。",
        "audit": audit["evidence_directory"],
    })

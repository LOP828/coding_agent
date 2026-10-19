import json
from pathlib import Path
import platform
import sys

import pytest

from coding_agent.codex_executor import CallLedger, CodexExecutor, configuration_identity, policy_template, prompt_for
from coding_agent.m0 import PolicyError
from coding_agent.verification import write_json
from support.m1_samples import repository
from support.m2_samples import runner, task


def fake_setup(tmp_path, *, model="gpt-6-luna", limit=10):
    proof = tmp_path / "synthetic-proof.json"
    write_json(proof, {"fixture_notice": "synthetic fixture, not actual sandbox evidence",
                      "policy_template": policy_template(), "platform": platform.system(),
                      "configuration_identity": configuration_identity(tmp_path / "repo"),
                      "usable_for_executor": True, "matrix_complete": True,
                      "codex_version": "codex-cli 0.163.0"})
    cli = tmp_path / "fake_cli.py"
    cli.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "if '--version' in sys.argv:\n    print('codex-cli 0.163.0'); sys.exit(0)\n"
        "prompt=sys.stdin.buffer.read().decode('utf-8')\n"
        "root=Path(sys.argv[sys.argv.index('-C')+1])\n"
        "root.joinpath('config_loader.py').write_text("
        + repr("class MissingProviderError(ValueError): pass\n"
               "def validate_config(config):\n"
               "    if 'provider' not in config: raise MissingProviderError('different message')\n"
               "    return config\n")
        + ",encoding='utf-8')\nprint(json.dumps({'type':'turn.completed'}))\n", encoding="utf-8")
    ledger = CallLedger(tmp_path / "ledger.json", limit=limit)
    executor = CodexExecutor(evidence=tmp_path / "evidence/executor", controller=tmp_path / "controller",
                             proof=proof, ledger=ledger, prompt=prompt_for(task()), model=model,
                             cli=(sys.executable, str(cli)))
    return executor, ledger


def test_fake_cli_flows_through_real_runner_without_model(tmp_path, evidence_root):
    executor, ledger = fake_setup(tmp_path)
    audit = runner(evidence_root).run(task(), repository(tmp_path / "repo"), executor)
    assert audit["report"]["gate"]["status"] == "PASS", audit
    request = json.loads((executor.evidence / "request.json").read_text(encoding="utf-8"))
    assert request["model"] == "gpt-6-luna" and request["reasoning"] == "medium"
    assert 'approval_policy="never"' in request["command"]
    assert 'default_permissions="m2_provider"' in request["command"]
    assert "--strict-config" not in request["command"]
    assert "--ignore-user-config" not in request["command"]
    assert not any("bypass" in arg or "danger-full-access" in arg for arg in request["command"])
    assert len(json.loads(ledger.path.read_text(encoding="utf-8"))["calls"]) == 1


def test_prompt_is_project_and_properties_only():
    card = task()
    card["acceptance_review"]["basis"] = "SECRET_APPROVAL"
    card["acceptance_test_manifest"][0]["path"] = "SECRET_CASES"
    for prop in card["properties"]:
        for check in prop["checks"]:
            check["reference"] = "SECRET_EXPECTED"
    text = prompt_for(card)
    assert "SECRET_" not in text
    assert "config_loader.py" in text and card["properties"][0]["statement"] in text


def test_astra_rejected_before_any_execution(tmp_path):
    with pytest.raises(PolicyError, match="INVALID_EXECUTOR_CONFIGURATION"):
        fake_setup(tmp_path, model="gpt-6-astra")


def test_unverified_sandbox_cannot_start_executor(tmp_path):
    executor, ledger = fake_setup(tmp_path)
    proof = json.loads(executor.proof.read_text(encoding="utf-8"))
    proof["usable_for_executor"] = False
    write_json(executor.proof, proof)
    with pytest.raises(PolicyError, match="SANDBOX_CONFIGURATION_NOT_VERIFIED"):
        executor(repository(tmp_path / "repo"))
    assert not ledger.path.exists()


def test_configuration_drift_invalidates_sandbox_proof(tmp_path):
    executor, ledger = fake_setup(tmp_path)
    repo = repository(tmp_path / "repo")
    (repo / ".codex").mkdir()
    (repo / ".codex/config.toml").write_text('model="gpt-6-luna"\n', encoding="utf-8")
    with pytest.raises(PolicyError, match="SANDBOX_CONFIGURATION_CHANGED"):
        executor(repo)
    assert not ledger.path.exists()


def test_budget_persisted_before_launch_and_never_exceeded(tmp_path):
    executor, ledger = fake_setup(tmp_path, limit=2)
    repo = repository(tmp_path / "repo")
    executor(repo)
    executor(repo)
    with pytest.raises(PolicyError, match="MODEL_CALL_BUDGET_EXHAUSTED"):
        executor(repo)
    data = json.loads(ledger.path.read_text(encoding="utf-8"))
    assert [c["number"] for c in data["calls"]] == [1, 2]
    with pytest.raises(PolicyError):
        CallLedger(tmp_path / "invalid.json", limit=11)

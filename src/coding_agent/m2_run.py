"""Prepare/review/execute one provider demonstration; never invoked by default pytest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from .codex_executor import CallLedger, CodexExecutor, MODELS, prompt_for
from .m0 import PolicyError, read_json
from .runner import Runner
from .verification import write_json
from .workspace import Workspace


def create_demo(path: Path, starter: Path) -> Path:
    path.mkdir(parents=True, exist_ok=False)
    for name in ("config_loader.py", "project_config.py"):
        shutil.copyfile(starter / name, path / name)
    (path / "protected").mkdir()
    (path / "protected/sentinel.txt").write_text("controller-created protected sentinel\n", encoding="utf-8")
    for args in (("init",), ("config", "user.name", "M2 Demo"),
                 ("config", "user.email", "m2-demo@example.invalid"), ("config", "core.autocrlf", "true"),
                 ("add", "."), ("commit", "-m", "disposable provider baseline")):
        subprocess.run(["git", "-c", "core.fsmonitor=false",
                        "-c", "core.hooksPath=" + (path / ".empty-hooks").as_posix(), *args],
                       cwd=path, capture_output=True, check=True, timeout=30)
    return path


def route_of(audit):
    if audit.get("report") is not None:
        return audit["report"]["gate"]["route"]
    return "BLOCKED" if any(e["event"] == "admitted" for e in audit["events"]) else "TASK_SPEC_FAIL"


def failed_requirements(task, audit):
    results = audit.get("report", {}).get("results", []) if audit.get("report") else []
    ids = {row["property_id"] for row in results if row["status"] != "PASS"}
    return [p["statement"] for p in task["properties"] if not results or p["id"] in ids]


def run_attempts(task, controller, repository_factory, executor_factory, evidence: Path):
    """Only the M0 route decides retries. Raw checks/expected values never enter feedback."""
    attempts = []
    feedback = None
    for number in (1, 2):
        repo = repository_factory(number)
        executor = executor_factory(number, prompt_for(task, feedback))
        audit = controller.run(task, repo, executor)
        route = route_of(audit)
        unmet = failed_requirements(task, audit)
        retry = route == "EXECUTION_FAIL" and number == 1
        summary = ("未满足任务 Property 或允许修改路径要求。" if route == "EXECUTION_FAIL"
                   else "本次验证通过。" if route == "NONE" else "任务准入或执行验证受阻，需 MK 决策。")
        attempt = {"attempt": number, "task_id": task["task_id"], "repository": repo.as_posix(),
                   "result_category": route, "failure_summary": summary, "unmet_requirements": unmet,
                   "retry_decision": "RETRY_ONCE" if retry else "STOP",
                   "audit": audit["evidence_directory"], "report": audit["report"],
                   "executor_result": getattr(executor, "last_result", None)}
        attempts.append(attempt)
        write_json(evidence / "attempts.json", {"attempts": attempts})
        if not retry:
            break
        feedback = "\n".join(unmet + [summary])  # no test references, inputs, expectations, or logs
    result = {"task_id": task["task_id"], "result_category": attempts[-1]["result_category"],
              "attempts": attempts, "evidence": evidence.as_posix(),
              "mk_decision": None if attempts[-1]["result_category"] == "NONE" else
              "请 MK 根据证据决定修订任务或后续处理；本次已停止，不自动重规划。",
              "cnc_task": "NOT_STARTED_PENDING_MK_PROPERTY_AND_PATHS"}
    write_json(evidence / "workflow.json", result)
    return result


def executor_for(prepared, number, prompt):
    evidence = Path(prepared["evidence"])
    return CodexExecutor(evidence=evidence / f"executor-{number}",
                         controller=Path(prepared["controller"]), proof=Path(prepared["proof"]),
                         ledger=CallLedger(Path(prepared["ledger"])), prompt=prompt,
                         model=prepared["model"], reasoning=prepared["reasoning"],
                         timeout=prepared["timeout_seconds"])


def prepare(run_root, fixture_root, proof, controller, *, model="gpt-6-luna", reasoning="medium", timeout=300):
    run_root, fixture_root, controller = run_root.resolve(), fixture_root.resolve(), controller.resolve()
    if run_root.is_relative_to(controller) or controller.is_relative_to(run_root):
        raise PolicyError("RUN_ROOT_MUST_BE_OUTSIDE_CONTROLLER")
    session = run_root / ("provider-" + uuid.uuid4().hex[:12])
    evidence = session / "evidence"
    evidence.mkdir(parents=True)
    repo = create_demo(session / "attempt-1", fixture_root / "demo_starter")
    card = read_json(fixture_root / "fixtures/01_correct/atomic_task.json")
    prepared = {"session": session.as_posix(), "repository": repo.as_posix(),
                "fixture_root": fixture_root.as_posix(), "controller": controller.as_posix(),
                "proof": proof.resolve().as_posix(), "evidence": evidence.as_posix(),
                "ledger": (run_root / "model-call-ledger.json").as_posix(),
                "model": model, "reasoning": reasoning, "timeout_seconds": timeout}
    with tempfile.TemporaryDirectory(prefix="m2-prepare-hooks-") as hooks:
        baseline = Workspace(repo, Path(hooks)).baseline()
    prepared["baseline"] = baseline
    prepared["task_sha256"] = hashlib.sha256(
        (fixture_root / "fixtures/01_correct/atomic_task.json").read_bytes()).hexdigest()
    prepared["executor_request"] = executor_for(prepared, 1, prompt_for(card)).preview(repo)
    path = evidence / "prepared-request.json"
    write_json(path, prepared)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def execute(prepared_path, approved_sha256):
    raw = prepared_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != approved_sha256:
        raise PolicyError("PREPARED_REQUEST_NOT_APPROVED_OR_CHANGED")
    prepared = json.loads(raw.decode("utf-8"))
    fixture_root = Path(prepared["fixture_root"])
    card_path = fixture_root / "fixtures/01_correct/atomic_task.json"
    if hashlib.sha256(card_path.read_bytes()).hexdigest() != prepared["task_sha256"]:
        raise PolicyError("TASK_CHANGED_AFTER_PREPARATION")
    card = read_json(card_path)
    repo = Path(prepared["repository"])
    with tempfile.TemporaryDirectory(prefix="m2-execute-hooks-") as hooks:
        baseline = Workspace(repo, Path(hooks)).baseline()
    if baseline != prepared["baseline"]:
        raise PolicyError("CANDIDATE_CHANGED_AFTER_PREPARATION")
    if executor_for(prepared, 1, prompt_for(card)).preview(repo) != prepared["executor_request"]:
        raise PolicyError("EXECUTOR_REQUEST_CHANGED_AFTER_PREPARATION")
    evidence = Path(prepared["evidence"])
    controller = Runner(fixture_root, read_json(fixture_root / "fixtures/source_requirements.json"),
                        read_json(fixture_root / "fixtures/trusted_review_records.json"),
                        evidence / "runner", fixture_mode=True)
    def repository_factory(number):
        return repo if number == 1 else create_demo(Path(prepared["session"]) / f"attempt-{number}",
                                                    fixture_root / "demo_starter")
    return run_attempts(card, controller, repository_factory,
                        lambda number, prompt: executor_for(prepared, number, prompt), evidence)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--run-root", type=Path, required=True)
    prep.add_argument("--fixture-root", type=Path, required=True)
    prep.add_argument("--sandbox-proof", type=Path, required=True)
    prep.add_argument("--controller-root", type=Path, default=Path.cwd())
    prep.add_argument("--model", choices=MODELS, default="gpt-6-luna")
    prep.add_argument("--reasoning", default="medium")
    prep.add_argument("--timeout", type=float, default=300)
    run = sub.add_parser("execute")
    run.add_argument("--prepared-request", type=Path, required=True)
    run.add_argument("--approved-sha256", required=True,
                     help="Only supply after MK has approved the displayed prompt and parameters")
    args = parser.parse_args()
    if args.action == "prepare":
        path, digest = prepare(args.run_root, args.fixture_root, args.sandbox_proof, args.controller_root,
                               model=args.model, reasoning=args.reasoning, timeout=args.timeout)
        print(json.dumps({"prepared_request": path.as_posix(), "approval_sha256": digest,
                          "model_calls": 0, "status": "AWAITING_MK_APPROVAL"}, ensure_ascii=False, indent=2))
    else:
        result = execute(args.prepared_request, args.approved_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

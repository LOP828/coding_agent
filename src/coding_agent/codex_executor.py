"""Sandbox-only Codex CLI adapter. Preparing a request never invokes a model."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

from .m0 import PolicyError
from .python_environment import clean_environment
from .verification import run_captured, write_json

PROFILE = "m2_provider"
MODELS = ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol")


def configuration_identity(repository: Path):
    """Bind ambient configuration without retaining configuration secrets."""
    codex_root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    paths = {codex_root / "config.toml", Path("/etc/codex/config.toml"),
             Path("/etc/codex/requirements.toml")}
    for ancestor in (repository.resolve(), *repository.resolve().parents):
        paths.add(ancestor / ".codex/config.toml")
    hashes = {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(paths) if path.is_file()}
    environment = {key: value for key, value in clean_environment().items()
                   if key in ("CODEX_HOME", "XDG_CONFIG_HOME") or
                   key.startswith(("CODEX_CONFIG", "CODEX_MANAGED", "CODEX_SANDBOX",
                                   "CODEX_LINUX", "CODEX_FEATURE"))}
    return {"loading": "ambient_with_explicit_overrides",
            "files_sha256": hashes,
            "configuration_environment_sha256": hashlib.sha256(
                json.dumps(environment, sort_keys=True).encode("utf-8")).hexdigest()}


def policy_template():
    return {"profile": PROFILE, "filesystem": {
        ":root": "read", "$REPOSITORY": "write",
        "$REPOSITORY/project_config.py": "read", "$REPOSITORY/protected": "read",
        "$CONTROLLER": "none", "$EVIDENCE": "none",
    }, "network": False}


def sandbox_overrides(repository: Path, controller: Path, evidence: Path) -> list[str]:
    substitutions = {"$REPOSITORY": repository.resolve().as_posix(),
                     "$CONTROLLER": controller.resolve().as_posix(),
                     "$EVIDENCE": evidence.resolve().as_posix()}
    filesystem = {}
    for key, access in policy_template()["filesystem"].items():
        for placeholder, path in substitutions.items():
            key = key.replace(placeholder, path)
        filesystem[key] = access
    table = "{" + ",".join(json.dumps(k, ensure_ascii=False) + "=" + json.dumps(v)
                           for k, v in filesystem.items()) + "}"
    values = [f'default_permissions="{PROFILE}"',
              f"permissions.{PROFILE}.filesystem={table}",
              f"permissions.{PROFILE}.network.enabled=false",
              'approval_policy="never"']
    return [argument for value in values for argument in ("-c", value)]


def prompt_for(task: dict, feedback: str | None = None) -> str:
    # Deliberate allowlist: no checks, fixtures, approvals, expected values or paths to them.
    text = ("在当前一次性 Python 演示仓库中实现以下任务。\n"
            "项目接口：config_loader.py 提供 MissingProviderError 和 validate_config(config)。"
            "config 为 JSON 对象；已有 provider 的配置保持原值。只使用现有依赖。\n"
            "要求：\n" + "\n".join(f"- {p['statement']}" for p in task["properties"]) +
            "\n允许修改的路径：\n" + "\n".join(f"- {p}" for p in task["allowed_change_paths"]) +
            "\n仅修改允许的文件；不要修改 Git 元数据，不要提交或访问其他项目。"
            "完成后简要说明实际改动。\n")
    if feedback:
        text += "\n上次失败反馈：\n" + feedback + "\n"
    return text


class CallLedger:
    """Count AI-backed CLI invocations, including failed starts/retries, at most ten.

    Pure version/help/sandbox commands do not invoke a model and are not charged.
    This is not a token budget or a count of internal inference turns in one CLI.
    """
    def __init__(self, path: Path, limit=10):
        if not 1 <= limit <= 10:
            raise PolicyError("MODEL_CALL_LIMIT_MUST_BE_1_TO_10")
        self.path = path
        self.limit = limit

    def reserve(self, request: dict):
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "counting_unit": "AI_BACKED_CODEX_EXEC_INVOCATION", "calls": []}
        if len(data["calls"]) >= self.limit:
            raise PolicyError("MODEL_CALL_BUDGET_EXHAUSTED")
        number = len(data["calls"]) + 1
        data["calls"].append({"number": number, "request": request, "state": "RESERVED"})
        write_json(self.path, data)  # persist before launch; crash never silently refunds a call
        return number

    def finish(self, number, result):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["calls"][number - 1].update(state="FINISHED", result=result)
        write_json(self.path, data)


class CodexExecutor:
    def __init__(self, *, evidence: Path, controller: Path, proof: Path, ledger: CallLedger,
                 prompt: str, model="gpt-6-luna", reasoning="medium", timeout=300,
                 cli=("codex", "--no-daemon")):
        if model not in MODELS or reasoning not in ("low", "medium", "high", "xhigh", "max") or timeout <= 0:
            raise PolicyError("INVALID_EXECUTOR_CONFIGURATION")
        if any("bypass" in arg or "danger-full-access" in arg for arg in cli):
            raise PolicyError("UNSANDBOXED_EXECUTOR_FORBIDDEN")
        self.evidence, self.controller, self.proof = evidence.resolve(), controller.resolve(), proof
        self.ledger, self.prompt = ledger, prompt
        self.model, self.reasoning, self.timeout, self.cli = model, reasoning, timeout, tuple(cli)
        self.last_result = None

    def preview(self, repository: Path):
        repository = repository.resolve()
        if repository.is_relative_to(self.controller) or self.controller.is_relative_to(repository):
            raise PolicyError("DEMO_MUST_BE_OUTSIDE_CONTROLLER")
        if self.evidence.is_relative_to(repository):
            raise PolicyError("EXECUTOR_EVIDENCE_INSIDE_CANDIDATE")
        proof = json.loads(self.proof.read_text(encoding="utf-8"))
        if (proof.get("policy_template") != policy_template() or proof.get("platform") != platform.system()
                or not proof.get("usable_for_executor") or not proof.get("matrix_complete")):
            raise PolicyError("SANDBOX_CONFIGURATION_NOT_VERIFIED")
        identity = configuration_identity(repository)
        if proof.get("configuration_identity") != identity:
            raise PolicyError("SANDBOX_CONFIGURATION_CHANGED")
        command = [*self.cli, "exec", "--ephemeral",
                   "-C", str(repository), "-m", self.model,
                   "-c", f'model_reasoning_effort="{self.reasoning}"',
                   *sandbox_overrides(repository, self.controller, self.evidence.parent),
                   "--json", "--color", "never", "-"]
        return {"command": command, "cwd": repository.as_posix(), "prompt": self.prompt,
                "model": self.model, "reasoning": self.reasoning, "timeout_seconds": self.timeout,
                "policy_template": policy_template(), "proof": self.proof.resolve().as_posix(),
                "configuration_identity": identity,
                "proof_sha256": hashlib.sha256(self.proof.read_bytes()).hexdigest(),
                "tested_codex_version": proof["codex_version"]}

    def __call__(self, repository: Path):
        request = self.preview(repository)
        version = subprocess.run([*self.cli, "--version"], capture_output=True, check=True,
                                 timeout=30).stdout.decode("utf-8").strip()
        if version != request["tested_codex_version"]:
            raise PolicyError("CODEX_VERSION_DIFFERS_FROM_SANDBOX_PROBE")
        write_json(self.evidence / "request.json", request)
        number = self.ledger.reserve(request)
        try:
            result = run_captured(request["command"], cwd=repository, env=clean_environment(),
                                  evidence=self.evidence, prefix="executor", timeout=self.timeout,
                                  stdin=self.prompt.encode("utf-8"))
        except Exception as error:
            result = {"launch_error": type(error).__name__}
            self.ledger.finish(number, result)
            raise
        self.last_result = {**result, "version": version, "call_number": number}
        self.ledger.finish(number, self.last_result)
        write_json(self.evidence / "execution.json", self.last_result)
        if result["timed_out"] or result["exit_code"] != 0:
            raise PolicyError("CODEX_TIMEOUT" if result["timed_out"] else "CODEX_NONZERO_EXIT")

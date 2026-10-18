"""Prewritten Executor simulations and disposable Git repositories, no AI."""
from pathlib import Path
import shutil
import subprocess

from coding_agent.m0 import read_json
from coding_agent.runner import Runner


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + (root / ".empty-hooks").as_posix(),
                           *args], cwd=root, check=True, capture_output=True).stdout


def repository(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init")
    git(path, "config", "user.name", "M1 Test")
    git(path, "config", "user.email", "m1@example.invalid")
    git(path, "config", "core.autocrlf", "true")
    (path / ".gitignore").write_text(".venv/\n.coding-agent-evidence/\n", encoding="utf-8")
    (path / "config_loader.py").write_text("# starting implementation\n", encoding="utf-8")
    (path / "project_config.py").write_text("DEFAULT_TIMEOUT = 30\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "clean baseline")
    return path


def executor(data_root: Path, case: str):
    def apply(root: Path):
        for file in (data_root / "example_code" / case).glob("*.py"):
            shutil.copyfile(file, root / file.name)
    return apply


def runner(data_root: Path, evidence_root: Path, **kwargs) -> Runner:
    return Runner(data_root, read_json(data_root / "fixtures/source_requirements.json"),
                  read_json(data_root / "fixtures/trusted_review_records.json"), evidence_root,
                  fixture_mode=True, **kwargs)

import pytest

from coding_agent.m0 import PolicyError
from coding_agent.workspace import Workspace
from support.m1_samples import git, repository


@pytest.mark.parametrize("change", ["modify", "add", "delete", "rename", "ignored_add", "ignored_modify", "ignored_delete", "hide_new", "staged"])
def test_real_changes_including_ignored(tmp_path, change):
    root = repository(tmp_path / "中文仓库")
    hidden = root / ".venv" / "existing.py"
    hidden.parent.mkdir()
    hidden.write_text("old\n", encoding="utf-8")
    workspace = Workspace(root, tmp_path / "hooks")
    baseline = workspace.baseline()
    target = root / "config_loader.py"
    expected = ["config_loader.py"]
    if change in ("modify", "staged"):
        target.write_text("changed\n", encoding="utf-8")
        if change == "staged":
            git(root, "add", "config_loader.py")
    elif change == "add":
        (root / "新增.py").write_text("new", encoding="utf-8")
        expected = ["新增.py"]
    elif change == "delete":
        target.unlink()
    elif change == "rename":
        target.rename(root / "renamed.py")
        expected += ["renamed.py"]
    elif change == "ignored_add":
        (hidden.parent / "new.py").write_text("new", encoding="utf-8")
        expected = [".venv/new.py"]
    elif change == "ignored_modify":
        hidden.write_text("new", encoding="utf-8")
        expected = [".venv/existing.py"]
    elif change == "ignored_delete":
        hidden.unlink()
        expected = [".venv/existing.py"]
    else:
        (root / ".gitignore").write_text("secret.py\n", encoding="utf-8")
        (root / "secret.py").write_text("hidden", encoding="utf-8")
        expected = [".gitignore", "secret.py"]
    result = workspace.collect(baseline)
    assert result["changed_paths"] == sorted(expected)
    if change.startswith("ignored"):
        assert ".venv" not in result["status_porcelain_z"]


@pytest.mark.parametrize("real_content", [False, True])
def test_autocrlf_only_newlines_vs_real_content(tmp_path, real_content):
    root = repository(tmp_path / "repo")
    workspace = Workspace(root, tmp_path / "hooks")
    baseline = workspace.baseline()
    path = root / "project_config.py"
    path.write_bytes(b"DEFAULT_TIMEOUT = " + (b"999" if real_content else b"30") + b"\r\n")
    assert workspace.collect(baseline)["changed_paths"] == (["project_config.py"] if real_content else [])
    assert git(root, "config", "core.autocrlf").strip() == b"true"


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_start_rejected(tmp_path, staged):
    root = repository(tmp_path / "repo")
    (root / "new.py").write_text("new", encoding="utf-8")
    if staged:
        git(root, "add", ".")
    with pytest.raises(PolicyError, match="DIRTY_BASELINE"):
        Workspace(root, tmp_path / "hooks").baseline()


def test_only_registered_evidence_directory_excluded(tmp_path):
    root = repository(tmp_path / "repo")
    workspace = Workspace(root, tmp_path / "hooks")
    baseline = workspace.baseline()
    directory = root / ".coding-agent-evidence"
    directory.mkdir()
    (directory / "audit.json").write_text("{}", encoding="utf-8")
    assert workspace.collect(baseline)["changed_paths"] == []
    assert baseline["excluded_evidence_directories"] == [".coding-agent-evidence"]


def test_staged_unauthorized_content_not_hidden_by_restoring_worktree(tmp_path):
    root = repository(tmp_path / "repo")
    workspace = Workspace(root, tmp_path / "hooks")
    baseline = workspace.baseline()
    path = root / "project_config.py"
    original = path.read_bytes()
    path.write_text("DEFAULT_TIMEOUT = 999\n", encoding="utf-8")
    git(root, "add", "project_config.py")
    path.write_bytes(original)
    result = workspace.collect(baseline)
    assert result["changed_paths"] == ["project_config.py"]
    assert result["staged_paths"] == ["project_config.py"]

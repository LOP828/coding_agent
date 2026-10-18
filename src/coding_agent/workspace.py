"""Controller-owned Git observations and ignore-independent filesystem evidence."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess

from .m0 import PolicyError

EVIDENCE_DIRECTORY = ".coding-agent-evidence"


def snapshot(root: Path, *, exclude: tuple[str, ...] = (), normalize: bool = False) -> dict:
    """Never follow directory links or consult ignore rules. Fail on unreadable files."""
    result = {}

    def visit(path: Path, relative: str) -> None:
        if relative in exclude:
            return
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            result[relative] = ["link", os.readlink(path)]
        elif stat.S_ISDIR(mode):
            result[relative] = ["directory"]
            for child in sorted(path.iterdir()):
                visit(child, child.relative_to(root).as_posix())
        elif stat.S_ISREG(mode):
            raw = path.read_bytes()
            if normalize and b"\0" not in raw:
                try:
                    raw = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                except UnicodeDecodeError:
                    pass
            result[relative] = ["file", hashlib.sha256(raw).hexdigest(), bool(mode & stat.S_IXUSR)]
        else:
            raise PolicyError(f"UNSUPPORTED_FILE_TYPE: {relative}")

    if root.exists() or root.is_symlink():
        visit(root, ".")
    return result


def differences(before: dict, after: dict, *, files_only: bool = False) -> list[str]:
    return sorted(path for path in before.keys() | after.keys()
                  if before.get(path) != after.get(path)
                  and not (files_only and before.get(path, after.get(path))[0] == "directory"
                           and after.get(path, before.get(path))[0] == "directory"))


class Workspace:
    def __init__(self, root: Path, empty_hooks: Path):
        self.root = root.resolve()
        self.empty_hooks = empty_hooks.resolve()
        self.empty_hooks.mkdir(parents=True, exist_ok=True)
        # M1 supports ordinary standalone repositories only. Do not resolve an
        # attacker-controlled .git file into another repository/worktree.
        if not (self.root / ".git").is_dir() or (self.root / ".git").is_symlink():
            raise PolicyError("STANDALONE_GIT_DIRECTORY_REQUIRED")
        self.metadata = self.git_metadata()
        if Path(self.git("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve() != self.root:
            raise PolicyError("REPOSITORY_ROOT_MISMATCH")

    def git(self, *args: str) -> bytes:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
        command = ["git", "-c", "core.fsmonitor=false", "-c", f"core.hooksPath={self.empty_hooks.as_posix()}",
                   "-c", "core.untrackedCache=false", "-c", "core.quotePath=false", *args]
        return subprocess.run(command, cwd=self.root, env=env, check=True,
                              capture_output=True, timeout=30).stdout

    def git_metadata(self) -> dict:
        return {name: snapshot(self.root / ".git" / name)
                for name in ("config", "config.worktree", "hooks", "info")}

    def check_metadata(self) -> list[str]:
        current = self.git_metadata()
        return [f".git/{name}/{path}" for name in self.metadata
                for path in differences(self.metadata[name], current[name])]

    def files(self) -> dict:
        return snapshot(self.root, exclude=(".git", EVIDENCE_DIRECTORY), normalize=True)

    def baseline(self) -> dict:
        status = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        # Only the registered evidence directory is exempt from a dirty start.
        entries = status.split(b"\0")
        if any(row and not row[3:].decode("utf-8").startswith(EVIDENCE_DIRECTORY + "/") for row in entries):
            raise PolicyError("DIRTY_BASELINE")
        return {"revision": self.git("rev-parse", "HEAD").decode("ascii").strip(),
                "files": self.files(), "git_metadata": self.metadata,
                "excluded_evidence_directories": [EVIDENCE_DIRECTORY],
                "git_metadata_handled_separately": [".git"]}

    def collect(self, baseline: dict) -> dict:
        # No Git process is launched after metadata tampering.
        metadata_changes = self.check_metadata()
        files = self.files()
        changed = differences(baseline["files"], files, files_only=True)
        evidence = {"changed_paths": changed, "files": files,
                    "git_metadata_changes": metadata_changes}
        if not metadata_changes:
            evidence["status_porcelain_z"] = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all").decode("utf-8")
            evidence["diff_name_status_z"] = self.git("diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "HEAD").decode("utf-8")
            evidence["revision_after"] = self.git("rev-parse", "HEAD").decode("ascii").strip()
            # An attacker can stage an unauthorized edit, then restore only the
            # working file. Observe the index as well as the on-disk snapshot.
            staged = self.git("diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", "HEAD")
            evidence["staged_paths"] = [p.decode("utf-8") for p in staged.split(b"\0") if p]
            for name in evidence["staged_paths"]:
                if name.startswith(EVIDENCE_DIRECTORY + "/"):
                    continue
                try:
                    raw = self.git("show", ":" + name)
                except subprocess.CalledProcessError:
                    changed.append(name)  # staged deletion
                    continue
                if b"\0" not in raw:
                    try:
                        raw = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                    except UnicodeDecodeError:
                        pass
                prior = baseline["files"].get(name)
                if prior is None or prior[0] != "file" or prior[1] != hashlib.sha256(raw).hexdigest():
                    changed.append(name)
            evidence["changed_paths"] = sorted(set(changed))
        return evidence

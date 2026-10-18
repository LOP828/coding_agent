"""Detect persistent environment writes; this is not OS access control."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from .workspace import snapshot, differences


def clean_environment() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("PYTHON", "PYTEST"))}


class PythonEnvironment:
    def __init__(self, executable: Path | None = None):
        # Keep the venv launcher path, not its resolved symlink target.
        self.executable = (executable or Path(sys.executable)).absolute()
        probe = (
            "import json,sys,sysconfig; print(json.dumps(dict("
            "paths=list(dict.fromkeys([sysconfig.get_path('purelib'),sysconfig.get_path('platlib')])),"
            "prefix=sys.prefix,version=sys.version.split()[0])))"
        )
        # Discovery occurs before any candidate executes, in the trusted initial environment.
        completed = subprocess.run([str(self.executable), "-I", "-B", "-c", probe],
                                   env=clean_environment(), capture_output=True, check=True, timeout=30)
        self.info = json.loads(completed.stdout)
        self.roots = [Path(p) for p in self.info["paths"]]
        self.roots += [self.executable, self.executable.resolve(), Path(self.info["prefix"]) / "pyvenv.cfg"]
        self.roots += [p.resolve() for p in self.roots if p.is_symlink()]
        self.before = self.capture()
        self.tainted = False

    def capture(self) -> dict:
        result = {path.as_posix(): snapshot(path) for path in self.roots}
        # Track targets of package links too; hashing a link's spelling alone
        # would miss writes through an existing symlink into site-packages.
        pending = list(self.roots)
        seen = set(result)
        while pending:
            root = pending.pop()
            for name, entry in result[root.as_posix()].items():
                if entry[0] == "link":
                    target = (root if name == "." else root / name).resolve()
                    key = target.as_posix()
                    if key not in seen:
                        seen.add(key)
                        result[key] = snapshot(target)
                        pending.append(target)
        return result

    def changes(self) -> list[str]:
        after = self.capture()
        changed = [f"{root}/{path}" for root in self.before.keys() | after.keys()
                   for path in differences(self.before.get(root, {}), after.get(root, {}))]
        self.tainted = self.tainted or bool(changed)
        return changed

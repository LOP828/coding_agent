"""Run honest M0 fixture checks plus local executions of trusted toy examples.

Fresh temporary directories are cleanup/isolation of examples, NOT a security
sandbox. This script is not a production Verification Runner.
"""
from __future__ import annotations

import json
import locale
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def junit_counts(path: Path) -> dict[str, int]:
    tree = ET.parse(path)
    cases = tree.findall(".//testcase")
    failed = sum(c.find("failure") is not None for c in cases)
    errors = sum(c.find("error") is not None for c in cases)
    skipped = sum(c.find("skipped") is not None for c in cases)
    return {"total": len(cases), "passed": len(cases) - failed - errors - skipped,
            "failed": failed, "errors": errors, "skipped": skipped}


def execute_pytest(cwd: Path, nodes: list[str], label: str, output: Path) -> dict[str, Any]:
    xml = output / f"{label}.xml"
    env = os.environ.copy()
    env.pop("PYTHONUTF8", None)
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = str(cwd)
    command = [sys.executable, "-m", "pytest", "-q", "--noconftest", *nodes, "--junitxml", str(xml)]
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=30, check=False)
    log = completed.stdout.decode(locale.getencoding()) + "\n" + completed.stderr.decode(locale.getencoding())
    (output / f"{label}.log").write_text(log, encoding="utf-8", newline="\n")
    return {"exit_code": completed.returncode, **junit_counts(xml),
            "junit_xml": xml.name, "log": f"{label}.log"}


def execute_candidate(root: Path, case: str, references: list[str], label: str, output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="m0-candidate-") as tmp:
        work = Path(tmp)
        for file in (root / "example_code" / case).glob("*.py"):
            shutil.copyfile(file, work / file.name)
        for name in sorted({ref.split("::", 1)[0] for ref in references}):
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, target)
        return execute_pytest(work, references, label, output)

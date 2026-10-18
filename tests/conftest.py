"""Shared paths for copied fixture data and newly generated evidence."""
from pathlib import Path
import importlib.metadata
import json
import locale
import os
import platform
import sys

import pytest


@pytest.fixture
def data_root():
    return Path(__file__).resolve().parent / "data" / "m0"


@pytest.fixture
def evidence_root():
    path = Path(__file__).resolve().parents[1] / "audit_evidence" / platform.system().lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def pytest_sessionfinish(session, exitstatus):
    """Record this platform's actual default-suite result, including failures."""
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    counts = {name: len(reporter.stats.get(name, []))
              for name in ("passed", "failed", "error", "skipped")}
    counts["errors"] = counts.pop("error")
    output = Path(__file__).resolve().parents[1] / "audit_evidence" / platform.system().lower()
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "command": "python -m pytest", "exit_code": int(exitstatus),
        "collected": session.testscollected, **counts,
        "system": platform.system(), "python": platform.python_version(),
        "executable": sys.executable, "locale_encoding": locale.getencoding(),
        "utf8_mode": sys.flags.utf8_mode, "PYTHONUTF8": os.environ.get("PYTHONUTF8"),
        "pytest": importlib.metadata.version("pytest"),
        "jsonschema": importlib.metadata.version("jsonschema"),
    }
    (output / "acceptance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

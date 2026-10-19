"""Versioned synthetic fixtures; no model calls."""
from pathlib import Path

from coding_agent.m0 import read_json
from coding_agent.runner import Runner

ROOT = Path(__file__).resolve().parents[1] / "data/m2"


def task(case="01_correct", root=ROOT):
    return read_json(root / "fixtures" / case / "atomic_task.json")


def runner(evidence_root=None, *, root=ROOT, **kwargs):
    return Runner(root, read_json(root / "fixtures/source_requirements.json"),
                  read_json(root / "fixtures/trusted_review_records.json"), evidence_root,
                  fixture_mode=True, **kwargs)


def source_executor(source):
    def execute(repository):
        (repository / "config_loader.py").write_text(source, encoding="utf-8")
    return execute

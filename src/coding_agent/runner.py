"""M1 controller. Executors are prewritten simulations, not an AI harness.

Temporary directories are not security sandboxes. Same-user malicious code can
read or destroy external files, race checks, or behave differently under tests.
"""
from __future__ import annotations

import copy
import hashlib
import platform
from pathlib import Path
import tempfile
from typing import Callable
import uuid

from .m0 import (PolicyError, aggregate_gate, declared_checks, scope_violations,
                 validate_admission, validate_report)
from .python_environment import PythonEnvironment
from .verification import FrozenTests, verify_candidate, write_json
from .workspace import EVIDENCE_DIRECTORY, Workspace


class Runner:
    """All constructor inputs belong to the controller, never the Executor.

    Executor receives only the repository Path. No schema root, approval store,
    test manifest, environment settings, or claimed result is accepted from it.
    """
    def __init__(self, test_root: Path, source: dict, trusted_records: dict,
                 evidence_root: Path, *, python: Path | None = None, fixture_mode: bool = False):
        self.test_root = test_root.resolve()
        self.source = copy.deepcopy(source)
        self.records = copy.deepcopy(trusted_records)
        self.evidence_root = evidence_root.resolve()
        self.python = python
        self.fixture_mode = fixture_mode
        self._environment = None

    def run(self, task: dict, repository: Path, executor: Callable[[Path], None]) -> dict:
        task = copy.deepcopy(task)
        repository = repository.resolve()
        if self.evidence_root.is_relative_to(repository) and not self.evidence_root.is_relative_to(repository / EVIDENCE_DIRECTORY):
            raise PolicyError("UNREGISTERED_EVIDENCE_DIRECTORY")
        evidence = self.evidence_root / uuid.uuid4().hex
        evidence.mkdir(parents=True)
        audit = {"events": [], "executor_calls": 0, "candidate_process_starts": 0, "checks": [],
                 "evidence_directory": evidence.as_posix(), "report": None}
        admitted = False
        rows = []
        changed = []
        baseline = None
        environment = None
        workspace = None
        try:
            validate_admission(task, self.source, self.records, self.test_root, fixture_mode=self.fixture_mode)
            admitted = True
            audit["events"].append({"event": "admitted"})
            frozen = FrozenTests(task, self.test_root)
            with tempfile.TemporaryDirectory(prefix="coding-agent-hooks-") as hooks:
                workspace = Workspace(repository, Path(hooks))
                baseline = workspace.baseline()
                audit["baseline"] = baseline
                if self._environment is None:
                    self._environment = PythonEnvironment(self.python)
                elif self._environment.changes():
                    raise PolicyError("PYTHON_ENVIRONMENT_QUARANTINED")
                environment = self._environment
                if environment.tainted:
                    raise PolicyError("PYTHON_ENVIRONMENT_QUARANTINED")
                audit["python_environment_baseline"] = environment.before
                audit["executor_calls"] += 1
                audit["events"].append({"event": "executor_started"})
                try:
                    executor(repository)
                except Exception as error:
                    audit["executor_error"] = f"{type(error).__name__}: {error}"
                audit["environment_changes_before_tests"] = environment.changes()
                collected = workspace.collect(baseline)
                audit["workspace"] = collected
                changed = collected["changed_paths"]
                if collected["git_metadata_changes"]:
                    raise PolicyError("GIT_METADATA_CHANGED")
                if collected["revision_after"] != baseline["revision"]:
                    raise PolicyError("GIT_REVISION_CHANGED")
                if environment.tainted:
                    raise PolicyError("PYTHON_ENVIRONMENT_CHANGED")
                if "executor_error" in audit:
                    raise PolicyError("EXECUTOR_FAILED: " + audit["executor_error"])
                try:
                    rows = verify_candidate(task, repository, frozen, environment, evidence, audit)
                finally:
                    collected = workspace.collect(baseline)
                    audit["workspace_after_tests"] = collected
                    changed = collected["changed_paths"]
                    if collected["git_metadata_changes"] or collected["revision_after"] != baseline["revision"]:
                        raise PolicyError("GIT_METADATA_OR_REVISION_CHANGED_DURING_TESTS")
        except Exception as error:
            audit["failure"] = f"{type(error).__name__}: {error}"
            audit["events"].append({"event": "blocked", "reason": audit["failure"]})
            rows = []  # Never retain successes from a compromised/incomplete run.
            if environment is not None:
                try:
                    audit["environment_changes_on_failure"] = environment.changes()
                except OSError as capture_error:
                    audit["environment_capture_error"] = str(capture_error)
        if admitted and baseline is not None:
            keys = {(row["property_id"], row["method"], row["reference"]) for row in rows}
            for owner, method, reference in declared_checks(task):
                if (owner, method, reference) in keys:
                    continue
                status = "NOT_RUN"
                if method == "DIFF_ALLOWLIST" and "workspace" in audit:
                    status = "FAIL" if scope_violations(task, changed) else "PASS"
                rows.append({"property_id": owner, "method": method, "reference": reference,
                             "status": status, "evidence": audit.get("failure", "Controller filesystem/Git comparison")})
            gate = aggregate_gate(task, rows, changed)
            revision = baseline["revision"] + ":" + hashlib.sha256(
                repr(audit.get("workspace_after_tests", audit.get("workspace", {})).get("files", {})).encode("utf-8")
            ).hexdigest()
            report = {"schema_version": "m0.2", "task_id": task["task_id"], "revision": revision,
                      "environment": {"platform": platform.system(), "python": environment.info["version"] if environment else platform.python_version(),
                                      "tool_versions": {"runner": "m1"}, "lockfile_sha256": None},
                      "results": rows, "gate": {**gate, "reason": audit.get("failure", "Controller-collected evidence")},
                      "approval_payload_sha256": task["acceptance_review"]["approved_payload_sha256"], "changed_paths": changed}
            validate_report(task, report, expected_revision=revision)
            audit["report"] = report
            write_json(evidence / "verification_report.json", report)
        write_json(evidence / "audit.json", audit)
        return audit

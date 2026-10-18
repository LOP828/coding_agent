"""Frozen tests, constrained pytest invocation, and actual JUnit results."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from .m0 import PolicyError, declared_checks, file_text_sha256
from .python_environment import PythonEnvironment, clean_environment
from .workspace import EVIDENCE_DIRECTORY, snapshot


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def parse_junit(path: Path, reference: str) -> dict:
    counts = dict(passed=0, failed=0, errors=0, skipped=0)
    executed = 0
    try:
        root = ET.parse(path).getroot()
        if root.tag not in ("testsuite", "testsuites"):
            raise ValueError("invalid JUnit root")
        cases = list(root.iter("testcase"))
        if not cases:
            raise ValueError("no test cases")
        filename, test_name = reference.split("::")
        classname = filename.removesuffix(".py").replace("/", ".")
        for case in cases:
            name = case.get("name", "")
            error = case.find("error")
            if error is not None:
                counts["errors"] += 1
                # pytest distinguishes setup/collection from teardown failures.
                # A teardown failure follows an executed call phase.
                executed += int(error.get("message", "").startswith("failed on teardown"))
                continue
            if case.get("classname") != classname or not (name == test_name or name.startswith(test_name + "[")):
                raise ValueError("unexpected JUnit identity")
            key = "skipped" if case.find("skipped") is not None else "failed" if case.find("failure") is not None else "passed"
            counts[key] += 1
            executed += int(key != "skipped")
        status = "FAIL" if counts["failed"] or counts["errors"] else "NOT_RUN" if counts["skipped"] else "PASS"
        # Collection/setup errors are not an executed test body.
        return {"status": status, "test_count": executed, **counts}
    except (OSError, ET.ParseError, ValueError) as error:
        return {"status": "UNVERIFIABLE", "test_count": 0, **counts,
                "reason": f"INVALID_JUNIT: {error}"}


class FrozenTests:
    def __init__(self, task: dict, root: Path):
        self.root = root
        self.manifest = {row["path"]: row["sha256_utf8_lf"] for row in task["acceptance_test_manifest"]}
        self.verify(root)
        self.contents = {name: (root / name).read_bytes() for name in self.manifest}

    def verify(self, root: Path) -> None:
        for name, digest in self.manifest.items():
            path = root / name
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise PolicyError("FROZEN_TEST_PATH_CHANGED")
            if not path.is_file() or file_text_sha256(path) != digest:
                raise PolicyError("FROZEN_TEST_HASH_MISMATCH")

    def inject(self, work: Path) -> None:
        self.verify(self.root)
        for name, raw in self.contents.items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.rmtree(target)
            target.write_bytes(raw)
        self.verify(work)


def verify_candidate(task: dict, repository: Path, frozen: FrozenTests,
                     environment: PythonEnvironment, evidence: Path, audit: dict) -> list[dict]:
    rows = []
    with tempfile.TemporaryDirectory(prefix="coding-agent-verification-") as temporary:
        work = Path(temporary) / "candidate"
        work.mkdir()
        files = snapshot(repository, exclude=(".git", EVIDENCE_DIRECTORY))
        for name, value in files.items():
            if value[0] == "link":
                raise PolicyError(f"CANDIDATE_SYMLINK_UNSUPPORTED: {name}")
            if value[0] == "file":
                target = work / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repository / name, target)
        frozen.inject(work)
        config = Path(temporary) / "pytest.ini"
        config.write_text("[pytest]\n", encoding="utf-8")
        bootstrap = Path(__file__).with_name("_pytest_bootstrap.py")
        audit["verification_directory"] = work.as_posix()
        audit["frozen_manifest"] = frozen.manifest
        for index, (owner, method, reference) in enumerate(declared_checks(task)):
            if method not in ("UNIT_TEST", "PROPERTY_TEST"):
                continue
            frozen.verify(work)
            if environment.tainted or environment.changes():
                raise PolicyError("PYTHON_ENVIRONMENT_CHANGED")
            xml = evidence / f"check-{index}.xml"
            invocation = evidence / f"check-{index}-invocation.json"
            arguments = ["-q", "-c", str(config), "--rootdir", str(work), "--noconftest",
                         "--import-mode=importlib", "-p", "no:cacheprovider", "-o", "addopts=",
                         reference, "--junitxml", str(xml)]
            write_json(invocation, {"dependency_paths": environment.info["paths"],
                                    "candidate_path": str(work), "arguments": arguments})
            command = [str(environment.executable), "-I", "-S", "-B", str(bootstrap), str(invocation)]
            env = clean_environment()
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            audit["candidate_process_starts"] += 1
            audit["events"].append({"event": "pytest_started", "reference": reference, "command": command})
            try:
                completed = subprocess.run(command, cwd=work, env=env, capture_output=True, timeout=30)
                # Store bytes too; UTF-8 log replacement never crashes on CP936 output.
                (evidence / f"check-{index}.stdout").write_bytes(completed.stdout)
                (evidence / f"check-{index}.stderr").write_bytes(completed.stderr)
                (evidence / f"check-{index}.log").write_text(
                    (completed.stdout + completed.stderr).decode("utf-8", errors="replace"), encoding="utf-8")
                parsed = parse_junit(xml, reference)
                if completed.returncode not in (0, 1) or (completed.returncode == 1 and parsed["status"] == "PASS"):
                    parsed.update(status="UNVERIFIABLE", reason="PYTEST_EXIT_INCONSISTENT")
                parsed["exit_code"] = completed.returncode
            except subprocess.TimeoutExpired:
                parsed = {"status": "UNVERIFIABLE", "test_count": 0, "reason": "PYTEST_TIMEOUT"}
            audit["checks"].append({"reference": reference, **parsed})
            rows.append({"property_id": owner, "method": method, "reference": reference,
                         "status": parsed["status"], "test_count": parsed["test_count"],
                         "evidence": xml.as_posix() + (": " + parsed["reason"] if "reason" in parsed else "")})
            frozen.verify(work)
        audit["environment_changes_after_tests"] = environment.changes()
        if environment.tainted:
            raise PolicyError("PYTHON_ENVIRONMENT_CHANGED")
    return rows

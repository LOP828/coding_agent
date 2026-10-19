"""Trusted data-case parsing/comparison. This module never imports candidate code."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import uuid

from .m0 import PolicyError, declared_checks, validate_path
from .python_environment import clean_environment
from .verification import FrozenTests, run_captured, write_json
from .workspace import EVIDENCE_DIRECTORY, snapshot

FORMAT = "coding-agent-observation-v2"
MAX_OBSERVATION_BYTES = 1024 * 1024


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite JSON number: " + value)

    result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    # Also reject overflow such as 1e999, which does not use parse_constant.
    json.dumps(result, allow_nan=False)
    return result


def exact_fields(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("invalid object fields")


def validate_outcome(value, *, expectation=False):
    if type(value) is not dict:
        raise ValueError("outcome must be an object")
    if value.get("kind") == "return":
        exact_fields(value, ("kind", "value"))
    elif value.get("kind") == "exception":
        exact_fields(value, ("kind", "type") if expectation else ("kind", "type", "message"),
                     ("message",) if expectation else ())
        if type(value["type"]) is not str or not value["type"].isidentifier():
            raise ValueError("invalid exception class name")
        if "message" in value and type(value["message"]) is not str:
            raise ValueError("invalid exception message")
    else:
        raise ValueError("invalid outcome kind")


def same_value(left, right):
    """JSON equality with exact types, including bool versus int."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_value(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    return left == right


def parse_observation(raw: bytes, run_id: str, case_id: str) -> dict:
    if len(raw) > MAX_OBSERVATION_BYTES:
        raise ValueError("observation too large")
    observation = strict_json(raw)
    exact_fields(observation, ("format", "run_id", "case_id", "outcome"))
    if observation["format"] != FORMAT or observation["run_id"] != run_id or observation["case_id"] != case_id:
        raise ValueError("observation identity mismatch")
    validate_outcome(observation["outcome"])
    return observation["outcome"]


def compare_outcome(observed: dict, expected: dict) -> bool:
    if observed["kind"] != expected["kind"]:
        return False
    if expected["kind"] == "return":
        return same_value(observed["value"], expected["value"])
    return (observed["type"] == expected["type"] and
            ("message" not in expected or observed["message"] == expected["message"]))


class FrozenCases(FrozenTests):
    format = "coding-agent-cases-v2"

    def __init__(self, task: dict, root: Path, *, timeout: float = 30):
        super().__init__(task, root)
        if timeout <= 0:
            raise PolicyError("INVALID_CASE_TIMEOUT")
        self.timeout = timeout
        self.cases = {}
        try:
            for filename, raw in self.contents.items():
                data = strict_json(raw)
                exact_fields(data, ("format", "cases"))
                if data["format"] != self.format or type(data["cases"]) is not dict or not data["cases"]:
                    raise ValueError("invalid case format")
                for case_id, case in data["cases"].items():
                    if not case_id or "::" in case_id:
                        raise ValueError("invalid case ID")
                    exact_fields(case, ("module", "function", "args", "kwargs", "expect"))
                    validate_path(case["module"])
                    if not case["module"].endswith(".py") or not case["function"].isidentifier():
                        raise ValueError("invalid invocation target")
                    if type(case["args"]) is not list or type(case["kwargs"]) is not dict:
                        raise ValueError("invalid invocation arguments")
                    validate_outcome(case["expect"], expectation=True)
                    self.cases[f"{filename}::{case_id}"] = case
            for _, method, reference in declared_checks(task):
                if method in ("UNIT_TEST", "PROPERTY_TEST") and reference not in self.cases:
                    raise ValueError("declared case missing")
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            raise PolicyError(f"INVALID_FROZEN_CASES: {error}") from error


def verify_cases(task, repository, frozen, environment, evidence, audit):
    rows = []
    with tempfile.TemporaryDirectory(prefix="coding-agent-observation-") as temporary:
        work = Path(temporary) / "candidate"
        work.mkdir()
        for name, entry in snapshot(repository, exclude=(".git", EVIDENCE_DIRECTORY)).items():
            if entry[0] == "link":
                raise PolicyError(f"CANDIDATE_SYMLINK_UNSUPPORTED: {name}")
            if entry[0] == "file":
                target = work / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repository / name, target)
        audit["verification_directory"] = work.as_posix()
        audit["frozen_manifest"] = frozen.manifest
        audit["verification_backend"] = frozen.format
        worker = Path(__file__).with_name("_candidate_worker.py")
        for index, (owner, method, reference) in enumerate(declared_checks(task)):
            if method not in ("UNIT_TEST", "PROPERTY_TEST"):
                continue
            frozen.verify(frozen.root)
            if environment.tainted or environment.changes():
                raise PolicyError("PYTHON_ENVIRONMENT_CHANGED")
            case = copy.deepcopy(frozen.cases[reference])
            run_id = uuid.uuid4().hex
            request = {"format": FORMAT, "run_id": run_id, "case_id": reference,
                       "candidate_root": work.as_posix(), "dependency_paths": environment.info["paths"],
                       **{k: case[k] for k in ("module", "function", "args", "kwargs")}}
            write_json(evidence / f"check-{index}-request.json", request)
            command = [str(environment.executable), "-I", "-S", "-B", str(worker)]
            audit["candidate_process_starts"] += 1
            audit["events"].append({"event": "candidate_started", "reference": reference, "command": command})
            result = run_captured(command, cwd=work, env=clean_environment(), evidence=evidence,
                                  prefix=f"check-{index}", timeout=frozen.timeout,
                                  stdin=json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            parsed = {"status": "UNVERIFIABLE", "test_count": 0, **result}
            if result["timed_out"]:
                parsed["reason"] = "CANDIDATE_TIMEOUT"
            elif result["exit_code"] != 0:
                parsed["reason"] = "CANDIDATE_ABNORMAL_EXIT"
            else:
                try:
                    with Path(result["stdout"]).open("rb") as stream:
                        observed = parse_observation(stream.read(MAX_OBSERVATION_BYTES + 1), run_id, reference)
                    matches = compare_outcome(observed, case["expect"])
                    parsed.update(status="PASS" if matches else "FAIL", test_count=1,
                                  reason="OBSERVATION_MATCH" if matches else "OBSERVATION_MISMATCH",
                                  observed=observed, expected=case["expect"])
                except (ValueError, TypeError, RecursionError) as error:
                    parsed["reason"] = f"INVALID_OBSERVATION: {error}"
            parsed.update(passed=int(parsed["status"] == "PASS"),
                          failed=int(parsed["status"] == "FAIL"),
                          errors=int(parsed["status"] == "UNVERIFIABLE"), skipped=0)
            write_json(evidence / f"check-{index}-comparison.json", parsed)
            audit["checks"].append({"reference": reference, **parsed})
            rows.append({"property_id": owner, "method": method, "reference": reference,
                         "status": parsed["status"], "test_count": parsed["test_count"],
                         "evidence": (evidence / f"check-{index}-comparison.json").as_posix() + ": " + parsed["reason"]})
            frozen.verify(frozen.root)
        audit["environment_changes_after_tests"] = environment.changes()
        if environment.tainted:
            raise PolicyError("PYTHON_ENVIRONMENT_CHANGED")
    return rows

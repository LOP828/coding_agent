"""M0.2 structural admission and deterministic policy aggregation.

No agent, sandbox, Git diff collector, approval service, or semantic checker.
Trust comes from the caller supplying controller-owned records, not from JSON
claiming APPROVED or from the SHA-256 algorithm alone.
"""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

Json = dict[str, Any]


class PolicyError(ValueError):
    """A stable policy code, rather than an invented execution result."""


def read_json(path: Path) -> Json:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema(name: str, data: Json, *, schema_root: Path | None = None) -> None:
    """Load bundled schemas by default; an explicit root contains schema files."""
    resource_root = files("coding_agent").joinpath("schemas") if schema_root is None else schema_root
    schema = json.loads(resource_root.joinpath(f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(data)


def text_sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_text_sha256(path: Path) -> str:
    text = path.read_bytes().decode("utf-8")
    if text.startswith("\ufeff"):
        raise PolicyError("UTF8_BOM_NOT_ALLOWED")
    return text_sha256(text.replace("\r\n", "\n").replace("\r", "\n"))


def approval_payload_sha256(task: Json, source: Json) -> str:
    payload = {
        "task": {key: value for key, value in task.items() if key != "acceptance_review"},
        "source_requirements": sorted(
            (row for row in source["requirements"] if row["id"] in task["requirement_refs"]),
            key=lambda row: row["id"],
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_path(value: str, *, pattern: bool = False) -> str:
    # Deliberately NOT pathlib.match, fnmatch, or shell globbing.
    stem = value[:-3] if pattern and value.endswith("/**") else value
    if (
        not stem
        or "\\" in value
        or ":" in value
        or any(ord(ch) < 32 for ch in value)
        or any(ch in stem for ch in "*?[]")
        or any(part in ("", ".", "..") for part in stem.split("/"))
    ):
        raise PolicyError("INVALID_PATH")
    return value


def path_matches(path: str, pattern: str) -> bool:
    validate_path(path)
    validate_path(pattern, pattern=True)
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3] + "/")
    return path == pattern


def scope_violations(task: Json, changed_paths: list[str]) -> list[str]:
    if len(changed_paths) != len(set(changed_paths)):
        raise PolicyError("DUPLICATE_CHANGED_PATH")
    violations = []
    for path in changed_paths:
        validate_path(path)
        protected = any(path_matches(path, p) for p in task["protected_paths"])
        allowed = any(path_matches(path, p) for p in task["allowed_change_paths"])
        if protected or not allowed:
            violations.append(path)
    return sorted(violations)


def declared_checks(task: Json) -> dict[tuple[str | None, str, str], Json]:
    checks: dict[tuple[str | None, str, str], Json] = {}
    for owner, rows in [(p["id"], p["checks"]) for p in task["properties"]] + [(None, task["task_checks"])]:
        for row in rows:
            key = (owner, row["method"], row["reference"])
            if key in checks:
                raise PolicyError("DUPLICATE_DECLARED_CHECK")
            checks[key] = row
    return checks


def validate_admission(
    task: Json,
    source: Json,
    trusted_records: Json,
    test_root: Path,
    *,
    schema_root: Path | None = None,
    fixture_mode: bool = False,
) -> None:
    """Return only after structural admission; do not execute code or attest intent."""
    validate_schema("source_requirements", source, schema_root=schema_root)
    validate_schema("atomic_task", task, schema_root=schema_root)
    sources = {row["id"]: row for row in source["requirements"]}
    if len(sources) != len(source["requirements"]):
        raise PolicyError("DUPLICATE_REQUIREMENT_ID")
    for row in source["requirements"]:
        if text_sha256(row["raw_text"]) != row["sha256_utf8"]:
            raise PolicyError("SOURCE_HASH_MISMATCH")
    task_refs = set(task["requirement_refs"])
    if not task_refs <= sources.keys():
        raise PolicyError("UNKNOWN_REQUIREMENT")
    for ref in sorted(task_refs):
        row = sources[ref]
        if row["status"] != "FROZEN":
            raise PolicyError("SOURCE_NOT_FROZEN")
        if row["source_kind"] == "USER_MESSAGE":
            if row["confirmation"] != "USER_CONFIRMED":
                raise PolicyError("SOURCE_NOT_CONFIRMED")
        elif not (fixture_mode and row["confirmation"] == "NOT_APPLICABLE_FIXTURE"):
            raise PolicyError("SYNTHETIC_SOURCE_NOT_ALLOWED")
    properties = task["properties"]
    if len({p["id"] for p in properties}) != len(properties):
        raise PolicyError("DUPLICATE_PROPERTY_ID")
    covered: set[str] = set()
    for prop in properties:
        refs = set(prop["requirement_refs"])
        if not refs <= task_refs:
            raise PolicyError("PROPERTY_SOURCE_OUTSIDE_TASK")
        covered.update(refs)
        if prop["origin"] == "UNSOURCED":
            raise PolicyError("UNSOURCED_PROPERTY")
        if prop["origin"] == "DERIVED" and not prop.get("derivation_reason", "").strip():
            raise PolicyError("DERIVED_REASON_REQUIRED")
        if prop["scope_impact"] != "LOCAL_REFINEMENT":
            if not prop["scope_expansion_authorized"]:
                raise PolicyError("SCOPE_AUTHORIZATION_REQUIRED")
            grants = [g for g in trusted_records["scope_authorizations"]
                      if g["authorization_ref"] == prop.get("scope_authorization_ref")]
            if len(grants) != 1 or any((
                grants[0].get("status") != "APPROVED",
                grants[0].get("task_id") != task["task_id"],
                grants[0].get("property_id") != prop["id"],
                grants[0].get("scope_impact") != prop["scope_impact"],
            )):
                raise PolicyError("UNTRUSTED_SCOPE_AUTHORIZATION")
    if covered != task_refs:
        raise PolicyError("UNCOVERED_TASK_REQUIREMENT")
    for pattern in task["allowed_change_paths"] + task["protected_paths"]:
        validate_path(pattern, pattern=True)
    checks = declared_checks(task)
    scope_key = (None, "DIFF_ALLOWLIST", "allowed_change_paths")
    scope_rows = [key for key in checks if key[1] == "DIFF_ALLOWLIST"]
    if scope_rows != [scope_key] or not checks[scope_key]["required"]:
        raise PolicyError("TASK_SCOPE_CHECK_REQUIRED")
    manifest = {row["path"]: row["sha256_utf8_lf"] for row in task["acceptance_test_manifest"]}
    if len(manifest) != len(task["acceptance_test_manifest"]):
        raise PolicyError("DUPLICATE_TEST_MANIFEST_PATH")
    used_test_files: set[str] = set()
    for _, method, reference in checks:
        if method in ("UNIT_TEST", "PROPERTY_TEST"):
            parts = reference.split("::")
            if len(parts) != 2 or not parts[1]:
                raise PolicyError("INVALID_TEST_REFERENCE")
            validate_path(parts[0])
            used_test_files.add(parts[0])
    if used_test_files != manifest.keys():
        raise PolicyError("TEST_MANIFEST_COVERAGE_MISMATCH")
    for relative, expected in manifest.items():
        validate_path(relative)
        full = (test_root / relative).resolve()
        if not full.is_relative_to(test_root.resolve()):
            raise PolicyError("TEST_PATH_OUTSIDE_PACKAGE")
        if not full.is_file() or file_text_sha256(full) != expected:
            raise PolicyError("TEST_CONTENT_HASH_MISMATCH")
    review = task["acceptance_review"]
    if review["status"] != "APPROVED":
        raise PolicyError("ACCEPTANCE_NOT_APPROVED")
    digest = approval_payload_sha256(task, source)
    if review["approved_payload_sha256"] != digest:
        raise PolicyError("APPROVAL_CONTENT_MISMATCH")
    records = [r for r in trusted_records["review_records"] if r["approval_ref"] == review["approval_ref"]]
    if len(records) != 1 or any((
        records[0].get("task_id") != task["task_id"],
        records[0].get("status") != "APPROVED",
        records[0].get("approved_payload_sha256") != digest,
    )):
        raise PolicyError("UNTRUSTED_APPROVAL")


def aggregate_gate(task: Json, results: list[Json], changed_paths: list[str]) -> Json:
    """Pure function: notably has NO input parameter named 'gate'.

    Inputs here are synthetic, trusted evidence in M0. Actual evidence collection
    and its provenance belong to the M1 runner.
    """
    expected = declared_checks(task)
    actual: dict[tuple[str | None, str, str], Json] = {}
    for row in results:
        key = (row["property_id"], row["method"], row["reference"])
        if key not in expected:
            raise PolicyError("UNDECLARED_CHECK_RESULT")
        if key in actual:
            raise PolicyError("DUPLICATE_CHECK_RESULT")
        if row["status"] not in ("PASS", "FAIL", "NOT_RUN", "UNVERIFIABLE"):
            raise PolicyError("INVALID_CHECK_STATUS")
        if row["status"] == "PASS" and row["method"] in ("UNIT_TEST", "PROPERTY_TEST"):
            count = row.get("test_count")
            if type(count) is not int or count < 1:
                raise PolicyError("INVALID_PASS_TEST_COUNT")
        actual[key] = row
    violations = scope_violations(task, changed_paths)
    scope_row = actual.get((None, "DIFF_ALLOWLIST", "allowed_change_paths"))
    # Preserve a proven scope violation even when the supplied report claims PASS.
    if violations:
        return {"status": "HARD_FAIL", "route": "EXECUTION_FAIL"}
    if scope_row is not None and scope_row["status"] in ("PASS", "FAIL") and scope_row["status"] != "PASS":
        raise PolicyError("SCOPE_RESULT_INCONSISTENT")
    missing = False
    for key, check in expected.items():
        if not check["required"]:
            continue
        status = actual[key]["status"] if key in actual else "NOT_RUN"
        if status == "FAIL":
            return {"status": "HARD_FAIL", "route": "EXECUTION_FAIL"}
        if status in ("NOT_RUN", "UNVERIFIABLE"):
            missing = True
    if missing:
        return {"status": "BLOCKED", "route": "BLOCKED"}
    return {"status": "PASS", "route": "NONE"}


def validate_report(
    task: Json, report: Json, *, expected_revision: str, schema_root: Path | None = None
) -> Json:
    """Check a report only AFTER successful admission by the caller."""
    validate_schema("verification_report", report, schema_root=schema_root)
    if report["task_id"] != task["task_id"]:
        raise PolicyError("REPORT_TASK_MISMATCH")
    if report["revision"] != expected_revision:
        raise PolicyError("REPORT_REVISION_MISMATCH")
    if report["approval_payload_sha256"] != task["acceptance_review"]["approved_payload_sha256"]:
        raise PolicyError("REPORT_APPROVAL_MISMATCH")
    computed = aggregate_gate(task, report["results"], report["changed_paths"])
    if any(report["gate"][key] != computed[key] for key in ("status", "route")):
        # Callers must retain computed separately; never accept the claimed gate.
        raise PolicyError("REPORTED_GATE_MISMATCH")
    return computed

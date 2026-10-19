"""No-model Codex sandbox matrix. All candidates live under --run-root."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coding_agent.codex_executor import PROFILE, configuration_identity, policy_template, sandbox_overrides
from coding_agent.m0 import scope_violations
from coding_agent.python_environment import clean_environment
from coding_agent.verification import run_captured, write_json
from coding_agent.workspace import Workspace


CASES = [
    ("allowed_write", "write", "config_loader.py", None, True),
    ("protected_write", "write", "project_config.py", None, False),
    ("allowed_new", "write", "allowed/new.txt", None, True),
    ("protected_new", "write", "protected/new.txt", None, False),
    ("undeclared_new", "write", "undeclared.py", None, False),
    ("allowed_rename", "rename", "allowed/existing.txt", "allowed/moved.txt", True),
    ("rename_to_protected", "rename", "allowed/existing.txt", "protected/moved.txt", False),
    ("rename_from_protected", "rename", "protected/existing.txt", "allowed/moved.txt", False),
    ("replace_protected_file", "rename", "allowed/existing.txt", "project_config.py", False),
    ("move_to_protected", "move", "allowed/existing.txt", "protected/moved.txt", False),
    ("move_from_protected", "move", "protected/existing.txt", "allowed/moved.txt", False),
    ("link_allowed", "link_write", "allowed/link.txt", "allowed/existing.txt", True),
    ("link_protected", "link_write", "allowed/link.txt", "protected/existing.txt", False),
    ("link_new_protected", "link_write", "allowed/link.txt", "protected/new.txt", False),
    ("create_link_protected", "link", "protected/link.txt", "allowed/existing.txt", False),
    ("child_allowed", "child", "config_loader.py", None, True),
    ("child_protected", "child", "project_config.py", None, False),
]


def seed(root):
    root.mkdir(parents=True)
    for name in ("config_loader.py", "project_config.py", "allowed/existing.txt", "protected/existing.txt"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original\n", encoding="utf-8")
    for args in (("init",), ("config", "user.name", "M2 Probe"),
                 ("config", "user.email", "m2-probe@example.invalid"), ("config", "core.autocrlf", "true"),
                 ("add", "."), ("commit", "-m", "disposable sandbox baseline")):
        subprocess.run(["git", "-c", "core.hooksPath=" + (root / ".empty-hooks").as_posix(), *args],
                       cwd=root, capture_output=True, check=True)


def operation(kind, target, destination):
    return (
        "from pathlib import Path\nimport subprocess,sys,shutil\nprint('PROBE_STARTED',flush=True)\n"
        f"target=Path({target!r})\ndestination={destination!r}\n"
        + {
            "write": "target.write_text('changed\\n',encoding='utf-8')\n",
            "rename": "target.replace(destination)\n",
            "move": "shutil.move(str(target),destination)\n",
            "link": "target.symlink_to(Path(destination).resolve())\n",
            "link_write": "target.symlink_to(Path(destination).resolve())\ntarget.write_text('changed\\n',encoding='utf-8')\n",
            "child": "subprocess.run([sys.executable,'-c',\"from pathlib import Path; Path(\"+repr(str(target))+\").write_text('changed\\\\n',encoding='utf-8')\"],check=True)\n",
        }[kind] + "print('PROBE_COMPLETED',flush=True)\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args()
    controller = Path(__file__).resolve().parents[1]
    run_root = args.run_root.resolve()
    if run_root.is_relative_to(controller):
        parser.error("run root must be outside coding_agent")
    session = run_root / ("sandbox-" + uuid.uuid4().hex[:12])
    evidence = session / "evidence"
    evidence.mkdir(parents=True)
    version = subprocess.run([args.codex, "--version"], capture_output=True, check=True, timeout=30)
    (evidence / "version.stdout").write_bytes(version.stdout)
    (evidence / "version.stderr").write_bytes(version.stderr)
    version_text = version.stdout.decode("utf-8").strip()
    rows = []
    identities = []
    for mode in ("named", "workspace"):
        for name, kind, target, destination, allowed in CASES:
            repository = session / mode / name
            seed(repository)
            identities.append(configuration_identity(repository))
            with tempfile.TemporaryDirectory(prefix="m2-probe-hooks-") as hooks:
                workspace = Workspace(repository, Path(hooks))
                baseline = workspace.baseline()
                if mode == "named":
                    overrides = sandbox_overrides(repository, controller, evidence)
                    profile = PROFILE
                else:
                    # Legacy config from the M1 investigation; cwd remains writable.
                    profile = "workspace-write"
                    overrides = ["-c", 'sandbox_mode="workspace-write"',
                                 "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
                                 "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
                                 "-c", "sandbox_workspace_write.network_access=false"]
                command = [args.codex, "--no-daemon", "sandbox", "-C", str(repository),
                           "-P", profile, *overrides, "--", sys.executable, "-I", "-B", "-c",
                           operation(kind, target, destination)]
                row_dir = evidence / mode / name
                result = run_captured(command, cwd=repository, env=clean_environment(),
                                      evidence=row_dir, prefix="probe", timeout=30)
                collected = workspace.collect(baseline)
            violations = scope_violations({"allowed_change_paths": ["config_loader.py", "allowed/**"],
                                          "protected_paths": ["project_config.py", "protected/**"]},
                                         collected["changed_paths"])
            stdout = Path(result["stdout"]).read_bytes()
            stderr = Path(result["stderr"]).read_bytes()
            started = b"PROBE_STARTED" in stdout
            success = b"PROBE_COMPLETED" in stdout and result["exit_code"] == 0
            denied = started and not success and any(s in stderr for s in
                (b"Read-only file system", b"Permission denied", b"Device or resource busy",
                 b"Invalid cross-device link"))
            if not allowed and violations:
                category = "沙箱未阻止、仅 M1 事后检测"
            elif not allowed and denied:
                category = "沙箱直接阻止"
            elif allowed and success:
                category = "允许路径写入成功（正向对照）"
            else:
                category = "未证实/受阻"
            row = {"mode": mode, "case": name, "allowed": allowed, "target": target,
                   "destination": destination, "operation": kind, "configuration": overrides,
                   "repository": repository.as_posix(), "execution": result, "started": started,
                   "completed": success, "classification": category, "verification": "已实测",
                   "changed_paths": collected["changed_paths"], "m1_scope_violations": violations,
                   "baseline": baseline, "after": collected}
            write_json(row_dir / "result.json", row)
            rows.append(row)
    named = [row for row in rows if row["mode"] == "named"]
    usable = all(row["completed"] if row["allowed"] else
                 row["classification"] == ("沙箱未阻止、仅 M1 事后检测" if row["case"] == "undeclared_new"
                                            else "沙箱直接阻止") for row in named)
    usable = usable and all(identity == identities[0] for identity in identities)
    proof = {"codex_version": version_text, "expected_version": "codex-cli 0.163.0",
             "platform": platform.system(), "policy_template": policy_template(),
             "configuration_identity": identities[0],
             "matrix_complete": len(named) == len(CASES), "usable_for_executor": usable,
             "strict_allowlist_enforced": False,
             "model_calls": 0, "evidence": evidence.as_posix(),
             "rows": [{k: row[k] for k in ("mode", "case", "classification", "changed_paths", "m1_scope_violations")}
                      for row in rows]}
    write_json(evidence / "sandbox-proof.json", proof)
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

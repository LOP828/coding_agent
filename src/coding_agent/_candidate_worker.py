"""Untrusted execution side of observation-v2; no expected values or verdicts.

The candidate shares this process and can forge its output. Correlation IDs are
not authentication. Import/lookup/serialization failures deliberately exit
abnormally, rather than masquerading as the tested function's exception.
"""
import importlib.util
import json
from pathlib import Path
import sys


def main():
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.path.extend(request["dependency_paths"])
    root = Path(request["candidate_root"])
    sys.path.append(str(root))
    spec = importlib.util.spec_from_file_location("candidate", root / request["module"])
    module = importlib.util.module_from_spec(spec)
    sys.modules["candidate"] = module
    spec.loader.exec_module(module)
    function = getattr(module, request["function"])
    if not callable(function):
        raise TypeError("candidate target is not callable")
    try:
        value = function(*request["args"], **request["kwargs"])
    except Exception as error:
        outcome = {"kind": "exception", "type": type(error).__name__, "message": str(error)}
    else:
        outcome = {"kind": "return", "value": value}
    record = {"format": request["format"], "run_id": request["run_id"],
              "case_id": request["case_id"], "outcome": outcome}
    sys.stdout.buffer.write((json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

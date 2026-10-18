"""Run only under -I -S -B; never execute site initialization or .pth files."""
import json
from pathlib import Path
import sys

configuration = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sys.path.extend(configuration["dependency_paths"])
import pytest  # noqa: E402 -- import the controller-selected installation first

sys.path.append(configuration["candidate_path"])
raise SystemExit(pytest.main(configuration["arguments"]))

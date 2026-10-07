"""The shared core is identical wherever it is used: core.sha256 records its exact bytes.

After changing a core file, copy it to every repository that shares the core and
regenerate the manifest: sha256sum logiops/service.py logiops/scenario.py logiops/tools.py tests/test_flow.py > core.sha256
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ("logiops/service.py", "logiops/scenario.py", "logiops/tools.py", "tests/test_flow.py")


def test_core_files_match_the_manifest():
    recorded = dict(reversed(line.split()) for line in (ROOT / "core.sha256").read_text().splitlines() if line.strip())
    assert sorted(recorded) == sorted(CORE)
    for path in CORE:
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == recorded[path], f"{path} differs from core.sha256"

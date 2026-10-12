"""The browser modules under static/app have their own node:test suite; pytest runs it when node exists."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_the_node_module_suite_passes():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    suites = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests" / "static").glob("*.test.mjs"))
    assert suites, "no node suites found"
    run = subprocess.run([node, "--test", *suites], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    assert "fail 0" in run.stdout and "pass 12" in run.stdout

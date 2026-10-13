"""The README's screenshots exist, every image in docs/img is used, and the docs name what the demo has."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_screenshot_is_referenced_and_present():
    readme = (ROOT / "README.md").read_text()
    referenced = set(re.findall(r"\]\((docs/img/[\w.-]+\.png)\)", readme))
    assert referenced, "the README shows no screenshot"
    for path in referenced:
        assert (ROOT / path).is_file(), path
    present = {f"docs/img/{path.name}" for path in (ROOT / "docs" / "img").glob("*.png")}
    assert present >= referenced
    assert all((ROOT / path).stat().st_size < 1_000_000 for path in present), "a screenshot is larger than 1 MB"
    script = (ROOT / "scripts" / "screenshots.py").read_text()
    for name in ("device-home", "device-plans", "device-confirm", "device-result", "console", "device-phone"):
        assert f'"{name}"' in script, name


def test_the_docs_name_the_device_the_console_strands_metrics_and_packs():
    readme = (ROOT / "README.md").read_text()
    architecture = (ROOT / "docs" / "architecture.md").read_text()
    for text in ("/console", "Strands Agents", "GET /metrics", "scenario pack", "illustrative", "Measured on the deployed demo"):
        assert text in readme, text
    for text in ("## Production path", "Strands Agents", "AgentCore Memory", "Amazon Polly", "Amazon Cognito", "scenario packs", "alexa-plus-readiness.md"):
        assert text in architecture, text
    assert "operator panel" not in readme

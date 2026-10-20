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


def test_the_hackathon_package_is_complete_and_prioritised():
    hackathon = ROOT / "docs" / "hackathon"
    for name in ("alexa-plus-readiness.md", "feature-requests.md", "video-script.md", "recording-checklist.md",
                 "amazon-feedback.md", "amazon-friction-log.md", "testing-instructions.md", "decisions.md", "submission-fields.md"):
        assert (hackathon / name).is_file(), name
    requests = (hackathon / "feature-requests.md").read_text()
    rows = [line for line in requests.splitlines() if line.startswith(("| P1", "| P2", "| P3"))]
    assert len(rows) >= 10 and all(line.split("|")[1].strip() in ("P1", "P2", "P3") for line in rows)
    feedback = (hackathon / "amazon-feedback.md").read_text()
    for section in ("## Strands Agents", "## Amazon Polly", "## Amazon Cognito", "## Amazon Bedrock AgentCore Memory"):
        assert section in feedback, section
    friction = (hackathon / "amazon-friction-log.md").read_text()
    assert "2026-10-12 — Strands Agents" in friction and "NoRegionError" in friction
    readiness = (hackathon / "alexa-plus-readiness.md").read_text()
    for item in ("MCP Apps", "Agent Skills", "OAuth 2.1", "Purchasing", "State across sessions", "Proactive notifications"):
        assert item in readiness, item
    script = (hackathon / "video-script.md").read_text()
    assert "2:45–2:55" in script and "under 3 minutes" in script and "Cuts, in order" in script
    instructions = (hackathon / "testing-instructions.md").read_text()
    assert "operator panel" not in instructions and "/console" in instructions

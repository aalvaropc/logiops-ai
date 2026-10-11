"""The exception-desk Agent Skill: one SKILL.md, served over MCP and loaded by the agent at runtime."""

from __future__ import annotations

import hashlib
from pathlib import Path

SKILL_NAME = "logiops-exception-desk"
SKILL_URI = f"skill://{SKILL_NAME}/SKILL.md"
SKILL_MIME_TYPE = "text/markdown"
SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / SKILL_NAME / "SKILL.md"
SKILL_TEXT = SKILL_PATH.read_bytes().decode("utf-8")
SKILL_SHA256 = hashlib.sha256(SKILL_TEXT.encode()).hexdigest()

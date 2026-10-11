"""Spoken replies with Amazon Polly, cached and capped per day, with the browser's voice as fallback.

A reply is cleaned for speech (no Markdown, internal ids or links), cut at a sentence boundary,
synthesized once per text (cached in SQLite by its hash) and charged against a daily character
budget shared by every visitor. When Polly is off, over budget or failing, `speak` returns None and
the page reads the reply with the browser's own voice. After a failure Polly rests for five minutes,
so a missing permission never slows every reply down.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .presentation import PLAN_ID
from .scenario import LIMA
from .storage import connect

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "Ruth"
DEFAULT_ENGINE = "generative"
DEFAULT_DAILY_CHARS = 30_000
MAX_CHARS = 600
REST_SECONDS = 300
FILLERS = (
    "One moment, I'm checking the shipment and the carriers.",
    "Still working on it. I'm comparing the plans.",
    "Almost there.",
)
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS speech_cache (key TEXT PRIMARY KEY, audio BLOB NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS speech_budget (day TEXT PRIMARY KEY, chars INTEGER NOT NULL)",
)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
URL = re.compile(r"https?://\S+")
BLOCK = re.compile(r"(?m)^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s?)")
INLINE = re.compile(r"[*_`]+")


def speech_text(text: str, limit: int = MAX_CHARS) -> str:
    """What a voice reads: no Markdown, links, URLs or plan ids, one line, cut at a sentence end."""
    plain = LINK.sub(r"\1", str(text or ""))
    plain = PLAN_ID.sub("", URL.sub("", plain))
    plain = INLINE.sub("", BLOCK.sub(" ", plain)).replace("|", " ")
    plain = re.sub(r"\s+([.,:;!?])", r"\1", re.sub(r"\s+", " ", plain)).strip()
    if len(plain) <= limit:
        return plain
    cut = plain[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def voice_mode() -> str:
    """polly or browser: LOGIOPS_VOICE, or polly when the agent runs on Bedrock and browser otherwise."""
    mode = os.environ.get("LOGIOPS_VOICE") or ("polly" if os.environ.get("LOGIOPS_AGENT_MODE", "bedrock") == "bedrock" else "browser")
    if mode not in ("polly", "browser"):
        raise RuntimeError("LOGIOPS_VOICE must be polly or browser")
    return mode


class PollyVoice:
    def __init__(
        self, db_path: str | Path, *, client: Any | None = None, enabled: bool | None = None,
        voice: str | None = None, engine: str | None = None, daily_chars: int | None = None,
        clock: Callable[[], datetime] | None = None, monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = voice_mode() == "polly" if enabled is None else enabled
        self.voice = voice or os.environ.get("LOGIOPS_POLLY_VOICE", DEFAULT_VOICE)
        self.engine = engine or os.environ.get("LOGIOPS_POLLY_ENGINE", DEFAULT_ENGINE)
        try:
            self.daily_chars = daily_chars if daily_chars is not None else int(
                os.environ.get("LOGIOPS_DAILY_SPEECH_CHARS", DEFAULT_DAILY_CHARS))
        except ValueError as exc:
            raise RuntimeError("LOGIOPS_DAILY_SPEECH_CHARS must be an integer") from exc
        self._client = client
        self._lock = threading.Lock()
        self._clock = clock or (lambda: datetime.now(LIMA))
        self._monotonic = monotonic
        self._resting_until = 0.0
        with connect(self.db_path) as connection:
            for statement in SCHEMA:
                connection.execute(statement)

    def config(self) -> dict[str, Any]:
        polly = self.enabled and self._monotonic() >= self._resting_until
        return {"engine": "polly" if polly else "browser", "voice": self.voice if polly else None, "fillers": list(FILLERS)}

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = boto3.client(
                    "polly", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                    config=Config(connect_timeout=3, read_timeout=10, retries={"mode": "standard", "max_attempts": 2}),
                )
            return self._client

    def _day(self) -> str:
        return self._clock().astimezone(LIMA).date().isoformat()

    def used(self) -> int:
        with connect(self.db_path) as connection:
            row = connection.execute("SELECT chars FROM speech_budget WHERE day = ?", (self._day(),)).fetchone()
        return row[0] if row else 0

    def _reserve(self, chars: int) -> str | None:
        day = self._day()
        with connect(self.db_path) as connection:
            connection.execute("INSERT INTO speech_budget (day, chars) VALUES (?, 0) ON CONFLICT(day) DO NOTHING", (day,))
            held = connection.execute(
                "UPDATE speech_budget SET chars = chars + ? WHERE day = ? AND chars + ? <= ?",
                (chars, day, chars, self.daily_chars),
            ).rowcount
        return day if held else None

    def _release(self, day: str, chars: int) -> None:
        with connect(self.db_path) as connection:
            connection.execute("UPDATE speech_budget SET chars = MAX(0, chars - ?) WHERE day = ?", (chars, day))

    def speak(self, text: str) -> bytes | None:
        """MP3 audio for the text, from the cache or Polly; None means: use the browser's voice."""
        line = speech_text(text)
        if not line or not self.enabled or self._monotonic() < self._resting_until:
            return None
        key = hashlib.sha256(f"{self.voice}|{self.engine}|{line}".encode()).hexdigest()
        with connect(self.db_path) as connection:
            row = connection.execute("SELECT audio FROM speech_cache WHERE key = ?", (key,)).fetchone()
        if row:
            return bytes(row[0])
        day = self._reserve(len(line))
        if day is None:
            return None
        try:
            response = self._get_client().synthesize_speech(
                Engine=self.engine, OutputFormat="mp3", Text=line, TextType="text", VoiceId=self.voice)
            audio = response["AudioStream"].read()
        except (BotoCoreError, ClientError) as exc:
            self._release(day, len(line))
            self._resting_until = self._monotonic() + REST_SECONDS
            code = exc.response.get("Error", {}).get("Code", "Unknown") if isinstance(exc, ClientError) else type(exc).__name__
            logger.warning("Polly failed (%s); using the browser's voice for %s s", code, REST_SECONDS)
            return None
        if not audio:
            self._release(day, len(line))
            return None
        with connect(self.db_path) as connection:
            connection.execute("INSERT OR REPLACE INTO speech_cache (key, audio, created_at) VALUES (?, ?, ?)",
                               (key, audio, self._clock().isoformat()))
        return audio

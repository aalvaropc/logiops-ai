"""Amazon Polly voice: cleaned text, one synthesis per text, a daily cap, and the browser as fallback."""

import asyncio
import io
from datetime import datetime

import boto3
import httpx
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from logiops.api import create_app
from logiops.scenario import LIMA
from logiops.voice import MAX_CHARS, PollyVoice, speech_text, voice_mode

BASE_URL = "http://127.0.0.1:8000"
MP3 = b"ID3\x04fake-mp3"


def polly():
    client = boto3.client("polly", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    return client, Stubber(client)


def audio_reply():
    return {"AudioStream": StreamingBody(io.BytesIO(MP3), len(MP3)), "ContentType": "audio/mpeg", "RequestCharacters": 10}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_speech_text_drops_markup_ids_and_links():
    text = ("## Plan\n\n**Recommend** `split-express`: see [the panel](https://example.com/x) "
            "and SHIP-421:0a1b2c3d4e:split-express:v1.\n- $120 extra\n| a | b |")
    assert speech_text(text) == "Plan Recommend split-express: see the panel and. $120 extra a b"


def test_long_replies_are_cut_at_a_sentence():
    text = " ".join(["The express carrier arrives on time." for _ in range(40)])
    cut = speech_text(text)
    assert len(cut) <= MAX_CHARS and cut.endswith("time.")
    words = speech_text("word " * 400)
    assert len(words) <= MAX_CHARS + 1 and words.endswith("…")


def test_polly_is_called_once_per_text_and_charged_against_the_day(tmp_path):
    client, stubber = polly()
    stubber.add_response("synthesize_speech", audio_reply(), {
        "Engine": "generative", "OutputFormat": "mp3", "Text": "Approved. $147.50 charged.", "TextType": "text", "VoiceId": "Ruth",
    })
    voice = PollyVoice(tmp_path / "v.sqlite3", client=client, enabled=True)
    with stubber:
        assert voice.speak("**Approved.** $147.50 charged.") == MP3
        assert voice.speak("Approved. $147.50 charged.") == MP3, "served from the cache"
    stubber.assert_no_pending_responses()
    assert voice.used() == len("Approved. $147.50 charged.")
    assert voice.config() == {"engine": "polly", "voice": "Ruth", "fillers": voice.config()["fillers"]}


def test_the_daily_cap_falls_back_without_calling_polly(tmp_path):
    client, stubber = polly()
    voice = PollyVoice(tmp_path / "v.sqlite3", client=client, enabled=True, daily_chars=10,
                       clock=lambda: datetime(2026, 10, 12, 9, tzinfo=LIMA))
    with stubber:
        assert voice.speak("This sentence is longer than ten characters.") is None
    assert voice.used() == 0


def test_a_polly_failure_releases_the_budget_and_rests(tmp_path):
    client, stubber = polly()
    stubber.add_client_error("synthesize_speech", service_error_code="AccessDeniedException", http_status_code=403)
    clock = Clock()
    voice = PollyVoice(tmp_path / "v.sqlite3", client=client, enabled=True, monotonic=clock)
    with stubber:
        assert voice.speak("Heads up on SHIP-421.") is None
        assert voice.speak("Another line.") is None, "resting: Polly is not called again"
    assert voice.used() == 0 and voice.config()["engine"] == "browser"
    clock.now += 301
    assert voice.config()["engine"] == "polly"


def test_voice_is_off_unless_polly_is_chosen(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGIOPS_VOICE", raising=False)
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")
    assert voice_mode() == "browser"
    assert PollyVoice(tmp_path / "v.sqlite3").speak("Hello") is None
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "bedrock")
    assert voice_mode() == "polly"
    monkeypatch.setenv("LOGIOPS_VOICE", "browser")
    assert voice_mode() == "browser"
    monkeypatch.setenv("LOGIOPS_VOICE", "loud")
    with pytest.raises(RuntimeError, match="LOGIOPS_VOICE"):
        voice_mode()


def test_the_api_serves_mp3_or_tells_the_page_to_use_the_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")
    client, stubber = polly()
    stubber.add_response("synthesize_speech", audio_reply())

    async def run(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
            return (await http.get("/voice/config")).json(), await http.post("/voice/speech", json={"text": "One moment."})

    on = create_app(tmp_path / "on.sqlite3", voice=PollyVoice(tmp_path / "on.sqlite3", client=client, enabled=True))
    with stubber:
        config, spoken = asyncio.run(run(on))
    assert config["engine"] == "polly" and config["voice"] == "Ruth" and config["fillers"]
    assert spoken.status_code == 200 and spoken.headers["content-type"] == "audio/mpeg" and spoken.content == MP3
    config, fallback = asyncio.run(run(create_app(tmp_path / "off.sqlite3")))
    assert config["engine"] == "browser" and fallback.status_code == 503 and fallback.json()["fallback"] == "browser"


def test_speech_has_its_own_per_minute_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "limit.sqlite3", agent_limit_per_minute=1)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                codes = [(await http.post("/voice/speech", json={"text": "Hi."})).status_code for _ in range(4)]
                agent = await http.post("/incidents/SHIP-421/agent/investigate", json={})
                return codes, agent.status_code

    codes, agent = asyncio.run(run())
    assert codes == [503, 503, 503, 429] and agent == 200

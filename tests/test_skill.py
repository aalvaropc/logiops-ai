"""The exception-desk Agent Skill: a valid SKILL.md, served over MCP and sent to the model unchanged."""

import asyncio
import re
import tarfile

import httpx
from botocore.stub import Stubber
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import AnyUrl

from logiops.agent import SYSTEM_PROMPT, investigate_with_bedrock
from logiops.api import create_app
from logiops.bedrock import BedrockConverse
from logiops.replay import ReplayConverse
from logiops.skill import SKILL_MIME_TYPE, SKILL_NAME, SKILL_PATH, SKILL_SHA256, SKILL_TEXT, SKILL_URI
from scripts.deploy_ec2 import package

BASE_URL = "http://127.0.0.1:8000"
FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def frontmatter():
    found = re.match(r"^---\n(.*?)\n---\n(.*)$", SKILL_TEXT, re.S)
    assert found, "SKILL.md starts with YAML frontmatter between --- lines"
    meta, block = {}, None
    for line in found.group(1).splitlines():
        pair = re.fullmatch(r"( *)([a-z-]+):(?: (.*))?", line)
        assert pair, line
        indent, key, value = pair.groups()
        value = (value or "").strip().strip('"')
        if indent:
            assert block is not None, line
            block[key] = value
        elif value:
            meta[key], block = value, None
        else:
            meta[key] = block = {}
    return meta, found.group(2)


def test_the_frontmatter_follows_the_agent_skills_format():
    meta, body = frontmatter()
    assert set(meta) <= FIELDS and {"name", "description"} <= set(meta)
    assert meta["name"] == SKILL_PATH.parent.name == SKILL_NAME
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
    assert 0 < len(meta["description"]) <= 1024 and "Use when" in meta["description"]
    assert 0 < len(meta["compatibility"]) <= 500
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in meta["metadata"].items())
    assert meta["metadata"]["mcp-resource"] == SKILL_URI
    assert len(body.splitlines()) < 500


def test_the_skill_names_only_real_tools_and_keeps_approval_human(tmp_path):
    from logiops.mcp_server import create_mcp_server
    from logiops.service import LogiOpsService

    tools = {tool.name for tool in asyncio.run(create_mcp_server(LogiOpsService(tmp_path / "tools.sqlite3")).list_tools())}
    named = set(re.findall(r"`([a-z_]+)`", SKILL_TEXT)) - {"operator_preferences", "preferred_plan_id", "default_plan_id"}
    assert named <= tools, named - tools
    assert "No tool approves" in SKILL_TEXT and "projected" in SKILL_TEXT and "Lima time" in SKILL_TEXT
    assert not re.search(r"SHIP-\d+:[0-9a-f]", SKILL_TEXT), "no internal plan ids"


class Recording(ReplayConverse):
    def __init__(self):
        self.skills = []

    async def converse(self, messages, system, tools, skill=None):
        self.skills.append(skill)
        return await super().converse(messages, system, tools, skill)


def test_the_resource_and_the_model_get_the_file_byte_for_byte(tmp_path):
    async def run():
        app = create_app(tmp_path / "skill.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = {str(item.uri): item for item in (await session.list_resources()).resources}
                        assert listed[SKILL_URI].mimeType == SKILL_MIME_TYPE == "text/markdown"
                        served = (await session.read_resource(AnyUrl(SKILL_URI))).contents[0].text
            client = Recording()
            result = await investigate_with_bedrock(app, client, "SHIP-421", "What should we do?")
        return served, client.skills, result

    served, sent, result = asyncio.run(run())
    on_disk = SKILL_PATH.read_bytes()
    assert served.encode() == on_disk
    assert sent and all(skill.encode() == on_disk for skill in sent)
    assert result["skill"] == {"name": SKILL_NAME, "uri": SKILL_URI, "sha256": SKILL_SHA256}


def test_bedrock_gets_the_skill_first_and_a_cache_point_after_the_prompt():
    import boto3

    client = boto3.client("bedrock-runtime", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    stubber = Stubber(client)
    reply = {
        "stopReason": "end_turn",
        "output": {"message": {"role": "assistant", "content": [{"text": "Done."}]}},
        "usage": {"inputTokens": 30, "outputTokens": 2, "totalTokens": 32, "cacheReadInputTokens": 1500, "cacheWriteInputTokens": 0},
        "metrics": {"latencyMs": 90},
    }
    messages = [{"role": "user", "content": [{"text": "Shipment: SHIP-421."}]}]
    tools = [{"toolSpec": {"name": "get_shipment", "description": "Read a shipment.", "inputSchema": {"json": {"type": "object"}}}}]
    stubber.add_response("converse", reply, {
        "modelId": "global.anthropic.claude-sonnet-4-6", "messages": messages,
        "system": [{"text": SKILL_TEXT}, {"text": SYSTEM_PROMPT}, {"cachePoint": {"type": "default"}}],
        "toolConfig": {"tools": tools}, "inferenceConfig": {"maxTokens": 2048, "temperature": 0.2},
    })
    stubber.add_response("converse", reply, {
        "modelId": "global.anthropic.claude-sonnet-4-6", "messages": messages,
        "system": [{"text": SYSTEM_PROMPT}],
        "toolConfig": {"tools": tools}, "inferenceConfig": {"maxTokens": 2048, "temperature": 0.2},
    })
    bedrock = BedrockConverse(client=client, model_id="global.anthropic.claude-sonnet-4-6")
    with stubber:
        with_skill = asyncio.run(bedrock.converse(messages, SYSTEM_PROMPT, tools, skill=SKILL_TEXT))
        asyncio.run(bedrock.converse(messages, SYSTEM_PROMPT, tools))
    assert with_skill["usage"]["cacheReadInputTokens"] == 1500


def test_the_release_and_the_image_ship_the_skill():
    from pathlib import Path

    archive, _ = package()
    with tarfile.open(archive, "r:gz") as release:
        member = release.extractfile(f"skills/{SKILL_NAME}/SKILL.md")
        assert member is not None and member.read() == SKILL_PATH.read_bytes()
    ignored = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text().split()
    assert not {"skills", "skills/", "*.md"} & set(ignored)

"""MCP prompts, argument completion and the incident resource template, through the official client."""

import asyncio
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.types import PromptReference, ResourceTemplateReference
from pydantic import AnyUrl

from logiops.api import create_app
from logiops.scenario import INCIDENT_IDS
from logiops.skill import SKILL_TEXT, SKILL_URI

BASE_URL = "http://127.0.0.1:8000"


def run_session(tmp_path, work):
    async def run():
        app = create_app(tmp_path / "prompts.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        return await work(session, initialized, http)
    return asyncio.run(run())


def test_the_server_declares_prompts_resources_and_completions(tmp_path):
    async def work(_session, initialized, _http):
        return initialized.capabilities

    capabilities = run_session(tmp_path, work)
    assert capabilities.prompts is not None and capabilities.resources is not None
    assert capabilities.completions is not None


def test_prompts_embed_the_skill_and_name_the_incident(tmp_path):
    async def work(session, _initialized, _http):
        listed = {prompt.name: prompt for prompt in (await session.list_prompts()).prompts}
        briefing = await session.get_prompt("morning_briefing")
        investigate = await session.get_prompt("investigate_incident", {"shipment_id": "case 433"})
        with pytest.raises(McpError) as unknown:
            await session.get_prompt("investigate_incident", {"shipment_id": "SHIP-999"})
        return listed, briefing, investigate, unknown.value.error.message

    listed, briefing, investigate, unknown = run_session(tmp_path, work)
    assert set(listed) == {"morning_briefing", "investigate_incident"}
    assert listed["morning_briefing"].title == "Morning briefing" and not listed["morning_briefing"].arguments
    [argument] = listed["investigate_incident"].arguments
    assert argument.name == "shipment_id" and argument.required and "SHIP-433" in argument.description
    for prompt in (briefing, investigate):
        skill, ask = prompt.messages
        assert skill.role == ask.role == "user"
        assert skill.content.type == "resource" and str(skill.content.resource.uri) == SKILL_URI
        assert skill.content.resource.text == SKILL_TEXT
    assert "list_incidents" in briefing.messages[1].content.text
    assert "SHIP-433" in investigate.messages[1].content.text and "Do not approve" in investigate.messages[1].content.text
    assert "Unknown incident" in unknown and "SHIP-421" in unknown


def test_incident_ids_complete_for_the_prompt_and_the_template(tmp_path):
    async def work(session, _initialized, _http):
        prompt = PromptReference(type="ref/prompt", name="investigate_incident")
        template = ResourceTemplateReference(type="ref/resource", uri="incident://{shipment_id}")
        return {
            "empty": await session.complete(prompt, {"name": "shipment_id", "value": ""}),
            "number": await session.complete(prompt, {"name": "shipment_id", "value": "43"}),
            "prefix": await session.complete(template, {"name": "shipment_id", "value": "ship-46"}),
            "spoken": await session.complete(template, {"name": "shipment_id", "value": "case 45"}),
            "other": await session.complete(prompt, {"name": "order_id", "value": "ORD"}),
        }

    results = run_session(tmp_path, work)
    assert sorted(results["empty"].completion.values) == sorted(INCIDENT_IDS)
    assert results["empty"].completion.hasMore is False
    assert results["number"].completion.values == ["SHIP-433"]
    assert results["prefix"].completion.values == ["SHIP-460"]
    assert results["spoken"].completion.values == ["SHIP-452"]
    assert results["other"].completion.values == []


def test_the_incident_template_reads_one_incident_as_json(tmp_path):
    async def work(session, _initialized, http):
        templates = (await session.list_resource_templates()).resourceTemplates
        before = await session.read_resource(AnyUrl("incident://433"))
        await session.call_tool("investigate_incident", {"shipment_id": "SHIP-433"})
        after = await session.read_resource(AnyUrl("incident://SHIP-433"))
        with pytest.raises(McpError):
            await session.read_resource(AnyUrl("incident://SHIP-999"))
        return templates, before.contents[0], after.contents[0]

    templates, before, after = run_session(tmp_path, work)
    [template] = [item for item in templates if item.uriTemplate == "incident://{shipment_id}"]
    assert template.mimeType == "application/json" and template.title == "Incident record"
    assert before.mimeType == "application/json"
    record = json.loads(before.text)
    assert record["incident"]["incident_id"] == record["shipment"]["id"] == "SHIP-433"
    assert record["plans"] == [] and record["approval"] is None and record["executions"] == []
    investigated = json.loads(after.text)
    assert len(investigated["plans"]) == 4
    assert {plan["source_version"] for plan in investigated["plans"]} == {investigated["source_version"]}

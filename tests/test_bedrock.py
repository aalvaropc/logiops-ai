"""Converse wire format, validated against the real botocore model, without a paid call."""

import asyncio

import boto3
import pytest
from botocore.stub import Stubber

from logiops.bedrock import BedrockConverse, BedrockError


MESSAGES = [
    {"role": "user", "content": [{"text": "What is happening with SHIP-421?"}]},
    {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": "1", "name": "get_shipment", "input": {"shipment_id": "SHIP-421"}}}
    ]},
    {"role": "user", "content": [
        {"toolResult": {"toolUseId": "1", "status": "success", "content": [
            {"json": {"id": "SHIP-421", "selected_plan_id": None, "fulfillments": [], "units": 20}}
        ]}}
    ]},
]
TOOLS = [{"toolSpec": {
    "name": "get_shipment", "description": "Read a shipment",
    "inputSchema": {"json": {"type": "object", "properties": {"shipment_id": {"type": "string"}}}},
}}]


def stubbed_client():
    client = boto3.client(
        "bedrock-runtime", region_name="us-east-1",
        aws_access_key_id="testing", aws_secret_access_key="testing",
    )
    return client, Stubber(client)


def test_converse_sends_messages_tools_and_system_prompt():
    client, stubber = stubbed_client()
    stubber.add_response(
        "converse",
        {
            "stopReason": "end_turn",
            "output": {"message": {"role": "assistant", "content": [{"text": "Delayed 12 h."}]}},
            "usage": {"inputTokens": 10, "outputTokens": 4, "totalTokens": 14},
            "metrics": {"latencyMs": 100},
        },
        {
            "modelId": "global.anthropic.claude-sonnet-4-6",
            "messages": MESSAGES,
            "system": [{"text": "Investigate"}],
            "toolConfig": {"tools": TOOLS},
            "inferenceConfig": {"maxTokens": 2048, "temperature": 0.2},
        },
    )
    with stubber:
        result = asyncio.run(
            BedrockConverse(client=client, model_id="global.anthropic.claude-sonnet-4-6")
            .converse(MESSAGES, "Investigate", TOOLS)
        )
    assert result["stopReason"] == "end_turn"
    assert result["usage"]["inputTokens"] == 10
    assert "ResponseMetadata" not in result


def test_converse_errors_only_expose_the_error_code():
    client, stubber = stubbed_client()
    stubber.add_client_error(
        "converse", service_error_code="AccessDeniedException",
        service_message="account 123456789012 is not authorized", http_status_code=403,
    )
    with stubber, pytest.raises(BedrockError) as raised:
        asyncio.run(BedrockConverse(client=client).converse(MESSAGES[:1], "Investigate", TOOLS))
    assert "AccessDeniedException" in str(raised.value)
    assert "123456789012" not in str(raised.value)

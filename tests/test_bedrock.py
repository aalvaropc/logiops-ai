"""Converse CLI wire format without sending a paid AWS request."""

import asyncio
import json

from logiops.bedrock import AwsCliConverse


def test_aws_cli_receives_converse_messages_and_tool_schema(monkeypatch):
    captured = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return json.dumps({
                "stopReason": "tool_use",
                "output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "1", "name": "get_shipment", "input": {"shipment_id": "SHIP-421"}}}
                ]}},
            }).encode(), b""

    async def fake_exec(*command, **kwargs):
        captured["command"] = command
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    messages = [{"role": "user", "content": [{"text": "What is happening with SHIP-421?"}]}]
    tools = [{"toolSpec": {
        "name": "get_shipment", "description": "Read a shipment",
        "inputSchema": {"json": {"type": "object", "properties": {"shipment_id": {"type": "string"}}}},
    }}]
    result = asyncio.run(AwsCliConverse().converse(messages, "Investigate", tools))
    assert result["stopReason"] == "tool_use"
    command = captured["command"]
    assert command[:3] == ("aws", "bedrock-runtime", "converse")
    assert json.loads(command[command.index("--messages") + 1]) == messages
    assert json.loads(command[command.index("--tool-config") + 1]) == {"tools": tools}
    assert json.loads(command[command.index("--system") + 1]) == [{"text": "Investigate"}]

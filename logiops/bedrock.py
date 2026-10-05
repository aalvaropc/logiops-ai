"""AWS Bedrock Converse adapter using the already configured AWS CLI login."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any


class BedrockError(Exception):
    pass


class AwsCliConverse:
    def __init__(self, *, region: str | None = None, model_id: str | None = None, timeout: int = 90) -> None:
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.model_id = model_id or os.environ.get(
            "BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"
        )
        self.timeout = timeout

    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        command = [
            "aws", "bedrock-runtime", "converse",
            "--region", self.region,
            "--model-id", self.model_id,
            "--messages", json.dumps(messages),
            "--system", json.dumps([{"text": system}]),
            "--tool-config", json.dumps({"tools": tools}),
            "--inference-config", json.dumps({"maxTokens": 1400, "temperature": 0.2}),
            "--output", "json",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except OSError as exc:
            raise BedrockError("AWS CLI is unavailable; install aws and sign in with aws login") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise BedrockError("Bedrock request timed out") from exc
        if process.returncode != 0:
            # The CLI can include account details in stderr, so do not relay it to HTTP clients.
            raise BedrockError("Bedrock Converse failed; check AWS login, model access, and region")
        try:
            response = json.loads(stdout)
            if not isinstance(response, dict) or "stopReason" not in response:
                raise ValueError("Missing stopReason")
            return response
        except (json.JSONDecodeError, ValueError) as exc:
            raise BedrockError("Bedrock returned an invalid Converse response") from exc

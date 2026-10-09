"""Amazon Bedrock Converse adapter using boto3 and the default credential chain."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)


DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"


class BedrockError(Exception):
    pass


class BedrockConverse:
    """Calls Converse with SDK retries and timeouts.

    Credentials come from boto3's default chain: an `aws login` session on a
    laptop, or the instance role on EC2. Nothing is passed on a command line,
    so message size is limited only by the model, not by the OS.
    """

    def __init__(
        self,
        *,
        region: str | None = None,
        model_id: str | None = None,
        read_timeout: int = 40,
        max_tokens: int = 2048,
        client: Any | None = None,
    ) -> None:
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
        self.read_timeout = read_timeout
        self.max_tokens = max_tokens
        self._client = client
        # boto3 clients are thread-safe once built; building one on the shared default session is not,
        # and the app shares one instance across requests that call it from worker threads.
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        with self._lock:
            return self._build_client()

    def _build_client(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    connect_timeout=5,
                    read_timeout=self.read_timeout,
                    # Adaptive mode backs off on ThrottlingException before we give up.
                    retries={"mode": "adaptive", "max_attempts": 4},
                ),
            )
        return self._client

    def _call(self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        return self._get_client().converse(
            modelId=self.model_id,
            messages=messages,
            system=[{"text": system}],
            toolConfig={"tools": tools},
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0.2},
        )

    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        try:
            response = await asyncio.to_thread(self._call, messages, system, tools)
        except NoCredentialsError as exc:
            raise BedrockError(
                "AWS credentials are not configured; sign in with aws login or attach an instance role"
            ) from exc
        except ClientError as exc:
            # Only the error code is relayed; messages can include account details.
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            raise BedrockError(f"Bedrock Converse failed ({code}); check model access and region") from exc
        except (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError) as exc:
            raise BedrockError("Bedrock request timed out or could not connect") from exc
        except BotoCoreError as exc:
            # The class name (e.g. MissingDependencyException) says what to fix without leaking details.
            raise BedrockError(f"Bedrock Converse failed ({type(exc).__name__})") from exc
        if not isinstance(response, dict) or "stopReason" not in response:
            raise BedrockError("Bedrock returned an invalid Converse response")
        response.pop("ResponseMetadata", None)
        return response

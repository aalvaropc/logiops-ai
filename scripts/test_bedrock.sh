#!/usr/bin/env bash
# Smoke test: Amazon Bedrock Converse API with tool calling.
# Requires: `aws login` already done (no static access keys used).
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
MODEL_ID="${BEDROCK_MODEL_ID:-global.anthropic.claude-sonnet-4-6}"

TOOL_CONFIG='{"tools":[{"toolSpec":{"name":"get_shipment","description":"Get shipment status by id","inputSchema":{"json":{"type":"object","properties":{"shipment_id":{"type":"string"}},"required":["shipment_id"]}}}}]}'

aws bedrock-runtime converse \
  --region "$REGION" \
  --model-id "$MODEL_ID" \
  --messages '[{"role":"user","content":[{"text":"What is happening with shipment SHIP-421?"}]}]' \
  --tool-config "$TOOL_CONFIG" \
  --inference-config '{"maxTokens":300,"temperature":0.2}' \
  --query '{stop:stopReason,usage:usage,out:output.message.content}' \
  --output json

#!/usr/bin/env bash
# Start the demo in replay mode (no credentials, zero tokens) for a rehearsal or a recording
# take. It frees the port first (by port, never by process name), resets nothing until the
# server is up, then prints the URL and the phrases for the video.
#
#   scripts/rehearse.sh [port]        (default 8000; Ctrl-C stops the server)
set -euo pipefail

port=${1:-8000}
[[ $port =~ ^[0-9]+$ ]] || { echo "Port must be a number" >&2; exit 2; }
cd "$(dirname "$0")/.."

pid=$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -n 1 || true)
if [ -n "$pid" ]; then
  echo "Port $port is in use by pid $pid; stopping it."
  kill "$pid"
  sleep 1
fi

db=$(mktemp -d "${TMPDIR:-/tmp}/logiops-rehearse.XXXXXX")
trap 'kill "$server" 2>/dev/null || true' EXIT
env -u LOGIOPS_ACCESS_TOKEN -u LOGIOPS_PUBLIC -u LOGIOPS_PUBLIC_HOST -u LOGIOPS_SANDBOX_HOST \
  LOGIOPS_AGENT_MODE=replay LOGIOPS_DB_PATH="$db/rehearse.sqlite3" \
  uv run uvicorn logiops.api:app --host 127.0.0.1 --port "$port" &
server=$!
curl -fsS --retry 30 --retry-delay 1 --retry-all-errors -o /dev/null "http://127.0.0.1:$port/healthz"

cat <<TEXT

Replay demo ready: http://127.0.0.1:$port/demo
(Open it on 127.0.0.1 or localhost; the MCP App card needs the other name as its sandbox.)

Say or type, in order:
  1. What's happening with shipment SHIP-421, and which plan should we choose?
  2. How much is the reroute?
  3. Approve the recommended plan.
  4. Execute it.
Then "Reset all incidents and preferences", ask again, approve, set stock to 11, Apply, and "Execute it".

Replay shows "replay mode" and 0 tokens. For the real take, start without LOGIOPS_AGENT_MODE.
Press Ctrl-C to stop.
TEXT
wait "$server"

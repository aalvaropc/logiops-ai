#!/usr/bin/env bash
# Prove the repository works from scratch: clone a ref into a temporary directory, then
# install, test, build the Docker image, run it in replay mode and call the MCP check.
#
#   scripts/clean_room.sh [ref]      (default: HEAD of this checkout)
#
# Needs git, uv, and Docker or Podman. Nothing outside the temporary directory is touched.
set -euo pipefail

ref=${1:-HEAD}
repo=$(git rev-parse --show-toplevel)
sha=$(git -C "$repo" rev-parse --short "$ref")
work=$(mktemp -d "${TMPDIR:-/tmp}/clean-room.XXXXXX")
runtime=$(command -v docker || command -v podman || true)
container=""
cleanup() {
  [ -z "$container" ] || "$runtime" rm -f "$container" >/dev/null 2>&1 || true
  # Only ever remove the directory created above, never a variable that could be empty.
  case "$work" in "${TMPDIR:-/tmp}"/clean-room.*) rm -rf -- "$work" ;; esac
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$*"; }
step "clone $sha"
git clone -q "$repo" "$work/repo"
git -C "$work/repo" checkout -q "$sha"
cd "$work/repo"

step "install"
uv sync --frozen --extra dev

step "tests (environment stripped)"
env -u LOGIOPS_ACCESS_TOKEN -u LOGIOPS_AGENT_MODE -u LOGIOPS_PUBLIC -u LOGIOPS_PUBLIC_HOST \
    -u LOGIOPS_SANDBOX_HOST -u LOGIOPS_TRUST_CLOUDFRONT uv run pytest -q

if [ -z "$runtime" ]; then
  echo "No Docker or Podman found: skipping the container steps." >&2
  exit 0
fi
step "container build and run (replay mode)"
"$runtime" build -q -t clean-room-logiops . >/dev/null
port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
container=$("$runtime" run -d -p "127.0.0.1:$port:8000" clean-room-logiops)
curl -fsS --retry 30 --retry-delay 1 --retry-all-errors -o /dev/null "http://127.0.0.1:$port/healthz"

step "MCP check against the container"
uv run python scripts/check_mcp.py "http://127.0.0.1:$port/mcp"

step "headless walkthrough against the container"
uv run python scripts/rehearse_api.py --url "http://127.0.0.1:$port"
printf '\nClean-room run of %s passed.\n' "$sha"

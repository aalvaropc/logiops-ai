"""Store a fresh demo token in SSM SecureString without exposing it in CLI args."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_SECRET = ROOT / ".secrets" / "access-token"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--name", default="/logiops-ai/access-token")
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args()
    if LOCAL_SECRET.exists() and not args.rotate:
        raise SystemExit("Local token exists; pass --rotate to replace it")

    token = secrets.token_hex(32)
    payload = {"Name": args.name, "Type": "SecureString", "Value": token, "Overwrite": args.rotate}
    with tempfile.NamedTemporaryFile(mode="w", prefix="logiops-ssm-", suffix=".json", delete=False) as tmp:
        os.chmod(tmp.name, 0o600)
        json.dump(payload, tmp)
        temp_path = Path(tmp.name)
    try:
        subprocess.run(
            ["aws", "--region", args.region, "ssm", "put-parameter", "--cli-input-json", f"file://{temp_path}"],
            check=True, stdout=subprocess.DEVNULL,
        )
    finally:
        temp_path.unlink(missing_ok=True)

    LOCAL_SECRET.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(LOCAL_SECRET, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as secret_file:
        secret_file.write(token + "\n")
    os.chmod(LOCAL_SECRET, 0o600)
    print(f"Token stored in SSM {args.name} and locally at {LOCAL_SECRET} (mode 0600)")


if __name__ == "__main__":
    main()

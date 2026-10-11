"""Create or reset the judges' demo user in the Cognito user pool.

Run it after `terraform apply`. The password is generated here, set as permanent, and written only
to .secrets/demo-user (mode 0600); it is never printed.

    uv run python scripts/create_demo_user.py              # the user "judge"
    uv run python scripts/create_demo_user.py --username reviewer
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import subprocess
from pathlib import Path
from typing import Any

import boto3

ROOT = Path(__file__).resolve().parents[1]


def terraform_output(name: str) -> str:
    return subprocess.run(
        ["terraform", f"-chdir={ROOT / 'infra' / 'amazon'}", "output", "-raw", name],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def new_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value):
            return value


def create(client: Any, pool_id: str, username: str, root: Path = ROOT) -> Path:
    try:
        client.admin_create_user(UserPoolId=pool_id, Username=username, MessageAction="SUPPRESS")
    except client.exceptions.UsernameExistsException:
        pass
    password = new_password()
    client.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)
    folder = root / ".secrets"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / "demo-user"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump({"username": username, "password": password, "user_pool_id": pool_id}, handle)
    os.chmod(path, 0o600)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", default="judge")
    args = parser.parse_args()
    client = boto3.client("cognito-idp", region_name=terraform_output("aws_region"))
    path = create(client, terraform_output("cognito_user_pool_id"), args.username)
    print(f"Demo user {args.username!r} is ready; its password is in {path.relative_to(ROOT)} (not printed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

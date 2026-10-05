"""Package the pinned app and deploy it through S3 and Systems Manager."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "amazon"


def package() -> tuple[Path, str]:
    files = [ROOT / "pyproject.toml", ROOT / "uv.lock", *sorted((ROOT / "logiops").glob("*.py"))]
    if not all(path.is_file() for path in files):
        raise RuntimeError("The app, pyproject.toml, or uv.lock is missing")
    output = Path(tempfile.gettempdir()) / "logiops-ai-release.tar.gz"
    with output.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for path in files:
                data = path.read_bytes()
                info = tarfile.TarInfo(path.relative_to(ROOT).as_posix())
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    final = output.with_name(f"logiops-ai-{digest}.tar.gz")
    output.replace(final)
    return final, digest


def command(*args: str) -> dict[str, Any]:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def terraform_outputs() -> dict[str, str]:
    raw = command("terraform", f"-chdir={INFRA}", "output", "-json")
    return {key: value["value"] for key, value in raw.items()}


def wait_for_ssm(region: str, instance_id: str) -> None:
    for _ in range(120):
        try:
            described = command(
                "aws", "--region", region, "ssm", "describe-instance-information",
                "--filters", f"Key=InstanceIds,Values={instance_id}", "--output", "json",
            )
            if any(
                item.get("PingStatus") == "Online"
                for item in described.get("InstanceInformationList", [])
            ):
                return
        except subprocess.CalledProcessError:
            pass
        time.sleep(5)
    raise RuntimeError(f"Instance {instance_id} did not become available in Systems Manager")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args()
    archive, digest = package()
    print(f"Release: {archive} (sha256 {digest})")
    if args.package_only:
        return

    outputs = terraform_outputs()
    region = outputs["aws_region"]
    bucket = outputs["release_bucket"]
    instance_id = outputs["instance_id"]
    host = outputs["cloudfront_domain"]
    if not re.fullmatch(r"[a-z0-9.-]+", bucket + host) or not re.fullmatch(r"i-[a-f0-9]+", instance_id):
        raise RuntimeError("Unexpected Terraform output")
    uri = f"s3://{bucket}/releases/{digest}.tar.gz"
    subprocess.run(["aws", "--region", region, "s3", "cp", str(archive), uri, "--only-show-errors"], check=True)
    wait_for_ssm(region, instance_id)

    remote_command = (
        "for attempt in $(seq 1 120); do "
        "test -x /usr/local/sbin/logiops-deploy && break; sleep 5; done; "
        f"/usr/local/sbin/logiops-deploy {uri} {digest} {host}"
    )
    sent = command(
        "aws", "--region", region, "ssm", "send-command",
        "--instance-ids", instance_id,
        "--document-name", "AWS-RunShellScript",
        "--parameters", json.dumps({"commands": [remote_command]}),
        "--output", "json",
    )
    command_id = sent["Command"]["CommandId"]
    for _ in range(120):
        time.sleep(5)
        try:
            invocation = command(
                "aws", "--region", region, "ssm", "get-command-invocation",
                "--command-id", command_id, "--instance-id", instance_id, "--output", "json",
            )
        except subprocess.CalledProcessError:
            continue
        status = invocation["Status"]
        if status == "Success":
            print(f"Deployment succeeded: https://{host}/healthz")
            print(f"MCP: https://{host}/mcp")
            return
        if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
            raise RuntimeError(f"SSM deployment {command_id} finished with {status}; inspect it in AWS")
    raise RuntimeError(f"SSM deployment {command_id} did not finish within 10 minutes")


if __name__ == "__main__":
    main()

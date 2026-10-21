import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def verify(upstream=False):
    manifest = json.loads((ROOT / "vendor/mcp-apps-web-host.json").read_text())
    if manifest["repository"] != "aalvaropc/mcp-apps-web-host" or not re.fullmatch(r"[a-f0-9]{40}", manifest["commit"]):
        raise ValueError("The vendor source must use the expected repository and an immutable commit")
    for item in manifest["files"]:
        path = (ROOT / item["path"]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Vendor path escapes the checkout")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"Vendor hash mismatch: {item['path']}")
        if upstream:
            url = f"https://raw.githubusercontent.com/{manifest['repository']}/{manifest['commit']}/{item['source']}"
            with urlopen(url, timeout=30) as response:
                if response.read() != data:
                    raise ValueError(f"Vendor differs from upstream: {item['path']}")
    print(f"Verified {len(manifest['files'])} vendored files at {manifest['commit']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", action="store_true")
    verify(parser.parse_args().upstream)

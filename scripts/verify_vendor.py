
import argparse
import hashlib
import json
import re
import time
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "vendor/mcp-apps-web-host.json"
REPOSITORY = "aalvaropc/mcp-apps-web-host"
ATTEMPTS = 4
FIRST_DELAY = 2.0


def read_url(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def fetch(url, read=read_url, sleep=time.sleep, attempts=ATTEMPTS, delay=FIRST_DELAY):
    for attempt in range(1, attempts + 1):
        try:
            return read(url)
        except HTTPError as error:
            if error.code < 500 and error.code != 429:
                raise
            if attempt == attempts:
                raise
        except OSError:
            if attempt == attempts:
                raise
        sleep(delay)
        delay *= 2


def verify(upstream=False, root=ROOT, read=fetch):
    root = Path(root).resolve()
    manifest = json.loads((root / MANIFEST).read_text())
    if manifest["repository"] != REPOSITORY or not re.fullmatch(r"[a-f0-9]{40}", manifest["commit"]):
        raise ValueError("The vendor source must use the expected repository and an immutable commit")
    for item in manifest["files"]:
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Vendor path escapes the checkout")
        source = PurePosixPath(item["source"])
        if source.is_absolute() or ".." in source.parts:
            raise ValueError("Vendor source escapes the upstream checkout")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"Vendor hash mismatch: {item['path']}")
        if upstream:
            url = f"https://raw.githubusercontent.com/{manifest['repository']}/{manifest['commit']}/{item['source']}"
            try:
                fetched = read(url)
            except OSError as error:
                raise ValueError(f"Could not read upstream {url}: {error}") from error
            if fetched != data:
                raise ValueError(f"Vendor differs from upstream: {item['path']}")
    print(f"Verified {len(manifest['files'])} vendored files at {manifest['commit']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", action="store_true")
    verify(parser.parse_args().upstream)

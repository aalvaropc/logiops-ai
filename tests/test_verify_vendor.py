"""verify_vendor.py pins the vendored host to an upstream commit and refuses anything that drifts from it."""

import hashlib
import json
from urllib.error import HTTPError, URLError

import pytest

from scripts.verify_vendor import ATTEMPTS, FIRST_DELAY, fetch, verify

COMMIT = "a" * 40
BODY = b"export const host = 1;\n"


def checkout(tmp_path, *, path="app/host.js", source="src/host.js", sha256=None, commit=COMMIT, repository="aalvaropc/mcp-apps-web-host"):
    root = tmp_path / "checkout"
    (root / "vendor").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "app/host.js").write_bytes(BODY)
    (tmp_path / "outside.js").write_bytes(BODY)
    entry = {"source": source, "path": path, "sha256": sha256 or hashlib.sha256(BODY).hexdigest()}
    (root / "vendor/mcp-apps-web-host.json").write_text(json.dumps({"repository": repository, "commit": commit, "version": "1.3.0", "files": [entry]}))
    return root


def http_error(code):
    return HTTPError("https://raw.githubusercontent.com/x", code, "failure", None, None)


def test_the_committed_vendor_files_match_their_manifest():
    verify()


def test_a_matching_copy_passes_and_is_compared_with_upstream(tmp_path):
    root = checkout(tmp_path)
    verify(root=root)
    urls = []

    def same(url):
        urls.append(url)
        return BODY

    verify(upstream=True, root=root, read=same)
    assert urls == [f"https://raw.githubusercontent.com/aalvaropc/mcp-apps-web-host/{COMMIT}/src/host.js"]
    with pytest.raises(ValueError, match="differs from upstream"):
        verify(upstream=True, root=root, read=lambda url: BODY + b"// edited\n")


def test_a_different_hash_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="hash mismatch"):
        verify(root=checkout(tmp_path, sha256="0" * 64))


@pytest.mark.parametrize("path", ["../outside.js", "app/../../outside.js", "/etc/passwd"])
def test_a_path_that_escapes_the_checkout_is_rejected(tmp_path, path):
    with pytest.raises(ValueError, match="escapes the checkout"):
        verify(root=checkout(tmp_path, path=path))


@pytest.mark.parametrize("source", ["../src/host.js", "/src/host.js", "src/../../host.js"])
def test_an_upstream_source_that_escapes_is_rejected(tmp_path, source):
    with pytest.raises(ValueError, match="escapes the upstream"):
        verify(root=checkout(tmp_path, source=source))


@pytest.mark.parametrize("override", [{"commit": "main"}, {"commit": "A" * 40}, {"commit": "a" * 39}, {"repository": "someone/else"}])
def test_only_the_expected_repository_at_an_immutable_commit_is_accepted(tmp_path, override):
    with pytest.raises(ValueError, match="immutable commit"):
        verify(root=checkout(tmp_path, **override))


def test_transient_failures_are_retried_with_a_doubling_delay():
    answers = [URLError("reset"), http_error(503), http_error(429), BODY]
    pauses = []

    def read(url):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert fetch("https://example.test/a", read=read, sleep=pauses.append) == BODY
    assert pauses == [FIRST_DELAY, FIRST_DELAY * 2, FIRST_DELAY * 4]


def test_a_missing_file_is_not_retried():
    calls = []
    pauses = []

    def read(url):
        calls.append(url)
        raise http_error(404)

    with pytest.raises(HTTPError):
        fetch("https://example.test/a", read=read, sleep=pauses.append)
    assert len(calls) == 1 and pauses == []


def test_retries_are_bounded_and_the_failure_is_reported(tmp_path):
    calls = []
    pauses = []

    def read(url):
        calls.append(url)
        raise URLError("unreachable")

    with pytest.raises(URLError):
        fetch("https://example.test/a", read=read, sleep=pauses.append)
    assert len(calls) == ATTEMPTS and len(pauses) == ATTEMPTS - 1

    def down(url):
        raise URLError("unreachable")

    with pytest.raises(ValueError, match="Could not read upstream"):
        verify(upstream=True, root=checkout(tmp_path), read=down)

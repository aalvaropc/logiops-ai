import httpx
import pytest

from scripts.verify_remote import verification_state


def test_failed_verification_cleans_memory_and_resets_the_demo():
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(respond), base_url="https://demo.test") as client:
        with pytest.raises(RuntimeError, match="investigation failed"):
            with verification_state(client):
                raise RuntimeError("investigation failed")
    assert calls == [("POST", "/demo/reset"), ("DELETE", "/memory"), ("POST", "/demo/reset")]


def test_reset_is_attempted_even_if_memory_cleanup_fails():
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(503 if request.method == "DELETE" else 200)

    with httpx.Client(transport=httpx.MockTransport(respond), base_url="https://demo.test") as client:
        with pytest.raises(httpx.HTTPStatusError):
            with verification_state(client):
                pass
    assert calls == ["/demo/reset", "/memory", "/demo/reset"]

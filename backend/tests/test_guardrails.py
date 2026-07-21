"""Guardrail checks: input caps and rate limiting."""
from fastapi.testclient import TestClient

from app.main import app
from app.rate_limit import CHAT_LIMIT_PER_MINUTE, _hits

client = TestClient(app)


def test_rejects_content_over_length_cap():
    huge = "x" * 8001
    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": huge}]},
    )
    assert response.status_code == 422


def test_rejects_too_many_messages():
    messages = [{"role": "user", "content": "hi"}] * 41
    response = client.post("/api/chat", json={"messages": messages})
    assert response.status_code == 422


def test_rate_limiter_returns_429_after_limit(monkeypatch):
    _hits.clear()

    async def _instant_stream(_messages):
        if False:
            yield ""

    monkeypatch.setattr("app.main.stream_chat_response", _instant_stream)

    payload = {"messages": [{"role": "user", "content": "hi"}]}
    for _ in range(CHAT_LIMIT_PER_MINUTE):
        assert client.post("/api/chat", json=payload).status_code == 200

    over = client.post("/api/chat", json=payload)
    assert over.status_code == 429

"""Tests for GET /api/activity/{id} — the 'click a card for more' endpoint.

The path param is always the opaque token from the `activity:<token>` link
(app/activity_ref.py) — the raw Mongo `_id` never reaches the browser, so
these tests exercise the endpoint the way the frontend actually calls it:
with a real, obfuscated token, not the underlying hex id.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.activity_ref import obfuscate_activity_id
from app.main import app, settings

client = TestClient(app)

REAL_ID = "66f1a2b3c4d5e6f7a8b9c0d1"
TOKEN = obfuscate_activity_id(REAL_ID)


def test_503_when_mcp_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "mcp_server_url", "")
    response = client.get(f"/api/activity/{TOKEN}")
    assert response.status_code == 503


def test_404_when_token_is_malformed(monkeypatch):
    # Not a valid token at all (wrong shape/charset) - never even reaches the
    # catalog. Also covers a stale plain hex id from before this feature shipped.
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")
    response = client.get("/api/activity/not-a-real-token!!")
    assert response.status_code == 404


def test_404_when_activity_not_found(monkeypatch):
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")

    async def fake_get_activity_by_id(identifier):
        return {"result": json.dumps({"success": False, "data": None})}

    monkeypatch.setattr("app.main.get_activity_by_id", fake_get_activity_by_id)
    response = client.get(f"/api/activity/{TOKEN}")
    assert response.status_code == 404


def test_200_returns_activity_data_after_resolving_the_token(monkeypatch):
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")

    async def fake_get_activity_by_id(identifier):
        # The endpoint must hand the catalog the REAL id, recovered from the
        # token - never the token itself.
        assert identifier == REAL_ID
        return {"result": json.dumps({"success": True, "data": {"_id": REAL_ID, "title": "Jumpin Heights"}})}

    monkeypatch.setattr("app.main.get_activity_by_id", fake_get_activity_by_id)
    response = client.get(f"/api/activity/{TOKEN}")
    assert response.status_code == 200
    assert response.json() == {"_id": REAL_ID, "title": "Jumpin Heights"}

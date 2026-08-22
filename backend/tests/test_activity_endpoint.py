"""Tests for GET /api/activity/{id} — the 'click a card for more' endpoint."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app, settings

client = TestClient(app)


def test_503_when_mcp_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "mcp_server_url", "")
    response = client.get("/api/activity/abc123")
    assert response.status_code == 503


def test_404_when_activity_not_found(monkeypatch):
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")

    async def fake_get_activity_by_id(identifier):
        return {"result": json.dumps({"success": False, "data": None})}

    monkeypatch.setattr("app.main.get_activity_by_id", fake_get_activity_by_id)
    response = client.get("/api/activity/nope")
    assert response.status_code == 404


def test_200_returns_activity_data(monkeypatch):
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")

    async def fake_get_activity_by_id(identifier):
        assert identifier == "abc123"
        return {"result": json.dumps({"success": True, "data": {"_id": "abc123", "title": "Jumpin Heights"}})}

    monkeypatch.setattr("app.main.get_activity_by_id", fake_get_activity_by_id)
    response = client.get("/api/activity/abc123")
    assert response.status_code == 200
    assert response.json() == {"_id": "abc123", "title": "Jumpin Heights"}

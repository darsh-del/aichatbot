"""Tests for GET /api/activity/{id} — the 'click a card for more' endpoint.

The path param is always the small reference number from the `activity:<ref>`
link (app/activity_ref.py) — the raw Mongo `_id` never reaches the browser, so
these tests exercise the endpoint the way the frontend actually calls it: with
a real ref, not the underlying hex id.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.activity_ref import get_or_create_ref
from app.main import app, settings

client = TestClient(app)

REAL_ID = "66f1a2b3c4d5e6f7a8b9c0d1"


@pytest.fixture
def ref():
    # Computed fresh per test rather than once at import time: activity_ref's
    # id<->ref tables are shared, global, in-memory state (see its module
    # docstring), and test_activity_ref.py's own tests reset that same state
    # between their runs - a module-level constant here would go stale the
    # moment those tests ran. get_or_create_ref() is safe to call again
    # regardless: it hands back the existing ref if one's still there, or
    # mints a fresh (still valid) one if not.
    return get_or_create_ref(REAL_ID)


def test_503_when_mcp_not_configured(monkeypatch, ref):
    monkeypatch.setattr(settings, "mcp_server_url", "")
    response = client.get(f"/api/activity/{ref}")
    assert response.status_code == 503


def test_404_when_ref_is_unknown(monkeypatch):
    # Never handed out by get_or_create_ref - never even reaches the catalog.
    # Also covers a stale plain hex id from before this feature shipped.
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")
    response = client.get("/api/activity/not-a-real-ref!!")
    assert response.status_code == 404


def test_404_when_activity_not_found(monkeypatch, ref):
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")

    async def fake_get_activity_by_id(identifier):
        return {"result": json.dumps({"success": False, "data": None})}

    monkeypatch.setattr("app.main.get_activity_by_id", fake_get_activity_by_id)
    response = client.get(f"/api/activity/{ref}")
    assert response.status_code == 404


def test_200_returns_activity_data_after_resolving_the_ref(monkeypatch, ref):
    monkeypatch.setattr(settings, "mcp_server_url", "https://mcp.example.com/mcp")

    async def fake_get_activity_by_id(identifier):
        # The endpoint must hand the catalog the REAL id, recovered from the
        # ref - never the ref itself.
        assert identifier == REAL_ID
        return {"result": json.dumps({"success": True, "data": {"_id": REAL_ID, "title": "Jumpin Heights"}})}

    monkeypatch.setattr("app.main.get_activity_by_id", fake_get_activity_by_id)
    response = client.get(f"/api/activity/{ref}")
    assert response.status_code == 200
    assert response.json() == {"_id": REAL_ID, "title": "Jumpin Heights"}

"""Tests for GET /api/admin/session-summaries* — the dashboard pull endpoints."""
from fastapi.testclient import TestClient

from app import dashboard
from app.main import app, settings

client = TestClient(app)


def test_returns_503_when_dashboard_api_key_unset(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_api_key", "")
    response = client.get("/api/admin/session-summaries")
    assert response.status_code == 503


def test_returns_401_with_wrong_or_missing_token(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_api_key", "secret")

    assert client.get("/api/admin/session-summaries").status_code == 401
    assert client.get(
        "/api/admin/session-summaries", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_returns_summaries_with_correct_token(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashboard_api_key", "secret")
    monkeypatch.setattr(dashboard, "SUMMARIES_FILE", tmp_path / "session_summaries.json")
    dashboard._append_summary({"session_id": "s1", "ended_at": "2026-08-08T00:00:00Z", "summary": "hi"})

    response = client.get(
        "/api/admin/session-summaries", headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 200
    assert response.json() == {"summaries": [{"session_id": "s1", "ended_at": "2026-08-08T00:00:00Z", "summary": "hi"}]}


def test_single_summary_404_when_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashboard_api_key", "secret")
    monkeypatch.setattr(dashboard, "SUMMARIES_FILE", tmp_path / "session_summaries.json")

    response = client.get(
        "/api/admin/session-summaries/nope", headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 404


def test_single_summary_found(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashboard_api_key", "secret")
    monkeypatch.setattr(dashboard, "SUMMARIES_FILE", tmp_path / "session_summaries.json")
    dashboard._append_summary({"session_id": "s1", "ended_at": "2026-08-08T00:00:00Z", "summary": "hi"})

    response = client.get(
        "/api/admin/session-summaries/s1", headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == "s1"

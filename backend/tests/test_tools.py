import asyncio
import json
from app import tools
from app.tools import dispatch_tool, escalate_and_capture_lead


def _isolate_leads_file(monkeypatch, tmp_path):
    # Without this, escalate_and_capture_lead writes to the real
    # backend/data/leads.json — every test run permanently pollutes
    # production lead data with fake test entries.
    monkeypatch.setattr(tools, "LEADS_FILE", tmp_path / "leads.json")


def test_escalate_and_capture_lead(monkeypatch, tmp_path):
    _isolate_leads_file(monkeypatch, tmp_path)
    res = escalate_and_capture_lead(
        name="Rahul Sharma",
        phone="+91 98765 43210",
        group_size=8,
        activity_interest="16 KM Rafting + Bungee Jump",
        notes="Group discount request for 8 people next weekend",
        urgency="high",
    )
    assert res["status"] == "success"
    assert res["ticket_id"].startswith("LEAD-")
    assert res["lead_details"]["name"] == "Rahul Sharma"
    assert res["lead_details"]["group_size"] == 8


def test_dispatch_tool_escalation(monkeypatch, tmp_path):
    _isolate_leads_file(monkeypatch, tmp_path)
    args = json.dumps({"name": "Test User", "phone": "1234567890", "group_size": 6})
    res = asyncio.run(dispatch_tool("escalate_and_capture_lead", args))
    assert res["status"] == "success"
    assert "ticket_id" in res

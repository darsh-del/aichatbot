import json
from app.tools import dispatch_tool, escalate_and_capture_lead


def test_escalate_and_capture_lead():
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


def test_dispatch_tool_escalation():
    args = json.dumps({"name": "Test User", "phone": "1234567890", "group_size": 6})
    res = dispatch_tool("escalate_and_capture_lead", args)
    assert res["status"] == "success"
    assert "ticket_id" in res

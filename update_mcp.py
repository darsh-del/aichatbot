import re

with open("backend/app/mcp_client.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add _active_closure before _slim
active_closure_code = """
import datetime

def _active_closure(closures: list, on_date: str) -> dict | None:
    \"\"\"Return the closure record covering `on_date` (YYYY-MM-DD), if any.\"\"\"
    for c in closures or []:
        if c.get("isActive") and c.get("startDate", "") <= on_date <= c.get("endDate", ""):
            return c
    return None

def _slim(obj):"""
content = content.replace("def _slim(obj):", active_closure_code)

# 2. Add bucketlisttSeasonalClosures to _DROP_KEYS
content = content.replace('"timeSlots",', '"timeSlots",\n    "bucketlisttSeasonalClosures",')

# 3. Inject closure logic inside _slim
slim_logic = """def _slim(obj):
    \"\"\"Recursively drop media/HTML bulk from an MCP JSON result.\"\"\"
    if isinstance(obj, dict):
        out = {}
        if "bucketlisttSeasonalClosures" in obj:
            today = datetime.date.today().isoformat()
            closure = _active_closure(obj["bucketlisttSeasonalClosures"], today)
            if closure:
                out["_closed_until"] = closure.get("endDate")
                out["_closure_reason"] = closure.get("message")
"""
content = content.replace('def _slim(obj):\n    """Recursively drop media/HTML bulk from an MCP JSON result."""\n    if isinstance(obj, dict):\n        out = {}', slim_logic)

# 4. Make _postprocess async and add tool_args
postprocess_def = "async def _postprocess(fn: str, text: str, tool_args: dict) -> dict:"
content = content.replace("def _postprocess(fn: str, text: str) -> dict:", postprocess_def)

# 5. Add supplementary lookup for get_time_slots
hint_logic = """    if fn in ("get_time_slots", "get_activity_slots"):
        if '"slots":[]' in text.replace(" ", ""):
            activity_id = tool_args.get("activityId") or tool_args.get("identifier")
            date_req = tool_args.get("date")
            is_closed = False
            closure_reason = ""
            closed_until = ""
            
            if activity_id and date_req:
                try:
                    # Supplementary lookup to check for closure
                    from litellm.experimental_mcp_client import call_openai_tool
                    from pydantic import BaseModel
                    class DummyFunc(BaseModel):
                        name: str = "get_activity"
                        arguments: str
                    class DummyCall(BaseModel):
                        function: DummyFunc

                    dummy_call = DummyCall(function=DummyFunc(arguments=json.dumps({"identifier": activity_id})))
                    # Use call_catalog_tool which handles caching implicitly!
                    act_result = await call_catalog_tool(dummy_call)
                    
                    if "_closed_until" in act_result.get("result", ""):
                        # Extract it simply, we know we just injected it in _slim!
                        res_obj = json.loads(act_result["result"])
                        if "_closed_until" in res_obj:
                            is_closed = True
                            closed_until = res_obj["_closed_until"]
                            closure_reason = res_obj["_closure_reason"]
                except Exception as e:
                    logger.error(f"Supplementary closure lookup failed: {e}")

            if is_closed:
                result["_hint"] = (
                    f"Zero slots for THIS activity because it is CLOSED for the season until {closed_until}. "
                    f"Reason: {closure_reason}. "
                    "Do NOT suggest same-category alternatives (like another rafting route) unless you "
                    "already know for sure they are open, because the entire category is likely closed."
                )
            else:
                result["_hint"] = (
                    "Zero slots for THIS activity. Other providers may offer the same "
                    "activity type with available slots — call search_activities_by_destination_and_tag "
                    "to find alternatives before telling the user it's unavailable."
                )
        else:
            result["_hint"] = (
                "Show ONLY the slot start time (e.g. '10:00 AM'). Do NOT show or "
                "fabricate an end time — the data does not have meaningful end times."
            )"""

old_hint_logic = """    if fn in ("get_time_slots", "get_activity_slots"):
        if '"slots":[]' in text.replace(" ", ""):
            result["_hint"] = (
                "Zero slots for THIS activity. Other providers may offer the same "
                "activity type with available slots — call search_activities_by_destination_and_tag "
                "to find alternatives before telling the user it's unavailable."
            )
        else:
            result["_hint"] = (
                "Show ONLY the slot start time (e.g. '10:00 AM'). Do NOT show or "
                "fabricate an end time — the data does not have meaningful end times."
            )"""

content = content.replace(old_hint_logic, hint_logic)

# 6. Update call_catalog_tool to await _postprocess and pass arguments
old_call = "postprocessed = _postprocess(fn, text)"
new_call = 'postprocessed = await _postprocess(fn, text, json.loads(tool_call.function.arguments or "{}"))'
content = content.replace(old_call, new_call)

with open("backend/app/mcp_client.py", "w", encoding="utf-8") as f:
    f.write(content)

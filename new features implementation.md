# Seasonal-Closure Availability Fix — Implementation Plan

**Status:** Planning only. No code changed yet — this document is the plan to review/approve before implementation.

## 1. The bug, as reported

River rafting has no fixed monsoon closure calendar (it varies year to year, and can vary per
route/provider). Today, when a user asks to book rafting during a closed window:

1. The bot calls `get_time_slots` for the requested route/date.
2. Slots come back empty.
3. The bot tells the user that route is unavailable and suggests a different route (shorter/longer)
   or a different provider.
4. The user picks the alternative — and it's *also* unavailable, because the whole category is
   seasonally closed, not just the one route they first asked about.

The bot isn't lying about slot #1 being empty. It's guessing why, guessing an alternative, and
never actually checking whether that alternative is closed for the same reason.

## 2. Root-cause research (live MCP server, verified today)

### 2.1 The data already has the answer — we're just not reading it

Every activity record returned by `get_activity` / `get_activities` / `get_activities_summary`
carries a `bucketlisttSeasonalClosures` array. Live example, fetched right now from all 7 Rishikesh
rafting activities across **both** providers (River Rafting and Dronecraft River Rafting):

```json
"bucketlisttSeasonalClosures": [
  {
    "startDate": "2026-07-01",
    "endDate": "2026-09-30",
    "message": "River rafting in Rishikesh remains closed from 1 July 2026 to 30 September 2026 due to the monsoon season and government safety regulations.",
    "isActive": true,
    "_id": "6a3d77cda0f4c6fa8f3e82ee"
  }
]
```

All 7 of 7 rafting activities (12/16/24/36 KM standard, plus the 3 Dronecraft variants) currently
carry an active closure covering today. This is a **structured, authoritative, per-activity field**
— exactly the "is it actually open" signal the ask is asking for. It is not rafting-specific either:
the same pattern exists on other activity types (e.g. one bungee provider, "Jumpin Heights", carries
its own closure record with its own message and dates, independent of the other 4 bungee providers,
which have none).

### 2.2 Where this field is invisible today

`get_time_slots` / `get_activity_slots` — the tools the bot is told to trust for availability — do
**not** include `bucketlisttSeasonalClosures` at all. Live check, same activity, three dates:

```
get_time_slots(12 KM River Rafting, 2026-08-10)  -> {"slots": []}   (no reason given)
get_time_slots(12 KM River Rafting, 2026-08-15)  -> {"slots": []}   (no reason given)
get_time_slots(12 KM River Rafting, 2026-10-05)  -> {"slots": [...7 slots...]}  (closure window ended)
```

An empty `slots: []` is structurally identical whether the cause is "seasonally closed for 3
months" or "this one date is sold out." Nothing in the response tells the bot which one it is.

### 2.3 Two things in this codebase currently make it worse

- [`backend/app/mcp_client.py:224-235`](backend/app/mcp_client.py) (`_postprocess`) — when
  `get_time_slots`/`get_activity_slots` return zero slots, it injects this hint into the model's
  context: *"Other providers may offer the same activity type with available slots — call
  `search_activities_by_destination_and_tag` to find alternatives before telling the user it's
  unavailable."* This is correct advice for "sold out on this date," and actively wrong advice for
  "closed for the season" — it's what's driving the bot to recommend a second route that's equally
  closed.
- [`backend/data/knowledge_base.md:292`](backend/data/knowledge_base.md) — *"River rafting: Operators
  set their own schedules year-round. **ALWAYS call `get_time_slots`** — do NOT assume any season is
  closed."* Combined with `llm.py`'s final guardrail (*"the tool is ALWAYS more authoritative than any
  seasonal text"*), the model is explicitly told to disregard closure information as unreliable
  "seasonal text" — even though `bucketlisttSeasonalClosures` is live tool data, not static KB prose,
  and is exactly what it should be trusting.

Net effect: the one field that would answer "is it actually closed, and until when" either never
reaches the model (slots calls) or is present but the model is told to distrust it (activity/list
calls).

## 3. Proposed fix

Two layers, matching the pattern already used elsewhere in this codebase for the bungee-summary tool
gate (`app/llm.py::_wants_bungee_summary`) — **decide deterministically in code, don't leave a
correctness-critical judgment to the LLM's discretion.**

### 3.1 Backend: compute closure status server-side (primary fix)

In `app/mcp_client.py`, add one small helper:

```python
def _active_closure(closures: list, on_date: str) -> dict | None:
    """Return the closure record covering `on_date` (YYYY-MM-DD), if any."""
    for c in closures or []:
        if c.get("isActive") and c.get("startDate", "") <= on_date <= c.get("endDate", ""):
            return c
    return None
```

Wire it into `_postprocess` in two places:

- **Activity-shaped results** (`get_activity`, `get_activities`, `get_activities_summary`,
  `search_activities_by_destination_and_tag`): for each activity, check
  `_active_closure(activity["bucketlisttSeasonalClosures"], today)`. If found, attach a clear,
  impossible-to-miss marker per activity, e.g. `"_closed_until": "2026-09-30"` and
  `"_closure_reason": "<message>"`, instead of leaving a raw ISO-date array for the model to
  interpret. (LLMs are not reliably good at "is 2026-08-11 between 2026-07-01 and 2026-09-30" —
  computing it in Python removes that failure mode entirely.)
- **`get_time_slots` / `get_activity_slots`** (the tools that don't carry the field at all): when
  slots come back empty, do **one supplementary lookup** — `get_activity(activityId)` — before
  writing the hint. This is a cheap addition: `get_activity` is already in `CACHEABLE_TOOLS`, backed
  by the shared Redis cache (`app/cache.py`) with a TTL, so this only costs a real network round-trip
  once per activity per cache window, not once per user. If the lookup finds an active closure for
  the requested date, replace the current "try other providers" hint with the authoritative reason
  and reopen date, and explicitly tell the model **not** to suggest same-category alternatives unless
  they're separately confirmed open. If no closure is found, keep today's existing "try other
  providers" hint unchanged — that logic is correct for a genuinely sold-out single date.

This directly fixes the "second suggestion also fails" complaint: alternates now carry their own
closure marker (from the list call the model already made to find them), so the model can see
up front that route B is closed too, instead of finding out only after the user tries to book it.

### 3.2 Prompt: teach the model what the new field means (reinforcement, not the primary fix)

In `app/llm.py::build_messages`:

- Explain `_closed_until` / `_closure_reason` as **authoritative, live data** — not the kind of
  "seasonal generalization" the existing guardrail warns against. Update the "MANDATORY" guardrail
  at the end of the prompt so it no longer reads as "ignore closure signals, trust empty slots alone."
- Update the empty-slots recipe: only suggest an alternate activity/provider if that alternate does
  **not** carry an active closure for the requested date. If every candidate in the category is
  closed, say so plainly with the real reason and reopen date — do not keep drilling into more
  alternates that are visibly closed in data already in context.

### 3.3 Knowledge base: fix the now-actively-wrong static line

`backend/data/knowledge_base.md:292` currently says rafting runs "year-round" and to never assume a
season is closed. Reword to say closures are real, vary year to year, and are reflected in the live
`bucketlisttSeasonalClosures` data on every activity — so the model stops being told to discount the
one signal that would have prevented this bug.

## 4. Why this doesn't disturb anything else

- Change is scoped to `_postprocess`'s handling of activity-shaped results and the empty-slots branch
  of `get_time_slots`/`get_activity_slots`. No other tool's post-processing, the bungee-summary gate,
  cart/auth flow, caching keys, or truncation behavior (`MAX_TOOL_RESULT_CHARS`, the
  `get_activities_summary` exemption) is touched.
- The supplementary `get_activity` lookup only fires on the already-rare empty-slots path, and only
  once per activity per cache TTL — negligible added cost, no added LLM tool-iteration (it's a
  backend-side enrichment, not a model-visible extra tool call).
- Falls back to exactly today's behavior ("try other providers") whenever no closure record is
  found — this is additive, not a behavior removal, so any activity type without seasonal closures
  (most of the catalog, per the live check) is unaffected.

## 5. Known limitations / open questions

- **Data-dependent.** This fix is only as good as ops keeping `bucketlisttSeasonalClosures` current
  on the MCP/catalog side. If a route closes without that field being set, the bot still falls back
  to the old "try alternates" heuristic — same blind spot as today, not worse.
- **Boundary dates.** A closure ending `2026-09-30` and a Redis-cached `get_activity` result could
  theoretically serve a stale "closed" verdict for a few minutes into Oct 1 (cache TTL, shared with
  the rest of `CACHEABLE_TOOLS`). Acceptable given the existing TTL is already short; flagging in
  case it's worth a shorter TTL specifically for closure-bearing calls.
- **Experience-level closures.** Only checked at the activity level (confirmed present and sufficient
  for both rafting and the bungee provider example). Have not confirmed whether `get_experience`
  ever carries its own provider-wide closure separate from per-activity ones — worth a quick check
  during implementation, low risk either way since activity-level covers the reported case.

## 6. Implementation checklist (for the follow-up coding session)

1. Add `_active_closure()` helper + unit tests (boundary dates, `isActive: false`, empty/missing
   array, overlapping closures) in `app/mcp_client.py`.
2. Wire it into `_postprocess` for `get_activity`/`get_activities`/`get_activities_summary`/
   `search_activities_by_destination_and_tag`.
3. Add the supplementary cached `get_activity` lookup on the empty-slots path for
   `get_time_slots`/`get_activity_slots`; replace the hint conditionally.
4. Update `build_messages` system prompt (closure-field explanation + revised empty-slots recipe +
   softened final guardrail).
5. Fix `knowledge_base.md:292`.
6. Tests: extend `backend/tests/test_mcp_client.py` for the new closure logic; add a case to
   `test_llm.py` or a new test file if the prompt logic needs coverage.
7. Local verification against the live MCP server (same method used for the bungee-summary feature):
   confirm a rafting query during the current closure window now surfaces the real reason instead of
   a second dead-end suggestion, and confirm an activity with no closure record is unaffected.

## 7. External references consulted

- [Booking.com Connectivity API — availability/restrictions](https://developers.booking.com/connectivity/docs/b_xml-availability) —
  industry precedent for an explicit structured "closed" field at the inventory-item level rather
  than inferring closure from empty availability.
- [Microsoft Learn — Inventory availability APIs for e-commerce](https://learn.microsoft.com/en-us/dynamics365/commerce/dev-itpro/inventory-availability-apis) —
  availability-to-promise as a computed value from structured state, not inferred from a single flat
  "no slots" signal.
- [AWS — MCP tool design: practical approaches and tradeoffs](https://aws.amazon.com/blogs/machine-learning/mcp-tool-design-practical-approaches-and-tradeoffs/) —
  general guidance on surfacing rich, structured context to the model rather than leaving
  interpretation of ambiguous empty results to the LLM.
- [Fast.io — MCP server caching](https://fast.io/resources/mcp-server-caching/) — confirms the
  supplementary-lookup-plus-cache approach (§3.1) is a standard, low-cost pattern for enriching one
  tool's result with data from another.

# Session Summary Webhook — Employee Dashboard Integration Guide

How the chatbot pushes generated conversation summaries to an external system in real time: what
gets sent, how to verify it's genuinely from us, how to handle retries/duplicates, and the fallback
endpoints for backfill. Written for whoever builds the *receiving* side on the employee-dashboard
team. Written against `main` @ `6333f34`.

---

## 1. The whole thing, in one sentence

Every ~15 minutes of user silence, the chatbot asks Claude to summarize that conversation, saves it
permanently on our side, and — if you've given us a URL — `POST`s the same record to you within
seconds; if that push ever fails, `GET /api/admin/session-summaries?since=` on our side always has
it, so nothing is ever silently lost.

```
User goes quiet for 15 min
        │
        ▼
Claude generates a structured summary
        │
        ▼
We save it permanently (backend/data/session_summaries.json)
        │
        ▼
We POST it to SUMMARY_WEBHOOK_URL ──────► YOUR endpoint
        │ (retries up to 3x on transient failure)
        ▼
Still failed after retries? We log it and move on —
you can always backfill via GET .../session-summaries?since=
```

Source: [`dashboard.py::summarize_idle_sessions()`](backend/app/dashboard.py:211) and
[`dashboard.py::_send_webhook()`](backend/app/dashboard.py:123).

---

## 2. What you need to give us

| Thing | What it's for |
|---|---|
| A public HTTPS URL that accepts `POST` | Goes into our `SUMMARY_WEBHOOK_URL` env var |
| A random secret string (e.g. `openssl rand -hex 32`) | Goes into our `SUMMARY_WEBHOOK_SECRET` env var **and** your verification code — same value on both sides |

Until `SUMMARY_WEBHOOK_URL` is set, this entire feature is off — no behavior change, nothing sent
anywhere. Once it's set, every summary generated from that point on gets pushed automatically; no
further action needed on our end.

---

## 3. The request you'll receive

```
POST <your SUMMARY_WEBHOOK_URL>
Content-Type: application/json
X-Webhook-Signature: t=1735392000,v1=8f3a9c1b...          (only present if a secret is configured)

{JSON body — see §4}
```

- **Method/body**: plain `POST`, JSON body, no query params.
- **Timeout**: we wait 5 seconds for your response per attempt.
- **No signature header at all** means `SUMMARY_WEBHOOK_SECRET` was left blank on our side — fine
  for a private/internal network, not recommended over the public internet.

---

## 4. The payload — full field reference

```json
{
  "session_id": "e2e-test-session",
  "ended_at": "2026-08-28T03:09:22Z",
  "message_count": 4,
  "user_info": {"name": "Rahul", "phone": "9876500000", "email": ""},
  "verified_phone": "+919876500000",
  "summary": "Customer inquired about bungee jumping pricing in Rishikesh. Assistant provided pricing information and offered to check availability.",
  "topics": ["bungee jumping", "pricing", "Rishikesh"],
  "questions_asked": ["How much is bungee jumping in Rishikesh?"],
  "sentiment": "neutral",
  "requires_followup": true
}
```

| Field | Type | Always present? | What it is |
|---|---|---|---|
| `session_id` | `string` | always | Opaque chat session id. Use this (+ `ended_at`) as your dedupe/upsert key — see §6. |
| `ended_at` | `string` (ISO 8601, UTC) | always | When the session went idle — i.e. roughly "when the conversation ended." |
| `message_count` | `number` | always | Total user turns in the conversation. |
| `user_info` | `object \| null` | only if the user filled the in-chat lead-capture prompt | `{name, phone, email}`. **Self-reported, unverified** — the user just typed it into chat. |
| `verified_phone` | `string \| null` | only if the user completed a real OTP login | The phone number from an actual `send_otp` → `verify_otp` flow the user completed themselves (read an SMS code, typed it back). **Stronger signal than `user_info.phone`** — it only ever appears once the user has proven they hold that phone number. Never auto-filled, never guessed — see §7 if you're wondering how this works. |
| `summary` | `string` | always | 2–4 sentence recap, Claude-generated. |
| `topics` | `string[]` | always | Short topic tags. |
| `questions_asked` | `string[]` | always | The user's distinct questions, lightly cleaned up. |
| `sentiment` | `"positive" \| "neutral" \| "frustrated"` | always | |
| `requires_followup` | `boolean` | always | `true` if a human should follow up — unresolved question, clear booking intent, or a complaint. |

Source: [`dashboard.py::summarize_idle_sessions()`, lines 224–231](backend/app/dashboard.py:224),
tool schema at [`dashboard.py::SUMMARY_TOOL`](backend/app/dashboard.py:37).

**Both `user_info` and `verified_phone` can be present, either, or neither** — a user might fill
the lead-capture form, or complete a real login, or do both, or do nothing and just chat. Design
your storage to handle all four combinations; don't assume either field is guaranteed.

---

## 5. Verifying the signature

The signed content is `"<timestamp>.<raw request body>"`, HMAC-SHA256'd with your shared secret —
same convention Stripe/GitHub/Shopify use.

```python
import hmac, hashlib, time

def verify(raw_body: bytes, signature_header: str, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in signature_header.split(","))
    ts, sig = parts["t"], parts["v1"]

    if abs(time.time() - int(ts)) > 300:      # reject anything older than 5 min
        return False

    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
```

Two things worth being careful about, both common sources of bugs:

1. **Use the raw request bytes**, not a re-serialized/re-parsed version of the JSON — re-encoding
   can reorder keys or change whitespace and the signature won't match even though the data is
   identical.
2. **Use a constant-time compare** (`hmac.compare_digest` / your language's equivalent), never `==`
   — a naive string compare leaks timing information an attacker can exploit.

Reject anything that fails verification with `401`. Reject a stale timestamp too — that's what
stops a captured request from being replayed later.

Source: [`dashboard.py::_sign_webhook()`](backend/app/dashboard.py:114).

---

## 6. Delivery behavior — retries, duplicates, what to expect

| Situation | What we do |
|---|---|
| You respond `2xx` | Done — no retry. |
| You respond `408` or `429`, or any `5xx` | Retried, up to 3 attempts total, with backoff (starts at 1s, doubles each retry). If you send a `Retry-After` header on a `429`, we honor it. |
| You respond any other `4xx` (`400`, `401`, `404`, ...) | **Not retried** — we assume the request itself is wrong (bad URL, bad auth) and retrying identically won't help. Fix your endpoint/config and the *next* summary will go through; the failed one is still safely stored on our side (see §8). |
| Connection error / timeout | Same retry policy as `5xx`. |
| All retries exhausted | We log it and move on. **The summary is not lost** — it's already durably saved before we even attempt the push (see the diagram in §1). |

**Implication for you: your endpoint must be idempotent.** A retry can, in rare cases, succeed on
our side detection-wise while you still get called more than once for the same summary (e.g. you
processed it and returned 200, but the response got lost in transit). Upsert on `session_id` (+
`ended_at` if you want to be extra safe), don't blindly insert — see the sample handler in §9.

**Respond fast.** Return `200` as soon as you've durably queued/stored the payload; don't do slow
work (emails, third-party calls) synchronously in the request — that's what causes us to time out
and retry unnecessarily.

Source: [`dashboard.py::_send_webhook()`](backend/app/dashboard.py:123).

---

## 7. About `verified_phone` — why it's trustworthy

Short version: it's not a form field, it's the output of a real login.

The chatbot has a normal SMS-OTP login built in (`send_otp` / `verify_otp`) — a user types their
phone number in chat, gets a real SMS code, types that code back in chat, and only **then** is
this field populated. There is no path where a phone number lands in `verified_phone` without the
user having actually proven they hold that phone. (We deliberately did **not** build any kind of
automatic/bypassed OTP verification — that would let anyone log in as anyone else just by knowing
their number, which is a real account-takeover vector, not a shortcut worth taking.)

Practically: if `verified_phone` is present, treat that contact as higher-confidence than
`user_info.phone` for outreach/CRM purposes.

Source: [`token_store.py`](backend/app/token_store.py) (`set_pending_phone` / `pop_pending_phone` /
`extract_phone`), wired in at [`llm.py::_execute_tool()`](backend/app/llm.py:358).

---

## 8. Backfill / historical load — the pull endpoints (your safety net)

Use these for: your very first sync (load everything historical), and a periodic "catch anything
the webhook missed" reconciliation job (e.g. nightly).

```
GET /api/admin/session-summaries?since=2026-08-28T00:00:00Z
Authorization: Bearer <DASHBOARD_API_KEY>
```
→ `{"summaries": [ ...same shape as §4, one per session... ]}`

```
GET /api/admin/session-summaries/{session_id}
Authorization: Bearer <DASHBOARD_API_KEY>
```
→ a single record (§4 shape), or `404` if that session hasn't been summarized (yet, or ever).

`since` is optional — omit it to get everything. `DASHBOARD_API_KEY` is a separate secret from
`SUMMARY_WEBHOOK_SECRET`; ask us for it if you don't have it. `503` on these two means the key
isn't configured on our side at all; `401` means the token you sent is wrong.

Source: [`main.py:149-167`](backend/app/main.py:149).

---

## 9. Reference receiver implementation

```python
from flask import Flask, request
import hmac, hashlib, time

app = Flask(__name__)
SECRET = "···"  # same value as our SUMMARY_WEBHOOK_SECRET

@app.post("/webhooks/chat-summary")
def receive_summary():
    sig_header = request.headers.get("X-Webhook-Signature", "")
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        ts, sig = parts["t"], parts["v1"]
    except (KeyError, ValueError):
        return "bad signature header", 401

    if abs(time.time() - int(ts)) > 300:
        return "stale", 401

    expected = hmac.new(SECRET.encode(), f"{ts}.".encode() + request.data,
                         hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return "bad signature", 401

    record = request.get_json()
    db.upsert_summary(                       # UPSERT, not insert — see §6
        key=record["session_id"],
        data=record,
    )
    return "ok", 200                          # respond fast, process async if needed
```

---

## 10. Testing checklist

- [ ] Point `SUMMARY_WEBHOOK_URL` at a local tunnel (ngrok, `webhook.site`, etc.) during dev and
      confirm you see a POST land.
- [ ] Verify the signature check actually rejects a tampered body and a wrong secret (not just that
      it accepts the correct one).
- [ ] Confirm your handler returns within a couple seconds — check for any synchronous slow call
      before the `return`.
- [ ] Send the same payload twice manually and confirm your storage doesn't create a duplicate row.
- [ ] Test with a payload where `user_info` is `null`, one where `verified_phone` is `null`, and one
      where both are present — your parsing shouldn't assume either exists.
- [ ] Confirm `GET /api/admin/session-summaries?since=` works as a manual backfill before going live.

---

## 11. FAQ

**We changed our webhook URL / rotated the secret — what do we tell you?**
Just the new value(s) — we update `SUMMARY_WEBHOOK_URL` / `SUMMARY_WEBHOOK_SECRET` and restart. No
schema or behavior change on either side.

**Our endpoint was down for an hour — did we lose summaries?**
No. Every summary is saved permanently on our side the moment it's generated, before any webhook
attempt. Pull `GET /api/admin/session-summaries?since=<start of the outage>` to backfill.

**Can we get summaries pushed for sessions that already happened before we integrated?**
Yes — that's exactly what `GET /api/admin/session-summaries` (no `since`) is for: a one-time full
export to seed your database, then rely on the webhook going forward.

**Do we need to do anything special for `verified_phone` vs `user_info.phone`?**
No special handling required, just don't assume they're the same value or that either is always
present — see the table in §4.

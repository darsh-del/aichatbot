# Functionality

Full inventory of what this software does today. For *why* things are built this way, see
[ARCHITECTURE.md](ARCHITECTURE.md). This file is about *what exists*.

## 1. Conversational chat

- `POST /api/chat` accepts the full message history (`{role: "user"|"assistant", content}[]`)
  and streams the reply back as Server-Sent Events — one `data: {"delta": "...", "done": bool}`
  frame per token, ending with `done: true` (an `error` field is set instead of the stream just
  dropping if anything fails).
- The client is stateless: no server-side session storage. Each request resends the full
  conversation; the frontend ([api/chat.ts](frontend/src/api/chat.ts)) decodes the SSE stream and
  calls back per token as it arrives.
- The server-side system prompt is non-negotiable: `ChatMessage.role` is typed as
  `Literal["user", "assistant"]` only, so a client-supplied `role: "system"` message is rejected
  with a 422 before it ever reaches the model.
- `GET /api/health` — liveness probe, reports `{"status": "ok", "model": <configured LLM model>}`.
- Model/provider is controlled entirely by the `LLM_MODEL` env var via litellm — switching from
  `gpt-4o-mini` to Claude, Gemini, a local Ollama model, etc. is a config change, not a code change.

## 2. Knowledge grounding (RAG)

Two layers, used together when both are configured:

- **Static base file** — [data/knowledge_base.md](backend/data/knowledge_base.md): contact info,
  company description, activity categories, booking policy, approximate prices, and the rules
  telling the model when to call `escalate_and_capture_lead`. Always loaded as the system prompt
  base.
- **Weaviate semantic search** — the latest user message is embedded (OpenAI
  `text-embedding-3-small`) and used to pull the top 6 relevant chunks from a `BucketlisttKB`
  Weaviate collection (scraped site content), which are appended to the system prompt under a
  "Relevant Knowledge Base Context" heading. If Weaviate isn't configured or the query fails, this
  degrades silently to the static file only — never crashes the chat.
- **Two Weaviate deployment options**, switched purely by whether `WEAVIATE_API_KEY` is set:
  - *Weaviate Cloud* (`WEAVIATE_URL` + `WEAVIATE_API_KEY`) — managed, but the free sandbox tier
    hard-expires after 14 days.
  - *Self-hosted* (`WEAVIATE_URL` only, e.g. `http://weaviate:8080`) — a `weaviate` service is
    defined in [docker-compose.yml](docker-compose.yml) with anonymous access and a persistent
    Docker volume, no time limit.
- **Ingestion pipeline** (run manually or on a schedule, not automated yet):
  [scripts/scrape_bucketlistt.py](backend/scripts/scrape_bucketlistt.py) crawls bucketlistt.com →
  [scripts/upsert_to_weaviate.py](backend/scripts/upsert_to_weaviate.py) chunks, embeds, and
  upserts into Weaviate (idempotent via deterministic UUIDs, works against either Weaviate mode).

## 3. Live catalog data (MCP)

The model has direct, real-time access to bucketlistt's own production database via its MCP
server (`mcp.bucketlistt.com/mcp`), through 8 whitelisted read-only tools
([app/mcp_client.py](backend/app/mcp_client.py)):

| Tool | Purpose |
|---|---|
| `get_destinations` | List active cities Bucketlistt operates in |
| `get_experiences` | List providers/operators in a destination |
| `get_experience` | Look up one provider by id/slug/name |
| `get_activities` | List activities for a provider or destination |
| `get_activity` | Look up one activity's details |
| `search_activities_by_destination_and_tag` | Find activities by keyword (e.g. "bungee") in a city |
| `get_activity_slots` | Real available time slots for an activity on a given date |
| `get_activity_addons` | Optional paid add-ons for an activity |

These return real provider names, phone numbers, live prices, and actual open slots — not the
static KB snapshot. The system prompt explicitly tells the model to prefer these over guessing and
to never invent destinations, activities, prices, or availability.

**Deliberately excluded, structurally not just by instruction:** `send_otp`, `verify_otp`,
`add_to_cart`, `get_cart`, `update_cart_item`, `remove_from_cart`, `get_my_bookings`,
`create_payment_link`, `create_booking_order`. These 9 tools exist on the MCP server but are
filtered out before the tool list ever reaches the model — they are not "forbidden," they are
simply never loaded, so the model has no way to log a user in, touch a cart, or move money,
regardless of what a user or injected prompt asks for.

Toggled entirely by the `MCP_SERVER_URL` env var; if unset, the chat works exactly as before
(static KB + Weaviate only). If the MCP server is unreachable, the connection failure is caught
and the request degrades to local tools only rather than failing the whole chat.

## 4. Human escalation / lead capture

- `escalate_and_capture_lead` (local tool, [app/tools.py](backend/app/tools.py)) — the model calls
  this for group bookings (5+ people), explicit "talk to a human" requests, custom
  itinerary/package asks, or whenever a user provides contact info.
- Writes a record (name, phone, email, group size, activity interest, preferred date, notes,
  urgency, a generated `LEAD-XXXXX` ticket ID, timestamp, status) to
  [data/leads.json](backend/data/leads.json).
- The frontend detects a `LEAD-\d{5}` pattern in the assistant's reply and renders a dedicated
  "Escalation Ticket Created" card with a direct WhatsApp link, instead of showing it as plain text.
- This is the **only** path to a real conversion in this build — MCP payment tools being excluded
  means group/high-value leads and checkout intent both route here, not to an automated charge.

## 5. Frontend UI ([frontend/src](frontend/src))

- **Sidebar** — brand header, "New Conversation" reset, 5 quick-topic shortcuts (Bungee, Rafting,
  Paragliding, Camping, Flying Fox Safety), a "Weaviate RAG Active" status indicator, and a
  "Group / Human Callback" button.
- **Header** — model/RAG tag, a persistent "10% Deposit Only" trust pill, and a Human Callback
  button.
- **Quick Chips** — 5 one-click popular-question prompts above the input box (disabled mid-stream).
- **Lead Modal** — form (name, phone*, group size, preferred experience, notes) that composes a
  structured message and sends it into the chat as a user turn, driving the escalation tool.
- **Message rendering** — hand-rolled lightweight markdown: headers, bullet lists, `**bold**`,
  auto-linked URLs and `[label](url)` links (opened in a new tab), plus a persistent
  "Pay 10% Deposit Only / Verified Operators" footer strip on every assistant message.
- Backend URL is configurable via `VITE_API_BASE_URL`, so the same frontend build can point at any
  backend instance speaking the same `/api/chat` SSE contract.

## 6. Security guardrails

Defense-in-depth without over-engineering — the model itself is the intent classifier (see §1), not a separate call, so refusals are free.

- **Scope enforcement** (system prompt, [knowledge_base.md](backend/data/knowledge_base.md)) — the model is explicitly told its scope (Bucketlistt adventure planning), what to refuse (general knowledge, coding, other companies, medical/legal/financial, jokes, roleplay), and how to refuse (one short warm sentence that pivots to trip planning, worded differently every time). Live-verified: general-knowledge, coding, jailbreak, and prompt-extraction prompts all get on-brand refusals; real activity questions still work.
- **Prompt-injection resistance** — the prompt explicitly instructs the model to ignore any user text claiming to be from a developer/admin/system, requesting the system prompt, or asking it to adopt a new persona. It also states the model has no ability to take payments, log users in, or access accounts — reinforcing the structural exclusion in §3.
- **Input caps** ([schemas.py](backend/app/schemas.py)) — `content` is capped at 8000 chars (~2000 tokens) per message and `messages` at 40 per request. Oversized payloads are rejected with a 422 before ever reaching the model, blocking token-flood abuse.
- **Output token cap** ([llm.py](backend/app/llm.py)) — `max_tokens=1500` on every litellm call bounds worst-case cost per turn.
- **Per-IP rate limit** ([rate_limit.py](backend/app/rate_limit.py)) — 20 chat requests/min per IP via an in-memory sliding-window middleware. Uses `X-Forwarded-For` when behind a proxy. Excess requests get a 429 without ever hitting the LLM.
- **Structural payment exclusion** — see §3; auth/cart/payment MCP tools are never loaded into the toolset, so no prompt injection can make the model take actions it doesn't have tools for.
- **CORS allowlist** — origins are configured via `CORS_ORIGINS`, not `*`.
- **No system-role forgery** — clients cannot inject a `system` message (`ChatMessage.role` is typed to `user`/`assistant` only, enforced at the schema layer).

Deliberately skipped: separate LLM intent classifiers (add 5-11s latency per turn for no benefit — the main call already classifies), regex blocklists (trivially bypassed, false positives), heavyweight guardrail libraries (guardrails-ai, NeMo — over-engineering for this scale).

## 7. Repurposing

Per [ARCHITECTURE.md](ARCHITECTURE.md), the same backend image serves either a customer-facing bot
or an internal policy bot purely via env config — `SYSTEM_PROMPT_FILE`, which tools/MCP servers are
enabled, and `CORS_ORIGINS` — no code branching required.

## 8. Configuration reference

| Env var | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | Yes | litellm default provider + embeddings |
| `LLM_MODEL` | No (default `gpt-4o-mini`) | Any litellm-understood model string |
| `SYSTEM_PROMPT_FILE` | No | Path to the base KB/system-prompt file |
| `CORS_ORIGINS` | No | Comma-separated allowed frontend origins |
| `PORT` | No (default `8000`) | uvicorn port |
| `WEAVIATE_URL` | No | Enables RAG when set |
| `WEAVIATE_API_KEY` | No | Set for Weaviate Cloud; blank = self-hosted |
| `MCP_SERVER_URL` | No | Enables live catalog tools when set |
| `VITE_API_BASE_URL` (frontend) | No | Backend base URL the UI talks to |

## 9. Testing & ops

- Backend: 13 pytest tests ([backend/tests](backend/tests)) covering health, chat SSE framing
  (happy path + failure path), config, tools, and guardrails (input caps + rate limiter).
- Frontend: 5 vitest tests ([frontend/src](frontend/src)) covering the chat API client and app
  rendering.
- `docker-compose.yml` runs three services: `backend` (FastAPI :8000), `frontend` (nginx-served
  static build :80→5173), `weaviate` (self-hosted vector DB :8080, persisted volume) — no cloud
  dependency required beyond the LLM provider and the bucketlistt MCP server.

## 10. Explicitly out of scope (by design, not yet-missing)

- No payments, bookings, cart, or login — see §3.
- No server-side conversation persistence — client resends full history each turn.
- No automated re-scraping schedule yet — the scrape → upsert pipeline exists but isn't cron'd.
- Not yet deployed anywhere — researched but unexecuted: Render (backend) + Cloudflare Pages
  (frontend) as the free-tier recommendation.

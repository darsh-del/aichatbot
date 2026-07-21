# Architecture

## Overview

A reusable, configurable chatbot: one backend codebase, repurposed for either the
customer-facing bot or the internal employee policy bot purely by swapping the
knowledge-base file and system prompt via env config — no code branching.

```
                    ┌─────────────────────────┐
   Browser  ───────▶│  Vite + React frontend   │
   (user)           │  (SSE stream consumer)   │
                    └────────────┬─────────────┘
                                 │ POST /api/chat (SSE)
                                 │ GET  /api/health
                    ┌────────────▼─────────────┐
                    │   FastAPI backend         │
                    │   thin routes             │
                    │   thick service layer     │
                    └────────────┬─────────────┘
                                 │ litellm.completion(model=env.LLM_MODEL)
                    ┌────────────▼─────────────┐
                    │   OpenAI API (today)      │
                    │   swappable via env only  │
                    └────────────────────────────┘
```

## Why these choices

- **litellm, not the raw OpenAI SDK** — the entire point of the "control the model
  from env" requirement. `LLM_MODEL` in `.env` is the only thing that changes to
  switch models or providers; the call site (`app/llm.py`) never changes.
- **Knowledge base stuffed into the system prompt, not a vector DB** — at this
  scale (a support-FAQ/policy doc, not a product catalog), a vector store adds
  operational surface (embeddings, an index to keep in sync) for no measurable
  benefit. `SYSTEM_PROMPT_FILE` points at a plain text/markdown file loaded at
  startup. Swap in a vector-backed retrieval step later only if the KB grows
  past what comfortably fits in context.
- **SSE, not WebSockets** — the traffic is one-directional (server → client
  token stream); SSE is simpler, has built-in reconnect, and is the standard
  pattern for LLM token streaming.
- **Thin routes / thick services** — route handlers only parse the request and
  format the response; all LLM/tool logic lives in plain functions that are
  unit-testable without an HTTP server.
- **Tool calling via the standard "resolve tools, then stream the final
  answer" loop** — a non-streaming call first so tool_calls can be executed
  and fed back, then a final streaming call for the user-visible answer. This
  is how the sample `lookup_booking` tool is wired, and how you'd add
  real booking-system calls.

## Repurposing for the two use cases

| | Customer-facing bot | Internal policy bot |
|---|---|---|
| `SYSTEM_PROMPT_FILE` | `data/customer_faq.md` | `data/internal_policies.md` |
| Tools enabled | `lookup_booking`, etc. | none (or internal-systems lookups) |
| `CORS_ORIGINS` | public site origin | internal tool origin |

Same backend image, different `.env` / mounted KB file per deployment.

## Deployment

`docker-compose.yml` at the repo root runs both services:
- `backend`: FastAPI on port 8000, config from `backend/.env`.
- `frontend`: static Vite build served by nginx on port 80 (mapped to 5173 locally).

For real production: put both behind a reverse proxy/CDN with TLS termination,
add structured logging + request metrics (latency, token counts, error rate)
around the litellm call, and consider Redis-backed session storage if you need
server-side conversation history instead of the client resending full history
each request (skipped here — the client-resends-history design is simpler and
sufficient at this scale).

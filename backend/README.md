# Chatbot Backend

FastAPI + litellm backend for a reusable chatbot. The same code serves two
use cases — a travel-booking customer-support bot or an internal employee
policy Q&A bot — the only difference is which knowledge-base file and
system prompt is loaded, via config. No code changes needed to switch.

## API contract

- `POST /api/chat` - body `{"messages": [{"role": "user"|"assistant", "content": "..."}], "session_id": "optional"}`.
  Streams the response as `text/event-stream`. Each frame is
  `data: {"delta": "<chunk>", "done": false}\n\n`, ending with
  `data: {"delta": "", "done": true}\n\n` (or `..."error": "<message>"` on
  failure, still with `done: true`).
- `GET /api/health` - `{"status": "ok", "model": "<LLM_MODEL>"}`.

## Setup

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# edit .env and set OPENAI_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload
```

Serves on `http://localhost:8000` by default (`PORT` env var to change).

## Test

```bash
pytest
```

All tests mock `litellm.acompletion` - no network calls, no real API key
needed to run the suite (conftest.py sets a dummy `OPENAI_API_KEY`). Run
from the `backend/` directory so the relative `SYSTEM_PROMPT_FILE` path
resolves.

## Lint

```bash
pylint app
```

Config lives in `pyproject.toml` under `[tool.pylint.*]`.

## Swapping the LLM provider/model

litellm is what makes this a one-value change. Set `LLM_MODEL` in `.env` to
any litellm-supported model string, and the matching provider API key env
var (litellm reads it directly from the process environment):

| Provider | `LLM_MODEL` example | key env var |
|---|---|---|
| OpenAI (default) | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `claude-3-5-sonnet-20241022` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini/gemini-1.5-pro` | `GEMINI_API_KEY` |
| Local Ollama | `ollama/llama3` | none |

No application code changes are required - `app/llm.py` only ever
references `settings.llm_model`.

## Repurposing: customer support vs. internal employee Q&A

The backend logic is identical for both use cases; only the knowledge base
differs. To switch:

1. Write a new markdown/text file with the relevant content (e.g.
   `data/employee_policy_kb.md` with HR/IT policy Q&A instead of
   `data/knowledge_base.md`'s travel booking FAQ). The file's contents are
   loaded verbatim into the system prompt at request time, so open with
   instructions on tone/role, then the reference material.
2. Point `SYSTEM_PROMPT_FILE` in `.env` at that file.
3. Restart the server. That's it - no route or service code changes.

This is a "knowledge base in context" pattern (the whole file is stuffed
into the system prompt), not a vector DB / RAG pipeline - intentionally
simple, and fine as long as the knowledge file stays small enough to fit
comfortably in the model's context window. If the knowledge base grows past
that, swap `_load_system_prompt` in `app/llm.py` for a retrieval step.

## Tool calling

`app/tools.py` defines one example tool, `lookup_booking(booking_id)`,
returning a mock booking record. `app/llm.py` implements the standard loop:
call the model non-streaming with `tools` attached; if it returns
`tool_calls`, execute them and append `role: "tool"` results, repeating up
to `MAX_TOOL_ITERATIONS` times; once the model stops requesting tools, make
one final `stream=True` call and stream that as the SSE response. Add more
tools by writing a function in `app/tools.py`, adding its schema to
`TOOL_SCHEMAS`, and registering it in `_TOOL_REGISTRY`.

## Docker

```bash
docker build -t chatbot-backend .
docker run -p 8000:8000 --env-file .env chatbot-backend
```

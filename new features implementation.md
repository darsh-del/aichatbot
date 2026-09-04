# Chatbot Hardening — Dashes, Activity IDs, Latency, Attachments, Guardrails

**Status: COMPLETE.** Every item below shipped and was verified against the current codebase
(not just assumed from git history) on 2026-09-04. Original diffs/code removed from this file
since they're now just... the code — see the file links.

| Item | Where it lives |
|---|---|
| Dash-free KB + streaming sanitizer | [backend/data/knowledge_base.md](backend/data/knowledge_base.md), [backend/app/stream_sanitizer.py](backend/app/stream_sanitizer.py) |
| Activity-ID leak fix | Same KB file + `StreamSanitizer`'s `_RAW_OBJECTID_RE` |
| Prompt-caching split (`build_messages()`) + rolling tool-loop breakpoint | [backend/app/llm.py](backend/app/llm.py) |
| MCP `httpx.AsyncClient` reuse | [backend/app/mcp_client.py](backend/app/mcp_client.py) |
| `_wants_catalog()` tool-choice gate | [backend/app/llm.py](backend/app/llm.py) |
| File attachments (upload endpoint, scan, extraction, frontend picker) | [backend/app/attachments.py](backend/app/attachments.py), [backend/app/main.py](backend/app/main.py), [frontend/src/components/AttachmentPicker.tsx](frontend/src/components/AttachmentPicker.tsx) |
| `flow_guard.py` protected-turn gate | [backend/app/flow_guard.py](backend/app/flow_guard.py) |
| Scope regression script | [backend/scripts/scope_regression_check.py](backend/scripts/scope_regression_check.py) |
| `clamav` service | `docker-compose.yml`, `docker-compose.prod.yml` |

Nothing outstanding from this plan. New work should start a fresh doc.

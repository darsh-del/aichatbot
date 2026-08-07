# Bucketlistt Chatbot — 8-Feature Implementation Plan

All 8 features shipped. Verified against source:

| # | Feature | Where |
|---|---------|-------|
| 01 | Welcome message | `frontend/src/App.tsx` — `WELCOME_MESSAGES` / `isWelcomeMsg()` |
| 02 | Persist chat on refresh | `frontend/src/App.tsx` — `STORAGE_KEY`/`SESSION_KEY` + localStorage effects |
| 03 | Copy button | `frontend/src/components/MessageContent.tsx` + `.copy-btn` in `App.css` |
| 04 | Multilingual support | `backend/data/knowledge_base.md` — "Language — mirror the user" |
| 05 | Price anchoring | `backend/data/knowledge_base.md` — "Price display rule" |
| 06 | Comparison helper | `backend/data/knowledge_base.md` — "Comparison tables"; `subtitle` in `_SEARCH_KEEP` (`mcp_client.py`) |
| 07 | Safety reassurance flow | `backend/data/knowledge_base.md` — "Safety reassurance — converting nervous users" |
| 08 | Smart upselling at checkout | `backend/data/knowledge_base.md` — "Checkout upselling moments"; `add_to_cart` `_hint` in `mcp_client.py` |

(Shipped alongside the Josh→Bucky rename — see commits `5c8bdbe`, `a27727e`.)

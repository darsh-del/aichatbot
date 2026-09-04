# Implemented Functionalities (Comprehensive List)

This document serves as an exhaustive list of all major and minor features, optimizations, and security guardrails currently implemented across the entire chatbot stack.

## 1. Conversational AI & Prompt Engineering
- **Live Catalog Database Integration (MCP)**: Fetches destinations, experiences, activities, pricing, and live availability via Model Context Protocol.
- **Dynamic System Prompts**: Injects today's date into the prompt so the LLM understands relative terms like "this weekend" or "tomorrow".
- **Retrieval-Augmented Generation (RAG)**: Weaviate vector DB integration that retrieves semantic chunks from `knowledge_base.md` based on user queries to answer policy/refund questions.
- **Domain Scope Guardrails**: Hard instructions forbidding the LLM from answering non-travel questions (politics, coding) or hallucinating prices.
- **Seasonal Closure Awareness**: The LLM is forced to trust `_closed_until` flags from the database and inform the user of monsoon/off-season closures.
- **Contact Nudging**: A boolean flag that prompts the LLM to warmly ask for a user's name and phone number mid-conversation for VIP discounts.

## 2. Frontend / User Interface (React + Vite)
- **Streaming UI (Server-Sent Events)**: Real-time token-by-token generation so users don't wait for the full response.
- **Dynamic Welcome Messages**: Rotates randomly through 5 different welcome greetings (Bucky the adventure concierge).
- **Persistent LocalStorage State**: Chat UI saves the conversation locally so users can refresh the page safely.
- **Auto-Scroll & Typing Indicators**: Smooth scrolling to the bottom of the chat and dynamic loading phrases ("Scouting the best adventure spots...").
- **Activity Clickable Modals**: Clicking on an activity in the UI opens a detailed Activity Modal.
- **Lead Capture Modal**: A manual button in the header allowing users to submit their contact info.
- **Login Prompt Banner**: Intercepts chat to ask for OTP authentication when the user tries to add something to their cart.
- **File Attachment Picker**: UI to select, preview, and upload multiple files into the chat.
- **Error Masking**: Raw backend JSON errors are intercepted and rendered as friendly alerts ("My servers are a bit overloaded...").

## 3. Attachments & Multimodal
- **Multi-format Support**: Users can attach images (`.jpg`, `.png`), `.pdf`, `.docx`, and `.txt` files.
- **Vision LLM Processing**: Images and PDFs are converted to base64 and sent directly to Anthropic's Vision API.
- **Local Disk Temp Storage**: Binary blobs bypass Redis and sit on an isolated local disk with a 2-hour TTL sweeper to prevent memory exhaustion.
- **Prompt Injection Warnings**: Uploaded text/documents are wrapped in a system warning instructing the AI to treat them as raw data and ignore any embedded instructions.

## 4. Security & Hardening
- **ClamAV Anti-Malware**: Every single byte of uploaded files is piped to a `clamd` container to block viruses before processing.
- **Zip-Bomb Protection**: When extracting `.docx` files, the system tracks uncompressed size and halts at 50MB to prevent decompression memory exhaustion.
- **XXE Prevention**: `defusedxml` is used for `.docx` XML parsing to block XML External Entity exploits.
- **MIME Magic-Byte Sniffing**: Uses `filetype` to verify actual file headers instead of trusting the user's file extension.
- **Anonymous File Storage**: Original filenames are discarded and replaced with UUIDs to prevent directory traversal and injection.
- **IP Rate Limiting**: Chat endpoints and upload endpoints are protected by `RateLimitMiddleware` to prevent volumetric DDoS.
- **Fail-Closed Architecture**: If ClamAV is unreachable, uploads are strictly rejected (HTTP 503) rather than silently bypassing the scan.

## 5. Performance & Architecture
- **Anthropic Prompt Caching**: The system prompt and massive catalog tool responses are heavily cached, slashing costs and latency.
- **Dynamic Cache Limits**: `_enforce_cache_limits` dynamically scrubs excess cache tags during heavy tool use, completely bypassing Anthropic's 4-block API restriction and preventing crashes.
- **MCP Connection Reuse (Fast Path)**: Instead of creating a new JSON-RPC tunnel for every tool call, a single session is pre-warmed per turn and shared concurrently across parallel tool executions.
- **Redis Session Store**: Conversation histories are stored in Redis with a 2-hour TTL.
- **Dockerized Infrastructure**: Entire stack (Frontend, Backend, Redis, Weaviate, ClamAV) is fully containerized via `docker-compose`.

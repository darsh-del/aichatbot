# Latest Chatbot Updates & Features

This document outlines the recent architecture changes, bug fixes, and a comprehensive list of all current functionalities implemented in the chatbot.

## 🛠️ Prior Issues & Resolutions

### 1. Anthropic Prompt Caching Crashes (400 Bad Request)
**The Issue:** The Anthropic API restricts developers to a maximum of 4 `cache_control` blocks per request. When the AI model decided to execute multiple tools in parallel during a single turn, the backend blindly appended `cache_control` tags to every tool result. If 4 or more tools were called, the request exceeded the hard limit and instantly crashed the stream with an ugly `liteLLM.BadRequestError` in the frontend.
**The Solution:** Implemented a new `_enforce_cache_limits` interceptor function. Right before dispatching to the LLM, this function scans the message history, guarantees the system prompt retains its cache tag (since it's the largest), and dynamically strips cache tags off the oldest tool responses until the total count is strictly ≤ 4. This guarantees the chatbot will never crash from this limit, regardless of how many tools are executed.

### 2. Poor User Experience on Upstream Errors
**The Issue:** When legitimate API errors occurred (e.g., Anthropic servers going down, rate limits exceeded, context window limits), the raw developer exception string was forwarded directly to the user interface via Server-Sent Events (SSE) and displayed as a red alert box.
**The Solution:** Overhauled the global `stream_chat_response` error handler. The backend now intercepts raw Python exceptions, alerts the development team silently via background logs, and maps the error to a friendly, conversational fallback response (e.g., *"My servers are a bit overloaded right now. Give me just a second to catch my breath and try again!"* or *"You have reached the limit of your messages. Please wait a moment before trying again."*).

### 3. High Latency on Concurrent Tool Calls
**The Issue:** The Model Context Protocol (MCP) requires a JSON-RPC `initialize` handshake when connecting to the catalog server. When the AI initiated 3 or 4 tool calls concurrently (e.g., looking up multiple adventure prices at once), the backend was spinning up a separate JSON-RPC session for *each* tool call, paying the 150ms connection penalty multiple times.
**The Solution:** Refactored the `_run_tool_loop` to instantiate exactly one pre-warmed `mcp_session` at the beginning of the turn. All concurrent tool executions now share this exact same pre-warmed connection natively, shaving off hundreds of milliseconds in response latency during heavy tool usage.

---

## 🌟 Comprehensive Features List

### 1. Core Conversational AI
* **Live Catalog Integration (MCP)**: Fetches real-time pricing, availability, and time slots directly from the database using Model Context Protocol tools.
* **Knowledge Base RAG**: Uses a Weaviate vector database to retrieve semantically relevant information from the company knowledge base (e.g., safety rules, refund policies).
* **Streaming Responses (SSE)**: The AI's response streams token-by-token to the frontend for a fast, snappy user experience.
* **Persistent Sessions**: Chat history is stored in a Redis database, allowing users to refresh the page and pick up right where they left off.
* **OTP Authentication & Lead Capture**: The bot can smoothly prompt the user for their phone number, send a real OTP, verify it, and save them as a lead.

### 2. Multimodal Attachments
* **File Uploads**: Users can upload Images, PDFs, Word Documents (`.docx`), and text files.
* **ClamAV Malware Scanning**: Every single file uploaded is piped into a local antivirus container to scan for viruses before processing.
* **Document Parsing Security**: `.docx` files are safely processed with zip-bomb limits and `defusedxml` to prevent memory exhaustion and XML External Entity (XXE) server exploits.
* **Type & Size Enforcement**: Enforces MIME-type magic-byte sniffing (blocking spoofed file extensions) and hard file size limits (5MB for images/PDFs, 2MB for text).

### 3. Security & Guardrails
* **Domain Scope Guardrails**: Strict instructions in the System Prompt and RAG context force the AI to refuse to answer off-topic queries (e.g., coding, politics) or invent fake pricing.
* **LLM Prompt Injection Defense**: Uploaded files are forcefully fenced off with a system warning so that users cannot use attachments to trick the AI into ignoring its main instructions.
* **Endpoint Rate Limiting**: The chat and attachment upload endpoints are protected by IP-based rate limiting to prevent spam and volumetric abuse.
* **Infrastructure Isolation**: Binary blobs are saved to an isolated local disk temp directory with a 2-hour TTL sweeper, completely avoiding Redis memory exhaustion.

### 4. Performance Optimizations
* **Anthropic Prompt Caching**: System prompts and tool results are cached on the LLM side, dramatically reducing API costs and speeding up responses.
* **Fast Path Transport**: Connection reuse logic eliminates overhead during concurrent network calls.

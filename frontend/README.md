# AI Chatbot — Frontend

A minimal, production-ready chat UI built with Vite + React + TypeScript. It
speaks the `/api/chat` SSE contract described below over plain `fetch()` —
there is no framework-specific backend client.

## Setup

```bash
npm install
```

## Dev server

```bash
npm run dev
```

Runs on the default Vite port, `http://localhost:5173`.

## Configuration

Set the backend base URL via env var (see `.env.example`):

```bash
VITE_API_BASE_URL=http://localhost:8000
```

Defaults to `http://localhost:8000` if unset. Copy `.env.example` to `.env`
and edit as needed.

## Build / test / lint

```bash
npm run build   # tsc -b && vite build -> dist/
npm run test    # vitest run
npm run lint    # eslint .
```

## Docker

```bash
docker build -t chatbot-frontend .
docker run -p 8080:80 chatbot-frontend
```

Multi-stage build: compiles the Vite app in a `node` stage, then serves the
static `dist/` output via `nginx:alpine` on port 80.

## Backend-agnostic

This UI only depends on the `/api/chat` SSE contract (`POST` a message
list, receive `data: {"delta", "done"}` frames) and `/api/health`. It works
against any bot instance — customer-facing or internal — that speaks the
same contract, regardless of what's running behind it.

// Typed client for the chat backend's HTTP contract.
// Backend base URL is configurable so this UI can point at any bot
// instance that speaks the same /api/chat SSE contract.
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
}

export interface ChatRequest {
  messages: ChatMessage[]
  session_id?: string
}

export interface ChatStreamFrame {
  delta: string
  done: boolean
  error?: string
}

export interface HealthResponse {
  status: string
  model: string
}

/** GET /api/health */
export async function getHealth(
  baseUrl: string = API_BASE_URL,
): Promise<HealthResponse> {
  const res = await fetch(`${baseUrl}/api/health`)
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status} ${res.statusText}`)
  }
  return (await res.json()) as HealthResponse
}

/**
 * POST /api/chat and stream the response.
 *
 * The backend responds with `text/event-stream`, one `data: <json>\n\n`
 * frame per chunk. Each frame is a ChatStreamFrame. This function decodes
 * the stream and invokes `onDelta` for every content chunk as it arrives.
 * It resolves once a frame with `done: true` is received, throwing if that
 * frame carries an `error`.
 */
export async function streamChat(
  request: ChatRequest,
  onDelta: (delta: string) => void,
  options: { baseUrl?: string; signal?: AbortSignal } = {},
): Promise<void> {
  const { baseUrl = API_BASE_URL, signal } = options

  const res = await fetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })

  if (!res.ok || !res.body) {
    throw new Error(`Chat request failed: ${res.status} ${res.statusText}`)
  }

  const reader = res.body
    .pipeThrough(new TextDecoderStream())
    .getReader()

  let buffer = ''

  const handleFrame = (rawFrame: string): boolean => {
    // Each SSE frame is one or more lines; we only care about `data:` lines.
    const dataLines = rawFrame
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim())
    if (dataLines.length === 0) return false

    const payload = JSON.parse(dataLines.join('')) as ChatStreamFrame
    if (payload.delta) onDelta(payload.delta)
    if (payload.done) {
      if (payload.error) throw new Error(payload.error)
      return true
    }
    return false
  }

  try {
    while (true) {
      const { value, done: readerDone } = await reader.read()
      if (value) buffer += value
      // SSE frames are separated by a blank line.
      let sepIndex: number
      while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
        const rawFrame = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)
        if (rawFrame.trim() && handleFrame(rawFrame)) return
      }
      if (readerDone) {
        if (buffer.trim()) handleFrame(buffer)
        return
      }
    }
  } finally {
    reader.releaseLock()
  }
}

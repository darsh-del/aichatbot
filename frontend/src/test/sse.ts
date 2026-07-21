// Test helper: build a fetch-Response-like object streaming canned SSE frames.
export function makeSSEResponse(frames: string[]): Response {
  const encoder = new TextEncoder()
  let i = 0
  const stream = new ReadableStream<Uint8Array>({
    // Real network streaming has a macrotask boundary between chunks; without
    // one here, the whole stream drains within one microtask burst and tests
    // can't observe transient in-flight state (e.g. input disabled).
    pull(controller) {
      return new Promise<void>((resolve) => {
        setTimeout(() => {
          if (i < frames.length) {
            controller.enqueue(encoder.encode(frames[i]))
            i++
          } else {
            controller.close()
          }
          resolve()
        }, 0)
      })
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

export function sseFrame(delta: string, done = false, error?: string): string {
  const payload = JSON.stringify({ delta, done, ...(error ? { error } : {}) })
  return `data: ${payload}\n\n`
}

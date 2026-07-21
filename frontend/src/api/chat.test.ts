import { describe, expect, it, vi } from 'vitest'
import { streamChat } from './chat'
import { makeSSEResponse, sseFrame } from '../test/sse'

describe('streamChat', () => {
  it('parses SSE frames, invokes onDelta incrementally, and resolves on done', async () => {
    const frames = [sseFrame('Hel'), sseFrame('lo '), sseFrame('there'), sseFrame('', true)]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse(frames)))

    const deltas: string[] = []
    await streamChat({ messages: [{ role: 'user', content: 'hi' }] }, (d) => deltas.push(d))

    expect(deltas).toEqual(['Hel', 'lo ', 'there'])
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/chat',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('throws when the final frame carries an error', async () => {
    const frames = [sseFrame('oops'), sseFrame('', true, 'model unavailable')]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse(frames)))

    await expect(
      streamChat({ messages: [{ role: 'user', content: 'hi' }] }, () => {}),
    ).rejects.toThrow('model unavailable')
  })
})

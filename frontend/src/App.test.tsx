import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { makeSSEResponse, sseFrame } from './test/sse'

describe('App', () => {
  it('clears the input and shows a new user bubble on submit', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(makeSSEResponse([sseFrame('', true)])),
    )
    const user = userEvent.setup()
    render(<App />)

    const input = screen.getByLabelText('Message')
    await user.type(input, 'Hello there')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(screen.getByText('Hello there')).toBeInTheDocument()
    expect(input).toHaveValue('')
  })

  it('appends streamed deltas into the assistant bubble and re-enables input after done', async () => {
    const frames = [sseFrame('Hi'), sseFrame(' there'), sseFrame('!'), sseFrame('', true)]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse(frames)))
    const user = userEvent.setup()
    render(<App />)

    const input = screen.getByLabelText('Message')
    await user.type(input, 'Hi')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(input).toBeDisabled()

    await waitFor(() => expect(screen.getByText('Hi there!')).toBeInTheDocument())
    await waitFor(() => expect(input).not.toBeDisabled())
  })

  it('opens and submits human lead escalation modal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(makeSSEResponse([sseFrame('Escalation created'), sseFrame('', true)])),
    )
    const user = userEvent.setup()
    render(<App />)

    // Click Human Callback button
    const callbackBtn = screen.getAllByRole('button', { name: /callback/i })[0]
    await user.click(callbackBtn)

    expect(screen.getByText(/human support & group lead escalation/i)).toBeInTheDocument()

    // Fill lead details
    await user.type(screen.getByLabelText(/your name/i), 'Rahul Sharma')
    await user.type(screen.getByLabelText(/whatsapp \/ phone/i), '+919876543210')

    // Submit lead form
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    // Modal closes & prompt is sent
    await waitFor(() => expect(screen.queryByText(/human support & group lead escalation/i)).not.toBeInTheDocument())
  })
})

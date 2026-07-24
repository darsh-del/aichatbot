import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { streamChat } from './api/chat'
import type { ChatMessage } from './api/chat'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { QuickChips } from './components/QuickChips'
import { LeadModal } from './components/LeadModal'
import { MessageContent } from './components/MessageContent'
import './App.css'

interface DisplayMessage extends ChatMessage {
  id: number
}

let nextId = 0

function App() {
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLeadModalOpen, setIsLeadModalOpen] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, isStreaming])

  const sendPromptMessage = async (text: string) => {
    if (!text || isStreaming) return

    setError(null)
    const userMessage: DisplayMessage = { id: nextId++, role: 'user', content: text }
    const assistantMessage: DisplayMessage = { id: nextId++, role: 'assistant', content: '' }
    const history = [...messages, userMessage]

    setMessages([...history, assistantMessage])
    setInput('')
    setIsStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamChat(
        { messages: history.map(({ role, content }) => ({ role, content })) },
        (delta) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessage.id ? { ...m, content: m.content + delta } : m,
            ),
          )
        },
        { signal: controller.signal },
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    sendPromptMessage(input.trim())
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter submits; Shift+Enter inserts a newline (textarea default).
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      sendPromptMessage(input.trim())
    }
  }

  const handleNewChat = () => {
    if (isStreaming && abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setIsStreaming(false)
    }
    setMessages([])
    setError(null)
  }

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setIsStreaming(false)
    }
  }

  return (
    <div className="app-viewport">
      <Sidebar
        onSelectPrompt={sendPromptMessage}
        onNewChat={handleNewChat}
      />

      <main className="chat-main-area">
        <Header onOpenCallbackModal={() => setIsLeadModalOpen(true)} />

        <div className="message-feed" aria-live="polite">
          {messages.length === 0 && (
            <div className="minimal-welcome-card">
              <div className="welcome-avatar">🪂</div>
              <h2>Where does your bucket list take you?</h2>
              <p>
                Ask about <strong>Bungee Jumping (117m)</strong>, <strong>Rafting (9-35km)</strong>, <strong>Paragliding</strong>, prices, safety rules, or group discounts!
              </p>

              <div className="quick-feature-grid">
                <div className="feature-card">
                  <span className="icon">⚡</span>
                  <div>
                    <strong>Pay 10% Only</strong>
                    <span>Confirm booking with 10% deposit</span>
                  </div>
                </div>

                <div className="feature-card">
                  <span className="icon">🛡️</span>
                  <div>
                    <strong>Verified Safety</strong>
                    <span>Certified & hand-picked operators</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className={`message-row row--${m.role}`}>
              <MessageContent content={m.content} role={m.role} />
            </div>
          ))}

          {isStreaming && (
            <div className="message-row row--assistant">
              <div className="typing-assistant-card">
                <div className="assistant-avatar-badge">
                  <span>🪂</span>
                </div>
                <div className="typing-indicator-box">
                  <div className="typing-indicator" data-testid="typing-indicator">
                    <span />
                    <span />
                    <span />
                  </div>
                  <span className="typing-label">Searching Bucketlistt Knowledge Base...</span>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="error-banner" role="alert">
              ❌ {error}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <QuickChips onSelectPrompt={sendPromptMessage} disabled={isStreaming} />

        <form className="composer-bar" onSubmit={handleSubmit}>
          <textarea
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question or request group quote... (Shift+Enter for new line)"
            disabled={isStreaming}
            aria-label="Message"
          />

          {isStreaming ? (
            <button type="button" className="stop-action-btn" onClick={handleStop}>
              ⏹ Stop
            </button>
          ) : (
            <button type="submit" disabled={!input.trim()} className="send-action-btn">
              Send ➔
            </button>
          )}
        </form>
      </main>

      <LeadModal
        isOpen={isLeadModalOpen}
        onClose={() => setIsLeadModalOpen(false)}
        onSubmitLead={sendPromptMessage}
      />
    </div>
  )
}

export default App

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

const uuid = (): string =>
  crypto.randomUUID?.() ??
  (Math.random().toString(36) + Math.random().toString(36)).replace(/0\./g, '').slice(0, 16)

// Feature 01 — Dynamic welcome messages (rotated randomly for freshness)
const WELCOME_MESSAGES = [
  "Hey! I'm Bucky, your adventure concierge 🪂 Ask me about bungee jumping, river rafting, paragliding, prices, safety, group discounts — or just tell me what kind of thrill you're after!",
  "Hey there! I'm Bucky 🪂 Ready to plan something epic? I can help with bungee, rafting, paragliding — or surprise me with what's on your bucket list!",
  "Hi! Bucky here — your go-to for adventure in Rishikesh and beyond 🏔️ Whether it's prices, safety info, or booking a 117m bungee jump, I've got you covered!",
  "Welcome! I'm Bucky, and I live for this stuff 🪂 Bungee off a cliff? Raft the Ganges? Paraglide over the mountains? Tell me what excites you and let's make it happen!",
  "Hey! I'm Bucky — think of me as your adventure-planning buddy 🙌 Ask me anything about activities, prices, group discounts, or what to expect on your first jump!",
]

const pickWelcome = () => WELCOME_MESSAGES[Math.floor(Math.random() * WELCOME_MESSAGES.length)]

// Marker to identify any welcome message when filtering API payloads
const isWelcomeMsg = (content: string) => WELCOME_MESSAGES.includes(content)

interface DisplayMessage extends ChatMessage {
  id: number
}

let nextId = 0

// Feature 02 — Persist chat on refresh
const STORAGE_KEY = 'bucketlistt_chat'
const SESSION_KEY = 'bucketlistt_session'

function loadMessages(): DisplayMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function loadSession(): string {
  return localStorage.getItem(SESSION_KEY) || uuid()
}

// Fix nextId counter from persisted messages
const _saved = loadMessages()
if (_saved.length) nextId = Math.max(..._saved.map(m => m.id)) + 1

const LOADING_PHRASES = [
  'Scouting the best adventure spots...',
  'Checking the wind conditions...',
  'Measuring the bungee cord...',
  'Consulting the mountain guides...',
  'Scanning the rapids...',
  'Tuning the adventure radar...',
  'Mapping your next thrill...',
  'Lacing up the hiking boots...',
  'Polishing the safety gear...',
  'Asking the river gods...',
  'Counting the parachutes...',
  'Warming up for takeoff...',
  'Loading up the adventure van...',
  'Calibrating the altimeter...',
  'Untangling the ropes...',
  'Brewing some adventure fuel...',
  'Chasing the adrenaline...',
  'Gearing up for the expedition...',
  'Scouring the trails ahead...',
  'Summoning the adventure spirit...',
]

function App() {
  const [messages, setMessages] = useState<DisplayMessage[]>(() => {
    const saved = loadMessages()
    return saved.length ? saved : [{ id: nextId++, role: 'assistant', content: pickWelcome() }]
  })
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLeadModalOpen, setIsLeadModalOpen] = useState(false)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const [loadingPhrase, setLoadingPhrase] = useState(LOADING_PHRASES[0])

  const abortRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)
  // One id per conversation, so the backend can reuse the login token across
  // turns (and not re-prompt for the OTP). Reset on New Conversation.
  const sessionIdRef = useRef<string>(loadSession())

  // Feature 02 — sync messages & session to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
  }, [messages])
  useEffect(() => {
    localStorage.setItem(SESSION_KEY, sessionIdRef.current)
  }, [])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, isStreaming])

  useEffect(() => {
    if (!isStreaming) return
    const id = setInterval(() => {
      setLoadingPhrase(LOADING_PHRASES[Math.floor(Math.random() * LOADING_PHRASES.length)])
    }, 2500)
    return () => clearInterval(id)
  }, [isStreaming])

  const sendPromptMessage = async (text: string) => {
    if (!text || isStreaming) return

    setError(null)
    const userMessage: DisplayMessage = { id: nextId++, role: 'user', content: text }
    const assistantMessage: DisplayMessage = { id: nextId++, role: 'assistant', content: '' }
    const history = [...messages, userMessage]

    setMessages([...history, assistantMessage])
    setInput('')
    setIsStreaming(true)
    setToolStatus(null)

    const controller = new AbortController()
    abortRef.current = controller

    // Feature 01 — filter welcome message from API payload (it's UI-only)
    const apiMessages = history
      .filter(m => !(m.role === 'assistant' && isWelcomeMsg(m.content)))
      .map(({ role, content }) => ({ role, content }))

    let fullContent = ''
    try {
      await streamChat(
        {
          messages: apiMessages,
          session_id: sessionIdRef.current,
        },
        (delta) => {
          fullContent += delta
          setToolStatus(null)
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessage.id ? { ...m, content: m.content + delta } : m,
            ),
          )
        },
        { signal: controller.signal, onStatus: setToolStatus },
      )
      if (fullContent.includes('bucketlistt.com/experiences/cart')) {
        window.open('https://www.bucketlistt.com/experiences/cart', '_blank')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setIsStreaming(false)
      setToolStatus(null)
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
    setMessages([{ id: nextId++, role: 'assistant', content: pickWelcome() }])
    setError(null)
    localStorage.removeItem(STORAGE_KEY)
    sessionIdRef.current = uuid()  // fresh session = fresh login
    localStorage.setItem(SESSION_KEY, sessionIdRef.current)
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
              <h2>Hey, I'm Bucky 🪂 Where's your bucket list taking you?</h2>
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
                  <span className="typing-label">{toolStatus || loadingPhrase}</span>
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
            placeholder="Ask Bucky anything about your next adventure... (Shift+Enter for new line)"
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

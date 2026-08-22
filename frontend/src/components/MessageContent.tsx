import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MessageContentProps {
  content: string
  role: 'user' | 'assistant'
  onActivityClick?: (activityId: string) => void
}

const CART_URL = 'https://www.bucketlistt.com/experiences/cart'
const CART_URL_RE = /https?:\/\/(?:www\.)?bucketlistt\.com\/cart\b(?![\w/])/g
const ACTIVITY_LINK_PREFIX = 'activity:'

export const MessageContent: React.FC<MessageContentProps> = ({ content, role, onActivityClick }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (role === 'user') {
    return <div className="user-bubble-text">{content}</div>
  }

  // Rewrite any old /cart links to /experiences/cart before rendering
  const normalized = content.replace(CART_URL_RE, CART_URL)

  const ticketMatch = normalized.match(/LEAD-\d{5}/)
  const ticketId = ticketMatch ? ticketMatch[0] : null
  const hasCartLink = normalized.includes('bucketlistt.com/experiences/cart')

  return (
    <div className="assistant-card">
      <div className="assistant-avatar-badge">
        <span>🪂</span>
      </div>

      <div className="assistant-card-body">
        {hasCartLink && (
          <div className="cart-redirect-card">
            <div className="cart-card-header">
              <span className="cart-badge">🛒 Added to Cart</span>
            </div>
            <p className="cart-card-desc">
              Your items are ready! Complete payment on Bucketlistt to confirm your booking.
            </p>
            <a
              href="https://www.bucketlistt.com/experiences/cart"
              target="_blank"
              rel="noopener noreferrer"
              className="cart-pay-btn"
            >
              Go to Cart & Pay →
            </a>
          </div>
        )}

        {ticketId && (
          <div className="lead-ticket-card">
            <div className="ticket-header">
              <span className="ticket-badge">🎉 Escalation Ticket Created</span>
              <span className="ticket-id">#{ticketId}</span>
            </div>
            <p className="ticket-desc">
              Your human callback request has been logged. A Bucketlistt specialist will contact you on WhatsApp shortly!
            </p>
            <div className="ticket-footer">
              <span className="ticket-status">● Priority Callback Pending</span>
              <a
                href="https://wa.me/918511838237"
                target="_blank"
                rel="noopener noreferrer"
                className="whatsapp-direct-btn"
              >
                💬 WhatsApp Us Direct
              </a>
            </div>
          </div>
        )}

        <div className="formatted-text-wrapper">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ node: _n, href, ...props }) => {
                if (href?.startsWith(ACTIVITY_LINK_PREFIX)) {
                  const activityId = href.slice(ACTIVITY_LINK_PREFIX.length)
                  return (
                    <a
                      {...props}
                      href={href}
                      className="styled-chat-link activity-link"
                      onClick={(e) => {
                        e.preventDefault()
                        onActivityClick?.(activityId)
                      }}
                    />
                  )
                }
                return (
                  <a {...props} href={href} target="_blank" rel="noopener noreferrer" className="styled-chat-link" />
                )
              },
              strong: ({ node: _n, ...props }) => <strong {...props} className="highlight-bold" />,
            }}
          >
            {content}
          </ReactMarkdown>
        </div>

        <button
          className={`copy-btn ${copied ? 'copied' : ''}`}
          onClick={handleCopy}
          aria-label="Copy message"
          title={copied ? 'Copied!' : 'Copy to clipboard'}
        >
          {copied ? '✓ Copied' : '📋 Copy'}
        </button>
      </div>
    </div>
  )
}

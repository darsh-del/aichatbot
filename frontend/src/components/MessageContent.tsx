import React from 'react'

interface MessageContentProps {
  content: string
  role: 'user' | 'assistant'
}

export const MessageContent: React.FC<MessageContentProps> = ({ content, role }) => {
  if (role === 'user') {
    return <div className="user-bubble-text">{content}</div>
  }

  // Detect Lead Ticket generation (e.g. LEAD-12345)
  const ticketMatch = content.match(/LEAD-\d{5}/)
  const ticketId = ticketMatch ? ticketMatch[0] : null

  // Helper to render markdown links, bold text, and bullet points nicely
  const renderFormattedParagraphs = (text: string) => {
    const lines = text.split('\n')
    return lines.map((line, idx) => {
      const trimmed = line.trim()
      if (!trimmed) return <div key={idx} className="line-spacer" />

      // Headers
      if (trimmed.startsWith('# ')) {
        return <h3 key={idx} className="content-h1">{trimmed.replace('# ', '')}</h3>
      }
      if (trimmed.startsWith('## ')) {
        return <h4 key={idx} className="content-h2">{trimmed.replace('## ', '')}</h4>
      }
      if (trimmed.startsWith('### ')) {
        return <h5 key={idx} className="content-h3">{trimmed.replace('### ', '')}</h5>
      }

      // Bullet items
      const isBullet = trimmed.startsWith('- ') || trimmed.startsWith('* ')
      const lineText = isBullet ? trimmed.substring(2) : trimmed

      // Parse markdown links [Label](url) or raw URLs
      const parts = lineText.split(/(https?:\/\/[^\s]+|\[[^\]]+\]\([^)]+\))/)
      const formattedParts = parts.map((part, i) => {
        const markdownLinkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
        if (markdownLinkMatch) {
          return (
            <a
              key={i}
              href={markdownLinkMatch[2]}
              target="_blank"
              rel="noopener noreferrer"
              className="styled-chat-link"
            >
              {markdownLinkMatch[1]} ↗
            </a>
          )
        }

        if (part.startsWith('http://') || part.startsWith('https://')) {
          const cleanUrl = part.replace(/[.,;)]$/, '')
          return (
            <a
              key={i}
              href={cleanUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="styled-chat-link"
            >
              {cleanUrl} ↗
            </a>
          )
        }

        // Handle bolding **text**
        const subParts = part.split(/(\*\*[^*]+\*\*)/)
        return subParts.map((sub, j) => {
          if (sub.startsWith('**') && sub.endsWith('**')) {
            return <strong key={j} className="highlight-bold">{sub.slice(2, -2)}</strong>
          }
          return sub
        })
      })

      if (isBullet) {
        return (
          <div key={idx} className="bullet-row">
            <span className="bullet-dot">•</span>
            <span className="bullet-text">{formattedParts}</span>
          </div>
        )
      }

      return <p key={idx} className="content-p">{formattedParts}</p>
    })
  }

  return (
    <div className="assistant-card">
      <div className="assistant-avatar-badge">
        <span>🪂</span>
      </div>

      <div className="assistant-card-body">
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
          {renderFormattedParagraphs(content)}
        </div>

        <div className="card-footer-strip">
          <span className="deposit-tag">⚡ Pay 10% Deposit Only</span>
          <span className="verify-tag">🛡️ Verified Operators</span>
        </div>
      </div>
    </div>
  )
}

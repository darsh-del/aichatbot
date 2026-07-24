import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MessageContentProps {
  content: string
  role: 'user' | 'assistant'
}

export const MessageContent: React.FC<MessageContentProps> = ({ content, role }) => {
  if (role === 'user') {
    return <div className="user-bubble-text">{content}</div>
  }

  const ticketMatch = content.match(/LEAD-\d{5}/)
  const ticketId = ticketMatch ? ticketMatch[0] : null

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
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ node: _n, ...props }) => (
                <a {...props} target="_blank" rel="noopener noreferrer" className="styled-chat-link" />
              ),
              strong: ({ node: _n, ...props }) => <strong {...props} className="highlight-bold" />,
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  )
}

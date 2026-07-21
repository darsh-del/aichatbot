import React from 'react'

interface HeaderProps {
  onOpenCallbackModal: () => void
}

export const Header: React.FC<HeaderProps> = ({ onOpenCallbackModal }) => {
  return (
    <header className="chat-topbar">
      <div className="topbar-info">
        <h2 className="chat-title">Bucketlistt Travel Concierge</h2>
        <span className="model-tag">gpt-4o-mini • Weaviate Vector DB</span>
      </div>

      <div className="topbar-actions">
        <span className="trust-pill-top">⚡ 10% Deposit Only</span>
        <button type="button" className="topbar-escalate-btn" onClick={onOpenCallbackModal}>
          <span>📞</span> Human Callback
        </button>
      </div>
    </header>
  )
}

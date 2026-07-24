import React from 'react'

interface HeaderProps {
  onOpenCallbackModal: () => void
}

export const Header: React.FC<HeaderProps> = ({ onOpenCallbackModal }) => {
  return (
    <header className="chat-topbar">
      <div className="topbar-info">
        <h2 className="chat-title">Bucketlistt Travel Concierge</h2>
      </div>

      <div className="topbar-actions">
        <button type="button" className="topbar-escalate-btn" onClick={onOpenCallbackModal}>
          <span>📞</span> Human Callback
        </button>
      </div>
    </header>
  )
}

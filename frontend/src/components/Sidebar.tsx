import React from 'react'

interface SidebarProps {
  onSelectPrompt: (prompt: string) => void
  onNewChat: () => void
}

const TOPICS = [
  { icon: '🪂', label: 'Bungee Jumping 117m', prompt: 'What are the bungee jumping prices and locations in Rishikesh?' },
  { icon: '🚣', label: 'River Rafting (9-35km)', prompt: 'Tell me about river rafting packages, distances (9/16/24/35km), and prices.' },
  { icon: '🪂', label: 'Paragliding Flights', prompt: 'What are the prices, flying time, and locations for Paragliding?' },
  { icon: '⛺', label: 'Camping & Combos', prompt: 'What river-side camping and activity combo packages are available?' },
  { icon: '⚖️', label: 'Flying Fox Safety', prompt: 'What are the weight and age limits for Flying Fox in Rishikesh?' },
]

export const Sidebar: React.FC<SidebarProps> = ({ onSelectPrompt, onNewChat }) => {
  return (
    <aside className="sidebar-nav">
      <div className="sidebar-brand">
        <div className="brand-logo-badge">
          <span>🪂</span>
        </div>
        <div className="brand-text">
          <span className="brand-title">bucketlistt</span>
          <span className="brand-sub">AI Assistant</span>
        </div>
      </div>

      <button type="button" className="new-chat-btn" onClick={onNewChat}>
        <span>+</span> New Conversation
      </button>

      <div className="sidebar-section">
        <span className="section-label">Explore Adventures</span>
        <div className="topic-list">
          {TOPICS.map((topic, idx) => (
            <button
              key={idx}
              type="button"
              className="topic-item"
              onClick={() => onSelectPrompt(topic.prompt)}
            >
              <span className="topic-icon">{topic.icon}</span>
              <span className="topic-name">{topic.label}</span>
            </button>
          ))}
        </div>
      </div>

    </aside>
  )
}

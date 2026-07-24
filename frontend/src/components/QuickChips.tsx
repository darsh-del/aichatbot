import React from 'react'

interface QuickChipsProps {
  onSelectPrompt: (prompt: string) => void
  disabled?: boolean
}

const CHIPS = [
  { label: '🪂 Bungee Jumping Prices', prompt: 'What are the prices and options for Bungee Jumping in Rishikesh?' },
  { label: '🚣 Rafting Packages (9/16/24/35km)', prompt: 'Tell me about the river rafting packages, distances, and prices in Rishikesh.' },
  { label: '🪂 Paragliding Guide', prompt: 'What are the prices, flying time, and locations for Paragliding?' },
  { label: '⚖️ Flying Fox Rules', prompt: 'What are the weight and age limits for Flying Fox in Rishikesh?' },
  { label: '👥 Group Booking (5+ People)', prompt: 'We are a group of 6 people looking for rafting and bungee discount packages.' },
]

export const QuickChips: React.FC<QuickChipsProps> = ({ onSelectPrompt, disabled }) => {
  return (
    <div className="quick-chips-bar">
      <span className="chips-title">Popular Topics:</span>
      <div className="chips-scroll">
        {CHIPS.map((chip, idx) => (
          <button
            key={idx}
            type="button"
            className="chip-button"
            disabled={disabled}
            onClick={() => onSelectPrompt(chip.prompt)}
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  )
}

import React, { useState } from 'react'

export interface UserInfo {
  name: string
  phone: string
  email: string
}

interface LoginPromptBannerProps {
  isVisible: boolean
  onSubmit: (userInfo: UserInfo) => void
  onDismiss: () => void
}

export function LoginPromptBanner({ isVisible, onSubmit, onDismiss }: LoginPromptBannerProps) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')

  if (!isVisible) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!phone) {
      alert("Phone number is required.")
      return
    }
    onSubmit({ name, phone, email })
  }

  return (
    <div className="login-prompt-banner slide-up-anim">
      <div className="login-prompt-header">
        <div className="login-prompt-icon-wrapper">
          <span className="login-prompt-icon">✨</span>
        </div>
        <div className="login-prompt-text">
          <strong>Elevate Your Adventure</strong>
          <p>Share your details to save this itinerary and get VIP access to exclusive slots & discounts.</p>
        </div>
        <button type="button" className="login-prompt-dismiss-x" onClick={onDismiss} aria-label="Dismiss">
          ✕
        </button>
      </div>

      <form className="login-prompt-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="login-prompt-input"
        />
        <input
          type="tel"
          placeholder="Phone Number *"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          required
          className="login-prompt-input"
        />
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="login-prompt-input"
        />
        <div className="login-prompt-actions">
          <button type="submit" className="btn-primary">Save My Details ✨</button>
        </div>
      </form>
    </div>
  )
}

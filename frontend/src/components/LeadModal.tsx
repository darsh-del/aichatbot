import React, { useState } from 'react'

interface LeadModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmitLead: (message: string) => void
}

export const LeadModal: React.FC<LeadModalProps> = ({ isOpen, onClose, onSubmitLead }) => {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [groupSize, setGroupSize] = useState('5')
  const [activity, setActivity] = useState('Rishikesh Bungee + Rafting Combo')
  const [notes, setNotes] = useState('')

  if (!isOpen) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!phone.trim()) return

    const promptMessage = `I want to request a human callback for a group booking. Name: ${name.trim() || 'Guest'}, Phone: ${phone.trim()}, Group Size: ${groupSize}, Interested Activity: ${activity}, Requirements: ${notes.trim() || 'Please call back with best group discount rates.'}`

    onSubmitLead(promptMessage)
    onClose()

    // Reset form
    setName('')
    setPhone('')
    setGroupSize('5')
    setNotes('')
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <h3>👥 Human Support & Group Lead Escalation</h3>
            <p>Connect with a Bucketlistt Specialist for bulk discounts & custom packages</p>
          </div>
          <button type="button" className="close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="lead-form">
          <div className="form-grid">
            <div className="form-group">
              <label htmlFor="lead-name">Your Name</label>
              <input
                id="lead-name"
                type="text"
                placeholder="e.g. Rahul Sharma"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label htmlFor="lead-phone">WhatsApp / Phone *</label>
              <input
                id="lead-phone"
                type="tel"
                required
                placeholder="+91 98765 43210"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label htmlFor="lead-size">Group Size</label>
              <select
                id="lead-size"
                value={groupSize}
                onChange={(e) => setGroupSize(e.target.value)}
              >
                <option value="1-4">1 - 4 People</option>
                <option value="5-10">5 - 10 People (Group Discount)</option>
                <option value="11-25">11 - 25 People (Corporate / College)</option>
                <option value="25+">25+ Large Event</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="lead-activity">Preferred Experience</label>
              <input
                id="lead-activity"
                type="text"
                placeholder="e.g. 16km Rafting, Himalayan Bungee, Camping"
                value={activity}
                onChange={(e) => setActivity(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="lead-notes">Special Requirements / Target Date</label>
            <textarea
              id="lead-notes"
              rows={2}
              placeholder="e.g. Target date is next Saturday, need transport from Tapovan"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary">
              ⚡ Submit Request & Generate Ticket
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

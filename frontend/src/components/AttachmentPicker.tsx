import React, { useRef, useState } from 'react'
import { uploadAttachment } from '../api/chat'
import type { PendingAttachment } from '../api/chat'

interface AttachmentPickerProps {
  attachments: PendingAttachment[]
  onChange: (attachments: PendingAttachment[]) => void
  disabled?: boolean
}

const ACCEPTED = '.jpg,.jpeg,.png,.pdf,.txt,.docx'
const MAX_FILES = 5

export const AttachmentPicker: React.FC<AttachmentPickerProps> = ({ attachments, onChange, disabled }) => {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    if (attachments.length + files.length > MAX_FILES) {
      setError(`Up to ${MAX_FILES} files per message.`)
      return
    }
    setError(null)
    setUploading(true)
    try {
      const uploaded = await Promise.all(
        Array.from(files).map(async (file) => {
          const result = await uploadAttachment(file)
          return { id: result.attachment_id, filename: result.filename, type: result.type }
        }),
      )
      onChange([...attachments, ...uploaded])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const removeAttachment = (id: string) => onChange(attachments.filter((a) => a.id !== id))

  return (
    <div className="attachment-picker">
      {attachments.length > 0 && (
        <div className="attachment-chips">
          {attachments.map((a) => (
            <span key={a.id} className="attachment-chip">
              📎 {a.filename}
              <button type="button" onClick={() => removeAttachment(a.id)} aria-label={`Remove ${a.filename}`}>
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        multiple
        hidden
        onChange={(e) => handleFiles(e.target.files)}
      />
      <button
        type="button"
        className="attach-btn"
        disabled={disabled || uploading}
        onClick={() => inputRef.current?.click()}
        title="Attach a file"
        aria-label="Attach a file"
      >
        {uploading ? '⏳' : '📎'}
      </button>
      {error && <span className="attachment-error">{error}</span>}
    </div>
  )
}

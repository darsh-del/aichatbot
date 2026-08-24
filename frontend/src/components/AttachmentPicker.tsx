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
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{marginRight: '4px'}}><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg> {a.filename}
              <button type="button" onClick={() => removeAttachment(a.id)} aria-label={`Remove ${a.filename}`}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
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
        style={{ background: '#F5F5F4', color: '#1C1917', border: '1px solid #E7E5E4', borderRadius: '12px', cursor: 'pointer', padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        {uploading ? (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
        ) : (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
        )}
      </button>
      {error && <span className="attachment-error">{error}</span>}
    </div>
  )
}

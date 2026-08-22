import React, { useEffect, useState } from 'react'
import { getActivity } from '../api/chat'

interface ActivityModalProps {
  activityId: string | null
  onClose: () => void
}

// Bare-bones field reader — the catalog's real shape varies by activity type,
// so this pulls out the common fields defensively rather than assuming a
// fixed schema. Stub: style/extend once you see real responses.
export const ActivityModal: React.FC<ActivityModalProps> = ({ activityId, onClose }) => {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!activityId) return
    setData(null)
    setError(null)
    setLoading(true)
    getActivity(activityId)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [activityId])

  if (!activityId) return null

  const title = (data?.title as string) || 'Activity details'
  const actualPrice = data?.actualPrice as number | undefined
  const discountedPrice = data?.discountedPrice as number | undefined
  const description = data?.description as string | undefined
  const subtitle = data?.subtitle as string | undefined

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content activity-modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <h3>{loading ? 'Loading…' : title}</h3>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button type="button" className="close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="activity-modal-body">
          {loading && <p>Fetching the latest details…</p>}

          {error && <p className="error-banner" role="alert">❌ {error}</p>}

          {data && !loading && (
            <>
              {(actualPrice || discountedPrice) && (
                <p className="activity-modal-price">
                  {discountedPrice && actualPrice && discountedPrice !== actualPrice ? (
                    <>
                      <s>₹{actualPrice.toLocaleString('en-IN')}</s>{' '}
                      ₹{discountedPrice.toLocaleString('en-IN')}
                    </>
                  ) : (
                    <>₹{(discountedPrice ?? actualPrice)?.toLocaleString('en-IN')}</>
                  )}
                </p>
              )}
              {description && <p className="activity-modal-desc">{description}</p>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

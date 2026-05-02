import type { ReactNode } from 'react'

interface StatusPillProps {
  label: string
  value: ReactNode
  tone?: 'neutral' | 'success'
}

export default function StatusPill({ label, value, tone = 'neutral' }: StatusPillProps) {
  return (
    <div className="status-pill">
      <span className={`status-dot status-dot--${tone}`} aria-hidden="true" />
      <span className="status-pill__label">{label}</span>
      <span className="status-pill__value">{value}</span>
    </div>
  )
}

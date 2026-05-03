import { useState } from 'react'
import type { CreateUpscalePayload } from '../../types/result'

interface UpscaleFormProps {
  onSubmit?: (payload: CreateUpscalePayload) => void
  isSubmitting?: boolean
}

export default function UpscaleForm({ onSubmit, isSubmitting = false }: UpscaleFormProps) {
  const [scale, setScale] = useState(2)

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit?.({
      model: 'seedvr2',
      scale_mode: 'factor',
      scale,
      replace_source: false,
    })
  }

  return (
    <form className="upscale-form" onSubmit={handleSubmit}>
      <label>
        <span>超分倍率</span>
        <select value={scale} onChange={(event) => setScale(Number(event.target.value))} disabled={isSubmitting}>
          <option value={2}>2x SeedVR2</option>
          <option value={4}>4x SeedVR2</option>
        </select>
      </label>
      <button type="submit" className="primary-action" disabled={isSubmitting}>
        {isSubmitting ? '创建中…' : '创建超分版本'}
      </button>
    </form>
  )
}

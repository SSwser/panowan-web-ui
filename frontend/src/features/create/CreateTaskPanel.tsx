import { useMemo, useState } from 'react'
import type { CreateResultPayload } from '../../types/result'

interface CreateTaskPanelProps {
  onSubmit: (payload: CreateResultPayload) => void
  isSubmitting?: boolean
}

const draftPreset = {
  num_inference_steps: 20,
  width: 448,
  height: 224,
}

const standardPreset = {
  num_inference_steps: 50,
  width: 896,
  height: 448,
}

export default function CreateTaskPanel({ onSubmit, isSubmitting = false }: CreateTaskPanelProps) {
  const [prompt, setPrompt] = useState('A cinematic alpine valley at sunset with drifting clouds and wide panoramic motion.')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [quality, setQuality] = useState<CreateResultPayload['quality']>('standard')
  const [seed, setSeed] = useState(0)

  const selectedPreset = useMemo(() => {
    if (quality === 'draft') {
      return draftPreset
    }

    // Custom keeps the standard preset until the dedicated controls land so the submit payload stays aligned with the current API contract.
    return standardPreset
  }, [quality])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    onSubmit({
      prompt,
      negative_prompt: negativePrompt,
      quality,
      params: {
        ...selectedPreset,
        seed,
      },
    })
  }

  return (
    <form className="create-task-panel" onSubmit={handleSubmit}>
      <label>
        <span>Prompt</span>
        <textarea
          name="prompt"
          rows={5}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </label>

      <label>
        <span>Negative Prompt</span>
        <textarea
          name="negativePrompt"
          rows={3}
          value={negativePrompt}
          onChange={(event) => setNegativePrompt(event.target.value)}
        />
      </label>

      <div className="quality-group">
        <span>质量预设</span>
        <div className="segmented" role="group" aria-label="质量预设">
          <button type="button" className={quality === 'draft' ? 'active' : ''} onClick={() => setQuality('draft')}>
            草稿
          </button>
          <button type="button" className={quality === 'standard' ? 'active' : ''} onClick={() => setQuality('standard')}>
            标准
          </button>
          <button type="button" className={quality === 'custom' ? 'active' : ''} onClick={() => setQuality('custom')}>
            自定义
          </button>
        </div>
      </div>

      <div className="preset-summary" aria-live="polite">
        <span>
          {selectedPreset.num_inference_steps} 步 · {selectedPreset.width}×{selectedPreset.height}
        </span>
        <span>Seed {seed}</span>
      </div>

      <label>
        <span>Seed</span>
        <input
          type="number"
          name="seed"
          value={seed}
          onChange={(event) => setSeed(Number(event.target.value) || 0)}
        />
      </label>

      <p className="estimate">当前预设先对齐后端 CreateResultPayload，后续任务再补充自定义参数编辑能力。</p>

      <button type="submit" className="primary-action" disabled={isSubmitting}>
        {isSubmitting ? '提交中…' : '提交任务'}
      </button>
    </form>
  )
}

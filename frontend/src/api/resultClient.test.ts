import { describe, expect, it, vi } from 'vitest'
import { createResult, fetchResults } from './resultClient'

describe('resultClient', () => {
  it('fetches result summaries', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ results: [{ result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'Prompt', status: 'completed', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:01:00Z', versions: [] }] }), { status: 200 })))

    const results = await fetchResults()

    expect(results[0].result_id).toBe('res_job_1')
    expect(fetch).toHaveBeenCalledWith('/api/results')
  })

  it('creates a result with workbench payload', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ result: { result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'Prompt', status: 'queued', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:00:00Z', versions: [] } }), { status: 202 })))

    const result = await createResult({ prompt: 'Prompt', negative_prompt: '', quality: 'draft', params: { num_inference_steps: 20, width: 448, height: 224, seed: 0 } })

    expect(result.result_id).toBe('res_job_1')
    expect(fetch).toHaveBeenCalledWith('/api/results', expect.objectContaining({ method: 'POST' }))
  })
})

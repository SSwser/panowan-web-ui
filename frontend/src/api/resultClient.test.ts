import { describe, expect, it, vi } from 'vitest'
import { createResult, createUpscaleVersion, fetchResult, fetchResults } from './resultClient'

describe('resultClient', () => {
  it('fetches result summaries', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ results: [{ result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'Prompt', status: 'completed', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:01:00Z', versions: [] }] }), { status: 200 })))

    const results = await fetchResults()

    expect(results[0].result_id).toBe('res_job_1')
    expect(fetch).toHaveBeenCalledWith('/api/results')
  })

  it('fetches a single result summary by result id', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ result: { result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'Prompt', status: 'completed', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:01:00Z', versions: [] } }), { status: 200 })))

    const result = await fetchResult('res_job_1')

    expect(result.result_id).toBe('res_job_1')
    expect(fetch).toHaveBeenCalledWith('/api/results/res_job_1')
  })

  it('creates a result with workbench payload', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ result: { result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'Prompt', status: 'queued', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:00:00Z', versions: [] } }), { status: 202 })))

    const result = await createResult({ prompt: 'Prompt', negative_prompt: '', quality: 'draft', params: { num_inference_steps: 20, width: 448, height: 224, seed: 0 } })

    expect(result.result_id).toBe('res_job_1')
    expect(fetch).toHaveBeenCalledWith('/api/results', expect.objectContaining({ method: 'POST' }))
  })

  it('creates an upscale version from the selected result version', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ version: { version_id: 'ver_2x', job_id: 'job_2', parent_version_id: 'ver_original', type: 'upscale', label: '2x SeedVR2', status: 'queued', model: 'seedvr2', scale: 2, params: {} } }), { status: 202 })))

    const version = await createUpscaleVersion('res_job_1', 'ver_original', {
      model: 'seedvr2',
      scale_mode: 'factor',
      scale: 2,
      replace_source: false,
    })

    expect(version.version_id).toBe('ver_2x')
    expect(fetch).toHaveBeenCalledWith(
      '/api/results/res_job_1/versions/ver_original/upscale',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})

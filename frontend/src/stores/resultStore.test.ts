import { describe, expect, it } from 'vitest'
import { applyVersionUpdate, selectInitialVersion } from './resultStore'
import type { ResultSummary } from '../types/result'

const result: ResultSummary = {
  result_id: 'res_job_1',
  root_job_id: 'job_1',
  prompt: 'Prompt',
  status: 'completed',
  selected_version_id: 'ver_job_1',
  created_at: '2026-05-02T12:00:00Z',
  updated_at: '2026-05-02T12:01:00Z',
  versions: [{ version_id: 'ver_job_1', job_id: 'job_1', type: 'original', label: '原始生成', status: 'succeeded', params: {} }],
}

describe('resultStore helpers', () => {
  it('selects backend selected version when present', () => {
    expect(selectInitialVersion(result)).toBe('ver_job_1')
  })

  it('applies version status updates without changing other versions', () => {
    const updated = applyVersionUpdate(result, { version_id: 'ver_job_1', status: 'running' })

    expect(updated.versions[0].status).toBe('running')
    expect(updated.result_id).toBe('res_job_1')
  })
})

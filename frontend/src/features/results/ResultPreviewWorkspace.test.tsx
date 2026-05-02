import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ResultPreviewWorkspace from './ResultPreviewWorkspace'
import type { ResultSummary } from '../../types/result'

const result: ResultSummary = {
  result_id: 'res_job_1',
  root_job_id: 'job_1',
  prompt: 'A cinematic alpine valley at sunset',
  status: 'completed',
  selected_version_id: 'ver_original',
  created_at: '2026-05-02T12:00:00Z',
  updated_at: '2026-05-02T12:01:00Z',
  versions: [
    {
      version_id: 'ver_original',
      job_id: 'job_1',
      type: 'original',
      label: '原始生成',
      status: 'succeeded',
      width: 896,
      height: 448,
      params: {},
      download_url: '/api/jobs/job_1/download',
    },
    {
      version_id: 'ver_4x',
      job_id: 'job_2',
      parent_version_id: 'ver_original',
      type: 'upscale',
      label: '4x SeedVR2',
      status: 'succeeded',
      width: 3584,
      height: 1792,
      model: 'seedvr2',
      scale: 4,
      params: {},
      download_url: '/api/jobs/job_2/download',
    },
  ],
}

describe('ResultPreviewWorkspace', () => {
  it('renders comparison modes and version metadata', () => {
    render(<ResultPreviewWorkspace result={result} selectedVersionId="ver_4x" />)

    expect(screen.getByText('结果预览')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '左右对比' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '单看' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '滑块对比' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'A/B 对比' })).toBeInTheDocument()
    expect(screen.getByText('4x SeedVR2')).toBeInTheDocument()
    expect(screen.getByText('3584×1792')).toBeInTheDocument()
  })
})

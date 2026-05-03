import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResultPreviewWorkspace from './ResultPreviewWorkspace'
import type { ResultSummary } from '../../types/result'

afterEach(() => cleanup())

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
      preview_url: '/api/jobs/job_2/preview.mp4',
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

  it('uses the selected version preview source for the video stage', () => {
    const { container } = render(<ResultPreviewWorkspace result={result} selectedVersionId="ver_4x" />)

    const video = container.querySelector('video')
    expect(video).toBeInTheDocument()
    expect(video).toHaveAttribute('src', '/api/jobs/job_2/preview.mp4')
  })

  it('falls back to the download source when no preview source exists', () => {
    const { container } = render(<ResultPreviewWorkspace result={result} selectedVersionId="ver_original" />)

    const video = container.querySelector('video')
    expect(video).toHaveAttribute('src', '/api/jobs/job_1/download')
  })

  it('does not request unfinished download sources as preview video', () => {
    const runningResult: ResultSummary = {
      ...result,
      selected_version_id: 'ver_running',
      versions: [
        {
          version_id: 'ver_running',
          job_id: 'job_running',
          type: 'original',
          label: '生成中',
          status: 'running',
          params: {},
          download_url: '/api/jobs/job_running/download',
        },
      ],
    }

    const { container } = render(<ResultPreviewWorkspace result={runningResult} selectedVersionId="ver_running" />)

    expect(container.querySelector('video')).not.toBeInTheDocument()
    expect(screen.getByText('等待生成完成')).toBeInTheDocument()
  })

  it('does not request failed preview sources as preview video', () => {
    const failedResult: ResultSummary = {
      ...result,
      selected_version_id: 'ver_failed',
      versions: [
        {
          version_id: 'ver_failed',
          job_id: 'job_failed',
          type: 'original',
          label: '生成失败',
          status: 'failed',
          params: {},
          preview_url: '/api/jobs/job_failed/download',
          download_url: '/api/jobs/job_failed/download',
          error: 'Service restarted before the job completed',
        },
      ],
    }

    const { container } = render(<ResultPreviewWorkspace result={failedResult} selectedVersionId="ver_failed" />)

    expect(container.querySelector('video')).not.toBeInTheDocument()
    expect(screen.getByText('等待生成完成')).toBeInTheDocument()
  })

  it('updates uncontrolled comparison mode and forwards selected version changes', async () => {
    const user = userEvent.setup()
    const onSelectVersion = vi.fn()

    render(<ResultPreviewWorkspace result={result} selectedVersionId="ver_original" onSelectVersion={onSelectVersion} />)

    const singleMode = screen.getByRole('button', { name: '单看' })
    await user.click(singleMode)
    expect(singleMode).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: /4x SeedVR2/ }))
    expect(onSelectVersion).toHaveBeenCalledWith('ver_4x')
  })
})

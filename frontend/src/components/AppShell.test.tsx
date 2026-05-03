import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AppShell from './AppShell'
import { emptyRuntimeSummary } from '../stores/runtimeStore'
import type { ResultSummary } from '../types/result'

afterEach(() => cleanup())

const result: ResultSummary = {
  result_id: 'res_job_1',
  root_job_id: 'job_1',
  prompt: 'A cinematic alpine valley at sunset',
  status: 'running',
  selected_version_id: 'ver_original',
  created_at: '2026-05-02T12:00:00Z',
  updated_at: '2026-05-02T12:01:00Z',
  versions: [
    {
      version_id: 'ver_original',
      job_id: 'job_1',
      type: 'original',
      label: '原始生成',
      status: 'running',
      width: 896,
      height: 448,
      params: {},
      download_url: '/jobs/job_1/download',
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
      download_url: '/jobs/job_2/download',
    },
  ],
}

function renderShell(overrides: Partial<Parameters<typeof AppShell>[0]> = {}) {
  const props: Parameters<typeof AppShell>[0] = {
    runtime: emptyRuntimeSummary,
    results: [result],
    selectedResult: result,
    selectedVersionId: 'ver_original',
    comparisonMode: 'side-by-side',
    isLoading: false,
    isCreating: false,
    isCreatingUpscale: false,
    error: null,
    upscaleError: null,
    onCreateResult: vi.fn(),
    onSelectVersion: vi.fn(),
    onSelectCurrentResultVersion: vi.fn(),
    onChangeComparisonMode: vi.fn(),
    onCreateUpscale: vi.fn(),
    onCancelJob: vi.fn(),
    onEscalateCancel: vi.fn(),
    onClearFailed: vi.fn(),
    ...overrides,
  }

  return { ...render(<AppShell {...props} />), props }
}

describe('AppShell', () => {
  it('renders the five workbench regions from real result state', () => {
    renderShell()

    expect(screen.getByText('PanoWan 视频生成')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '新建任务' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '结果预览' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '版本与超分' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最近任务' })).toBeInTheDocument()
    expect(screen.getAllByText('A cinematic alpine valley at sunset').length).toBeGreaterThan(0)
  })

  it('passes version, comparison, and task actions through to child panels', async () => {
    const user = userEvent.setup()
    const { props } = renderShell()

    await user.click(screen.getByRole('button', { name: '单看' }))
    expect(props.onChangeComparisonMode).toHaveBeenCalledWith('single')

    const previewRegion = screen.getByRole('region', { name: '结果预览' })
    await user.click(within(previewRegion).getByRole('button', { name: /4x SeedVR2/ }))
    expect(props.onSelectCurrentResultVersion).toHaveBeenCalledWith('ver_4x')

    const recentRegion = screen.getByRole('region', { name: '最近任务' })
    await user.click(within(recentRegion).getByRole('button', { name: /4x SeedVR2/ }))
    expect(props.onSelectVersion).toHaveBeenCalledWith('res_job_1', 'ver_4x')

    await user.click(within(recentRegion).getByRole('button', { name: '取消' }))
    expect(props.onCancelJob).toHaveBeenCalledWith('job_1')
  })
})

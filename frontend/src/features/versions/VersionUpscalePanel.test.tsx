import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import VersionUpscalePanel from './VersionUpscalePanel'
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
    },
  ],
}

describe('VersionUpscalePanel', () => {
  it('submits a SeedVR2 factor upscale payload for the selected version', async () => {
    const user = userEvent.setup()
    const onCreateUpscale = vi.fn()

    render(<VersionUpscalePanel result={result} selectedVersionId="ver_original" onCreateUpscale={onCreateUpscale} />)

    expect(screen.getByText('原始生成')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('超分倍率'), '4')
    await user.click(screen.getByRole('button', { name: '创建超分版本' }))

    expect(onCreateUpscale).toHaveBeenCalledWith({
      model: 'seedvr2',
      scale_mode: 'factor',
      scale: 4,
      replace_source: false,
    })
  })

  it('disables the upscale controls while submitting and shows errors', () => {
    render(
      <VersionUpscalePanel
        result={result}
        selectedVersionId="ver_original"
        onCreateUpscale={vi.fn()}
        isSubmitting
        error="创建超分版本失败"
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('创建超分版本失败')
    expect(screen.getByLabelText('超分倍率')).toBeDisabled()
    expect(screen.getByRole('button', { name: '创建中…' })).toBeDisabled()
  })
})

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TaskActionsMenu from './TaskActionsMenu'

afterEach(() => cleanup())

describe('TaskActionsMenu', () => {
  it('shows download and cancellation actions for active jobs', async () => {
    const user = userEvent.setup()
    const onCancelJob = vi.fn()
    const onEscalateCancel = vi.fn()

    render(
      <TaskActionsMenu
        jobId="job_1"
        status="running"
        downloadUrl="/jobs/job_1/download"
        onCancelJob={onCancelJob}
        onEscalateCancel={onEscalateCancel}
      />,
    )

    expect(screen.getByRole('link', { name: '下载' })).toHaveAttribute('href', '/jobs/job_1/download')
    await user.click(screen.getByRole('button', { name: '取消' }))
    await user.click(screen.getByRole('button', { name: '强制取消' }))

    expect(onCancelJob).toHaveBeenCalledWith('job_1')
    expect(onEscalateCancel).toHaveBeenCalledWith('job_1')
  })

  it('shows clear failed for failed jobs only', async () => {
    const user = userEvent.setup()
    const onClearFailed = vi.fn()

    render(<TaskActionsMenu jobId="job_2" status="failed" onClearFailed={onClearFailed} />)

    expect(screen.queryByRole('button', { name: '取消' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '清理失败' }))
    expect(onClearFailed).toHaveBeenCalledTimes(1)
  })
})

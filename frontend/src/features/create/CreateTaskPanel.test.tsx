import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CreateTaskPanel from './CreateTaskPanel'

afterEach(() => cleanup())

describe('CreateTaskPanel', () => {
  it('submits the draft create payload from the panel controls', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<CreateTaskPanel onSubmit={onSubmit} />)

    const promptInput = screen.getByLabelText('Prompt')
    await user.clear(promptInput)
    await user.type(promptInput, 'A cinematic alpine valley at sunset')
    await user.click(screen.getByRole('button', { name: '草稿' }))
    await user.click(screen.getByRole('button', { name: '提交任务' }))

    expect(onSubmit).toHaveBeenCalledWith({
      prompt: 'A cinematic alpine valley at sunset',
      negative_prompt: '',
      quality: 'draft',
      params: { num_inference_steps: 20, width: 448, height: 224, seed: 0 },
    })
  })

  it('disables submission while a create request is pending', () => {
    render(<CreateTaskPanel onSubmit={vi.fn()} isSubmitting />)

    expect(screen.getByRole('button', { name: '提交中…' })).toBeDisabled()
  })
})

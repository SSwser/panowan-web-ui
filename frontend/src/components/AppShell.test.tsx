import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import AppShell from './AppShell'
import { emptyRuntimeSummary } from '../stores/runtimeStore'

describe('AppShell', () => {
  it('renders the five workbench regions', () => {
    render(<AppShell runtime={emptyRuntimeSummary} />)

    expect(screen.getByText('PanoWan 视频生成')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '新建任务' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '结果预览' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '版本与超分' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最近任务' })).toBeInTheDocument()
  })
})

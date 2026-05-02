import RuntimeStatusBar from './RuntimeStatusBar'
import type { RuntimeSummary } from '../types/runtime'

interface AppShellProps {
  runtime: RuntimeSummary
}

export default function AppShell({ runtime }: AppShellProps) {
  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <div>
          <h1>PanoWan 视频生成</h1>
        </div>
        <RuntimeStatusBar runtime={runtime} />
      </header>

      <section className="workbench-grid" aria-label="结果工作台">
        {/* Task 9 only establishes the desktop shell so later tasks can mount real panels without changing layout semantics. */}
        <section className="workbench-card workbench-card--composer" aria-label="新建任务">
          <h2>新建任务</h2>
        </section>
        <section className="workbench-card workbench-card--preview" aria-label="结果预览">
          <h2>结果预览</h2>
        </section>
        <section className="workbench-card workbench-card--versions" aria-label="版本与超分">
          <h2>版本与超分</h2>
        </section>
        <section className="workbench-card workbench-card--recent" aria-label="最近任务">
          <h2>最近任务</h2>
        </section>
      </section>
    </main>
  )
}

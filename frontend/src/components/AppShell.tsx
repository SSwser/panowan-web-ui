import RuntimeStatusBar from './RuntimeStatusBar'
import CreateTaskPanel from '../features/create/CreateTaskPanel'
import ResultPreviewWorkspace from '../features/results/ResultPreviewWorkspace'
import VersionUpscalePanel from '../features/versions/VersionUpscalePanel'
import RecentTasksTable from '../features/tasks/RecentTasksTable'
import type { ComparisonMode, CreateResultPayload, CreateUpscalePayload, ResultSummary } from '../types/result'
import type { RuntimeSummary } from '../types/runtime'

interface AppShellProps {
  runtime: RuntimeSummary
  results: ResultSummary[]
  selectedResult: ResultSummary | null
  selectedVersionId: string | null
  comparisonMode: ComparisonMode
  isLoading: boolean
  isCreating: boolean
  isCreatingUpscale: boolean
  error: string | null
  upscaleError: string | null
  onCreateResult: (payload: CreateResultPayload) => void
  onSelectVersion: (resultId: string, versionId: string) => void
  onSelectCurrentResultVersion: (versionId: string) => void
  onChangeComparisonMode: (mode: ComparisonMode) => void
  onCreateUpscale: (payload: CreateUpscalePayload) => void
  onCancelJob: (jobId: string) => void
  onEscalateCancel: (jobId: string) => void
  onClearFailed: () => void
}

export default function AppShell({
  runtime,
  results,
  selectedResult,
  selectedVersionId,
  comparisonMode,
  isLoading,
  isCreating,
  isCreatingUpscale,
  error,
  upscaleError,
  onCreateResult,
  onSelectVersion,
  onSelectCurrentResultVersion,
  onChangeComparisonMode,
  onCreateUpscale,
  onCancelJob,
  onEscalateCancel,
  onClearFailed,
}: AppShellProps) {
  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <div>
          <h1>PanoWan 视频生成</h1>
        </div>
        <RuntimeStatusBar runtime={runtime} />
      </header>

      {error ? <div className="workbench-alert" role="alert">{error}</div> : null}
      {isLoading ? <div className="workbench-alert" aria-live="polite">正在加载工作台…</div> : null}

      <section className="workbench-grid" aria-label="结果工作台">
        <section className="workbench-card workbench-card--composer" aria-label="新建任务">
          <h2>新建任务</h2>
          <CreateTaskPanel onSubmit={onCreateResult} isSubmitting={isCreating} />
        </section>
        <section className="workbench-card workbench-card--preview" aria-label="结果预览">
          <ResultPreviewWorkspace
            result={selectedResult}
            selectedVersionId={selectedVersionId}
            comparisonMode={comparisonMode}
            onSelectVersion={onSelectCurrentResultVersion}
            onChangeComparisonMode={onChangeComparisonMode}
          />
        </section>
        <section className="workbench-card workbench-card--versions" aria-label="版本与超分">
          <VersionUpscalePanel
            result={selectedResult}
            selectedVersionId={selectedVersionId}
            onCreateUpscale={onCreateUpscale}
            isSubmitting={isCreatingUpscale}
            error={upscaleError}
          />
        </section>
        <section className="workbench-card workbench-card--recent" aria-label="最近任务">
          <RecentTasksTable
            results={results}
            selectedResultId={selectedResult?.result_id ?? null}
            selectedVersionId={selectedVersionId}
            onSelectVersion={onSelectVersion}
            onCancelJob={onCancelJob}
            onEscalateCancel={onEscalateCancel}
            onClearFailed={onClearFailed}
          />
        </section>
      </section>
    </main>
  )
}

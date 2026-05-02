import RuntimeStatusBar from './RuntimeStatusBar'
import CreateTaskPanel from '../features/create/CreateTaskPanel'
import ResultPreviewWorkspace from '../features/results/ResultPreviewWorkspace'
import VersionUpscalePanel from '../features/versions/VersionUpscalePanel'
import RecentTasksTable from '../features/tasks/RecentTasksTable'
import type { ResultSummary } from '../types/result'
import type { RuntimeSummary } from '../types/runtime'

interface AppShellProps {
  runtime: RuntimeSummary
}

const sampleResult: ResultSummary = {
  result_id: 'res_sample_job',
  root_job_id: 'sample_job',
  prompt: 'A cinematic alpine valley at sunset with drifting clouds and wide panoramic motion.',
  status: 'completed',
  selected_version_id: 'ver_sample_4x',
  created_at: '2026-05-02T12:00:00Z',
  updated_at: '2026-05-02T12:01:00Z',
  versions: [
    {
      version_id: 'ver_sample_original',
      job_id: 'sample_job',
      type: 'original',
      label: '原始生成',
      status: 'succeeded',
      width: 896,
      height: 448,
      params: {},
      download_url: '/api/jobs/sample_job/download',
    },
    {
      version_id: 'ver_sample_4x',
      job_id: 'sample_upscale_job',
      parent_version_id: 'ver_sample_original',
      type: 'upscale',
      label: '4x SeedVR2',
      status: 'succeeded',
      model: 'seedvr2',
      scale: 4,
      width: 3584,
      height: 1792,
      params: {},
      download_url: '/api/jobs/sample_upscale_job/download',
    },
  ],
}

export default function AppShell({ runtime }: AppShellProps) {
  const selectedVersionId = sampleResult.selected_version_id ?? sampleResult.versions[0]?.version_id ?? null

  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <div>
          <h1>PanoWan 视频生成</h1>
        </div>
        <RuntimeStatusBar runtime={runtime} />
      </header>

      <section className="workbench-grid" aria-label="结果工作台">
        <section className="workbench-card workbench-card--composer" aria-label="新建任务">
          <h2>新建任务</h2>
          <CreateTaskPanel onSubmit={() => undefined} />
        </section>
        <section className="workbench-card workbench-card--preview" aria-label="结果预览">
          <ResultPreviewWorkspace result={sampleResult} selectedVersionId={selectedVersionId} />
        </section>
        <section className="workbench-card workbench-card--versions" aria-label="版本与超分">
          <VersionUpscalePanel result={sampleResult} selectedVersionId={selectedVersionId} />
        </section>
        <section className="workbench-card workbench-card--recent" aria-label="最近任务">
          <RecentTasksTable results={[sampleResult]} />
        </section>
      </section>
    </main>
  )
}

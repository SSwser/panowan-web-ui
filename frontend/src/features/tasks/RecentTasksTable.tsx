import type { ResultSummary } from '../../types/result'
import TaskActionsMenu from './TaskActionsMenu'

interface RecentTasksTableProps {
  results: ResultSummary[]
  selectedResultId?: string | null
  selectedVersionId?: string | null
  onSelectVersion?: (resultId: string, versionId: string) => void
  onCancelJob?: (jobId: string) => void
  onEscalateCancel?: (jobId: string) => void
  onClearFailed?: () => void
}

export default function RecentTasksTable({
  results,
  selectedResultId,
  selectedVersionId,
  onSelectVersion,
  onCancelJob,
  onEscalateCancel,
  onClearFailed,
}: RecentTasksTableProps) {
  const versions = results.flatMap((result) =>
    result.versions.map((version) => ({
      result,
      version,
    })),
  )

  return (
    <div className="recent-tasks-panel">
      <div className="panel-heading">
        <h2>最近任务</h2>
      </div>
      {versions.length > 0 ? (
        <table className="recent-tasks-table">
          <thead>
            <tr>
              <th>版本</th>
              <th>状态</th>
              <th>尺寸</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {versions.map(({ result, version }) => {
              const isSelected = result.result_id === selectedResultId && version.version_id === selectedVersionId
              return (
                <tr key={`${result.result_id}-${version.version_id}`} className={isSelected ? 'selected-row' : ''}>
                  <td>
                    <button
                      type="button"
                      className="table-version-button"
                      onClick={() => onSelectVersion?.(result.result_id, version.version_id)}
                    >
                      <strong>{version.label}</strong>
                      <small>{result.prompt}</small>
                    </button>
                  </td>
                  <td>{version.status}</td>
                  <td>{version.width && version.height ? `${version.width}×${version.height}` : '待定'}</td>
                  <td>
                    <TaskActionsMenu
                      jobId={version.job_id}
                      status={version.status}
                      downloadUrl={version.download_url}
                      onCancelJob={onCancelJob}
                      onEscalateCancel={onEscalateCancel}
                      onClearFailed={onClearFailed}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <div className="empty-panel">暂无任务。</div>
      )}
    </div>
  )
}

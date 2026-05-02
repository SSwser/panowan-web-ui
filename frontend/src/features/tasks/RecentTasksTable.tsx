import type { ResultSummary } from '../../types/result'
import TaskActionsMenu from './TaskActionsMenu'

interface RecentTasksTableProps {
  results: ResultSummary[]
}

export default function RecentTasksTable({ results }: RecentTasksTableProps) {
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
            {versions.map(({ result, version }) => (
              <tr key={`${result.result_id}-${version.version_id}`}>
                <td>
                  <strong>{version.label}</strong>
                  <small>{result.prompt}</small>
                </td>
                <td>{version.status}</td>
                <td>{version.width && version.height ? `${version.width}×${version.height}` : '待定'}</td>
                <td>
                  <TaskActionsMenu status={version.status} downloadUrl={version.download_url} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="empty-panel">暂无任务。</div>
      )}
    </div>
  )
}

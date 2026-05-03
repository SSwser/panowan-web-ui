interface TaskActionsMenuProps {
  jobId: string
  status: string
  downloadUrl?: string | null
  onCancelJob?: (jobId: string) => void
  onEscalateCancel?: (jobId: string) => void
  onClearFailed?: () => void
}

export default function TaskActionsMenu({
  jobId,
  status,
  downloadUrl,
  onCancelJob,
  onEscalateCancel,
  onClearFailed,
}: TaskActionsMenuProps) {
  const canCancel = ['queued', 'claimed', 'running', 'cancelling'].includes(status)
  const canClear = status === 'failed'

  return (
    <div className="task-actions" aria-label="任务操作">
      {downloadUrl ? <a href={downloadUrl}>下载</a> : null}
      {canCancel ? (
        <button type="button" onClick={() => onCancelJob?.(jobId)}>
          取消
        </button>
      ) : null}
      {canCancel ? (
        <button type="button" onClick={() => onEscalateCancel?.(jobId)}>
          强制取消
        </button>
      ) : null}
      {canClear ? (
        <button type="button" onClick={() => onClearFailed?.()}>
          清理失败
        </button>
      ) : null}
    </div>
  )
}

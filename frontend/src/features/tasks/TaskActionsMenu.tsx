interface TaskActionsMenuProps {
  status: string
  downloadUrl?: string | null
}

export default function TaskActionsMenu({ status, downloadUrl }: TaskActionsMenuProps) {
  const canCancel = ['queued', 'claimed', 'running', 'cancelling'].includes(status)
  const canClear = status === 'failed'

  return (
    <div className="task-actions" aria-label="任务操作">
      {downloadUrl ? <a href={downloadUrl}>下载</a> : null}
      {canCancel ? <button type="button">取消</button> : null}
      {canCancel ? <button type="button">强制取消</button> : null}
      {canClear ? <button type="button">清理失败</button> : null}
    </div>
  )
}

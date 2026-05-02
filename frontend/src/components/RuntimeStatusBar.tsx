import type { RuntimeSummary } from '../types/runtime'
import StatusPill from './StatusPill'

interface RuntimeStatusBarProps {
  runtime: RuntimeSummary
}

export default function RuntimeStatusBar({ runtime }: RuntimeStatusBarProps) {
  const workerLabel = `${runtime.online_workers} 在线`
  const queueLabel = `${runtime.queued_jobs} 排队`
  const runtimeLabel = runtime.runtime_warm ? '已预热' : '冷启动'

  return (
    <div className="runtime-status-bar" aria-label="运行时状态栏">
      <div className="runtime-status-bar__pills">
        <StatusPill label="容量" value={`${runtime.available_capacity}/${runtime.capacity}`} />
        <StatusPill label="Worker" value={workerLabel} />
        <StatusPill label="队列" value={queueLabel} />
        <StatusPill label="Runtime" value={runtimeLabel} tone={runtime.runtime_warm ? 'success' : 'neutral'} />
        <StatusPill label="自动刷新" value="开启" tone="success" />
      </div>
      <button type="button" className="icon-button" aria-label="设置">
        <span aria-hidden="true">···</span>
      </button>
    </div>
  )
}

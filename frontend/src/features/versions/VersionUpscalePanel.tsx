import type { ResultSummary } from '../../types/result'
import UpscaleForm from './UpscaleForm'

interface VersionUpscalePanelProps {
  result: ResultSummary | null
  selectedVersionId: string | null
}

export default function VersionUpscalePanel({ result, selectedVersionId }: VersionUpscalePanelProps) {
  const selectedVersion = result?.versions.find((version) => version.version_id === selectedVersionId) ?? null

  return (
    <div className="version-upscale-panel">
      <div className="panel-heading">
        <h2>版本与超分</h2>
      </div>
      {selectedVersion ? (
        <>
          <div className="selected-version-card">
            <span className="metadata-label">当前版本</span>
            <strong>{selectedVersion.label}</strong>
            <small>{selectedVersion.width && selectedVersion.height ? `${selectedVersion.width}×${selectedVersion.height}` : '尺寸待定'}</small>
          </div>
          <UpscaleForm />
        </>
      ) : (
        <div className="empty-panel">选择一个版本后，可在这里创建 2x 或 4x 超分版本。</div>
      )}
    </div>
  )
}

import { useState } from 'react'
import type { ComparisonMode, ResultSummary } from '../../types/result'
import ResultMetadataBar from './ResultMetadataBar'
import VersionStrip from './VersionStrip'

interface ResultPreviewWorkspaceProps {
  result: ResultSummary | null
  selectedVersionId: string | null
  comparisonMode?: ComparisonMode
  onSelectVersion?: (versionId: string) => void
  onChangeComparisonMode?: (mode: ComparisonMode) => void
}

const comparisonModes: Array<{ mode: ComparisonMode; label: string }> = [
  { mode: 'side-by-side', label: '左右对比' },
  { mode: 'single', label: '单看' },
  { mode: 'slider', label: '滑块对比' },
  { mode: 'ab', label: 'A/B 对比' },
]

export default function ResultPreviewWorkspace({
  result,
  selectedVersionId,
  comparisonMode = 'side-by-side',
  onSelectVersion,
  onChangeComparisonMode,
}: ResultPreviewWorkspaceProps) {
  const [localMode, setLocalMode] = useState<ComparisonMode>(comparisonMode)
  const activeMode = onChangeComparisonMode ? comparisonMode : localMode
  const selectedVersion = result?.versions.find((version) => version.version_id === selectedVersionId) ?? null
  const isPlayableVersion = selectedVersion?.status === 'succeeded' || selectedVersion?.status === 'completed'
  const videoUrl = isPlayableVersion ? selectedVersion?.preview_url || selectedVersion?.download_url || null : null

  function handleModeChange(mode: ComparisonMode) {
    if (onChangeComparisonMode) {
      onChangeComparisonMode(mode)
      return
    }
    setLocalMode(mode)
  }

  return (
    <div className="result-preview-workspace">
      <div className="panel-heading">
        <h2>结果预览</h2>
        <div className="comparison-mode-group" role="group" aria-label="对比模式">
          {comparisonModes.map((item) => (
            <button
              key={item.mode}
              type="button"
              className={activeMode === item.mode ? 'active' : ''}
              aria-pressed={activeMode === item.mode}
              onClick={() => handleModeChange(item.mode)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {result ? (
        <>
          <ResultMetadataBar result={result} version={selectedVersion} />
          <div className={`preview-stage preview-stage--${activeMode}`}>
            {videoUrl ? (
              <video className="preview-video" src={videoUrl} controls muted playsInline />
            ) : (
              <div className="preview-placeholder">
                <span>360° Viewer</span>
                <small>{isPlayableVersion && selectedVersion?.download_url ? '视频源已就绪' : '等待生成完成'}</small>
              </div>
            )}
          </div>
          <VersionStrip result={result} selectedVersionId={selectedVersionId} onSelect={onSelectVersion} />
        </>
      ) : (
        <div className="empty-panel">提交或选择一个结果后，这里会显示全景预览与版本链。</div>
      )}
    </div>
  )
}

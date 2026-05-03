import type { ResultSummary } from '../../types/result'

interface VersionStripProps {
  result: ResultSummary
  selectedVersionId: string | null
  onSelect?: (versionId: string) => void
}

function formatDimensions(width?: number | null, height?: number | null) {
  return width && height ? `${width}×${height}` : '尺寸待定'
}

export default function VersionStrip({ result, selectedVersionId, onSelect }: VersionStripProps) {
  return (
    <div className="version-strip" aria-label="版本链">
      {result.versions.map((version) => (
        <button
          key={version.version_id}
          type="button"
          className={version.version_id === selectedVersionId ? 'version-chip version-chip--active' : 'version-chip'}
          onClick={() => onSelect?.(version.version_id)}
        >
          <span>{version.label}</span>
          <small>{formatDimensions(version.width, version.height)}</small>
        </button>
      ))}
    </div>
  )
}

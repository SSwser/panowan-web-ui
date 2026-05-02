import type { ResultSummary, ResultVersion } from '../../types/result'

interface ResultMetadataBarProps {
  result: ResultSummary
  version: ResultVersion | null
}

export default function ResultMetadataBar({ result, version }: ResultMetadataBarProps) {
  return (
    <div className="result-metadata-bar" aria-label="结果元数据">
      <div>
        <span className="metadata-label">Prompt</span>
        <strong>{result.prompt}</strong>
      </div>
      <div>
        <span className="metadata-label">Result</span>
        <strong>{result.status}</strong>
      </div>
      <div>
        <span className="metadata-label">Version</span>
        <strong>{version?.status ?? '未选择'}</strong>
      </div>
    </div>
  )
}

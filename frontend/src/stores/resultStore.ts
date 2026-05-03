import type { ResultSummary, ResultVersion } from '../types/result'

export interface VersionUpdatePayload {
  version_id: string
  status?: ResultVersion['status']
  download_url?: string | null
  preview_url?: string | null
  error?: string | null
}

export function selectInitialVersion(result: ResultSummary): string | null {
  if (result.selected_version_id) return result.selected_version_id
  const lastVersion = result.versions[result.versions.length - 1]
  return lastVersion?.version_id ?? null
}

export function applyVersionUpdate(result: ResultSummary, patch: VersionUpdatePayload): ResultSummary {
  return {
    ...result,
    versions: result.versions.map((version) =>
      version.version_id === patch.version_id
        ? {
            ...version,
            status: patch.status ?? version.status,
            download_url: patch.download_url ?? version.download_url,
            preview_url: patch.preview_url ?? version.preview_url,
            error: patch.error ?? version.error,
          }
        : version,
    ),
  }
}

export function upsertResult(results: ResultSummary[], next: ResultSummary): ResultSummary[] {
  const index = results.findIndex((result) => result.result_id === next.result_id)
  if (index === -1) return [next, ...results]
  return results.map((result) => (result.result_id === next.result_id ? next : result))
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import AppShell from './components/AppShell'
import { connectWorkbenchEvents } from './api/eventClient'
import { createResult, createUpscaleVersion, fetchResult, fetchResults } from './api/resultClient'
import { fetchRuntimeSummary } from './api/runtimeClient'
import { clearFailedJobs, escalateCancelJob, requestCancelJob } from './api/taskClient'
import { applyVersionUpdate, selectInitialVersion, upsertResult, type VersionUpdatePayload } from './stores/resultStore'
import { emptyRuntimeSummary } from './stores/runtimeStore'
import { initialWorkspaceState, type WorkspaceState } from './stores/workspaceStore'
import type { ComparisonMode, CreateResultPayload, CreateUpscalePayload, ResultSummary, ResultVersion } from './types/result'
import type { RuntimeSummary } from './types/runtime'

interface VersionEventPayload extends VersionUpdatePayload {
  result_id: string
}

function selectDefaultWorkspace(results: ResultSummary[]): WorkspaceState {
  const firstResult = results[0] ?? null
  return {
    ...initialWorkspaceState,
    selectedResultId: firstResult?.result_id ?? null,
    selectedVersionId: firstResult ? selectInitialVersion(firstResult) : null,
  }
}

function appendVersion(result: ResultSummary, version: ResultVersion): ResultSummary {
  if (result.versions.some((item) => item.version_id === version.version_id)) {
    return {
      ...result,
      versions: result.versions.map((item) => (item.version_id === version.version_id ? version : item)),
    }
  }
  return {
    ...result,
    versions: [...result.versions, version],
    selected_version_id: version.version_id,
  }
}

export default function App() {
  const [runtime, setRuntime] = useState<RuntimeSummary>(emptyRuntimeSummary)
  const [results, setResults] = useState<ResultSummary[]>([])
  const [workspace, setWorkspace] = useState<WorkspaceState>(initialWorkspaceState)
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [isCreatingUpscale, setIsCreatingUpscale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [upscaleError, setUpscaleError] = useState<string | null>(null)

  const selectedResult = useMemo(
    () => results.find((result) => result.result_id === workspace.selectedResultId) ?? results[0] ?? null,
    [results, workspace.selectedResultId],
  )

  const selectedVersionId = useMemo(() => {
    if (!selectedResult) return null
    if (selectedResult.versions.some((version) => version.version_id === workspace.selectedVersionId)) {
      return workspace.selectedVersionId
    }
    return selectInitialVersion(selectedResult)
  }, [selectedResult, workspace.selectedVersionId])

  const refreshRuntime = useCallback(async () => {
    setRuntime(await fetchRuntimeSummary())
  }, [])

  const refreshResults = useCallback(async () => {
    const nextResults = await fetchResults()
    setResults(nextResults)
    setWorkspace((current) => {
      if (current.selectedResultId && nextResults.some((result) => result.result_id === current.selectedResultId)) {
        return current
      }
      return selectDefaultWorkspace(nextResults)
    })
  }, [])

  const refreshAll = useCallback(async () => {
    const [nextRuntime, nextResults] = await Promise.all([fetchRuntimeSummary(), fetchResults()])
    setRuntime(nextRuntime)
    setResults(nextResults)
    setWorkspace((current) => {
      if (current.selectedResultId && nextResults.some((result) => result.result_id === current.selectedResultId)) {
        return current
      }
      return selectDefaultWorkspace(nextResults)
    })
  }, [])

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchRuntimeSummary(), fetchResults()])
      .then(([nextRuntime, nextResults]) => {
        if (cancelled) return
        setRuntime(nextRuntime)
        setResults(nextResults)
        setWorkspace(selectDefaultWorkspace(nextResults))
        setError(null)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setError(caught instanceof Error ? caught.message : '加载工作台失败')
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const source = connectWorkbenchEvents((eventName, payload) => {
      if (eventName === 'heartbeat') return
      if (eventName === 'runtime_updated') {
        void refreshRuntime().catch(() => undefined)
        return
      }
      if (eventName === 'version_updated') {
        const eventPayload = payload as VersionEventPayload
        setResults((current) =>
          current.map((result) =>
            result.result_id === eventPayload.result_id ? applyVersionUpdate(result, eventPayload) : result,
          ),
        )
        void refreshRuntime().catch(() => undefined)
        return
      }
      if (eventName === 'version_created') {
        const eventPayload = payload as VersionEventPayload
        void fetchResult(eventPayload.result_id)
          .then((result) => {
            setResults((current) => upsertResult(current, result))
            setWorkspace((current) => ({
              ...current,
              selectedResultId: current.selectedResultId ?? result.result_id,
              selectedVersionId: current.selectedVersionId ?? selectInitialVersion(result),
            }))
          })
          .catch(() => refreshResults())
        return
      }
      if (eventName === 'result_created' || eventName === 'result_updated') {
        const result = payload as ResultSummary
        setResults((current) => upsertResult(current, result))
      }
    })
    source.onerror = () => {
      void refreshAll().catch(() => undefined)
    }
    return () => source.close()
  }, [refreshAll, refreshResults, refreshRuntime])

  async function handleCreateResult(payload: CreateResultPayload) {
    setIsCreating(true)
    setError(null)
    try {
      const result = await createResult(payload)
      setResults((current) => upsertResult(current, result))
      setWorkspace((current) => ({
        ...current,
        selectedResultId: result.result_id,
        selectedVersionId: selectInitialVersion(result),
      }))
      await refreshRuntime()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建任务失败')
    } finally {
      setIsCreating(false)
    }
  }

  function handleSelectVersion(resultId: string, versionId: string) {
    setWorkspace((current) => ({
      ...current,
      selectedResultId: resultId,
      selectedVersionId: versionId,
    }))
  }

  function handleSelectCurrentResultVersion(versionId: string) {
    if (!selectedResult) return
    handleSelectVersion(selectedResult.result_id, versionId)
  }

  function handleComparisonModeChange(comparisonMode: ComparisonMode) {
    setWorkspace((current) => ({ ...current, comparisonMode }))
  }

  async function handleCreateUpscale(payload: CreateUpscalePayload) {
    if (!selectedResult || !selectedVersionId) return
    setIsCreatingUpscale(true)
    setUpscaleError(null)
    try {
      const version = await createUpscaleVersion(selectedResult.result_id, selectedVersionId, payload)
      setResults((current) =>
        current.map((result) =>
          result.result_id === selectedResult.result_id ? appendVersion(result, version) : result,
        ),
      )
      setWorkspace((current) => ({ ...current, selectedVersionId: version.version_id }))
      await refreshRuntime()
    } catch (caught) {
      setUpscaleError(caught instanceof Error ? caught.message : '创建超分版本失败')
    } finally {
      setIsCreatingUpscale(false)
    }
  }

  async function handleCancelJob(jobId: string) {
    await requestCancelJob(jobId)
    await refreshAll()
  }

  async function handleEscalateCancel(jobId: string) {
    await escalateCancelJob(jobId)
    await refreshAll()
  }

  async function handleClearFailed() {
    await clearFailedJobs()
    await refreshAll()
  }

  return (
    <AppShell
      runtime={runtime}
      results={results}
      selectedResult={selectedResult}
      selectedVersionId={selectedVersionId}
      comparisonMode={workspace.comparisonMode}
      isLoading={isLoading}
      isCreating={isCreating}
      isCreatingUpscale={isCreatingUpscale}
      error={error}
      upscaleError={upscaleError}
      onCreateResult={handleCreateResult}
      onSelectVersion={handleSelectVersion}
      onSelectCurrentResultVersion={handleSelectCurrentResultVersion}
      onChangeComparisonMode={handleComparisonModeChange}
      onCreateUpscale={handleCreateUpscale}
      onCancelJob={handleCancelJob}
      onEscalateCancel={handleEscalateCancel}
      onClearFailed={handleClearFailed}
    />
  )
}

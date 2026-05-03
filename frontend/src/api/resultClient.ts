import { requestJson } from './client'
import type { CreateResultPayload, CreateUpscalePayload, ResultSummary, ResultVersion } from '../types/result'

export async function fetchResults(): Promise<ResultSummary[]> {
  const body = await requestJson<{ results: ResultSummary[] }>('/api/results')
  return body.results
}

export async function fetchResult(resultId: string): Promise<ResultSummary> {
  const body = await requestJson<{ result: ResultSummary }>(`/api/results/${resultId}`)
  return body.result
}

export async function createResult(payload: CreateResultPayload): Promise<ResultSummary> {
  const body = await requestJson<{ result: ResultSummary }>('/api/results', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return body.result
}

export async function createUpscaleVersion(resultId: string, versionId: string, payload: CreateUpscalePayload): Promise<ResultVersion> {
  const body = await requestJson<{ version: ResultVersion }>(`/api/results/${resultId}/versions/${versionId}/upscale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return body.version
}

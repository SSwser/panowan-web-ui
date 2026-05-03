import { requestJson } from './client'

export function requestCancelJob(jobId: string): Promise<unknown> {
  return requestJson(`/jobs/${jobId}/cancel`, { method: 'POST' })
}

export function escalateCancelJob(jobId: string): Promise<unknown> {
  return requestJson(`/jobs/${jobId}/cancel/escalate`, { method: 'POST' })
}

export function clearFailedJobs(): Promise<unknown> {
  return requestJson('/jobs/failed', { method: 'DELETE' })
}

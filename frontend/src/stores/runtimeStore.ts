import type { RuntimeSummary } from '../types/runtime'

export const emptyRuntimeSummary: RuntimeSummary = {
  capacity: 0,
  available_capacity: 0,
  online_workers: 0,
  loading_workers: 0,
  busy_workers: 0,
  queued_jobs: 0,
  running_jobs: 0,
  cancelling_jobs: 0,
  runtime_warm: false,
}

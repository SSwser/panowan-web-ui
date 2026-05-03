export interface RuntimeSummary {
  capacity: number
  available_capacity: number
  online_workers: number
  loading_workers: number
  busy_workers: number
  queued_jobs: number
  running_jobs: number
  cancelling_jobs: number
  runtime_warm: boolean
}

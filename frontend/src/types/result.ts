export type JobStatus = 'queued' | 'claimed' | 'running' | 'cancelling' | 'succeeded' | 'completed' | 'failed' | 'cancelled'
export type ResultStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'mixed'
export type ResultVersionType = 'original' | 'upscale'
export type ComparisonMode = 'side-by-side' | 'single' | 'slider' | 'ab'

export interface ResultVersion {
  version_id: string
  job_id: string
  parent_version_id?: string | null
  type: ResultVersionType
  label: string
  status: JobStatus
  model?: string | null
  scale?: number | null
  width?: number | null
  height?: number | null
  duration_seconds?: number | null
  fps?: number | null
  bitrate_mbps?: number | null
  file_size_bytes?: number | null
  thumbnail_url?: string | null
  preview_url?: string | null
  download_url?: string | null
  params: Record<string, unknown>
  error?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface ResultSummary {
  result_id: string
  root_job_id: string
  prompt: string
  negative_prompt?: string
  status: ResultStatus
  selected_version_id?: string | null
  created_at?: string | null
  updated_at?: string | null
  versions: ResultVersion[]
}

export interface CreateResultPayload {
  prompt: string
  negative_prompt: string
  quality: 'draft' | 'standard' | 'custom'
  params: {
    num_inference_steps: number
    width: number
    height: number
    seed: number
  }
}

export interface CreateUpscalePayload {
  model: string
  scale_mode: 'factor' | 'resolution'
  scale?: number
  target_width?: number
  target_height?: number
  replace_source: boolean
}

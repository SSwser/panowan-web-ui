import type { ComparisonMode } from '../types/result'

export interface PanoViewState {
  yaw: number
  pitch: number
  fov: number
}

export interface WorkspaceState {
  selectedResultId: string | null
  selectedVersionId: string | null
  comparisonMode: ComparisonMode
  viewState: PanoViewState
  currentTime: number
  paused: boolean
  muted: boolean
}

export const initialWorkspaceState: WorkspaceState = {
  selectedResultId: null,
  selectedVersionId: null,
  comparisonMode: 'side-by-side',
  viewState: { yaw: 0, pitch: 0, fov: 90 },
  currentTime: 0,
  paused: true,
  muted: false,
}

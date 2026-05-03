import { requestJson } from './client'
import type { RuntimeSummary } from '../types/runtime'

export function fetchRuntimeSummary(): Promise<RuntimeSummary> {
  return requestJson<RuntimeSummary>('/api/runtime/summary')
}

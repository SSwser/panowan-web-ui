export type WorkbenchEventHandler = (eventName: string, payload: unknown) => void

export function connectWorkbenchEvents(handler: WorkbenchEventHandler): EventSource {
  const source = new EventSource('/api/events')
  for (const name of ['result_created', 'result_updated', 'version_created', 'version_updated', 'version_deleted', 'runtime_updated', 'heartbeat']) {
    source.addEventListener(name, (event) => {
      handler(name, JSON.parse((event as MessageEvent).data))
    })
  }
  return source
}

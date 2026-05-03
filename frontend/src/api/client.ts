export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = init === undefined ? await fetch(url) : await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(String(body.detail ?? response.statusText))
  }
  return response.json() as Promise<T>
}

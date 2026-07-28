import axios from 'axios'

export async function getJson<T>(url: string): Promise<T> {
  const response = await axios.get<T>(url, {
    headers: { 'Cache-Control': 'no-store' },
  })
  return response.data
}

export async function postJson<T>(url: string, body?: unknown): Promise<T> {
  const response = await axios.post<T>(url, body ?? {})
  return response.data
}

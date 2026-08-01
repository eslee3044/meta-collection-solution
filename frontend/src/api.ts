const API = import.meta.env.VITE_API_URL || ''

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('metavault_token')
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, body.detail || '요청을 처리하지 못했습니다.')
  return body
}

export const fmt = (value?: string | null) => value ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—'


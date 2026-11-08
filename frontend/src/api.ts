const API = import.meta.env.VITE_API_URL || ''
const SESSION_EXPIRED_EVENT = 'metavault:session-expired'

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export function notifySessionExpired(status: number, path: string, hadToken = Boolean(localStorage.getItem('metavault_token'))) {
  if (status !== 401 || !hadToken || path.includes('/api/auth/login')) return
  localStorage.removeItem('metavault_token')
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, {
    detail: { message: '세션이 만료되었습니다. 다시 로그인해 주세요.' },
  }))
}

export async function authorizedFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = localStorage.getItem('metavault_token')
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  notifySessionExpired(response.status, path, Boolean(token))
  return response
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authorizedFetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, body.detail || '요청을 처리하지 못했습니다.')
  return body
}

export const fmt = (value?: string | null) => value ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—'

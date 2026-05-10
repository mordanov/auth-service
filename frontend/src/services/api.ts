import axios, { AxiosInstance } from 'axios'
import { useAuthStore } from './auth'

const APPS = [
  'budget-site',
  'family-admin-routine',
  'family-archive',
  'news-site',
  'poetry-site',
  'reminders-app',
] as const

export type AppName = (typeof APPS)[number]
export { APPS }

function createApiClient(): AxiosInstance {
  const client = axios.create({ baseURL: '/', withCredentials: true })

  // Attach access token to every request
  client.interceptors.request.use((config) => {
    const token = useAuthStore.getState().token
    if (token) {
      config.headers = config.headers ?? {}
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  })

  // Auto-refresh on 401
  client.interceptors.response.use(
    (r) => r,
    async (error) => {
      if (error.response?.status === 401 && !error.config?._retry) {
        error.config._retry = true
        try {
          const refreshResp = await axios.post('/auth/refresh', {}, { withCredentials: true })
          const newToken: string = refreshResp.data.access_token
          useAuthStore.getState().setToken(newToken)
          error.config.headers['Authorization'] = `Bearer ${newToken}`
          return client(error.config)
        } catch {
          useAuthStore.getState().clearToken()
          window.location.href = '/auth/login'
        }
      }
      return Promise.reject(error)
    },
  )

  return client
}

export const api = createApiClient()

// ── API methods ───────────────────────────────────────────────────────────────

export interface UserSummary {
  id: string
  display_name: string
  is_active: boolean
  created_at: string
  grants: GrantRecord[]
  identity_providers: IdentityProvider[]
}

export interface UserDetail extends UserSummary {
  recent_events: AuditEvent[]
}

export interface GrantRecord {
  id: string
  user_id: string
  app_name: string
  role: 'user' | 'admin'
  granted_at: string
  is_active: boolean
  granted_by_display_name: string | null
}

export interface IdentityProvider {
  provider: 'google' | 'microsoft' | 'local'
  email: string
  created_at: string
}

export interface AuditEvent {
  id: string
  actor_user_id: string | null
  actor_display_name: string | null
  action_type: string
  target_user_id: string | null
  target_user_display_name: string | null
  target_app: string | null
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
}

export const adminApi = {
  listUsers: (params: { limit?: number; offset?: number; q?: string }) =>
    api.get<PaginatedResponse<UserSummary>>('/admin/users', { params }).then((r) => r.data),

  getUser: (userId: string) =>
    api.get<UserDetail>(`/admin/users/${userId}`).then((r) => r.data),

  createGrant: (data: { user_id: string; app_name: string; role?: string }) =>
    api.post<GrantRecord>('/admin/grants', data).then((r) => r.data),

  revokeGrant: (grantId: string) =>
    api.patch<GrantRecord>(`/admin/grants/${grantId}`, { is_active: false }).then((r) => r.data),

  revokeAllSessions: (userId: string) =>
    api.post(`/admin/users/${userId}/revoke-sessions`).then((r) => r.data),

  getAuditLog: (params: {
    limit?: number
    offset?: number
    user_id?: string
    app_name?: string
    action_type?: string
  }) => api.get<PaginatedResponse<AuditEvent>>('/admin/audit', { params }).then((r) => r.data),
}

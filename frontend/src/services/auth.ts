import { create } from 'zustand'

interface AuthState {
  token: string | null
  isAdmin: boolean
  setToken: (token: string) => void
  clearToken: () => void
}

// Simple in-memory auth store — no localStorage for security
export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  isAdmin: false,
  setToken: (token: string) => {
    try {
      // NOTE: This decode is for UI rendering only (show/hide admin nav).
      // The signature is NOT verified here. Real access control is enforced
      // server-side on every API call and by the SDK middleware on client apps.
      const payload = JSON.parse(atob(token.split('.')[1]))
      const isAdmin = Array.isArray(payload.grants) && payload.grants.includes('admin')
      set({ token, isAdmin })
    } catch {
      set({ token: null, isAdmin: false })
    }
  },
  clearToken: () => set({ token: null, isAdmin: false }),
}))

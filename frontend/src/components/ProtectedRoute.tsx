import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '../services/auth'

export function ProtectedRoute() {
  const { token, isAdmin } = useAuthStore()
  if (!token) return <Navigate to="/auth/login" replace />
  if (!isAdmin) return <Navigate to="/auth/login" replace />
  return <Outlet />
}

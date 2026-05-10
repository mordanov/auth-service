import { Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/Login'
import UserListPage from './pages/UserList'
import UserDetailPage from './pages/UserDetail'
import AuditLogPage from './pages/AuditLog'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AdminLayout } from './components/AdminLayout'

export default function App() {
  return (
    <Routes>
      <Route path="/auth/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AdminLayout />}>
          <Route path="/admin" element={<Navigate to="/admin/users" replace />} />
          <Route path="/admin/users" element={<UserListPage />} />
          <Route path="/admin/users/:userId" element={<UserDetailPage />} />
          <Route path="/admin/audit" element={<AuditLogPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/auth/login" replace />} />
    </Routes>
  )
}

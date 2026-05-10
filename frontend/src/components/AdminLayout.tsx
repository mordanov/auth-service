import { Link, useLocation, Outlet } from 'react-router-dom'
import { useAuthStore } from '../services/auth'

export function AdminLayout() {
  const location = useLocation()
  const clearToken = useAuthStore((s) => s.clearToken)

  const navItems = [
    { path: '/admin/users', label: 'Users' },
    { path: '/admin/audit', label: 'Audit Log' },
  ]

  async function handleLogout() {
    await fetch('/auth/logout', { method: 'POST', credentials: 'include' })
    clearToken()
    window.location.href = '/auth/login'
  }

  return (
    <div className="min-h-screen bg-background">
      <nav className="border-b border-border bg-card px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <span className="font-semibold text-foreground">Auth Admin</span>
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`text-sm font-medium transition-colors ${
                location.pathname.startsWith(item.path)
                  ? 'text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {item.label}
            </Link>
          ))}
        </div>
        <button
          onClick={handleLogout}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Sign out
        </button>
      </nav>
      <main>
        <Outlet />
      </main>
    </div>
  )
}

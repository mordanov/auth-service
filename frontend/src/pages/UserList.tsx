import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { adminApi, UserSummary } from '../services/api'

const PROVIDER_LABELS: Record<string, string> = {
  google: 'Google',
  microsoft: 'Microsoft',
  local: 'Password',
}

function GrantBadge({ appName, isActive }: { appName: string; isActive: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        isActive
          ? 'bg-primary/10 text-primary'
          : 'bg-muted text-muted-foreground line-through'
      }`}
    >
      {appName}
    </span>
  )
}

export default function UserListPage() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const limit = 20

  const { data, isLoading, error } = useQuery({
    queryKey: ['users', search, page],
    queryFn: () => adminApi.listUsers({ limit, offset: page * limit, q: search || undefined }),
  })

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Users</h1>
        <span className="text-sm text-muted-foreground">{data?.total ?? 0} total</span>
      </div>

      <input
        type="search"
        placeholder="Search by name or email…"
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(0) }}
        className="w-full max-w-sm rounded-md border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
      />

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {error && <p className="text-sm text-destructive">Failed to load users.</p>}

      {data && (
        <div className="rounded-lg border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Name</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Providers</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">App Access</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Since</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.items.map((user: UserSummary) => (
                <tr key={user.id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3 font-medium">{user.display_name}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {user.identity_providers.map((idp) => (
                        <span key={idp.provider} className="text-xs text-muted-foreground">
                          {PROVIDER_LABELS[idp.provider] ?? idp.provider} ({idp.email})
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {user.grants.filter((g) => g.is_active).map((g) => (
                        <GrantBadge key={g.id} appName={g.app_name} isActive={g.is_active} />
                      ))}
                      {user.grants.filter((g) => g.is_active).length === 0 && (
                        <span className="text-xs text-muted-foreground">No access</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {new Date(user.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/admin/users/${user.id}`}
                      className="text-primary hover:underline text-xs font-medium"
                    >
                      Manage →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > limit && (
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded border border-border px-3 py-1 disabled:opacity-40 hover:bg-muted transition-colors"
          >
            ← Prev
          </button>
          <span className="text-muted-foreground">
            Page {page + 1} of {Math.ceil(data.total / limit)}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={(page + 1) * limit >= data.total}
            className="rounded border border-border px-3 py-1 disabled:opacity-40 hover:bg-muted transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}

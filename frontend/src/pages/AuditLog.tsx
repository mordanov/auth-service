import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi, APPS } from '../services/api'

const ACTION_OPTIONS = [
  'grant_created',
  'grant_revoked',
  'login_success',
  'login_failed',
  'token_revoked_all',
  'user_created',
  'user_deactivated',
]

const ACTION_LABELS: Record<string, string> = {
  grant_created: '✅ Grant created',
  grant_revoked: '🚫 Grant revoked',
  login_success: '🔑 Login success',
  login_failed: '❌ Login failed',
  token_revoked_all: '🔒 Sessions revoked',
  user_created: '👤 User created',
  user_deactivated: '⛔ User deactivated',
}

export default function AuditLogPage() {
  const [page, setPage] = useState(0)
  const [appFilter, setAppFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const limit = 50

  const { data, isLoading } = useQuery({
    queryKey: ['audit', page, appFilter, actionFilter],
    queryFn: () =>
      adminApi.getAuditLog({
        limit,
        offset: page * limit,
        app_name: appFilter || undefined,
        action_type: actionFilter || undefined,
      }),
  })

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Audit Log</h1>
        <span className="text-sm text-muted-foreground">{data?.total ?? 0} events</span>
      </div>

      <div className="flex gap-3">
        <select
          value={appFilter}
          onChange={(e) => { setAppFilter(e.target.value); setPage(0) }}
          className="rounded-md border border-border bg-background px-3 py-2 text-sm"
        >
          <option value="">All apps</option>
          {APPS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select
          value={actionFilter}
          onChange={(e) => { setActionFilter(e.target.value); setPage(0) }}
          className="rounded-md border border-border bg-background px-3 py-2 text-sm"
        >
          <option value="">All actions</option>
          {ACTION_OPTIONS.map((a) => <option key={a} value={a}>{ACTION_LABELS[a] ?? a}</option>)}
        </select>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {data && (
        <div className="rounded-lg border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">When</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Action</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Actor</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Target</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">App</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.items.map((event) => (
                <tr key={event.id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                    {new Date(event.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 font-medium">
                    {ACTION_LABELS[event.action_type] ?? event.action_type}
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground">
                    {event.actor_display_name ?? event.actor_user_id?.slice(0, 8) ?? '—'}
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground">
                    {event.target_user_display_name ?? event.target_user_id?.slice(0, 8) ?? '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    {event.target_app ? (
                      <span className="rounded-full bg-primary/10 text-primary px-2 py-0.5 text-xs">
                        {event.target_app}
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > limit && (
        <div className="flex items-center gap-3 text-sm">
          <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
            className="rounded border border-border px-3 py-1 disabled:opacity-40 hover:bg-muted transition-colors">
            ← Prev
          </button>
          <span className="text-muted-foreground">Page {page + 1} of {Math.ceil(data.total / limit)}</span>
          <button onClick={() => setPage((p) => p + 1)} disabled={(page + 1) * limit >= data.total}
            className="rounded border border-border px-3 py-1 disabled:opacity-40 hover:bg-muted transition-colors">
            Next →
          </button>
        </div>
      )}
    </div>
  )
}

import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, APPS } from '../services/api'

const ACTION_LABELS: Record<string, string> = {
  grant_created: '✅ Grant created',
  grant_revoked: '🚫 Grant revoked',
  login_success: '🔑 Login',
  login_failed: '❌ Login failed',
  token_revoked_all: '🔒 All sessions revoked',
  user_created: '👤 User created',
  user_deactivated: '⛔ User deactivated',
}

export default function UserDetailPage() {
  const { userId } = useParams<{ userId: string }>()
  const qc = useQueryClient()

  const { data: user, isLoading } = useQuery({
    queryKey: ['user', userId],
    queryFn: () => adminApi.getUser(userId!),
    enabled: !!userId,
  })

  const grantMutation = useMutation({
    mutationFn: ({ appName, role }: { appName: string; role: string }) =>
      adminApi.createGrant({ user_id: userId!, app_name: appName, role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['user', userId] }),
  })

  const revokeMutation = useMutation({
    mutationFn: (grantId: string) => adminApi.revokeGrant(grantId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['user', userId] }),
  })

  const revokeSessionsMutation = useMutation({
    mutationFn: () => adminApi.revokeAllSessions(userId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['user', userId] }),
  })

  if (isLoading) return <div className="p-6 text-muted-foreground">Loading…</div>
  if (!user) return <div className="p-6 text-destructive">User not found.</div>

  const activeGrants = new Set(user.grants.filter((g) => g.is_active).map((g) => g.app_name))

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-center gap-3">
        <Link to="/admin/users" className="text-muted-foreground hover:text-foreground text-sm">
          ← Users
        </Link>
        <h1 className="text-xl font-semibold">{user.display_name}</h1>
        {!user.is_active && (
          <span className="rounded-full bg-destructive/10 text-destructive text-xs px-2 py-0.5">Inactive</span>
        )}
      </div>

      {/* Identity providers */}
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Identity Providers</h2>
        <div className="flex flex-wrap gap-2">
          {user.identity_providers.map((idp) => (
            <div key={idp.provider} className="rounded-md border border-border px-3 py-1.5 text-sm">
              <span className="font-medium capitalize">{idp.provider}</span>
              <span className="ml-2 text-muted-foreground">{idp.email}</span>
            </div>
          ))}
        </div>
      </section>

      {/* App access toggles */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Application Access</h2>
        <div className="grid gap-2">
          {APPS.map((appName) => {
            const grant = user.grants.find((g) => g.app_name === appName && g.is_active)
            const hasAccess = activeGrants.has(appName)
            return (
              <div
                key={appName}
                className="flex items-center justify-between rounded-lg border border-border px-4 py-2"
              >
                <div>
                  <span className="font-medium text-sm">{appName}</span>
                  {grant && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      since {new Date(grant.granted_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => {
                    if (hasAccess && grant) {
                      revokeMutation.mutate(grant.id)
                    } else {
                      grantMutation.mutate({ appName, role: 'user' })
                    }
                  }}
                  disabled={grantMutation.isPending || revokeMutation.isPending}
                  className={`rounded-full px-4 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                    hasAccess
                      ? 'bg-destructive/10 text-destructive hover:bg-destructive/20'
                      : 'bg-primary/10 text-primary hover:bg-primary/20'
                  }`}
                >
                  {hasAccess ? 'Revoke' : 'Grant'}
                </button>
              </div>
            )
          })}
        </div>
      </section>

      {/* Emergency revocation */}
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Sessions</h2>
        <button
          onClick={() => {
            if (confirm(`Revoke ALL sessions for ${user.display_name}? They will be signed out immediately.`)) {
              revokeSessionsMutation.mutate()
            }
          }}
          disabled={revokeSessionsMutation.isPending}
          className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
        >
          {revokeSessionsMutation.isPending ? 'Revoking…' : '⚠ Revoke all sessions'}
        </button>
      </section>

      {/* Recent activity */}
      {user.recent_events.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Recent Activity</h2>
          <div className="space-y-1">
            {user.recent_events.map((event) => (
              <div key={event.id} className="flex items-center justify-between text-sm py-1.5 border-b border-border last:border-0">
                <span>{ACTION_LABELS[event.action_type] ?? event.action_type}</span>
                {event.target_app && (
                  <span className="text-xs text-muted-foreground">{event.target_app}</span>
                )}
                <span className="text-xs text-muted-foreground">
                  {new Date(event.created_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

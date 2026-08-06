// Local session state: who is signed in and whether the backend has moved
// us to blocked (revoked / grace period over / build too old).
import { useEffect, useState } from 'react'

import { t } from '../i18n'
import type { AuthState } from '../types'

// Re-read the local /api/auth/status every minute — the backend's background
// verify may have moved us to blocked.
const STATUS_POLL_INTERVAL_MS = 60 * 1000

type StatusResponse = {
  logged_in: boolean
  username?: string
  effective_status?: 'ok' | 'blocked'
  status?: 'ok' | 'revoked' | 'offline' | 'update_required'
  download_url?: string | null
}

function blockedReason(status: StatusResponse['status']): string {
  if (status === 'revoked') return t('blocked.revoked')
  if (status === 'update_required') return t('blocked.updateRequired')
  return t('blocked.offline')
}

export function useAuth() {
  const [auth, setAuth] = useState<AuthState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    function applyStatus(data: StatusResponse | null) {
      if (cancelled) return
      if (!data?.logged_in) {
        setAuth({ phase: 'anonymous' })
        return
      }
      if (data.effective_status === 'blocked') {
        setAuth({
          phase: 'blocked',
          username: data.username ?? '',
          reason: blockedReason(data.status),
          downloadUrl: data.download_url ?? undefined,
        })
        return
      }
      setAuth({ phase: 'authenticated', username: data.username ?? '' })
    }

    function check() {
      fetch('/api/auth/status')
        .then((res) => (res.ok ? res.json() : null))
        .then(applyStatus)
        .catch(() => {
          // /api/auth/status is local; an error here means "backend is down".
          // Don't drop the session: wait for the next tick.
        })
    }

    check()
    const id = setInterval(check, STATUS_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  async function logout() {
    await fetch('/api/auth/logout', { method: 'POST' })
    // Search state lives in SearchPage and dies with it when the login
    // screen replaces the shell — nothing else to clear here.
    setAuth({ phase: 'anonymous' })
  }

  return { auth, setAuth, logout }
}

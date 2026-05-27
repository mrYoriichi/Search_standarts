import { useState } from 'react'
import { Button } from '@/components/ui/button'

type Props = {
  onLoggedIn: (username: string) => void
}

export default function LoginPage({ onLoggedIn }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (res.status === 401) {
        setError('Неверный логин или пароль')
        return
      }
      if (res.status === 403) {
        setError('Доступ отозван. Обратитесь к администратору.')
        return
      }
      if (res.status === 503) {
        setError('Сервер лицензий недоступен. Попробуйте позже.')
        return
      }
      if (!res.ok) {
        setError(`Ошибка: ${res.status}`)
        return
      }
      const data = await res.json()
      onLoggedIn(data.username)
    } catch {
      setError('Не удалось связаться с приложением.')
    } finally {
      setLoading(false)
    }
  }

  const canSubmit =
    username.trim().length > 0 && password.length > 0 && !loading

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm flex flex-col gap-4 rounded-md border bg-card p-6"
      >
        <h1 className="text-2xl font-bold">Search_standarts</h1>
        <p className="text-sm text-muted-foreground">
          Вход в приложение
        </p>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Логин</span>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={loading}
            autoFocus
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Пароль</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={loading}
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
        </label>

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <Button type="submit" disabled={!canSubmit}>
          {loading ? 'Вхожу...' : 'Войти'}
        </Button>
      </form>
    </div>
  )
}

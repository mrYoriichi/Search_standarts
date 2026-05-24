import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

type HealthStatus = 'loading' | 'ok' | 'error'

function App() {
  const [count, setCount] = useState(0)
  const [health, setHealth] = useState<HealthStatus>('loading')

  useEffect(() => {
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => setHealth(data.status === 'ok' ? 'ok' : 'error'))
      .catch(() => setHealth('error'))
  }, [])

  const healthLabel = {
    loading: '⏳ проверяю...',
    ok: '✅ ok',
    error: '❌ недоступен',
  }[health]

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background text-foreground gap-6">
      <h1 className="text-4xl font-bold">Search_standarts</h1>
      <p className="text-muted-foreground">Каркас фронтенда — shadcn/ui подключён.</p>
      <Button onClick={() => setCount((c) => c + 1)}>
        Нажатий: {count}
      </Button>
      <p className="text-sm text-muted-foreground">Сервер: {healthLabel}</p>
    </div>
  )
}

export default App

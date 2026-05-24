import { useState } from 'react'
import { Button } from '@/components/ui/button'

function App() {
  const [count, setCount] = useState(0)

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background text-foreground gap-6">
      <h1 className="text-4xl font-bold">Search_standarts</h1>
      <p className="text-muted-foreground">Каркас фронтенда — shadcn/ui подключён.</p>
      <Button onClick={() => setCount((c) => c + 1)}>
        Нажатий: {count}
      </Button>
    </div>
  )
}

export default App

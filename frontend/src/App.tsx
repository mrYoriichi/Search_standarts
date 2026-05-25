import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import LibraryPage from './LibraryPage'

type Source = {
  document: string
  section: string
  pages: number[]
}

type AskResponse = {
  answer: string
  sources: Source[]
  query_log_id: number
}

type Document = {
  id: number
  slug: string
  title: string
  status: string
}

type View = 'search' | 'library'

function App() {
  const [view, setView] = useState<View>('search')

  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AskResponse | null>(null)

  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(new Set())

  // Загружаем список документов один раз при открытии страницы
  useEffect(() => {
    fetch('/api/documents')
      .then((res) => res.json())
      .then((data: Document[]) => setDocuments(data))
      .catch(() => setDocuments([]))
  }, [])

  function toggleSlug(slug: string) {
    setSelectedSlugs((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  async function handleAsk() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      // Если ничего не выбрано — не шлём document_ids, бэк ищет везде
      const body: { question: string; document_ids?: string[] } = { question }
      if (selectedSlugs.size > 0) {
        body.document_ids = Array.from(selectedSlugs)
      }

      const res = await fetch('/api/queries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        throw new Error(`Сервер вернул ${res.status}`)
      }
      const data: AskResponse = await res.json()
      setResult(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Неизвестная ошибка')
    } finally {
      setLoading(false)
    }
  }

  const canSubmit = question.trim().length > 0 && !loading

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-3xl mx-auto px-6 py-10 flex flex-col gap-6">
        <h1 className="text-3xl font-bold">Search_standarts</h1>

        <nav className="flex gap-1 border-b">
          <button
            onClick={() => setView('search')}
            className={
              'px-4 py-2 text-sm border-b-2 -mb-px ' +
              (view === 'search'
                ? 'border-foreground font-medium'
                : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            Поиск
          </button>
          <button
            onClick={() => setView('library')}
            className={
              'px-4 py-2 text-sm border-b-2 -mb-px ' +
              (view === 'library'
                ? 'border-foreground font-medium'
                : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            Библиотека
          </button>
        </nav>

        {view === 'library' && <LibraryPage />}

        {view === 'search' && (
          <>
        <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-muted-foreground">
            Где искать (пусто — во всех документах)
          </h2>
          {documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Документов нет. Запусти seed-скрипт.
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {documents.map((doc) => (
                <li key={doc.id}>
                  <label className="flex items-center gap-2 cursor-pointer text-sm">
                    <input
                      type="checkbox"
                      checked={selectedSlugs.has(doc.slug)}
                      onChange={() => toggleSlug(doc.slug)}
                      className="h-4 w-4"
                    />
                    <span>{doc.title}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Textarea
          placeholder="Задайте вопрос по строительным нормам..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={4}
          disabled={loading}
        />

        <Button onClick={handleAsk} disabled={!canSubmit} className="self-start">
          {loading ? 'Ищу...' : 'Спросить'}
        </Button>

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
            {error}
          </div>
        )}

        {result && (
          <div className="flex flex-col gap-4">
            <div className="rounded-md border bg-card p-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                Ответ
              </h2>
              <p className="whitespace-pre-wrap">{result.answer}</p>
            </div>

            <div className="rounded-md border bg-card p-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                Источники
              </h2>
              {result.sources.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Модель не нашла ответа в фрагментах.
                </p>
              ) : (
                <ul className="flex flex-col gap-2 text-sm">
                  {result.sources.map((src, i) => (
                    <li key={i}>
                      <span className="font-medium">{src.document}</span>
                      {' / '}
                      <span>{src.section}</span>
                      {' / стр. '}
                      <span>{src.pages.join(', ')}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
          </>
        )}
      </div>
    </div>
  )
}

export default App

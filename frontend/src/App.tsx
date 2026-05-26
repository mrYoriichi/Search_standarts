import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import LibraryPage from './LibraryPage'

type Source = {
  document: string
  slug: string
  section: string
  pages: number[]
}

type AskResponse = {
  answer: string
  sources: Source[]
  query_log_id: number
}

type LibraryFile = {
  name: string
  path: string
  slug: string
  status: 'processing' | 'ready' | 'failed' | null
  pinned: boolean
}

type LibraryFolder = {
  name: string
  path: string
  folders: LibraryFolder[]
  files: LibraryFile[]
}

type LibraryResponse = {
  tree: LibraryFolder
  orphans: unknown[]
}

type View = 'search' | 'library'


// Собирает slug'и всех индексированных (ready) PDF в папке, включая подпапки.
// Используется для чекбокса «выбрать всю папку».
function collectReadySlugs(folder: LibraryFolder): string[] {
  const result: string[] = []
  for (const f of folder.files) {
    if (f.status === 'ready') result.push(f.slug)
  }
  for (const sub of folder.folders) {
    result.push(...collectReadySlugs(sub))
  }
  return result
}

function FilterTree({
  folder,
  selectedSlugs,
  searchAll,
  onToggleFile,
  onToggleFolder,
  isRoot = false,
}: {
  folder: LibraryFolder
  selectedSlugs: Set<string>
  // Когда searchAll=true, чекбоксы в дереве визуально checked и неактивны —
  // пользователь сначала снимает «Вся база», а потом делает тонкий выбор.
  searchAll: boolean
  onToggleFile: (slug: string) => void
  onToggleFolder: (folder: LibraryFolder) => void
  isRoot?: boolean
}) {
  const readySlugs = collectReadySlugs(folder)
  // Папки без индексированных файлов скрываем — иначе много пустоты.
  if (readySlugs.length === 0) return null
  const allSelected = searchAll || readySlugs.every((s) => selectedSlugs.has(s))
  const readyFiles = folder.files.filter((f) => f.status === 'ready')

  return (
    <details className="text-sm">
      <summary className="cursor-pointer flex items-center gap-2">
        {/* У root чекбокса нет — он дублировал бы «Вся база» сверху. */}
        {!isRoot && (
          <input
            type="checkbox"
            checked={allSelected}
            disabled={searchAll}
            onChange={() => onToggleFolder(folder)}
            onClick={(e) => e.stopPropagation()}
            className="h-4 w-4"
          />
        )}
        <span className="font-medium">📁 {folder.name}</span>
      </summary>
      <div className="ml-5 mt-1 flex flex-col gap-1">
        {folder.folders.map((sub) => (
          <FilterTree
            key={sub.path}
            folder={sub}
            selectedSlugs={selectedSlugs}
            searchAll={searchAll}
            onToggleFile={onToggleFile}
            onToggleFolder={onToggleFolder}
          />
        ))}
        {readyFiles.map((file) => (
          <FileCheckbox
            key={file.path}
            file={file}
            selected={searchAll || selectedSlugs.has(file.slug)}
            disabled={searchAll}
            onToggle={onToggleFile}
          />
        ))}
      </div>
    </details>
  )
}


function FileCheckbox({
  file,
  selected,
  disabled,
  onToggle,
}: {
  file: LibraryFile
  selected: boolean
  disabled: boolean
  onToggle: (slug: string) => void
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-sm">
      <input
        type="checkbox"
        checked={selected}
        disabled={disabled}
        onChange={() => onToggle(file.slug)}
        className="h-4 w-4"
      />
      <span>📄 {file.name}</span>
    </label>
  )
}


function App() {
  const [view, setView] = useState<View>('search')

  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AskResponse | null>(null)

  const [library, setLibrary] = useState<LibraryResponse | null>(null)
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(new Set())
  // По умолчанию ищем во всех — самый частый кейс. При снятии открывается дерево.
  const [searchAll, setSearchAll] = useState(true)

  // Загружаем дерево библиотеки один раз — берём готовое API /api/library,
  // в фильтре показываем только ready-документы и папки, где они есть.
  useEffect(() => {
    fetch('/api/library')
      .then((res) => (res.ok ? res.json() : null))
      .then((data: LibraryResponse | null) => setLibrary(data))
      .catch(() => setLibrary(null))
  }, [])

  function toggleSlug(slug: string) {
    setSelectedSlugs((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  function toggleFolder(folder: LibraryFolder) {
    const slugs = collectReadySlugs(folder)
    if (slugs.length === 0) return
    setSelectedSlugs((prev) => {
      const next = new Set(prev)
      const allSelected = slugs.every((s) => next.has(s))
      if (allSelected) {
        slugs.forEach((s) => next.delete(s))
      } else {
        slugs.forEach((s) => next.add(s))
      }
      return next
    })
  }

  async function handleAsk() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      // Если режим «во всех документах» или ничего не выбрано — не шлём
      // document_ids, бэк ищет везде.
      const body: { question: string; document_ids?: string[] } = { question }
      if (!searchAll && selectedSlugs.size > 0) {
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
            Где искать
          </h2>
          {!library || collectReadySlugs(library.tree).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Индексированных документов нет. Перейди в «Библиотеку» и нажми «Сканировать».
            </p>
          ) : (
            <>
              <label className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="checkbox"
                  checked={searchAll}
                  onChange={() => setSearchAll((v) => !v)}
                  className="h-4 w-4"
                />
                <span>Вся база</span>
              </label>
              <div className="mt-1">
                <FilterTree
                  folder={library.tree}
                  selectedSlugs={selectedSlugs}
                  searchAll={searchAll}
                  onToggleFile={toggleSlug}
                  onToggleFolder={toggleFolder}
                  isRoot
                />
              </div>
            </>
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
                  {result.sources.map((src, i) => {
                    const firstPage = src.pages[0]
                    const href = `/api/library/pdf/${src.slug}${
                      firstPage ? `#page=${firstPage}` : ''
                    }`
                    return (
                      <li key={i}>
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:underline"
                          title="Открыть PDF на этой странице"
                        >
                          <span className="font-medium">{src.document}</span>
                          {' / '}
                          <span>{src.section}</span>
                          {' / стр. '}
                          <span>{src.pages.join(', ')}</span>
                        </a>
                      </li>
                    )
                  })}
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

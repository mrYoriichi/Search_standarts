import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'


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

type OrphanDocument = {
  slug: string
  title: string
  status: string
}

type LibraryResponse = {
  tree: LibraryFolder
  orphans: OrphanDocument[]
}


async function openFile(path: string): Promise<void> {
  try {
    const res = await fetch('/api/library/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? 'Не удалось открыть файл')
    }
  } catch {
    alert('Не удалось открыть файл')
  }
}


async function togglePin(slug: string): Promise<void> {
  try {
    const res = await fetch(`/api/documents/${slug}/pin`, { method: 'POST' })
    if (!res.ok) {
      alert(`Не удалось переключить закрепление: ${res.status}`)
    }
  } catch {
    alert('Ошибка сети')
  }
}


async function reindexDocument(slug: string, title: string): Promise<boolean> {
  // Полная переобработка PDF: удаляет старые чанки/эмбеддинги и запускает pipeline заново.
  // Стоит как обычная обработка ($), занимает несколько минут.
  const ok = confirm(
    `Переиндексировать «${title}»?\n\n` +
      `Старые чанки и эмбеддинги будут удалены, документ обработается заново. ` +
      `Это занимает 5–10 минут и стоит примерно $0.50–$1.50.`
  )
  if (!ok) return false
  try {
    const res = await fetch(`/api/documents/${slug}/reindex`, { method: 'POST' })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? `Ошибка ${res.status}`)
      return false
    }
    return true
  } catch {
    alert('Ошибка сети')
    return false
  }
}


async function deleteDocument(slug: string, title: string): Promise<boolean> {
  // Удаляем запись из БД + папку data/raw_data/{slug}/.
  // Сам PDF в библиотеке остаётся — программа файлы юзера не трогает.
  const ok = confirm(
    `Убрать «${title}» из индекса?\n\nСам PDF в папке библиотеки останется. ` +
      `Чанки и эмбеддинги будут удалены.`
  )
  if (!ok) return false
  try {
    const res = await fetch(`/api/documents/${slug}`, { method: 'DELETE' })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? `Ошибка ${res.status}`)
      return false
    }
    return true
  } catch {
    alert('Ошибка сети')
    return false
  }
}


function collectPinned(folder: LibraryFolder): LibraryFile[] {
  const result: LibraryFile[] = []
  for (const file of folder.files) {
    if (file.pinned) result.push(file)
  }
  for (const sub of folder.folders) {
    result.push(...collectPinned(sub))
  }
  return result
}


function collectUnindexed(folder: LibraryFolder): LibraryFile[] {
  const result: LibraryFile[] = []
  for (const file of folder.files) {
    if (file.status === null) result.push(file)
  }
  for (const sub of folder.folders) {
    result.push(...collectUnindexed(sub))
  }
  return result
}


function hasProcessing(folder: LibraryFolder): boolean {
  if (folder.files.some((f) => f.status === 'processing')) return true
  return folder.folders.some(hasProcessing)
}


function OrphanRow({
  orphan,
  unindexed,
  onChange,
}: {
  orphan: OrphanDocument
  unindexed: LibraryFile[]
  onChange: () => void
}) {
  const [selectedSlug, setSelectedSlug] = useState('')

  async function relink() {
    if (!selectedSlug) return
    try {
      const res = await fetch('/api/documents/relink', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_slug: orphan.slug, new_slug: selectedSlug }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? `Ошибка ${res.status}`)
        return
      }
      onChange()
    } catch {
      alert('Ошибка сети')
    }
  }

  return (
    <div className="flex flex-col gap-1 text-sm border-l-2 border-red-500/60 pl-3 py-1">
      <div className="flex items-center gap-2">
        <span>📄 {orphan.title}</span>
        <span className="text-xs text-red-600">файл удалён из папки</span>
        <button
          onClick={async () => {
            if (await deleteDocument(orphan.slug, orphan.title)) onChange()
          }}
          title="Убрать из индекса"
          className="text-base leading-none opacity-40 hover:opacity-100 ml-auto"
        >
          🗑
        </button>
      </div>
      {unindexed.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Чтобы переименовать — положи новый файл в папку библиотеки.
        </p>
      ) : (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Это переименование?</span>
          <select
            value={selectedSlug}
            onChange={(e) => setSelectedSlug(e.target.value)}
            className="border rounded px-1 py-0.5 text-xs flex-1"
          >
            <option value="">— выбрать новое имя —</option>
            {unindexed.map((f) => (
              <option key={f.slug} value={f.slug}>{f.name}</option>
            ))}
          </select>
          <button
            onClick={relink}
            disabled={!selectedSlug}
            className="border rounded px-2 py-0.5 text-xs disabled:opacity-40"
          >
            Связать
          </button>
        </div>
      )}
    </div>
  )
}


function FileRow({
  file,
  freshlyReady,
  onChange,
}: {
  file: LibraryFile
  freshlyReady: Set<string>
  onChange: () => void
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <button
        onClick={async () => {
          await togglePin(file.slug)
          onChange()
        }}
        title={file.pinned ? 'Открепить' : 'Закрепить'}
        className={
          file.pinned
            ? 'text-base leading-none'
            : 'text-base leading-none opacity-25 hover:opacity-100'
        }
      >
        📌
      </button>
      <button
        onClick={() => openFile(file.path)}
        className="text-foreground hover:underline text-left flex-1"
        title="Открыть в системном просмотрщике"
      >
        📄 {file.name}
      </button>
      <StatusLabel status={file.status} freshlyReady={freshlyReady.has(file.slug)} />
      {(file.status === 'ready' || file.status === 'failed') && (
        <button
          onClick={async () => {
            if (await reindexDocument(file.slug, file.name)) onChange()
          }}
          title="Переиндексировать"
          className="text-base leading-none opacity-25 hover:opacity-100"
        >
          🔄
        </button>
      )}
      {file.status !== null && (
        <button
          onClick={async () => {
            if (await deleteDocument(file.slug, file.name)) onChange()
          }}
          title="Убрать из индекса"
          className="text-base leading-none opacity-25 hover:opacity-100"
        >
          🗑
        </button>
      )}
    </div>
  )
}


function StatusLabel({
  status,
  freshlyReady,
}: {
  status: LibraryFile['status']
  freshlyReady: boolean
}) {
  if (status === null) {
    return <span className="text-xs text-muted-foreground">не индексирован</span>
  }
  if (status === 'processing') {
    return <span className="text-xs text-blue-600">обрабатывается…</span>
  }
  if (status === 'failed') {
    return <span className="text-xs text-red-600">ошибка</span>
  }
  // ready: показываем зелёную плашку только если документ только что
  // перешёл в этот статус в текущей сессии. После F5 плашка исчезает.
  if (freshlyReady) {
    return <span className="text-xs text-green-600">готов</span>
  }
  return null
}


function FolderView({
  folder,
  freshlyReady,
  onChange,
}: {
  folder: LibraryFolder
  freshlyReady: Set<string>
  onChange: () => void
}) {
  const isEmpty = folder.folders.length === 0 && folder.files.length === 0
  return (
    <div className="flex flex-col gap-1">
      {isEmpty && (
        <p className="text-xs text-muted-foreground italic">пусто</p>
      )}
      {folder.folders.map((f) => (
        <details key={f.path} open className="text-sm">
          <summary className="cursor-pointer font-medium">📁 {f.name}</summary>
          <div className="ml-5 mt-1">
            <FolderView folder={f} freshlyReady={freshlyReady} onChange={onChange} />
          </div>
        </details>
      ))}
      {folder.files.map((file) => (
        <FileRow
          key={file.path}
          file={file}
          freshlyReady={freshlyReady}
          onChange={onChange}
        />
      ))}
    </div>
  )
}


function LibraryPage() {
  const [path, setPath] = useState<string | null>(null)
  const [pathInput, setPathInput] = useState('')
  const [library, setLibrary] = useState<LibraryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [scanning, setScanning] = useState(false)
  // Slug'и документов, которые в этой сессии только что перешли в 'ready'
  // (например, после Сканировать или Переиндексировать). На них показываем
  // зелёную плашку «готов». После F5 set сбрасывается → плашки пропадают.
  const [freshlyReady, setFreshlyReady] = useState<Set<string>>(new Set())
  const prevStatusesRef = useRef<Map<string, string | null>>(new Map())

  async function loadAll() {
    setLoading(true)
    setError(null)
    try {
      const pathRes = await fetch('/api/settings/library')
      const pathData: { path: string | null } = await pathRes.json()
      setPath(pathData.path)
      if (pathData.path) {
        setPathInput(pathData.path)
        const libRes = await fetch('/api/library')
        if (libRes.ok) {
          setLibrary(await libRes.json())
        } else {
          const errData = await libRes.json().catch(() => ({}))
          setError(errData.detail ?? `Ошибка ${libRes.status}`)
          setLibrary(null)
        }
      } else {
        setLibrary(null)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить библиотеку')
    } finally {
      setLoading(false)
    }
  }

  // Тихий рефреш для поллинга: перезапрашивает только дерево, без лоадера
  // и без перечитывания пути. React перерисует только изменившиеся узлы.
  async function refreshLibrary() {
    try {
      const res = await fetch('/api/library')
      if (res.ok) setLibrary(await res.json())
    } catch {
      // Ошибки сети в фоновом поллинге игнорируем — на следующем тике повторим.
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  // Пока есть документы в статусе processing — обновляем дерево раз в 3 сек,
  // чтобы юзер видел переход в ready/failed без F5.
  useEffect(() => {
    if (!library || !hasProcessing(library.tree)) return
    const id = setInterval(refreshLibrary, 3000)
    return () => clearInterval(id)
  }, [library])

  // Отслеживаем переходы статусов: если документ был не-ready и стал ready —
  // добавляем в freshlyReady, чтобы один раз показать зелёную плашку «готов».
  useEffect(() => {
    if (!library) return
    const nextStatuses = new Map<string, string | null>()
    const justBecameReady: string[] = []

    function visit(folder: LibraryFolder) {
      for (const f of folder.files) {
        nextStatuses.set(f.slug, f.status)
        const prev = prevStatusesRef.current.get(f.slug)
        // prev === undefined → файл виден впервые (первый рендер
        // или только что появился через сканирование). Не подсвечиваем.
        if (prev !== undefined && prev !== 'ready' && f.status === 'ready') {
          justBecameReady.push(f.slug)
        }
      }
      folder.folders.forEach(visit)
    }
    visit(library.tree)
    prevStatusesRef.current = nextStatuses

    if (justBecameReady.length > 0) {
      setFreshlyReady((prev) => {
        const next = new Set(prev)
        justBecameReady.forEach((s) => next.add(s))
        return next
      })
    }
  }, [library])

  async function scan() {
    setScanning(true)
    try {
      const res = await fetch('/api/library/scan', { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? `Ошибка ${res.status}`)
        return
      }
      const data: { created: number; already_indexed: number } = await res.json()
      if (data.created === 0) {
        alert(`Новых PDF не найдено (уже в индексе: ${data.already_indexed}).`)
      } else {
        alert(`Запущена обработка ${data.created} новых PDF.`)
      }
      await loadAll()
    } catch {
      alert('Ошибка сети')
    } finally {
      setScanning(false)
    }
  }

  async function savePath() {
    const value = pathInput.trim()
    if (!value) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/library', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: value }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? `Ошибка ${res.status}`)
        return
      }
      await loadAll()
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">Загрузка…</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Папка библиотеки
        </h2>
        <p className="text-xs text-muted-foreground">
          Все PDF из этой папки (и подпапок) появятся в библиотеке.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            placeholder="/Users/.../Normy"
            className="flex-1 border rounded px-2 py-1 text-sm font-mono"
          />
          <Button
            onClick={savePath}
            disabled={saving || !pathInput.trim() || pathInput === path}
          >
            {saving ? 'Сохраняю…' : 'Сохранить'}
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {library && (() => {
        const pinned = collectPinned(library.tree)
        const unindexed = collectUnindexed(library.tree)
        return (
          <>
            {library.orphans.length > 0 && (
              <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4">
                <h2 className="text-sm font-semibold text-red-600 mb-2">
                  Висячие документы
                </h2>
                <p className="text-xs text-muted-foreground mb-3">
                  Эти документы есть в индексе, но файлов в папке не нашлось. Возможно ты их переименовал или удалил.
                </p>
                <div className="flex flex-col gap-2">
                  {library.orphans.map((orphan) => (
                    <OrphanRow
                      key={orphan.slug}
                      orphan={orphan}
                      unindexed={unindexed}
                      onChange={loadAll}
                    />
                  ))}
                </div>
              </div>
            )}

            {pinned.length > 0 && (
              <div className="rounded-md border bg-card p-4">
                <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                  📌 Закреплённые
                </h2>
                <div className="flex flex-col gap-1">
                  {pinned.map((file) => (
                    <FileRow
                      key={file.path}
                      file={file}
                      freshlyReady={freshlyReady}
                      onChange={loadAll}
                    />
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-md border bg-card p-4">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-sm font-semibold text-muted-foreground">
                  Содержимое
                </h2>
                <Button
                  onClick={scan}
                  disabled={scanning}
                  variant="outline"
                  size="sm"
                >
                  {scanning ? 'Сканирую…' : 'Сканировать'}
                </Button>
              </div>
              <FolderView
                folder={library.tree}
                freshlyReady={freshlyReady}
                onChange={loadAll}
              />
            </div>
          </>
        )
      })()}
    </div>
  )
}


export default LibraryPage

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { IndexingSettingsButton } from './IndexingSettings'
import { t, useI18n } from './i18n'


type LibraryFile = {
  name: string
  path: string
  slug: string
  status: 'pending' | 'processing' | 'ready' | 'failed' | null
  pinned: boolean
  error: string | null
  progress: string | null
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
      alert(data.detail ?? t('lib.openFailed'))
    }
  } catch {
    alert(t('lib.openFailed'))
  }
}


async function togglePin(slug: string): Promise<void> {
  try {
    const res = await fetch(`/api/documents/${slug}/pin`, { method: 'POST' })
    if (!res.ok) {
      alert(t('lib.pinFailed', { status: res.status }))
    }
  } catch {
    alert(t('common.networkError'))
  }
}


async function reindexDocument(
  slug: string,
  title: string,
  resume: boolean,
): Promise<boolean> {
  // ready → полная пересборка (артефакты сносятся, vision платится заново);
  // failed → продолжение с чекпоинта (оплачиваются только новые страницы).
  const ok = confirm(
    t(resume ? 'lib.retryConfirm' : 'lib.reindexConfirm', { title }),
  )
  if (!ok) return false
  try {
    const res = await fetch(`/api/documents/${slug}/reindex`, { method: 'POST' })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? t('common.errorStatus', { status: res.status }))
      return false
    }
    return true
  } catch {
    alert(t('common.networkError'))
    return false
  }
}


async function deleteDocument(slug: string, title: string): Promise<boolean> {
  // Удаляем запись из БД + папку data/raw_data/{slug}/.
  // Сам PDF в библиотеке остаётся — программа файлы юзера не трогает.
  const ok = confirm(t('lib.deleteConfirm', { title }))
  if (!ok) return false
  try {
    const res = await fetch(`/api/documents/${slug}`, { method: 'DELETE' })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? t('common.errorStatus', { status: res.status }))
      return false
    }
    return true
  } catch {
    alert(t('common.networkError'))
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


function countPending(folder: LibraryFolder): number {
  let count = folder.files.filter((f) => f.status === 'pending').length
  for (const sub of folder.folders) {
    count += countPending(sub)
  }
  return count
}


// eslint предупредил бы про хук в map — OrphanRow компонент, useI18n тут законен.
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
        alert(data.detail ?? t('common.errorStatus', { status: res.status }))
        return
      }
      onChange()
    } catch {
      alert(t('common.networkError'))
    }
  }

  return (
    <div className="flex flex-col gap-1 text-sm border-l-2 border-red-500/60 pl-3 py-1">
      <div className="flex items-center gap-2">
        <span>📄 {orphan.title}</span>
        <span className="text-xs text-red-600 dark:text-red-400">
          {t('lib.orphanGone')}
        </span>
        <button
          onClick={async () => {
            if (await deleteDocument(orphan.slug, orphan.title)) onChange()
          }}
          title={t('lib.removeFromIndex')}
          className="text-base leading-none opacity-40 hover:opacity-100 ml-auto"
        >
          🗑
        </button>
      </div>
      {unindexed.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t('lib.orphanHint')}</p>
      ) : (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">{t('lib.isRename')}</span>
          <select
            value={selectedSlug}
            onChange={(e) => setSelectedSlug(e.target.value)}
            className="border rounded px-1 py-0.5 text-xs flex-1"
          >
            <option value="">{t('lib.chooseNewName')}</option>
            {unindexed.map((f) => (
              <option key={f.slug} value={f.slug}>{f.name}</option>
            ))}
          </select>
          <button
            onClick={relink}
            disabled={!selectedSlug}
            className="border rounded px-2 py-0.5 text-xs disabled:opacity-40"
          >
            {t('lib.relink')}
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
    <div>
    <div className="flex items-center gap-2 text-sm">
      <button
        onClick={async () => {
          await togglePin(file.slug)
          onChange()
        }}
        title={file.pinned ? t('lib.unpin') : t('lib.pin')}
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
        title={t('lib.openInViewer')}
      >
        📄 {file.name}
      </button>
      <StatusLabel
        status={file.status}
        progress={file.progress}
        freshlyReady={freshlyReady.has(file.slug)}
      />
      {(file.status === 'ready' || file.status === 'failed') && (
        <button
          onClick={async () => {
            if (
              await reindexDocument(
                file.slug,
                file.name,
                file.status === 'failed',
              )
            )
              onChange()
          }}
          title={t('lib.reindexTitle')}
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
          title={t('lib.removeFromIndex')}
          className="text-base leading-none opacity-25 hover:opacity-100"
        >
          🗑
        </button>
      )}
    </div>
    {file.status === 'failed' && file.error && (
      <div className="text-xs text-red-600 dark:text-red-400 pl-7">{file.error}</div>
    )}
    </div>
  )
}


function StatusLabel({
  status,
  progress,
  freshlyReady,
}: {
  status: LibraryFile['status']
  progress: string | null
  freshlyReady: boolean
}) {
  if (status === null) {
    return <span className="text-xs text-muted-foreground">{t('status.notIndexed')}</span>
  }
  if (status === 'pending') {
    return (
      <span className="text-xs text-amber-600 dark:text-amber-400">
        {t('status.pending')}
      </span>
    )
  }
  if (status === 'processing') {
    return (
      <span className="text-xs text-blue-600 dark:text-blue-400">
        {progress ?? t('status.processing')}
      </span>
    )
  }
  if (status === 'failed') {
    return <span className="text-xs text-red-600 dark:text-red-400">{t('status.failed')}</span>
  }
  // ready: показываем зелёную плашку только если документ только что
  // перешёл в этот статус в текущей сессии. После F5 плашка исчезает.
  if (freshlyReady) {
    return <span className="text-xs text-green-600 dark:text-green-400">{t('status.ready')}</span>
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
        <p className="text-xs text-muted-foreground italic">{t('lib.empty')}</p>
      )}
      {folder.folders.map((f) => (
        <details key={f.path} className="rounded-md border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-semibold flex items-center gap-2">
            📁 {f.name}
          </summary>
          <div className="flex flex-col gap-1 mt-2 ml-1">
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
  useI18n() // подписка: смена языка перерисовывает страницу
  const [paths, setPaths] = useState<string[]>([])
  const [pathInput, setPathInput] = useState('')
  // Какую папку сейчас правим (её путь) и текущий текст правки. null — не правим.
  const [editingPath, setEditingPath] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [library, setLibrary] = useState<LibraryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [indexing, setIndexing] = useState(false)
  // Slug'и документов, которые в этой сессии только что перешли в 'ready'
  // (например, после Сканировать или Переиндексировать). На них показываем
  // зелёную плашку «готов». После F5 set сбрасывается → плашки пропадают.
  const [freshlyReady, setFreshlyReady] = useState<Set<string>>(new Set())
  const prevStatusesRef = useRef<Map<string, string | null>>(new Map())

  async function loadAll() {
    setLoading(true)
    setError(null)
    try {
      const pathRes = await fetch('/api/settings/libraries')
      const pathData: { paths: string[] } = await pathRes.json()
      setPaths(pathData.paths)
      if (pathData.paths.length > 0) {
        const libRes = await fetch('/api/library')
        if (libRes.ok) {
          setLibrary(await libRes.json())
        } else {
          const errData = await libRes.json().catch(() => ({}))
          setError(errData.detail ?? `Chyba ${libRes.status}`)
          setLibrary(null)
        }
      } else {
        setLibrary(null)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t('lib.loadFailed'))
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
    // Ложный оклик правила: setState в loadAll случается после await,
    // не синхронно (плагин не моделирует async-функции).
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
        alert(data.detail ?? t('common.errorStatus', { status: res.status }))
        return
      }
      const data: {
        created: number
        already_indexed: number
        adopted?: number
        duplicates?: string[]
        limit_skipped?: number
      } = await res.json()
      let msg =
        data.created === 0
          ? t('lib.scanNoNew', { n: data.already_indexed })
          : t('lib.scanFound', { n: data.created })
      if (data.adopted && data.adopted > 0) {
        msg += '\n\n' + t('lib.scanAdopted', { n: data.adopted })
      }
      if (data.limit_skipped && data.limit_skipped > 0) {
        msg += '\n\n' + t('lib.scanLimit', { n: data.limit_skipped })
      }
      if (data.duplicates && data.duplicates.length > 0) {
        msg += '\n\n' + t('lib.scanDuplicates') + '\n' + data.duplicates.join('\n')
      }
      alert(msg)
      await loadAll()
    } catch {
      alert(t('common.networkError'))
    } finally {
      setScanning(false)
    }
  }

  async function startIndexing() {
    setIndexing(true)
    try {
      const res = await fetch('/api/library/index', { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? t('common.errorStatus', { status: res.status }))
        return
      }
      const data: { started: number; locked?: string[]; over_limit?: number } =
        await res.json()
      if (data.locked && data.locked.length > 0) {
        alert(t('lib.lockedMsg', { list: data.locked.join('\n') }))
      }
      if (data.over_limit && data.over_limit > 0) {
        alert(t('lib.overLimitMsg', { n: data.over_limit }))
      }
      await loadAll()
    } catch {
      alert(t('common.networkError'))
    } finally {
      setIndexing(false)
    }
  }

  async function addPath() {
    const value = pathInput.trim()
    if (!value) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/libraries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: value }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? t('common.errorStatus', { status: res.status }))
        return
      }
      setPathInput('')
      await loadAll()
    } finally {
      setSaving(false)
    }
  }

  async function removePath(target: string) {
    if (!confirm(t('lib.removePathConfirm', { path: target }))) return
    const res = await fetch('/api/settings/libraries', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: target }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? t('common.errorStatus', { status: res.status }))
      return
    }
    await loadAll()
  }

  function startEdit(target: string) {
    setEditingPath(target)
    setEditValue(target)
  }

  async function savePathEdit() {
    const value = editValue.trim()
    if (!value || editingPath === null) return
    if (value === editingPath) {
      setEditingPath(null)
      return
    }
    setSaving(true)
    try {
      const res = await fetch('/api/settings/libraries', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_path: editingPath, new_path: value }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? t('common.errorStatus', { status: res.status }))
        return
      }
      setEditingPath(null)
      await loadAll()
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          {t('lib.folders')}
        </h2>
        <p className="text-xs text-muted-foreground">{t('lib.foldersText')}</p>
        {paths.length > 0 && (
          <ul className="flex flex-col gap-1">
            {paths.map((p) => (
              <li
                key={p}
                className="flex items-center gap-2 text-sm font-mono bg-muted/40 rounded px-2 py-1"
              >
                {editingPath === p ? (
                  <>
                    <input
                      type="text"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') savePathEdit()
                        if (e.key === 'Escape') setEditingPath(null)
                      }}
                      autoFocus
                      className="flex-1 border rounded px-2 py-0.5 text-sm font-mono"
                    />
                    <button
                      onClick={savePathEdit}
                      disabled={saving || !editValue.trim()}
                      className="text-muted-foreground hover:text-foreground shrink-0"
                      title={t('common.saveTitle')}
                    >
                      ✓
                    </button>
                    <button
                      onClick={() => setEditingPath(null)}
                      className="text-muted-foreground hover:text-foreground shrink-0"
                      title={t('common.cancel')}
                    >
                      ✕
                    </button>
                  </>
                ) : (
                  <>
                    <span className="flex-1 break-all">{p}</span>
                    <button
                      onClick={() => startEdit(p)}
                      className="text-muted-foreground hover:text-foreground shrink-0"
                      title={t('lib.editPath')}
                    >
                      ✎
                    </button>
                    <button
                      onClick={() => removePath(p)}
                      className="text-muted-foreground hover:text-destructive shrink-0"
                      title={t('lib.detachFolder')}
                    >
                      🗑
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addPath()}
            placeholder="/Users/.../Normy"
            className="flex-1 border rounded px-2 py-1 text-sm font-mono"
          />
          <Button onClick={addPath} disabled={saving || !pathInput.trim()}>
            {saving ? t('lib.adding') : t('lib.addFolder')}
          </Button>
        </div>
      </div>

      <div>
        <IndexingSettingsButton />
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {library && (() => {
        const pinned = collectPinned(library.tree)
        const unindexed = collectUnindexed(library.tree)
        const pendingCount = countPending(library.tree)
        return (
          <>
            {library.orphans.length > 0 && (
              <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4">
                <h2 className="text-sm font-semibold text-red-600 dark:text-red-400 mb-2">
                  {t('lib.orphans')}
                </h2>
                <p className="text-xs text-muted-foreground mb-3">
                  {t('lib.orphansText')}
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
                  📌 {t('lib.pinned')}
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
                  {t('lib.contents')}
                </h2>
                <div className="flex items-center gap-2">
                  {pendingCount > 0 && (
                    <Button
                      onClick={startIndexing}
                      disabled={indexing}
                      size="sm"
                    >
                      {indexing
                        ? t('lib.starting')
                        : t('lib.indexN', { n: pendingCount })}
                    </Button>
                  )}
                  <Button
                    onClick={scan}
                    disabled={scanning}
                    variant="outline"
                    size="sm"
                  >
                    {scanning ? t('lib.scanning') : t('lib.scan')}
                  </Button>
                </div>
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

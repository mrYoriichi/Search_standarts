import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { IndexingSettingsButton } from './IndexingSettings'
import { t, useI18n } from './i18n'

// Архив проектов юзера: каждая подключённая папка = один проект (все PDF
// внутри, включая подпапки). «Skenovat», документы по проектам со статусами.

type ArchiveDocument = {
  slug: string
  project: string
  relative_path: string
  page_count: number
  status: string
  error: string | null
  pinned: boolean
  progress: string | null
}

type ArchiveResponse = {
  paths: string[]
  projects: { name: string; documents: ArchiveDocument[] }[]
}

type ScanSummary = {
  found: number
  new: number
  missing: number
  changed: number // заменённые PDF (новое содержимое) — вернулись в «čeká»
  duplicates: string[]
  errors: string[]
  unavailable: string[]
}

// Поллинг статусов, пока что-то обрабатывается (pipeline идёт в фоне).
const POLL_INTERVAL_MS = 3000

async function togglePin(slug: string): Promise<void> {
  try {
    const res = await fetch(`/api/projects/${slug}/pin`, { method: 'POST' })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? t('lib.pinFailed', { status: res.status }))
    }
  } catch {
    alert(t('common.networkError'))
  }
}

async function reindexDocument(
  slug: string,
  name: string,
  resume: boolean,
): Promise<boolean> {
  // ready → полная пересборка (vision платится заново); error → продолжение
  // с чекпоинта (оплачиваются только новые страницы).
  const ok = confirm(
    t(resume ? 'lib.retryConfirm' : 'arch.reindexConfirm', { title: name }),
  )
  if (!ok) return false
  try {
    const res = await fetch(`/api/projects/${slug}/reindex`, { method: 'POST' })
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

// Все закреплённые документы архива (плоско, для секции «Připnuté»).
function collectPinned(archive: ArchiveResponse): ArchiveDocument[] {
  const pinned: ArchiveDocument[] = []
  for (const project of archive.projects) {
    for (const doc of project.documents) {
      if (doc.pinned) pinned.push(doc)
    }
  }
  return pinned
}

function StatusLabel({
  doc,
  freshlyReady,
}: {
  doc: ArchiveDocument
  freshlyReady: boolean
}) {
  if (doc.status === 'pending') {
    return (
      <span className="text-xs text-amber-600 dark:text-amber-400">
        {t('status.pending')}
      </span>
    )
  }
  if (doc.status === 'processing') {
    return (
      <span className="text-xs text-blue-600 dark:text-blue-400">
        {doc.progress ?? t('status.processing')}
      </span>
    )
  }
  if (doc.status === 'error') {
    return <span className="text-xs text-red-600 dark:text-red-400">{t('status.failed')}</span>
  }
  // ready: зелёную плашку показываем только на переходе (как в knihovně).
  if (freshlyReady) {
    return <span className="text-xs text-green-600 dark:text-green-400">{t('status.ready')}</span>
  }
  return null
}

function DocumentRow({
  doc,
  freshlyReady,
  onChange,
}: {
  doc: ArchiveDocument
  freshlyReady: Set<string>
  onChange: () => void
}) {
  // relative_path уже относителен папке проекта (модель «папка = проект»,
  // 2026-07-28) — показываем целиком. Отрезание первого сегмента осталось бы
  // от старой модели и съедало бы имя файла в корне проекта. `\` → `/`:
  // старые записи с Windows содержат обратный слэш.
  const insideProject = doc.relative_path.split(/[\\/]/).join('/')
  return (
    <div>
      <div className="flex items-center gap-2 text-sm">
        <button
          onClick={async () => {
            await togglePin(doc.slug)
            onChange()
          }}
          title={doc.pinned ? t('lib.unpin') : t('lib.pin')}
          className={
            doc.pinned
              ? 'text-base leading-none'
              : 'text-base leading-none opacity-25 hover:opacity-100'
          }
        >
          📌
        </button>
        {doc.status === 'ready' ? (
          <a
            href={`/api/library/pdf/${doc.slug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground hover:underline flex-1"
            title={t('arch.openPdf')}
          >
            📄 {insideProject}
          </a>
        ) : (
          <span className="flex-1 text-muted-foreground">
            📄 {insideProject}
          </span>
        )}
        <span className="text-xs text-muted-foreground">
          {t('arch.pages', { n: doc.page_count })}
        </span>
        <StatusLabel doc={doc} freshlyReady={freshlyReady.has(doc.slug)} />
        {(doc.status === 'ready' || doc.status === 'error') && (
          <button
            onClick={async () => {
              if (
                await reindexDocument(
                  doc.slug,
                  insideProject,
                  doc.status === 'error',
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
      </div>
      {doc.status === 'error' && doc.error && (
        <div className="text-xs text-red-600 dark:text-red-400 pl-7">{doc.error}</div>
      )}
    </div>
  )
}

export default function ArchivePage() {
  useI18n() // подписка: смена языка перерисовывает страницу
  const [paths, setPaths] = useState<string[]>([])
  const [pathInput, setPathInput] = useState('')
  const [editingPath, setEditingPath] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [archive, setArchive] = useState<ArchiveResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [summary, setSummary] = useState<ScanSummary | null>(null)
  // Документы, только что перешедшие в ready — для зелёной плашки «hotovo».
  const [freshlyReady, setFreshlyReady] = useState<Set<string>>(new Set())
  const prevStatusesRef = useRef<Map<string, string>>(new Map())

  // useCallback — стабильная ссылка, чтобы эффекты могли честно указать
  // loadAll в зависимостях без перезапуска на каждый рендер.
  const loadAll = useCallback(async () => {
    // Переход в ready → один раз показываем «hotovo» (как в knihovně). После F5
    // ref сбрасывается, документ считается уже виденным — плашка не мигает.
    function markFreshlyReady(data: ArchiveResponse) {
      const nextStatuses = new Map<string, string>()
      const justReady: string[] = []
      for (const project of data.projects) {
        for (const doc of project.documents) {
          nextStatuses.set(doc.slug, doc.status)
          const prev = prevStatusesRef.current.get(doc.slug)
          if (prev !== undefined && prev !== 'ready' && doc.status === 'ready') {
            justReady.push(doc.slug)
          }
        }
      }
      prevStatusesRef.current = nextStatuses
      if (justReady.length > 0) {
        setFreshlyReady((prev) => {
          const next = new Set(prev)
          justReady.forEach((s) => next.add(s))
          return next
        })
      }
    }

    setError(null)
    try {
      const pathRes = await fetch('/api/settings/projects-libraries')
      const pathData: { paths: string[] } = await pathRes.json()
      setPaths(pathData.paths)

      const res = await fetch('/api/projects')
      if (res.ok) {
        const data: ArchiveResponse = await res.json()
        setArchive(data)
        markFreshlyReady(data)
      } else {
        const data = await res.json().catch(() => ({}))
        setError(data.detail ?? `Chyba ${res.status}`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t('arch.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Ложный оклик правила: setState в loadAll случается после await,
    // не синхронно (плагин не моделирует async-функции).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadAll()
  }, [loadAll])

  // Пока что-то реально обрабатывается — раз в 3 с перечитываем статусы.
  // pending НЕ считается: он ждёт клика «Indexovat», на сервере ничего не
  // меняется — поллинг был бы бесконечным холостым ходом.
  const hasActive = (archive?.projects ?? []).some((p) =>
    p.documents.some((d) => d.status === 'processing'),
  )
  // Обнаруженные, но ещё не индексированные — для кнопки «Indexovat (N)».
  const pendingCount = (archive?.projects ?? []).reduce(
    (sum, p) => sum + p.documents.filter((d) => d.status === 'pending').length,
    0,
  )
  useEffect(() => {
    if (!hasActive) return
    const id = setInterval(loadAll, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [hasActive, loadAll])

  async function addPath() {
    const value = pathInput.trim()
    if (!value) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/projects-libraries', {
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
    if (!confirm(t('arch.removePathConfirm', { path: target }))) return
    const res = await fetch('/api/settings/projects-libraries', {
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
      const res = await fetch('/api/settings/projects-libraries', {
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

  async function scan() {
    setScanning(true)
    setSummary(null)
    try {
      const res = await fetch('/api/projects/scan', { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? t('common.errorStatus', { status: res.status }))
        return
      }
      setSummary(await res.json())
      await loadAll()
    } finally {
      setScanning(false)
    }
  }

  async function startIndexing() {
    setIndexing(true)
    try {
      const res = await fetch('/api/projects/index', { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? t('common.errorStatus', { status: res.status }))
        return
      }
      const data: { started: number; over_limit?: number } = await res.json()
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

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          {t('arch.folders')}
        </h2>
        <p className="text-xs text-muted-foreground">{t('arch.foldersText')}</p>
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
            placeholder="/Users/.../Projekty"
            className="flex-1 border rounded px-2 py-1 text-sm font-mono"
          />
          <Button onClick={addPath} disabled={saving || !pathInput.trim()}>
            {saving ? t('lib.adding') : t('lib.addFolder')}
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <div>
        <IndexingSettingsButton />
      </div>

      {archive &&
        (() => {
          const pinned = collectPinned(archive)
          return (
            <>
              {pinned.length > 0 && (
                <div className="rounded-md border bg-card p-4">
                  <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                    📌 {t('lib.pinned')}
                  </h2>
                  <div className="flex flex-col gap-1">
                    {pinned.map((doc) => (
                      <DocumentRow
                        key={doc.slug}
                        doc={doc}
                        freshlyReady={freshlyReady}
                        onChange={loadAll}
                      />
                    ))}
                  </div>
                </div>
              )}

              <div className="rounded-md border bg-card p-4 flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-muted-foreground">
                    {t('arch.myProjects')}
                  </h2>
                  {paths.length > 0 && (
                    <div className="flex items-center gap-2">
                      {pendingCount > 0 && (
                        <Button
                          onClick={startIndexing}
                          disabled={indexing}
                          size="sm"
                        >
                          {indexing ? t('lib.starting') : t('lib.indexN', { n: pendingCount })}
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
                  )}
                </div>
                {summary && (
                  <p className="text-xs text-muted-foreground">
                    {t('arch.summary', { found: summary.found, fresh: summary.new })}
                    {summary.changed > 0 &&
                      t('arch.summaryChanged', { n: summary.changed })}
                    {summary.missing > 0 &&
                      t('arch.summaryMissing', { n: summary.missing })}
                    {summary.duplicates.length > 0 &&
                      t('arch.summaryDuplicates', { n: summary.duplicates.length })}
                    {summary.errors.length > 0 &&
                      t('arch.summaryErrors', { n: summary.errors.length })}
                  </p>
                )}
                {summary && summary.unavailable.length > 0 && (
                  <p className="text-xs text-red-600 dark:text-red-400">
                    {t('arch.unavailable', { list: summary.unavailable.join(', ') })}
                  </p>
                )}
                {archive.projects.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    {archive.projects.map((project) => {
                      const active = project.documents.filter(
                        (d) => d.status === 'pending' || d.status === 'processing',
                      ).length
                      const errors = project.documents.filter(
                        (d) => d.status === 'error',
                      ).length
                      return (
                        // Проекты свёрнуты по умолчанию — их может быть много.
                        <details
                          key={project.name}
                          className="rounded-md border bg-muted/20 p-3"
                        >
                          <summary className="cursor-pointer text-sm font-semibold flex items-center gap-2">
                            <span>📁 {project.name}</span>
                            <span className="text-xs font-normal text-muted-foreground">
                              {t('arch.docCount', { n: project.documents.length })}
                              {active > 0 && t('arch.processingCount', { n: active })}
                              {errors > 0 && t('arch.errorCount', { n: errors })}
                            </span>
                          </summary>
                          <div className="flex flex-col gap-1 mt-2 ml-1">
                            {project.documents.map((doc) => (
                              <DocumentRow
                                key={doc.slug}
                                doc={doc}
                                freshlyReady={freshlyReady}
                                onChange={loadAll}
                              />
                            ))}
                          </div>
                        </details>
                      )
                    })}
                  </div>
                ) : (
                  paths.length > 0 && (
                    <p className="text-sm text-muted-foreground">
                      {t('arch.noDocs')}
                    </p>
                  )
                )}
              </div>
            </>
          )
        })()}
    </div>
  )
}

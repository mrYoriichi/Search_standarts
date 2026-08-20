import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { IndexingSettingsButton } from './IndexingSettings'
import { t, useI18n } from './i18n'
import { fetchPagesTotal } from './lib/stats'

// The user's project archive: each connected folder = one project (all PDFs
// inside, subfolders included). "Skenovat", documents by project with statuses.

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
  changed: number // replaced PDFs (new content) — returned to "čeká"
  adopted: number // ready indexes taken over from the folder, at no cost
  duplicates: string[]
  errors: string[]
  unavailable: string[]
}

// Status polling while something is processing (the pipeline runs in the background).
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
  // ready -> full rebuild (vision paid again); error -> continue from the
  // checkpoint (only new pages are paid).
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

async function stopDocument(slug: string): Promise<void> {
  // ⏹: queued docs return to čeká immediately, a running one stops at
  // the nearest safe point (checkpoints survive, resuming is free).
  try {
    await fetch(`/api/projects/${slug}/stop`, { method: 'POST' })
  } catch {
    alert(t('common.networkError'))
  }
}


async function indexOneDocument(slug: string): Promise<boolean> {
  // The ▶ button on a pending file: send just this document to processing.
  try {
    const res = await fetch(`/api/projects/index/${slug}`, { method: 'POST' })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? t('common.errorStatus', { status: res.status }))
      return false
    }
    const data: { locked?: string[] } = await res.json()
    if (data.locked && data.locked.length > 0) {
      alert(t('lib.lockedMsg', { list: data.locked.join('\n') }))
    }
    return true
  } catch {
    alert(t('common.networkError'))
    return false
  }
}

function StopProjectButton({
  docs,
  onStop,
}: {
  docs: ArchiveDocument[]
  onStop: (docs: ArchiveDocument[]) => void
}) {
  return (
    <button
      onClick={(e) => {
        // Не сворачивать проект кликом по ⏹.
        e.preventDefault()
        e.stopPropagation()
        onStop(docs)
      }}
      title={t('lib.stopFolderTitle')}
      className="text-base leading-none opacity-25 hover:opacity-100"
    >
      ⏹
    </button>
  )
}

// All pinned archive documents (flat, for the "Připnuté" section).
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
  // ready: the green badge shows only on the transition (as in the library).
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
  // relative_path is already relative to the project folder (the "folder =
  // project" model, 2026-07-28) — show it whole. Cutting the first segment
  // would be a leftover of the old model and would eat the file name in the
  // project root. `\` -> `/`: old Windows records contain backslashes.
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
        {doc.status === 'pending' && (
          <button
            onClick={async () => {
              if (await indexOneDocument(doc.slug)) onChange()
            }}
            title={t('lib.indexOneTitle')}
            className="text-base leading-none opacity-25 hover:opacity-100"
          >
            ▶️
          </button>
        )}
        {doc.status === 'processing' && (
          <button
            onClick={async () => {
              await stopDocument(doc.slug)
              onChange()
            }}
            title={t('lib.stopTitle')}
            className="text-base leading-none opacity-25 hover:opacity-100"
          >
            ⏹
          </button>
        )}
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
  useI18n() // subscription: a language switch re-renders the page
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
  // Documents that just turned ready — for the green "hotovo" badge.
  const [freshlyReady, setFreshlyReady] = useState<Set<string>>(new Set())
  const prevStatusesRef = useRef<Map<string, string>>(new Map())
  // Ready pages of both pools (the whole pool loads into RAM on a question).
  const [pagesTotal, setPagesTotal] = useState<number | null>(null)

  // useCallback — a stable reference so effects can honestly list loadAll
  // in dependencies without restarting on every render.
  const loadAll = useCallback(async () => {
    // Transition to ready -> show "hotovo" once (as in the library). After
    // F5 the ref resets, the document counts as seen — no badge flicker.
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
      const pages = await fetchPagesTotal()
      if (pages !== null) setPagesTotal(pages)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('arch.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // False positive of the rule: setState in loadAll happens after await,
    // not synchronously (the plugin does not model async functions).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadAll()
  }, [loadAll])

  // While something is actually processing — re-read statuses every 3 s.
  // pending does NOT count: it waits for the "Indexovat" click, nothing
  // changes on the server — polling would idle forever.
  const hasActive = (archive?.projects ?? []).some((p) =>
    p.documents.some((d) => d.status === 'processing'),
  )
  // Discovered but not yet indexed — for the "Indexovat (N)" button.
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

  async function stopProject(docs: ArchiveDocument[]) {
    // ⏹ в шапке проекта: остановить все его работающие документы.
    for (const d of docs) {
      if (d.status === 'processing') await stopDocument(d.slug)
    }
    await loadAll()
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
      const data: { started: number; locked?: string[] } = await res.json()
      if (data.locked && data.locked.length > 0) {
        alert(t('lib.lockedMsg', { list: data.locked.join('\n') }))
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
                      {pagesTotal !== null && pagesTotal > 0 && (
                        <span className="text-xs text-muted-foreground">
                          {t('lib.pagesTotal', { n: pagesTotal })}
                        </span>
                      )}
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
                    {summary.adopted > 0 &&
                      t('arch.summaryAdopted', { n: summary.adopted })}
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
                        // Projects are collapsed by default — there may be many.
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
                            {project.documents.some(
                              (d) => d.status === 'processing',
                            ) && (
                              <StopProjectButton
                                docs={project.documents}
                                onStop={stopProject}
                              />
                            )}
                          </summary>
                          {/* Кап высоты: длинный список документов
                              прокручивается внутри проекта, а не
                              растягивает страницу. */}
                          <div className="flex flex-col gap-1 mt-2 ml-1 max-h-96 overflow-y-auto pr-1">
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

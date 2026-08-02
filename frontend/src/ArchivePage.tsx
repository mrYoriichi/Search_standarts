import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { IndexingSettingsButton } from './IndexingSettings'

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
      alert(data.detail ?? `Nepodařilo se přepnout připnutí: ${res.status}`)
    }
  } catch {
    alert('Chyba sítě')
  }
}

async function reindexDocument(slug: string, name: string): Promise<boolean> {
  // Полная переобработка: старые артефакты удаляются, pipeline запускается
  // заново. Vision оплачивается повторно — поэтому подтверждение.
  const ok = confirm(
    `Přeindexovat „${name}“?\n\n` +
      `Staré úryvky a embeddingy budou smazány a dokument se zpracuje znovu. ` +
      `Popisy stránek (vision) se platí znovu.`,
  )
  if (!ok) return false
  try {
    const res = await fetch(`/api/projects/${slug}/reindex`, { method: 'POST' })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? `Chyba ${res.status}`)
      return false
    }
    return true
  } catch {
    alert('Chyba sítě')
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
    return <span className="text-xs text-amber-600 dark:text-amber-400">čeká na indexaci</span>
  }
  if (doc.status === 'processing') {
    return (
      <span className="text-xs text-blue-600 dark:text-blue-400">
        {doc.progress ?? 'zpracovává se…'}
      </span>
    )
  }
  if (doc.status === 'error') {
    return <span className="text-xs text-red-600 dark:text-red-400">chyba</span>
  }
  // ready: зелёную плашку показываем только на переходе (как в knihovně).
  if (freshlyReady) {
    return <span className="text-xs text-green-600 dark:text-green-400">hotovo</span>
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
  // Путь внутри проекта (без имени проекта) — короче и читабельнее.
  // Делим по обоим разделителям: старые записи с Windows содержат `\`.
  const insideProject = doc.relative_path.split(/[\\/]/).slice(1).join('/')
  return (
    <div>
      <div className="flex items-center gap-2 text-sm">
        <button
          onClick={async () => {
            await togglePin(doc.slug)
            onChange()
          }}
          title={doc.pinned ? 'Odepnout' : 'Připnout'}
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
            title="Otevřít PDF v prohlížeči"
          >
            📄 {insideProject}
          </a>
        ) : (
          <span className="flex-1 text-muted-foreground">
            📄 {insideProject}
          </span>
        )}
        <span className="text-xs text-muted-foreground">{doc.page_count} s.</span>
        <StatusLabel doc={doc} freshlyReady={freshlyReady.has(doc.slug)} />
        {(doc.status === 'ready' || doc.status === 'error') && (
          <button
            onClick={async () => {
              if (await reindexDocument(doc.slug, insideProject)) onChange()
            }}
            title="Přeindexovat"
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
      setError(e instanceof Error ? e.message : 'Nepodařilo se načíst archiv')
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
        alert(data.detail ?? `Chyba ${res.status}`)
        return
      }
      setPathInput('')
      await loadAll()
    } finally {
      setSaving(false)
    }
  }

  async function removePath(target: string) {
    if (!confirm(`Odpojit složku archivu?\n${target}\n\nIndexy zůstanou.`)) return
    const res = await fetch('/api/settings/projects-libraries', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: target }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? `Chyba ${res.status}`)
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
        alert(data.detail ?? `Chyba ${res.status}`)
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
        alert(data.detail ?? `Chyba ${res.status}`)
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
        alert(data.detail ?? `Chyba ${res.status}`)
        return
      }
      const data: { started: number; over_limit?: number } = await res.json()
      if (data.over_limit && data.over_limit > 0) {
        alert(
          `${data.over_limit} dokumentů se nevešlo do limitu veřejné verze ` +
            '(3000 stran) — nebyly indexovány. Uvolněte místo smazáním ' +
            'nepotřebných dokumentů.',
        )
      }
      await loadAll()
    } catch {
      alert('Chyba sítě')
    } finally {
      setIndexing(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">Načítání…</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Složky projektů
        </h2>
        <p className="text-xs text-muted-foreground">
          Každá připojená složka = jeden projekt: indexují se všechny PDF uvnitř
          včetně podsložek (TZ, statické výpočty, výkresy). Můžete připojit více
          projektů. Soubory se pouze čtou. Zpracování výkresů využívá vision
          model (viz „Knihovna“).
        </p>
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
                      title="Uložit"
                    >
                      ✓
                    </button>
                    <button
                      onClick={() => setEditingPath(null)}
                      className="text-muted-foreground hover:text-foreground shrink-0"
                      title="Zrušit"
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
                      title="Upravit cestu"
                    >
                      ✎
                    </button>
                    <button
                      onClick={() => removePath(p)}
                      className="text-muted-foreground hover:text-destructive shrink-0"
                      title="Odpojit složku"
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
            {saving ? 'Přidávám…' : 'Přidat složku'}
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
                    📌 Připnuté
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
                    Moje projekty
                  </h2>
                  {paths.length > 0 && (
                    <div className="flex items-center gap-2">
                      {pendingCount > 0 && (
                        <Button
                          onClick={startIndexing}
                          disabled={indexing}
                          size="sm"
                        >
                          {indexing ? 'Spouštím…' : `Indexovat (${pendingCount})`}
                        </Button>
                      )}
                      <Button
                        onClick={scan}
                        disabled={scanning}
                        variant="outline"
                        size="sm"
                      >
                        {scanning ? 'Skenuji…' : 'Skenovat'}
                      </Button>
                    </div>
                  )}
                </div>
                {summary && (
                  <p className="text-xs text-muted-foreground">
                    Nalezeno {summary.found}, nových {summary.new}
                    {summary.changed > 0 &&
                      `, nahrazeno ${summary.changed} (vráceno k indexaci)`}
                    {summary.missing > 0 && `, odstraněno ${summary.missing}`}
                    {summary.duplicates.length > 0 &&
                      `, duplicit ${summary.duplicates.length}`}
                    {summary.errors.length > 0 && `, chyb ${summary.errors.length}`}
                  </p>
                )}
                {summary && summary.unavailable.length > 0 && (
                  <p className="text-xs text-red-600 dark:text-red-400">
                    Nedostupné složky (úklid přeskočen):{' '}
                    {summary.unavailable.join(', ')}
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
                              {project.documents.length} dokumentů
                              {active > 0 && ` · zpracovává se ${active}`}
                              {errors > 0 && ` · chyb ${errors}`}
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
                      Zatím žádné dokumenty — klikněte na „Skenovat“.
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

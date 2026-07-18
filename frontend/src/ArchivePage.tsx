import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

// Архив проектов юзера: список папок архива, «Skenovat», документы по
// проектам со статусами обработки. Можно подключить несколько папок.

type ArchiveDocument = {
  slug: string
  project: string
  relative_path: string
  doc_type: string
  page_count: number
  status: string
  error: string | null
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
  duplicates: string[]
  skipped_root: string[]
  errors: string[]
}

// Поллинг статусов, пока что-то обрабатывается (pipeline идёт в фоне).
const POLL_INTERVAL_MS = 3000

function statusLabel(doc: ArchiveDocument): { text: string; className: string } {
  switch (doc.status) {
    case 'pending':
      return { text: 'čeká', className: 'text-muted-foreground' }
    case 'processing':
      return {
        text: doc.progress ?? 'zpracovává se…',
        className: 'text-amber-600 dark:text-amber-400',
      }
    case 'error':
      return { text: 'chyba', className: 'text-destructive' }
    default:
      return { text: '', className: '' }
  }
}

function DocumentRow({ doc }: { doc: ArchiveDocument }) {
  // Путь внутри проекта (без имени проекта) — короче и читабельнее.
  const insideProject = doc.relative_path.split('/').slice(1).join('/')
  const label = statusLabel(doc)
  const icon = doc.doc_type === 'sheet' ? '📐' : '📄'
  return (
    <div>
      <div className="flex items-center gap-2 text-sm">
        {doc.status === 'ready' ? (
          <a
            href={`/api/library/pdf/${doc.slug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground hover:underline flex-1"
            title="Otevřít PDF v prohlížeči"
          >
            {icon} {insideProject}
          </a>
        ) : (
          <span className="flex-1 text-muted-foreground">
            {icon} {insideProject}
          </span>
        )}
        <span className="text-xs text-muted-foreground">{doc.page_count} s.</span>
        {label.text && (
          <span className={`text-xs ${label.className}`}>{label.text}</span>
        )}
      </div>
      {doc.status === 'error' && doc.error && (
        <div className="text-xs text-destructive pl-6">{doc.error}</div>
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

  async function loadAll() {
    setError(null)
    try {
      const pathRes = await fetch('/api/settings/projects-libraries')
      const pathData: { paths: string[] } = await pathRes.json()
      setPaths(pathData.paths)

      const res = await fetch('/api/projects')
      if (res.ok) {
        setArchive(await res.json())
      } else {
        const data = await res.json().catch(() => ({}))
        setError(data.detail ?? `Chyba ${res.status}`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nepodařilo se načíst archiv')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  // Пока есть документы в обработке/очереди — раз в 3 с перечитываем статусы.
  const hasActive = (archive?.projects ?? []).some((p) =>
    p.documents.some((d) => d.status === 'pending' || d.status === 'processing'),
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
  }, [hasActive])

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
          Složky archivu projektů
        </h2>
        <p className="text-xs text-muted-foreground">
          Složky s dokončenými projekty: každý projekt = podsložka první úrovně
          (TZ, statické výpočty, výkresy). Můžete připojit více složek. Soubory
          se pouze čtou. Zpracování výkresů využívá vision model (viz „Knihovna“).
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

      {paths.length > 0 && (
        <div className="flex items-center gap-3">
          <Button onClick={scan} disabled={scanning} variant="outline">
            {scanning ? 'Skenuji…' : 'Skenovat'}
          </Button>
          {pendingCount > 0 && (
            <Button onClick={startIndexing} disabled={indexing}>
              {indexing ? 'Spouštím…' : `Indexovat (${pendingCount})`}
            </Button>
          )}
          {summary && (
            <p className="text-xs text-muted-foreground">
              Nalezeno {summary.found}, nových {summary.new}
              {summary.missing > 0 && `, odstraněno ${summary.missing}`}
              {summary.duplicates.length > 0 &&
                `, duplicit ${summary.duplicates.length}`}
              {summary.errors.length > 0 && `, chyb ${summary.errors.length}`}
            </p>
          )}
        </div>
      )}

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Moje projekty
        </h2>
        {archive && archive.projects.length > 0 ? (
          <div className="flex flex-col gap-2">
            {archive.projects.map((project) => {
              const active = project.documents.filter(
                (d) => d.status === 'pending' || d.status === 'processing',
              ).length
              const errors = project.documents.filter(
                (d) => d.status === 'error',
              ).length
              return (
                // Проекты свёрнуты по умолчанию — в архиве их может быть много.
                <details
                  key={project.name}
                  className="rounded-md border bg-card p-3"
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
                      <DocumentRow key={doc.slug} doc={doc} />
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
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

// Архив проектов юзера: путь к папке, «Skenovat», документы по проектам
// со статусами обработки. Пока только личный пул; общие проекты — потом
// (второй колонкой на этой же странице).

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
  path: string | null
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
        className: 'text-amber-600',
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
  const [path, setPath] = useState<string | null>(null)
  const [pathInput, setPathInput] = useState('')
  const [archive, setArchive] = useState<ArchiveResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [summary, setSummary] = useState<ScanSummary | null>(null)

  async function loadAll() {
    setError(null)
    try {
      const pathRes = await fetch('/api/settings/projects')
      const pathData: { path: string | null } = await pathRes.json()
      setPath(pathData.path)
      if (pathData.path) setPathInput(pathData.path)

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
  useEffect(() => {
    if (!hasActive) return
    const id = setInterval(loadAll, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [hasActive])

  async function savePath() {
    const value = pathInput.trim()
    if (!value) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/projects', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: value }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(data.detail ?? `Chyba ${res.status}`)
        return
      }
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

  if (loading) {
    return <p className="text-sm text-muted-foreground">Načítání…</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Složka archivu projektů
        </h2>
        <p className="text-xs text-muted-foreground">
          Složka s dokončenými projekty: každý projekt = podsložka první úrovně
          (TZ, statické výpočty, výkresy). Soubory se pouze čtou, nic se
          nemění. Zpracování výkresů využívá vision model (viz „Knihovna“).
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            placeholder="/Users/.../Projekty"
            className="flex-1 border rounded px-2 py-1 text-sm font-mono"
          />
          <Button
            onClick={savePath}
            disabled={saving || !pathInput.trim() || pathInput === path}
          >
            {saving ? 'Ukládám…' : 'Uložit'}
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {path && (
        <div className="flex items-center gap-3">
          <Button onClick={scan} disabled={scanning}>
            {scanning ? 'Skenuji…' : 'Skenovat'}
          </Button>
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
          path && (
            <p className="text-sm text-muted-foreground">
              Zatím žádné dokumenty — klikněte na „Skenovat“.
            </p>
          )
        )}
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Projekty obecné
        </h2>
        <p className="text-sm text-muted-foreground rounded-md border bg-card p-3">
          Sdílené projekty od vlastníka (jen pro čtení) — připravuje se.
        </p>
      </div>
    </div>
  )
}

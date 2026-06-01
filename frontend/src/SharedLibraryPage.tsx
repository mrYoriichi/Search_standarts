import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

// Общая база норм от владельца: read-only. Своё дерево + кликабельные PDF, но
// без «Сканировать»/pin/удаления/переиндексации — индексы приходят готовыми.

type LibraryFile = {
  name: string
  path: string
  slug: string
  status: 'ready' | null
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


async function openShared(path: string): Promise<void> {
  try {
    const res = await fetch('/api/library/shared/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      alert(data.detail ?? 'Nepodařilo se otevřít soubor')
    }
  } catch {
    alert('Nepodařilo se otevřít soubor')
  }
}


async function togglePinShared(slug: string): Promise<void> {
  try {
    const res = await fetch(`/api/library/shared/${slug}/pin`, { method: 'POST' })
    if (!res.ok) alert(`Nepodařilo se přepnout připnutí: ${res.status}`)
  } catch {
    alert('Chyba sítě')
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


function SharedFileRow({
  file,
  onChange,
}: {
  file: LibraryFile
  onChange: () => void
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <button
        onClick={async () => {
          await togglePinShared(file.slug)
          onChange()
        }}
        title={file.pinned ? 'Odepnout' : 'Připnout'}
        className={
          file.pinned
            ? 'text-base leading-none'
            : 'text-base leading-none opacity-25 hover:opacity-100'
        }
      >
        📌
      </button>
      <button
        onClick={() => openShared(file.path)}
        className="text-foreground hover:underline text-left flex-1"
        title="Otevřít v systémovém prohlížeči"
      >
        📄 {file.name}
      </button>
      {file.status !== 'ready' && (
        <span className="text-xs text-muted-foreground">neindexováno</span>
      )}
    </div>
  )
}


function ReadOnlyFolder({
  folder,
  onChange,
}: {
  folder: LibraryFolder
  onChange: () => void
}) {
  const isEmpty = folder.folders.length === 0 && folder.files.length === 0
  return (
    <div className="flex flex-col gap-1">
      {isEmpty && <p className="text-xs text-muted-foreground italic">prázdné</p>}
      {folder.folders.map((f) => (
        <details key={f.path} className="text-sm">
          <summary className="cursor-pointer font-medium">📁 {f.name}</summary>
          <div className="ml-5 mt-1">
            <ReadOnlyFolder folder={f} onChange={onChange} />
          </div>
        </details>
      ))}
      {folder.files.map((file) => (
        <SharedFileRow key={file.path} file={file} onChange={onChange} />
      ))}
    </div>
  )
}


export default function SharedLibraryPage() {
  const [path, setPath] = useState<string | null>(null)
  const [pathInput, setPathInput] = useState('')
  const [library, setLibrary] = useState<LibraryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function loadAll() {
    setLoading(true)
    setError(null)
    try {
      const pathRes = await fetch('/api/settings/shared-library')
      const pathData: { path: string | null } = await pathRes.json()
      setPath(pathData.path)
      if (pathData.path) {
        setPathInput(pathData.path)
        const libRes = await fetch('/api/library/shared')
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
      setError(e instanceof Error ? e.message : 'Nepodařilo se načíst knihovnu')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  async function savePath() {
    const value = pathInput.trim()
    if (!value) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/shared-library', {
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

  if (loading) {
    return <p className="text-sm text-muted-foreground">Načítání…</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Složka obecné knihovny
        </h2>
        <p className="text-xs text-muted-foreground">
          Sdílená databáze norem s hotovými indexy. Stáhněte ji a rozbalte;
          složka musí obsahovat podsložky „pdfs“ a „raw_data“. Jen pro čtení —
          neskenuje se.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            placeholder="/Users/.../SharedLibrary"
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

      {library && (() => {
        const pinned = collectPinned(library.tree)
        return (
          <>
            {pinned.length > 0 && (
              <div className="rounded-md border bg-card p-4">
                <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                  📌 Připnuté
                </h2>
                <div className="flex flex-col gap-1">
                  {pinned.map((file) => (
                    <SharedFileRow
                      key={file.path}
                      file={file}
                      onChange={loadAll}
                    />
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-md border bg-card p-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                Obsah
              </h2>
              <ReadOnlyFolder folder={library.tree} onChange={loadAll} />
            </div>
          </>
        )
      })()}
    </div>
  )
}

import { useEffect, useState } from 'react'
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


function FileRow({ file, onChange }: { file: LibraryFile; onChange: () => void }) {
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
      <StatusLabel status={file.status} />
    </div>
  )
}


function StatusLabel({ status }: { status: LibraryFile['status'] }) {
  if (status === null) {
    return <span className="text-xs text-muted-foreground">не индексирован</span>
  }
  if (status === 'processing') {
    return <span className="text-xs text-blue-600">обрабатывается…</span>
  }
  if (status === 'ready') {
    return <span className="text-xs text-green-600">готов</span>
  }
  return <span className="text-xs text-red-600">ошибка</span>
}


function FolderView({ folder, onChange }: { folder: LibraryFolder; onChange: () => void }) {
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
            <FolderView folder={f} onChange={onChange} />
          </div>
        </details>
      ))}
      {folder.files.map((file) => (
        <FileRow key={file.path} file={file} onChange={onChange} />
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

  useEffect(() => {
    loadAll()
  }, [])

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
                    <FileRow key={file.path} file={file} onChange={loadAll} />
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-md border bg-card p-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                Содержимое
              </h2>
              <FolderView folder={library.tree} onChange={loadAll} />
            </div>
          </>
        )
      })()}
    </div>
  )
}


export default LibraryPage

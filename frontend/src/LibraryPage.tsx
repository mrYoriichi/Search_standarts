import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'


type LibraryFile = {
  name: string
  path: string
  slug: string
  status: 'processing' | 'ready' | 'failed' | null
}

type LibraryFolder = {
  name: string
  path: string
  folders: LibraryFolder[]
  files: LibraryFile[]
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


function FolderView({ folder }: { folder: LibraryFolder }) {
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
            <FolderView folder={f} />
          </div>
        </details>
      ))}
      {folder.files.map((file) => (
        <div key={file.path} className="flex items-center gap-2 text-sm">
          <button
            onClick={() => openFile(file.path)}
            className="text-foreground hover:underline text-left"
            title="Открыть в системном просмотрщике"
          >
            📄 {file.name}
          </button>
          <StatusLabel status={file.status} />
        </div>
      ))}
    </div>
  )
}


function LibraryPage() {
  const [path, setPath] = useState<string | null>(null)
  const [pathInput, setPathInput] = useState('')
  const [tree, setTree] = useState<LibraryFolder | null>(null)
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
          setTree(await libRes.json())
        } else {
          const errData = await libRes.json().catch(() => ({}))
          setError(errData.detail ?? `Ошибка ${libRes.status}`)
          setTree(null)
        }
      } else {
        setTree(null)
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

      {tree && (
        <div className="rounded-md border bg-card p-4">
          <h2 className="text-sm font-semibold text-muted-foreground mb-2">
            Содержимое
          </h2>
          <FolderView folder={tree} />
        </div>
      )}
    </div>
  )
}


export default LibraryPage

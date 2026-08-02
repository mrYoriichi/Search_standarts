import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import ArchivePage from './ArchivePage'
import LibraryPage from './LibraryPage'
import { Logo } from './Logo'
import LoginPage from './LoginPage'
import SettingsPage from './SettingsPage'
import { LangSwitcher, t, useI18n } from './i18n'

type AuthState =
  | { phase: 'loading' }
  | { phase: 'anonymous' }
  | { phase: 'authenticated'; username: string }
  | { phase: 'blocked'; username: string; reason: string; downloadUrl?: string }

// Re-read the local /api/auth/status every minute — the backend's background
// verify may have moved us to blocked.
const STATUS_POLL_INTERVAL_MS = 60 * 1000

type Source = {
  document: string
  slug: string
  section: string
  pages: number[]
}

type UsedChunk = {
  chunk_id: string
  document: string
  section: string
  pages: number[]
  text: string
}

type AskResponse = {
  answer: string
  sources: Source[]
  related_sources: Source[]
  used_chunks: UsedChunk[]
  query_log_id: number
  search_query: string
  answer_model: string
  answer_ms: number
}

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

type LibraryResponse = {
  tree: LibraryFolder
  orphans: unknown[]
}

type ArchiveDocument = {
  slug: string
  project: string
  relative_path: string
  status: string
}

type ArchiveApiResponse = {
  paths: string[]
  projects: { name: string; documents: ArchiveDocument[] }[]
}

// Turns the flat /api/projects response into a LibraryFolder-shaped tree to
// reuse FilterTree unchanged. Nesting is built from relative_path
// (project / section subfolders / file).
function buildArchiveTree(archive: ArchiveApiResponse): LibraryFolder {
  const root: LibraryFolder = {
    name: t('nav.archive'),
    path: '',
    folders: [],
    files: [],
  }
  function ensureFolder(
    parent: LibraryFolder,
    name: string,
    path: string,
  ): LibraryFolder {
    let folder = parent.folders.find((f) => f.name === name)
    if (!folder) {
      folder = { name, path, folders: [], files: [] }
      parent.folders.push(folder)
    }
    return folder
  }
  for (const project of archive.projects) {
    for (const doc of project.documents) {
      // Split on both separators: old Windows records contain `\`.
      const parts = doc.relative_path.split(/[\\/]/)
      let node = root
      let accPath = ''
      for (const part of parts.slice(0, -1)) {
        accPath = accPath ? `${accPath}/${part}` : part
        node = ensureFolder(node, part, accPath)
      }
      node.files.push({
        name: parts[parts.length - 1],
        path: doc.relative_path,
        slug: doc.slug,
        status:
          doc.status === 'ready'
            ? 'ready'
            : doc.status === 'processing'
              ? 'processing'
              : null,
        pinned: false,
      })
    }
  }
  return root
}

type View = 'search' | 'library' | 'archive' | 'settings'


// Collects slugs of all indexed (ready) PDFs in a folder, subfolders included.
// Used by the "select the whole folder" checkbox.
function collectReadySlugs(folder: LibraryFolder): string[] {
  const result: string[] = []
  for (const f of folder.files) {
    if (f.status === 'ready') result.push(f.slug)
  }
  for (const sub of folder.folders) {
    result.push(...collectReadySlugs(sub))
  }
  return result
}

function FilterTree({
  folder,
  selectedSlugs,
  searchAll,
  onToggleFile,
  onToggleFolder,
}: {
  folder: LibraryFolder
  selectedSlugs: Set<string>
  // With searchAll=true the tree checkboxes look checked and are disabled —
  // the user first unchecks "whole database", then fine-tunes the selection.
  searchAll: boolean
  onToggleFile: (slug: string) => void
  onToggleFolder: (folder: LibraryFolder) => void
}) {
  const readySlugs = collectReadySlugs(folder)
  // Hide folders without indexed files — otherwise lots of emptiness.
  if (readySlugs.length === 0) return null
  const allSelected = searchAll || readySlugs.every((s) => selectedSlugs.has(s))
  const readyFiles = folder.files.filter((f) => f.status === 'ready')

  return (
    <details className="text-sm">
      <summary className="cursor-pointer flex items-center gap-2">
        {/* A checkbox on every folder, root included — select/clear the pool. */}
        <input
          type="checkbox"
          checked={allSelected}
          disabled={searchAll}
          onChange={() => onToggleFolder(folder)}
          onClick={(e) => e.stopPropagation()}
          className="h-4 w-4"
        />
        <span className="font-medium">📁 {folder.name}</span>
      </summary>
      <div className="ml-5 mt-1 flex flex-col gap-1">
        {folder.folders.map((sub) => (
          <FilterTree
            key={sub.path}
            folder={sub}
            selectedSlugs={selectedSlugs}
            searchAll={searchAll}
            onToggleFile={onToggleFile}
            onToggleFolder={onToggleFolder}
          />
        ))}
        {readyFiles.map((file) => (
          <FileCheckbox
            key={file.path}
            file={file}
            selected={searchAll || selectedSlugs.has(file.slug)}
            disabled={searchAll}
            onToggle={onToggleFile}
          />
        ))}
      </div>
    </details>
  )
}


function FileCheckbox({
  file,
  selected,
  disabled,
  onToggle,
}: {
  file: LibraryFile
  selected: boolean
  disabled: boolean
  onToggle: (slug: string) => void
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-sm">
      <input
        type="checkbox"
        checked={selected}
        disabled={disabled}
        onChange={() => onToggle(file.slug)}
        className="h-4 w-4"
      />
      <span>📄 {file.name}</span>
    </label>
  )
}


function SourceLink({ src }: { src: Source }) {
  // Each page gets its own link: a chunk may span a page range, and the user
  // jumps straight to the right one instead of paging from the first.
  const base = `/api/library/pdf/${src.slug}`
  return (
    <span>
      <a
        href={`${base}${src.pages[0] ? `#page=${src.pages[0]}` : ''}`}
        target="_blank"
        rel="noopener noreferrer"
        className="hover:underline"
        title={t('source.openPdf')}
      >
        <span className="font-medium">{src.document}</span>
        {' / '}
        <span>{src.section}</span>
      </a>
      {t('source.pagesPrefix')}
      {src.pages.map((page, i) => (
        <span key={page}>
          {i > 0 && ', '}
          <a
            href={`${base}#page=${page}`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:no-underline"
            title={t('source.openPdfPage', { page })}
          >
            {page}
          </a>
        </span>
      ))}
    </span>
  )
}


// The "Nahlásit" button under the answer: the user flags a wrong/missing
// answer. The question/answer text (+ an optional note) goes to the owner.
function ReportAnswer({
  question,
  result,
}: {
  question: string
  result: AskResponse
}) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)

  async function submit() {
    setSending(true)
    try {
      const res = await fetch('/api/queries/flag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          answer: result.answer,
          answer_model: result.answer_model,
          note: note.trim() || null,
          used_chunks: result.used_chunks,
        }),
      })
      if (res.ok) setSent(true)
      else alert(t('common.errorStatus', { status: res.status }))
    } catch {
      alert(t('report.failed'))
    } finally {
      setSending(false)
    }
  }

  if (sent) {
    return (
      <p className="text-xs text-green-600 dark:text-green-400">
        {t('report.thanks')}
      </p>
    )
  }
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-muted-foreground underline self-start"
      >
        {t('report.link')}
      </button>
    )
  }
  return (
    <div className="flex flex-col gap-2 rounded-md border bg-card p-3">
      <p className="text-xs text-muted-foreground">{t('report.prompt')}</p>
      <Textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        disabled={sending}
      />
      <div className="flex gap-2">
        <Button onClick={submit} disabled={sending} size="sm">
          {sending ? t('report.sending') : t('report.send')}
        </Button>
        <Button
          onClick={() => setOpen(false)}
          disabled={sending}
          size="sm"
          variant="outline"
        >
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  )
}


// Theme on first run: the user's saved choice, otherwise the system setting.
function getInitialTheme(): 'light' | 'dark' {
  const saved = localStorage.getItem('theme')
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

// Label keys of the search modes — by mode value.
const MODE_KEYS = {
  hybrid: 'search.modeHybrid',
  vector: 'search.modeVector',
  keyword: 'search.modeKeyword',
} as const

function App() {
  // Subscribe to language changes: a switch re-renders App and its whole tree.
  useI18n()
  const [auth, setAuth] = useState<AuthState>({ phase: 'loading' })
  const [view, setView] = useState<View>('search')
  const [theme, setTheme] = useState<'light' | 'dark'>(getInitialTheme)

  // The dark palette is enabled by the .dark class on <html> (see index.css).
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('theme', theme)
  }, [theme])

  const [question, setQuestion] = useState('')
  // The question the current result was actually produced for — pinned at
  // answer time so "Nahlásit" sends exactly it, even if the user is already
  // editing the input.
  const [askedQuestion, setAskedQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AskResponse | null>(null)

  const [library, setLibrary] = useState<LibraryResponse | null>(null)
  // Project archive (tree already LibraryFolder-shaped). null — unset/empty.
  const [archiveTree, setArchiveTree] = useState<LibraryFolder | null>(null)
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(new Set())
  // Search everywhere by default — the most common case. Unchecking opens the tree.
  const [searchAll, setSearchAll] = useState(true)
  // Search mode: hybrid (7 vector + 7 BM25), vector (top 20 meaning), keyword (top 10 words).
  const [searchMode, setSearchMode] = useState<'hybrid' | 'vector' | 'keyword'>('hybrid')
  // Answer generation model. The answer language is a profile setting
  // (Nastavení), the backend reads it itself.
  const [answerModel, setAnswerModel] = useState<'gpt-5.4-mini' | 'gpt-5.5'>('gpt-5.4-mini')
  // Whether to expand the query via LLM before search (diacritics/synonyms). Default yes.
  const [expandQuery, setExpandQuery] = useState(true)
  // Strong search: page snapshots of the top sources go as images to the
  // answering LLM (heavy drawing/table questions). Pricier and slower — off
  // by default.
  const [strongSearch, setStrongSearch] = useState(false)

  // Check on start + once a minute: is there an active local session and has
  // it moved to blocked (revoked / grace period expired). If blocked — show
  // the fullscreen overlay right away.
  useEffect(() => {
    let cancelled = false

    function applyStatus(data: {
      logged_in: boolean
      username?: string
      effective_status?: 'ok' | 'blocked'
      status?: 'ok' | 'revoked' | 'offline' | 'update_required'
      download_url?: string | null
    } | null) {
      if (cancelled) return
      if (!data?.logged_in) {
        setAuth({ phase: 'anonymous' })
        return
      }
      if (data.effective_status === 'blocked') {
        let reason: string
        if (data.status === 'revoked') {
          reason = t('blocked.revoked')
        } else if (data.status === 'update_required') {
          reason = t('blocked.updateRequired')
        } else {
          reason = t('blocked.offline')
        }
        setAuth({
          phase: 'blocked',
          username: data.username ?? '',
          reason,
          downloadUrl: data.download_url ?? undefined,
        })
        return
      }
      setAuth({
        phase: 'authenticated',
        username: data.username ?? '',
      })
    }

    function check() {
      fetch('/api/auth/status')
        .then((res) => (res.ok ? res.json() : null))
        .then(applyStatus)
        .catch(() => {
          // /api/auth/status is local; an error here means "backend is down".
          // Don't drop the session: wait for the next tick.
        })
    }

    check()
    const id = setInterval(check, STATUS_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  // Fetch the library tree only after login — the backend would answer 401
  // in the protected build, and the "where to search" form is useless anyway.
  // The view dependency: returning to "Vyhledávání" re-reads the trees — a
  // background scan may have processed documents, the filter must not go stale.
  useEffect(() => {
    if (auth.phase !== 'authenticated') return
    if (view !== 'search') return
    const libraryPromise: Promise<LibraryResponse | null> = fetch('/api/library')
      .then((res) => (res.ok ? res.json() : null))
      .catch(() => null)
    // The project archive is the second pool for the filter.
    const archivePromise: Promise<ArchiveApiResponse | null> = fetch('/api/projects')
      .then((res) => (res.ok ? res.json() : null))
      .catch(() => null)
    Promise.all([libraryPromise, archivePromise]).then(([lib, archive]) => {
      const archiveTree = archive ? buildArchiveTree(archive) : null
      setLibrary(lib)
      setArchiveTree(archiveTree)
      // Prune the stale selection: while we were on another tab a document
      // may have been deleted/renamed. Otherwise nonexistent slugs go into
      // document_ids — the backend answers "empty selection" instead of a result.
      const valid = new Set<string>()
      if (lib) collectReadySlugs(lib.tree).forEach((s) => valid.add(s))
      if (archiveTree) collectReadySlugs(archiveTree).forEach((s) => valid.add(s))
      setSelectedSlugs((prev) => {
        const next = new Set([...prev].filter((s) => valid.has(s)))
        return next.size === prev.size ? prev : next
      })
    })
  }, [auth.phase, view])

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' })
    setAuth({ phase: 'anonymous' })
    setLibrary(null)
    setArchiveTree(null)
    setResult(null)
  }

  function toggleSlug(slug: string) {
    setSelectedSlugs((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  function toggleFolder(folder: LibraryFolder) {
    const slugs = collectReadySlugs(folder)
    if (slugs.length === 0) return
    setSelectedSlugs((prev) => {
      const next = new Set(prev)
      const allSelected = slugs.every((s) => next.has(s))
      if (allSelected) {
        slugs.forEach((s) => next.delete(s))
      } else {
        slugs.forEach((s) => next.add(s))
      }
      return next
    })
  }

  async function handleAsk() {
    // "Whole database" unchecked but nothing selected — this used to silently
    // search everywhere. Now an explicit scope is required, otherwise it is
    // unclear where the search ran.
    if (!searchAll && selectedSlugs.size === 0) {
      setError(t('search.selectWhere'))
      return
    }

    setLoading(true)
    setError(null)
    setResult(null)
    try {
      // "Whole database" -> no document_ids sent, the backend searches everywhere.
      // Otherwise send the selected slugs (size > 0 guaranteed by the check above).
      const body: {
        question: string
        document_ids?: string[]
        mode: string
        answer_model: string
        expand: boolean
        strong: boolean
      } = {
        question,
        mode: searchMode,
        answer_model: answerModel,
        expand: expandQuery,
        strong: strongSearch,
      }
      if (!searchAll) {
        body.document_ids = Array.from(selectedSlugs)
      }

      const res = await fetch('/api/queries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        // The backend sends a clear reason in detail (empty library, stale
        // selection…) — show it, not the bare status code.
        const errData = await res.json().catch(() => null)
        throw new Error(
          errData?.detail ?? t('common.serverReturned', { status: res.status }),
        )
      }
      const data: AskResponse = await res.json()
      setResult(data)
      setAskedQuestion(question)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('common.unknownError'))
    } finally {
      setLoading(false)
    }
  }

  const canSubmit = question.trim().length > 0 && !loading

  if (auth.phase === 'loading') {
    // A short flicker; a full spinner is overkill.
    return <div className="min-h-screen bg-background" />
  }
  if (auth.phase === 'anonymous') {
    return (
      <LoginPage
        onLoggedIn={(username) => setAuth({ phase: 'authenticated', username })}
      />
    )
  }
  if (auth.phase === 'blocked') {
    return (
      <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
        <div className="w-full max-w-md flex flex-col gap-4 rounded-md border bg-card p-6">
          <h1 className="text-2xl font-bold">{t('blocked.title')}</h1>
          <p className="text-sm text-muted-foreground">{auth.reason}</p>
          <p className="text-sm text-muted-foreground">
            {t('blocked.user')}{' '}
            <span className="text-foreground">{auth.username}</span>
          </p>
          {auth.downloadUrl && (
            <a
              href={auth.downloadUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-foreground underline self-start"
            >
              {t('blocked.download')}
            </a>
          )}
          <Button onClick={handleLogout} className="self-start" variant="outline">
            {t('common.logout')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-3xl mx-auto px-6 py-10 flex flex-col gap-6">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-3xl">
            <Logo />
          </h1>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <LangSwitcher />
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              title={theme === 'dark' ? t('theme.toLight') : t('theme.toDark')}
              className="text-base leading-none"
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <button
              onClick={() => setView('settings')}
              className={
                'hover:text-foreground hover:underline ' +
                (view === 'settings' ? 'text-foreground font-medium' : '')
              }
              title={t('header.settingsTitle')}
            >
              👤 {auth.username}
            </button>
            <button
              onClick={handleLogout}
              className="hover:text-foreground hover:underline"
            >
              {t('common.logout')}
            </button>
          </div>
        </div>

        <nav className="flex gap-1 border-b">
          <button
            onClick={() => setView('search')}
            className={
              'px-4 py-2 text-sm border-b-2 -mb-px ' +
              (view === 'search'
                ? 'border-foreground font-medium'
                : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            {t('nav.search')}
          </button>
          <button
            onClick={() => setView('library')}
            className={
              'px-4 py-2 text-sm border-b-2 -mb-px ' +
              (view === 'library'
                ? 'border-foreground font-medium'
                : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            {t('nav.library')}
          </button>
          <button
            onClick={() => setView('archive')}
            className={
              'px-4 py-2 text-sm border-b-2 -mb-px ' +
              (view === 'archive'
                ? 'border-foreground font-medium'
                : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            {t('nav.archive')}
          </button>
        </nav>

        {view === 'library' && <LibraryPage />}

        {view === 'archive' && <ArchivePage />}

        {view === 'settings' && <SettingsPage />}

        {view === 'search' && (
          <>
        <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-muted-foreground">
            {t('search.where')}
          </h2>
          {(() => {
            const userReady = library ? collectReadySlugs(library.tree).length : 0
            const archiveReady = archiveTree
              ? collectReadySlugs(archiveTree).length
              : 0
            if (userReady + archiveReady === 0) {
              return (
                <p className="text-sm text-muted-foreground">{t('search.noDocs')}</p>
              )
            }
            return (
              <>
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    checked={searchAll}
                    onChange={() => setSearchAll((v) => !v)}
                    className="h-4 w-4"
                  />
                  <span>{t('search.wholeDb')}</span>
                </label>
                <div className="mt-1 flex flex-col sm:flex-row gap-8">
                  {userReady > 0 && library && (
                    <div className="flex-1">
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t('search.ownLibrary')}
                      </p>
                      <FilterTree
                        folder={library.tree}
                        selectedSlugs={selectedSlugs}
                        searchAll={searchAll}
                        onToggleFile={toggleSlug}
                        onToggleFolder={toggleFolder}
                      />
                    </div>
                  )}
                  {archiveReady > 0 && archiveTree && (
                    <div className="flex-1">
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t('nav.archive')}
                      </p>
                      <FilterTree
                        folder={archiveTree}
                        selectedSlugs={selectedSlugs}
                        searchAll={searchAll}
                        onToggleFile={toggleSlug}
                        onToggleFolder={toggleFolder}
                      />
                    </div>
                  )}
                </div>
              </>
            )
          })()}
        </div>

        <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-muted-foreground">
            {t('search.mode')}
          </h2>
          <div className="flex gap-2">
            {(['hybrid', 'vector', 'keyword'] as const).map((value) => (
              <button
                key={value}
                onClick={() => setSearchMode(value)}
                className={
                  'px-3 py-1.5 text-sm rounded-md border ' +
                  (searchMode === value
                    ? 'bg-foreground text-background font-medium'
                    : 'text-muted-foreground hover:text-foreground')
                }
              >
                {t(MODE_KEYS[value])}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-muted-foreground">
            {t('search.answerModel')}
          </h2>
          <div className="flex gap-2">
            {(['gpt-5.4-mini', 'gpt-5.5'] as const).map((value) => (
              <button
                key={value}
                onClick={() => setAnswerModel(value)}
                className={
                  'px-3 py-1.5 text-sm rounded-md border ' +
                  (answerModel === value
                    ? 'bg-foreground text-background font-medium'
                    : 'text-muted-foreground hover:text-foreground')
                }
              >
                {value}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center gap-2 px-1 text-sm text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={expandQuery}
            onChange={(e) => setExpandQuery(e.target.checked)}
          />
          {t('search.expand')}
        </label>

        <label className="flex items-center gap-2 px-1 text-sm text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={strongSearch}
            onChange={(e) => setStrongSearch(e.target.checked)}
          />
          {t('search.strong')}
        </label>

        <Textarea
          placeholder={t('search.placeholder')}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={4}
          disabled={loading}
        />

        <Button onClick={handleAsk} disabled={!canSubmit} className="self-start">
          {loading ? t('search.asking') : t('search.ask')}
        </Button>

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
            {error}
          </div>
        )}

        {result && (
          <div className="flex flex-col gap-4">
            {result.search_query && result.search_query !== askedQuestion && (
              <p className="text-xs text-muted-foreground">
                {t('search.searchedAs')}{' '}
                <span className="italic">{result.search_query}</span>
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {t('search.modelLine', {
                model: result.answer_model,
                seconds: (result.answer_ms / 1000).toFixed(1),
              })}
            </p>
            <div className="rounded-md border bg-card p-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                {t('search.answer')}
              </h2>
              <p className="whitespace-pre-wrap">{result.answer}</p>
            </div>

            <div className="rounded-md border bg-card p-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                {t('search.sources')}
              </h2>
              {result.sources.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t('search.noAnswer')}
                </p>
              ) : (
                <ul className="flex flex-col gap-2 text-sm">
                  {result.sources.map((src, i) => (
                    <li key={i}><SourceLink src={src} /></li>
                  ))}
                </ul>
              )}
            </div>

            {result.related_sources.length > 0 && (
              <div className="rounded-md border bg-card p-4">
                <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                  {t('search.related')}
                </h2>
                <ul className="flex flex-col gap-2 text-sm">
                  {result.related_sources.map((src, i) => (
                    <li key={i}><SourceLink src={src} /></li>
                  ))}
                </ul>
              </div>
            )}

            <ReportAnswer
              key={result.query_log_id}
              question={askedQuestion}
              result={result}
            />
          </div>
        )}
          </>
        )}
      </div>
    </div>
  )
}

export default App

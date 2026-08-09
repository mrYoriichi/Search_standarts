// The search view: pick where to search, ask, read the answer with sources.
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { FilterTree } from './components/FilterTree'
import { ReportAnswer } from './components/ReportAnswer'
import { SourceLink } from './components/SourceLink'
import { t } from './i18n'
import { buildArchiveTree, collectReadySlugs } from './lib/tree'
import type {
  ArchiveApiResponse,
  AskResponse,
  LibraryFolder,
  LibraryResponse,
} from './types'

// Label keys of the search modes — by mode value.
const MODE_KEYS = {
  hybrid: 'search.modeHybrid',
  vector: 'search.modeVector',
  keyword: 'search.modeKeyword',
} as const

const cardClass = 'rounded-md border bg-card p-4 flex flex-col gap-2'

export default function SearchPage({ active }: { active: boolean }) {
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
  const [answerModel, setAnswerModel] = useState<'gpt-5.6-luna' | 'gpt-5.6-sol'>('gpt-5.6-luna')
  // Whether to expand the query via LLM before search (diacritics/synonyms). Default yes.
  const [expandQuery, setExpandQuery] = useState(true)
  // Strong search: page snapshots of the top sources go as images to the
  // answering LLM (heavy drawing/table questions). Pricier and slower — off
  // by default.
  const [strongSearch, setStrongSearch] = useState(false)

  // Re-read the trees whenever this page becomes visible: a background scan
  // may have processed documents, and the filter must not go stale.
  useEffect(() => {
    if (!active) return
    const libraryPromise: Promise<LibraryResponse | null> = fetch('/api/library')
      .then((res) => (res.ok ? res.json() : null))
      .catch(() => null)
    // The project archive is the second pool for the filter.
    const archivePromise: Promise<ArchiveApiResponse | null> = fetch('/api/projects')
      .then((res) => (res.ok ? res.json() : null))
      .catch(() => null)
    Promise.all([libraryPromise, archivePromise]).then(([lib, archive]) => {
      const tree = archive ? buildArchiveTree(archive) : null
      setLibrary(lib)
      setArchiveTree(tree)
      // Prune the stale selection: while we were on another tab a document
      // may have been deleted/renamed. Otherwise nonexistent slugs go into
      // document_ids — the backend answers "empty selection" instead of a result.
      const valid = new Set<string>()
      if (lib) collectReadySlugs(lib.tree).forEach((s) => valid.add(s))
      if (tree) collectReadySlugs(tree).forEach((s) => valid.add(s))
      setSelectedSlugs((prev) => {
        const next = new Set([...prev].filter((s) => valid.has(s)))
        return next.size === prev.size ? prev : next
      })
    })
  }, [active])

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
      if (allSelected) slugs.forEach((s) => next.delete(s))
      else slugs.forEach((s) => next.add(s))
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
      if (!searchAll) body.document_ids = Array.from(selectedSlugs)

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
  const userReady = library ? collectReadySlugs(library.tree).length : 0
  const archiveReady = archiveTree ? collectReadySlugs(archiveTree).length : 0

  return (
    <div
      className="flex flex-col gap-6"
      // Kept mounted while another tab is open: switching tabs must not throw
      // away an answer the user paid for.
      style={{ display: active ? undefined : 'none' }}
    >
      <div className={cardClass}>
        <h2 className="text-sm font-semibold text-muted-foreground">
          {t('search.where')}
        </h2>
        {userReady + archiveReady === 0 ? (
          <p className="text-sm text-muted-foreground">{t('search.noDocs')}</p>
        ) : (
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
        )}
      </div>

      <ChoiceCard
        title={t('search.mode')}
        options={['hybrid', 'vector', 'keyword'] as const}
        selected={searchMode}
        onSelect={setSearchMode}
        label={(value) => t(MODE_KEYS[value])}
      />

      <ChoiceCard
        title={t('search.answerModel')}
        options={['gpt-5.6-luna', 'gpt-5.6-sol'] as const}
        selected={answerModel}
        onSelect={setAnswerModel}
        label={(value) => value}
      />

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
              <p className="text-sm text-muted-foreground">{t('search.noAnswer')}</p>
            ) : (
              <SourceList sources={result.sources} />
            )}
          </div>

          {result.related_sources.length > 0 && (
            <div className="rounded-md border bg-card p-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                {t('search.related')}
              </h2>
              <SourceList sources={result.related_sources} />
            </div>
          )}

          <ReportAnswer
            key={result.query_log_id}
            question={askedQuestion}
            result={result}
          />
        </div>
      )}
    </div>
  )
}

function SourceList({ sources }: { sources: AskResponse['sources'] }) {
  return (
    <ul className="flex flex-col gap-2 text-sm">
      {sources.map((src, i) => (
        <li key={i}>
          <SourceLink src={src} />
        </li>
      ))}
    </ul>
  )
}

// A row of mutually exclusive buttons in a titled card — search mode and
// answer model differ only in their options.
function ChoiceCard<T extends string>({
  title,
  options,
  selected,
  onSelect,
  label,
}: {
  title: string
  options: readonly T[]
  selected: T
  onSelect: (value: T) => void
  label: (value: T) => string
}) {
  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">{title}</h2>
      <div className="flex gap-2">
        {options.map((value) => (
          <button
            key={value}
            onClick={() => onSelect(value)}
            className={
              'px-3 py-1.5 text-sm rounded-md border cursor-pointer ' +
              (selected === value
                ? 'bg-foreground text-background font-medium'
                : 'text-muted-foreground hover:text-foreground')
            }
          >
            {label(value)}
          </button>
        ))}
      </div>
    </div>
  )
}

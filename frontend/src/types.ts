// Shapes the backend returns, shared by the shell and the search page.

export type AuthState =
  | { phase: 'loading' }
  | { phase: 'anonymous' }
  | { phase: 'authenticated'; username: string }
  | { phase: 'blocked'; username: string; reason: string; downloadUrl?: string }

export type View = 'search' | 'library' | 'archive' | 'settings'

export type Source = {
  document: string
  slug: string
  section: string
  pages: number[]
}

export type UsedChunk = {
  chunk_id: string
  document: string
  section: string
  pages: number[]
  text: string
}

export type AskResponse = {
  answer: string
  sources: Source[]
  related_sources: Source[]
  used_chunks: UsedChunk[]
  query_log_id: number
  search_query: string
  answer_model: string
  answer_ms: number
}

export type LibraryFile = {
  name: string
  path: string
  slug: string
  status: 'processing' | 'ready' | 'failed' | null
  pinned: boolean
}

export type LibraryFolder = {
  name: string
  path: string
  folders: LibraryFolder[]
  files: LibraryFile[]
}

export type LibraryResponse = {
  tree: LibraryFolder
  orphans: unknown[]
}

export type ArchiveDocument = {
  slug: string
  project: string
  relative_path: string
  status: string
}

export type ArchiveApiResponse = {
  paths: string[]
  projects: { name: string; documents: ArchiveDocument[] }[]
}

// The main flow of the whole app: choose a scope, ask, read the answer.
// These tests exist because this page was carved out of App.tsx — they say
// what "still works" means for that move.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import SearchPage from './SearchPage'
import { callsTo, stubApi } from './test/api'
import type { AskResponse } from './types'

const LIBRARY = {
  tree: {
    name: 'Normy',
    path: '',
    folders: [],
    files: [
      {
        name: 'csn.pdf',
        path: 'csn.pdf',
        slug: 'fid__csn',
        status: 'ready',
        pinned: false,
      },
    ],
  },
  orphans: [],
}

const ANSWER: AskResponse = {
  answer: 'Minimalni krytí je 30 mm.',
  sources: [
    { document: 'CSN 73 6201', slug: 'fid__csn', section: '5.2 Krytí', pages: [12, 13] },
  ],
  related_sources: [],
  used_chunks: [],
  query_log_id: 7,
  search_query: 'kryti vyztuze',
  answer_model: 'gpt-5.6-luna',
  answer_ms: 4200,
}

function stubSearch(extra: Parameters<typeof stubApi>[0] = {}) {
  return stubApi({
    '/api/library': { body: LIBRARY },
    '/api/projects': { body: { paths: [], projects: [] } },
    ...extra,
  })
}

async function ask(question: string) {
  await userEvent.type(
    screen.getByPlaceholderText('Ask a question about construction standards...'),
    question,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
}

describe('search page', () => {
  it('asks over the whole database by default', async () => {
    const calls = stubSearch({ '/api/queries': { body: ANSWER } })
    render(<SearchPage active={true} />)
    await screen.findByText('Whole database')

    await ask('kryti vyztuze?')

    const [post] = callsTo(calls, '/api/queries', 'POST')
    expect(post.body).toEqual({
      question: 'kryti vyztuze?',
      mode: 'hybrid',
      answer_model: 'gpt-5.6-luna',
      expand: true,
      strong: false,
    })
    // No document_ids at all — that is what tells the backend "search everywhere".
    expect(post.body).not.toHaveProperty('document_ids')
  })

  it('shows the answer and its sources', async () => {
    stubSearch({ '/api/queries': { body: ANSWER } })
    render(<SearchPage active={true} />)
    await screen.findByText('Whole database')

    await ask('kryti?')

    expect(await screen.findByText('Minimalni krytí je 30 mm.')).toBeVisible()
    const source = screen.getByRole('link', { name: /CSN 73 6201/ })
    expect(source).toHaveAttribute('href', '/api/library/pdf/fid__csn#page=12')
  })

  it('refuses to search when the scope is empty', async () => {
    const calls = stubSearch({ '/api/queries': { body: ANSWER } })
    render(<SearchPage active={true} />)
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Whole database' }))

    await ask('kryti?')

    expect(callsTo(calls, '/api/queries', 'POST')).toHaveLength(0)
    expect(screen.getByText(/Choose where to search/i)).toBeVisible()
  })

  it('sends the picked documents when the scope is narrowed', async () => {
    const calls = stubSearch({ '/api/queries': { body: ANSWER } })
    render(<SearchPage active={true} />)
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Whole database' }))
    await userEvent.click(screen.getByRole('checkbox', { name: /csn.pdf/ }))

    await ask('kryti?')

    const [post] = callsTo(calls, '/api/queries', 'POST')
    expect(post.body).toMatchObject({ document_ids: ['fid__csn'] })
  })

  it('does not load the trees while another tab is open', async () => {
    const calls = stubSearch()
    render(<SearchPage active={false} />)

    await waitFor(() => expect(calls.length).toBe(0))
  })
})

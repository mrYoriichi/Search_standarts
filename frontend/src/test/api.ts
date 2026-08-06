// Stubbing the backend in component tests.
//
// Every page talks to FastAPI through fetch. Tests declare what each
// endpoint answers and then assert on what was actually sent — that is
// where the real bugs live (a form that saves blanks, a request that
// never happens).
import { vi } from 'vitest'

export type Reply = { body?: unknown; ok?: boolean; status?: number }

export type Call = { url: string; method: string; body: unknown }

/**
 * Install a fetch stub. Keys are matched as substrings of the URL, so
 * '/api/auth/profile' covers both the GET and the PUT. Unlisted endpoints
 * answer 200 with an empty object — a page under test usually calls more
 * of them than the test cares about.
 */
export function stubApi(routes: Record<string, Reply>): Call[] {
  const calls: Call[] = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({
        url,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      const key = Object.keys(routes).find((k) => url.includes(k))
      const reply: Reply = key ? routes[key] : {}
      const ok = reply.ok ?? true
      return {
        ok,
        status: reply.status ?? (ok ? 200 : 500),
        json: async () => reply.body ?? {},
      } as Response
    }),
  )

  return calls
}

/** The calls that hit an endpoint, in order. */
export function callsTo(calls: Call[], fragment: string, method?: string): Call[] {
  return calls.filter(
    (c) => c.url.includes(fragment) && (method === undefined || c.method === method),
  )
}

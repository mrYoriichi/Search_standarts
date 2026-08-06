// Ready-page counter of both pools (GET /api/library/stats). The whole
// pool loads into RAM on a question, so the total is the number to watch.
// Returns null on any error — callers keep the previous value.
export async function fetchPagesTotal(): Promise<number | null> {
  try {
    const res = await fetch('/api/library/stats')
    if (!res.ok) return null
    const data: { pages_total: number } = await res.json()
    return data.pages_total
  } catch {
    return null
  }
}

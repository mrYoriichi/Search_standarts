// A source under the answer: the document, its section and clickable pages.
import { t } from '../i18n'
import type { Source } from '../types'

export function SourceLink({ src }: { src: Source }) {
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

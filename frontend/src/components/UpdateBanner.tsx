// "A new version is available" line under the header. The backend asks
// GitHub for the latest release (fail-open: offline = no banner), so a
// fetch failure here just keeps the banner hidden.
import { useEffect, useState } from 'react'

import { useI18n } from '../i18n'

type UpdateInfo = {
  update_available: boolean
  latest_version: string | null
  download_url: string | null
}

export function UpdateBanner() {
  const { t } = useI18n()
  const [info, setInfo] = useState<UpdateInfo | null>(null)

  useEffect(() => {
    fetch('/api/update')
      .then((res) => (res.ok ? res.json() : null))
      .then(setInfo)
      .catch(() => {})
  }, [])

  if (!info?.update_available || !info.latest_version) return null

  return (
    <div className="rounded-md border bg-muted px-4 py-2 text-sm flex items-center justify-between gap-4">
      <span>{t('update.available', { version: info.latest_version })}</span>
      {info.download_url && (
        <a
          href={info.download_url}
          target="_blank"
          rel="noreferrer"
          className="underline hover:text-foreground whitespace-nowrap"
        >
          {t('update.download')}
        </a>
      )}
    </div>
  )
}

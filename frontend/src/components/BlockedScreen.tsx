// Fullscreen stop: access revoked, the grace period ran out, or the build
// is older than the server allows.
import { Button } from '@/components/ui/button'
import { t } from '../i18n'

export function BlockedScreen({
  username,
  reason,
  downloadUrl,
  onLogout,
}: {
  username: string
  reason: string
  downloadUrl?: string
  onLogout: () => void
}) {
  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
      <div className="w-full max-w-md flex flex-col gap-4 rounded-md border bg-card p-6">
        <h1 className="text-2xl font-bold">{t('blocked.title')}</h1>
        <p className="text-sm text-muted-foreground">{reason}</p>
        <p className="text-sm text-muted-foreground">
          {t('blocked.user')} <span className="text-foreground">{username}</span>
        </p>
        {downloadUrl && (
          <a
            href={downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-foreground underline self-start"
          >
            {t('blocked.download')}
          </a>
        )}
        <Button onClick={onLogout} className="self-start" variant="outline">
          {t('common.logout')}
        </Button>
      </div>
    </div>
  )
}

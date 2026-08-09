import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { t, useI18n } from './i18n'

// Shared indexing settings (vision model + image description toggle).
// The settings are global — both pipelines read them (standards and project
// archive), so one modal serves both "Knihovna" and "Archiv projektů".

const VISION_MODELS = ['gpt-5.6-sol', 'gpt-5.6-luna'] as const

function VisionModelCard() {
  const [model, setModel] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch('/api/settings/vision-model')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { model: string } | null) => d && setModel(d.model))
      .catch(() => {})
  }, [])

  async function choose(m: string) {
    if (m === model || saving) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/vision-model', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: m }),
      })
      if (res.ok) setModel((await res.json()).model)
      else alert(t('common.errorStatus', { status: res.status }))
    } catch {
      alert(t('common.networkError'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
      <h2 className="text-sm font-semibold text-muted-foreground">
        {t('idx.visionModel')}
      </h2>
      <p className="text-xs text-muted-foreground">{t('idx.visionModelText')}</p>
      <div className="flex gap-2">
        {VISION_MODELS.map((m) => (
          <button
            key={m}
            onClick={() => choose(m)}
            disabled={saving}
            className={
              'px-3 py-1.5 text-sm rounded-md border ' +
              (model === m
                ? 'bg-foreground text-background font-medium'
                : 'text-muted-foreground hover:text-foreground')
            }
          >
            {m}
          </button>
        ))}
      </div>
    </div>
  )
}

function DescribeImagesCard() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch('/api/settings/describe-images')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { enabled: boolean } | null) => d && setEnabled(d.enabled))
      .catch(() => {})
  }, [])

  async function choose(value: boolean) {
    if (value === enabled || saving) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/describe-images', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: value }),
      })
      if (res.ok) setEnabled((await res.json()).enabled)
      else alert(t('common.errorStatus', { status: res.status }))
    } catch {
      alert(t('common.networkError'))
    } finally {
      setSaving(false)
    }
  }

  const options = [
    { value: true, label: t('idx.standard') },
    { value: false, label: t('idx.noLlm') },
  ]

  return (
    <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
      <h2 className="text-sm font-semibold text-muted-foreground">
        {t('idx.describeImages')}
      </h2>
      <p className="text-xs text-muted-foreground">{t('idx.describeImagesText')}</p>
      <div className="flex gap-2">
        {options.map((o) => (
          <button
            key={String(o.value)}
            onClick={() => choose(o.value)}
            disabled={saving || enabled === null}
            className={
              'px-3 py-1.5 text-sm rounded-md border ' +
              (enabled === o.value
                ? 'bg-foreground text-background font-medium'
                : 'text-muted-foreground hover:text-foreground')
            }
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// Button opening the indexing settings modal. The modal is a plain overlay
// (no ready-made Dialog in the project): background/cross click closes it.
export function IndexingSettingsButton() {
  useI18n() // subscription: a language switch re-renders the modal
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        {t('idx.button')}
      </Button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-lg rounded-md border bg-card p-4 shadow-lg flex flex-col gap-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">{t('idx.button')}</h2>
              <button
                onClick={() => setOpen(false)}
                aria-label={t('idx.close')}
                className="text-muted-foreground hover:text-foreground text-xl leading-none px-1"
              >
                ×
              </button>
            </div>
            <p className="text-xs text-muted-foreground">{t('idx.scope')}</p>
            <VisionModelCard />
            <DescribeImagesCard />
          </div>
        </div>
      )}
    </>
  )
}

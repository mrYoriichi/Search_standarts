import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

// Общие настройки индексации (модель vision + тумблер описания картинок).
// Настройки глобальные — их читают оба пайплайна (нормы и архив проектов),
// поэтому одна модалка используется и на «Knihovna», и на «Archiv projektů».

const VISION_MODELS = ['gpt-5.5', 'gpt-5.4-mini'] as const

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
      else alert(`Chyba ${res.status}`)
    } catch {
      alert('Chyba sítě')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
      <h2 className="text-sm font-semibold text-muted-foreground">
        Model pro zpracování (vision)
      </h2>
      <p className="text-xs text-muted-foreground">
        Použije se při skenování dokumentů. Vision tvoří ~99 % ceny dokumentu —
        „gpt-5.4-mini“ je výrazně levnější, „gpt-5.5“ kvalitnější.
      </p>
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
      else alert(`Chyba ${res.status}`)
    } catch {
      alert('Chyba sítě')
    } finally {
      setSaving(false)
    }
  }

  const options = [
    { value: true, label: 'Standardní (s popisem)' },
    { value: false, label: 'Bez LLM (jen OCR)' },
  ]

  return (
    <div className="rounded-md border bg-card p-4 flex flex-col gap-2">
      <h2 className="text-sm font-semibold text-muted-foreground">
        Popis obrázků a výkresů (vision)
      </h2>
      <p className="text-xs text-muted-foreground">
        „Standardní“ nechá vision popsat schémata a výkresy (lepší vyhledávání,
        vision tvoří ~99 % ceny). „Bez LLM“ použije jen OCR a text — zdarma.
      </p>
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

// Кнопка, открывающая модалку с настройками индексации. Модалка — простой
// оверлей (готового Dialog в проекте нет): клик по фону/крестику закрывает.
export function IndexingSettingsButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Nastavení indexace
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
              <h2 className="text-base font-semibold">Nastavení indexace</h2>
              <button
                onClick={() => setOpen(false)}
                aria-label="Zavřít"
                className="text-muted-foreground hover:text-foreground text-xl leading-none px-1"
              >
                ×
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              Platí pro knihovnu i archiv projektů.
            </p>
            <VisionModelCard />
            <DescribeImagesCard />
          </div>
        </div>
      )}
    </>
  )
}

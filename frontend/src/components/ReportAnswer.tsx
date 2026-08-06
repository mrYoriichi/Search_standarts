// The "Nahlásit" button under the answer: the user flags a wrong/missing
// answer. The question/answer text (+ an optional note) goes to the owner.
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { t } from '../i18n'
import type { AskResponse } from '../types'

export function ReportAnswer({
  question,
  result,
}: {
  question: string
  result: AskResponse
}) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)

  async function submit() {
    setSending(true)
    try {
      const res = await fetch('/api/queries/flag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          answer: result.answer,
          answer_model: result.answer_model,
          note: note.trim() || null,
          used_chunks: result.used_chunks,
        }),
      })
      if (res.ok) setSent(true)
      else alert(t('common.errorStatus', { status: res.status }))
    } catch {
      alert(t('report.failed'))
    } finally {
      setSending(false)
    }
  }

  if (sent) {
    return (
      <p className="text-xs text-green-600 dark:text-green-400">
        {t('report.thanks')}
      </p>
    )
  }
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-muted-foreground underline self-start"
      >
        {t('report.link')}
      </button>
    )
  }
  return (
    <div className="flex flex-col gap-2 rounded-md border bg-card p-3">
      <p className="text-xs text-muted-foreground">{t('report.prompt')}</p>
      <Textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        disabled={sending}
      />
      <div className="flex gap-2">
        <Button onClick={submit} disabled={sending} size="sm">
          {sending ? t('report.sending') : t('report.send')}
        </Button>
        <Button
          onClick={() => setOpen(false)}
          disabled={sending}
          size="sm"
          variant="outline"
        >
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useI18n } from './i18n'

const inputClass = 'rounded-md border bg-background px-3 py-2 text-sm max-w-md'
const cardClass = 'rounded-md border bg-card p-4 flex flex-col gap-3'

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <ProfileSection />
      <PasswordSection />
      <AnswerLanguageSection />
      <OpenAIKeySection />
      <VersionLine />
    </div>
  )
}

// ── Installed app version ─────────────────────────────────────────────────────

function VersionLine() {
  const { t } = useI18n()
  const [version, setVersion] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { version?: string } | null) => d?.version && setVersion(d.version))
      .catch(() => {})
  }, [])

  if (!version) return null
  return (
    <p className="text-sm text-muted-foreground">
      {t('settings.version', { version })}
    </p>
  )
}

// ── LLM answer language ───────────────────────────────────────────────────────

function AnswerLanguageSection() {
  const { t } = useI18n()
  const [language, setLanguage] = useState<'cs' | 'en' | 'de' | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch('/api/settings/answer-language')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { language: 'cs' | 'en' | 'de' } | null) => d && setLanguage(d.language))
      .catch(() => {})
  }, [])

  async function choose(value: 'cs' | 'en' | 'de') {
    if (value === language || saving) return
    setSaving(true)
    try {
      const res = await fetch('/api/settings/answer-language', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: value }),
      })
      if (res.ok) setLanguage((await res.json()).language)
      else alert(t('common.errorStatus', { status: res.status }))
    } catch {
      alert(t('common.networkError'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">
        {t('settings.answerLang')}
      </h2>
      <p className="text-sm text-muted-foreground">{t('settings.answerLangText')}</p>
      <div className="flex gap-2">
        {(['cs', 'en', 'de'] as const).map((value) => (
          <button
            key={value}
            onClick={() => choose(value)}
            disabled={saving || language === null}
            className={
              'px-3 py-1.5 text-sm rounded-md border ' +
              (language === value
                ? 'bg-foreground text-background font-medium'
                : 'text-muted-foreground hover:text-foreground')
            }
          >
            {t(`lang.${value}`)}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Profile (name, email, company) ───────────────────────────────────────────

type Profile = {
  username: string
  email: string | null
  full_name: string | null
  company: string | null
  position: string | null
  linkedin: string | null
}

function ProfileSection() {
  const { t } = useI18n()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [company, setCompany] = useState('')
  const [position, setPosition] = useState('')
  const [linkedin, setLinkedin] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetch('/api/auth/profile')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('load'))))
      .then((data: Profile) => {
        setProfile(data)
        setEmail(data.email ?? '')
        setFullName(data.full_name ?? '')
        setCompany(data.company ?? '')
        setPosition(data.position ?? '')
        setLinkedin(data.linkedin ?? '')
      })
      .catch(() => setError(t('settings.profileLoadFailed')))
    // t is stable (a module-level function) — the effect runs once.
  }, [t])

  async function handleSave() {
    setError(null)
    setSaved(false)
    setLoading(true)
    try {
      // PUT is a full replace: send all fields, or the server clears the rest.
      const res = await fetch('/api/auth/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          full_name: fullName,
          company,
          position,
          linkedin,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(
          typeof data?.detail === 'string'
            ? data.detail
            : t('settings.profileSaveFailed'),
        )
        return
      }
      setProfile(await res.json())
      setSaved(true)
    } catch {
      setError(t('settings.appUnavailable'))
    } finally {
      setLoading(false)
    }
  }

  // Until the profile arrives the fields are empty, and PUT is a full
  // replace — saving now would blank the stored data (the license server
  // sleeps on Render, so a slow or failed load is normal).
  const busy = loading || profile === null

  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">
        {t('settings.profile')}
      </h2>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('login.username')}</span>
        <input
          type="text"
          value={profile?.username ?? ''}
          disabled
          className={inputClass + ' opacity-60'}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('settings.name')}</span>
        <input
          type="text"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          disabled={busy}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('login.email')}</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={busy}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('login.company')}</span>
        <input
          type="text"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          disabled={busy}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('login.position')}</span>
        <input
          type="text"
          value={position}
          onChange={(e) => setPosition(e.target.value)}
          disabled={busy}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('settings.linkedinOptional')}</span>
        <input
          type="text"
          value={linkedin}
          onChange={(e) => setLinkedin(e.target.value)}
          disabled={busy}
          className={inputClass}
        />
      </label>

      <Button onClick={handleSave} disabled={busy} className="self-start">
        {loading ? t('settings.saving') : t('settings.saveProfile')}
      </Button>

      {error && <ErrorBox text={error} />}
      {saved && (
        <p className="text-sm text-green-600 dark:text-green-400">
          {t('settings.profileSaved')}
        </p>
      )}
    </div>
  )
}

// ── Password change ───────────────────────────────────────────────────────────

function PasswordSection() {
  const { t } = useI18n()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleSave() {
    setError(null)
    setSaved(false)
    setLoading(true)
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(
          typeof data?.detail === 'string'
            ? data.detail
            : t('settings.passwordChangeFailed'),
        )
        return
      }
      setOldPassword('')
      setNewPassword('')
      setSaved(true)
    } catch {
      setError(t('settings.appUnavailable'))
    } finally {
      setLoading(false)
    }
  }

  // New password — at least 8 characters (same requirement on the server).
  const canSubmit =
    oldPassword.length > 0 && newPassword.length >= 8 && !loading

  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">
        {t('settings.changePassword')}
      </h2>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('settings.currentPassword')}</span>
        <input
          type="password"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('settings.newPassword')}</span>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <Button onClick={handleSave} disabled={!canSubmit} className="self-start">
        {loading ? t('settings.saving') : t('settings.changePasswordBtn')}
      </Button>

      {error && <ErrorBox text={error} />}
      {saved && (
        <p className="text-sm text-green-600 dark:text-green-400">
          {t('settings.passwordChanged')}
        </p>
      )}
    </div>
  )
}

// ── OpenAI key ────────────────────────────────────────────────────────────────

type KeyStatus = {
  is_set: boolean
  masked: string | null
}

function OpenAIKeySection() {
  const { t } = useI18n()
  const [status, setStatus] = useState<KeyStatus | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)

  function loadStatus() {
    fetch('/api/settings/openai-key')
      .then((res) => (res.ok ? res.json() : null))
      .then((data: KeyStatus | null) => setStatus(data))
      .catch(() => setStatus(null))
  }

  useEffect(loadStatus, [])

  async function handleSave() {
    setError(null)
    setSaved(false)
    setLoading(true)
    try {
      const res = await fetch('/api/settings/openai-key', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: keyInput }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(
          typeof data?.detail === 'string'
            ? data.detail
            : t('settings.keySaveFailed'),
        )
        return
      }
      setStatus(await res.json())
      setKeyInput('')
      setSaved(true)
    } catch {
      setError(t('settings.appUnavailable'))
    } finally {
      setLoading(false)
    }
  }

  const canSubmit = keyInput.trim().length > 0 && !loading

  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">
        {t('settings.openaiKey')}
      </h2>
      <p className="text-sm text-muted-foreground">{t('settings.openaiKeyText')}</p>

      {status && (
        <p className="text-sm">
          {status.is_set
            ? t('settings.currentKey', { masked: status.masked ?? '' })
            : t('settings.keyNotSet')}
        </p>
      )}

      <input
        type="password"
        placeholder="sk-…"
        value={keyInput}
        onChange={(e) => setKeyInput(e.target.value)}
        disabled={loading}
        className={inputClass}
      />

      <Button onClick={handleSave} disabled={!canSubmit} className="self-start">
        {loading ? t('settings.saving') : t('settings.saveKey')}
      </Button>

      {error && <ErrorBox text={error} />}
      {saved && (
        <p className="text-sm text-green-600 dark:text-green-400">
          {t('settings.keySaved')}
        </p>
      )}
    </div>
  )
}

// ── Shared error block ────────────────────────────────────────────────────────

function ErrorBox({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      {text}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

const inputClass = 'rounded-md border bg-background px-3 py-2 text-sm max-w-md'
const cardClass = 'rounded-md border bg-card p-4 flex flex-col gap-3'

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <ProfileSection />
      <PasswordSection />
      <OpenAIKeySection />
    </div>
  )
}

// ── Профиль (имя, email, компания) ───────────────────────────────────────────

type Profile = {
  username: string
  email: string | null
  full_name: string | null
  company: string | null
  position: string | null
  linkedin: string | null
}

function ProfileSection() {
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
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Profile | null) => {
        if (!data) return
        setProfile(data)
        setEmail(data.email ?? '')
        setFullName(data.full_name ?? '')
        setCompany(data.company ?? '')
        setPosition(data.position ?? '')
        setLinkedin(data.linkedin ?? '')
      })
      .catch(() => setError('Profil se nepodařilo načíst.'))
  }, [])

  async function handleSave() {
    setError(null)
    setSaved(false)
    setLoading(true)
    try {
      // PUT — полная замена: шлём все поля, иначе сервер очистит пропущенные.
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
        setError(typeof data?.detail === 'string' ? data.detail : 'Uložení profilu selhalo.')
        return
      }
      setProfile(await res.json())
      setSaved(true)
    } catch {
      setError('Aplikace není dostupná. Zkuste to později.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">Profil</h2>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Přihlašovací jméno</span>
        <input
          type="text"
          value={profile?.username ?? ''}
          disabled
          className={inputClass + ' opacity-60'}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Jméno</span>
        <input
          type="text"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">E-mail</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Společnost</span>
        <input
          type="text"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Pozice</span>
        <input
          type="text"
          value={position}
          onChange={(e) => setPosition(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">LinkedIn (nepovinné)</span>
        <input
          type="text"
          value={linkedin}
          onChange={(e) => setLinkedin(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <Button onClick={handleSave} disabled={loading} className="self-start">
        {loading ? 'Ukládání...' : 'Uložit profil'}
      </Button>

      {error && <ErrorBox text={error} />}
      {saved && <p className="text-sm text-green-600">Profil byl uložen.</p>}
    </div>
  )
}

// ── Смена пароля ──────────────────────────────────────────────────────────────

function PasswordSection() {
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
        setError(typeof data?.detail === 'string' ? data.detail : 'Změna hesla selhala.')
        return
      }
      setOldPassword('')
      setNewPassword('')
      setSaved(true)
    } catch {
      setError('Aplikace není dostupná. Zkuste to později.')
    } finally {
      setLoading(false)
    }
  }

  // Новый пароль — минимум 8 символов (то же требование на сервере).
  const canSubmit =
    oldPassword.length > 0 && newPassword.length >= 8 && !loading

  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">Změna hesla</h2>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Současné heslo</span>
        <input
          type="password"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Nové heslo (min. 8 znaků)</span>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          disabled={loading}
          className={inputClass}
        />
      </label>

      <Button onClick={handleSave} disabled={!canSubmit} className="self-start">
        {loading ? 'Ukládání...' : 'Změnit heslo'}
      </Button>

      {error && <ErrorBox text={error} />}
      {saved && <p className="text-sm text-green-600">Heslo bylo změněno.</p>}
    </div>
  )
}

// ── Ключ OpenAI ───────────────────────────────────────────────────────────────

type KeyStatus = {
  is_set: boolean
  masked: string | null
}

function OpenAIKeySection() {
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
        setError(typeof data?.detail === 'string' ? data.detail : 'Uložení klíče selhalo.')
        return
      }
      setStatus(await res.json())
      setKeyInput('')
      setSaved(true)
    } catch {
      setError('Aplikace není dostupná. Zkuste to později.')
    } finally {
      setLoading(false)
    }
  }

  const canSubmit = keyInput.trim().length > 0 && !loading

  return (
    <div className={cardClass}>
      <h2 className="text-sm font-semibold text-muted-foreground">Klíč OpenAI</h2>
      <p className="text-sm text-muted-foreground">
        Klíč se ukládá pouze na vašem počítači. Náklady na dotazy se účtují na tento klíč.
      </p>

      {status && (
        <p className="text-sm">
          {status.is_set
            ? `Aktuální klíč: ${status.masked}`
            : 'Klíč zatím není nastaven.'}
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
        {loading ? 'Ukládání...' : 'Uložit klíč'}
      </Button>

      {error && <ErrorBox text={error} />}
      {saved && <p className="text-sm text-green-600">Klíč byl uložen.</p>}
    </div>
  )
}

// ── Общий блок ошибки ─────────────────────────────────────────────────────────

function ErrorBox({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      {text}
    </div>
  )
}

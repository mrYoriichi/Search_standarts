import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Logo } from './Logo'

type Props = {
  onLoggedIn: (username: string) => void
}

type FieldProps = {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  disabled?: boolean
  autoFocus?: boolean
  hint?: string
  optional?: boolean
}

// Одна подпись + поле ввода. Вынесено, чтобы не повторять разметку для 6 полей.
function Field({
  label,
  value,
  onChange,
  type = 'text',
  disabled,
  autoFocus,
  hint,
  optional,
}: FieldProps) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted-foreground">
        {label}
        {optional && ' (nepovinné)'}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        autoFocus={autoFocus}
        className="rounded-md border bg-background px-3 py-2 text-sm"
      />
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  )
}

export default function LoginPage({ onLoggedIn }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  // username держит логин-строку: при входе — přihlašovací jméno, при регистрации — e-mail.
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  // Поля только для регистрации.
  const [fullName, setFullName] = useState('')
  const [company, setCompany] = useState('')
  const [position, setPosition] = useState('')
  const [linkedin, setLinkedin] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Если сервер сказал 426 — форма скрывается, показываем блок «Установите новую версию».
  // Логин не пройдёт пока юзер не обновит приложение.
  const [updateRequired, setUpdateRequired] = useState<{ downloadUrl: string } | null>(null)

  const isRegister = mode === 'register'

  function switchMode(next: 'login' | 'register') {
    setMode(next)
    setError(null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const endpoint = isRegister ? '/api/auth/register' : '/api/auth/login'
      const body = isRegister
        ? {
            email: username,
            password,
            full_name: fullName,
            company,
            position,
            linkedin: linkedin.trim() || null,
          }
        : { username, password }
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.status === 426) {
        const data = await res.json()
        setUpdateRequired({ downloadUrl: data?.detail?.download_url ?? '' })
        return
      }
      if (res.status === 401) {
        setError('Nesprávné přihlašovací jméno nebo heslo')
        return
      }
      if (res.status === 403) {
        setError('Přístup byl odebrán. Obraťte se na administrátora.')
        return
      }
      // Только регистрация: e-mail занят / невалидные или неполные данные.
      if (res.status === 409) {
        setError('Tento e-mail je již zaregistrovaný.')
        return
      }
      if (res.status === 400) {
        setError(
          'Zkontrolujte údaje: platný e-mail, heslo alespoň 8 znaků, vyplněné jméno, firma a pozice.',
        )
        return
      }
      if (res.status === 503) {
        setError('Licenční server není dostupný. Zkuste to později.')
        return
      }
      if (!res.ok) {
        setError(`Chyba: ${res.status}`)
        return
      }
      const data = await res.json()
      onLoggedIn(data.username)
    } catch {
      setError('Nepodařilo se spojit s aplikací.')
    } finally {
      setLoading(false)
    }
  }

  const canSubmit = isRegister
    ? username.trim().length > 0 &&
      password.length > 0 &&
      fullName.trim().length > 0 &&
      company.trim().length > 0 &&
      position.trim().length > 0 &&
      !loading
    : username.trim().length > 0 && password.length > 0 && !loading

  if (updateRequired) {
    return (
      <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
        <div className="w-full max-w-md flex flex-col gap-4 rounded-md border bg-card p-6">
          <h1 className="text-2xl font-bold">Nainstalujte novou verzi</h1>
          <p className="text-sm text-muted-foreground">
            Je dostupná povinná verze aplikace. Přihlásit se lze až po aktualizaci.
          </p>
          {updateRequired.downloadUrl ? (
            <a
              href={updateRequired.downloadUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-foreground underline self-start"
            >
              Stáhnout aktualizaci →
            </a>
          ) : (
            <p className="text-sm text-muted-foreground">
              Odkaz zatím není dostupný. Obraťte se na administrátora.
            </p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6 py-10">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm flex flex-col gap-4 rounded-md border bg-card p-6"
      >
        <h1 className="text-2xl">
          <Logo />
        </h1>
        <p className="text-sm text-muted-foreground">
          {isRegister ? 'Registrace nového účtu' : 'Přihlášení do aplikace'}
        </p>

        {isRegister && (
          <Field
            label="Jméno a příjmení"
            value={fullName}
            onChange={setFullName}
            disabled={loading}
            autoFocus
          />
        )}

        <Field
          label={isRegister ? 'E-mail' : 'Přihlašovací jméno'}
          type={isRegister ? 'email' : 'text'}
          value={username}
          onChange={setUsername}
          disabled={loading}
          autoFocus={!isRegister}
        />

        <Field
          label="Heslo"
          type="password"
          value={password}
          onChange={setPassword}
          disabled={loading}
          hint={isRegister ? 'Alespoň 8 znaků.' : undefined}
        />

        {isRegister && (
          <>
            <Field
              label="Společnost"
              value={company}
              onChange={setCompany}
              disabled={loading}
            />
            <Field
              label="Pozice"
              value={position}
              onChange={setPosition}
              disabled={loading}
            />
            <Field
              label="LinkedIn"
              value={linkedin}
              onChange={setLinkedin}
              disabled={loading}
              optional
            />
          </>
        )}

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <Button type="submit" disabled={!canSubmit}>
          {loading
            ? isRegister
              ? 'Registruji...'
              : 'Přihlašuji...'
            : isRegister
              ? 'Zaregistrovat se'
              : 'Přihlásit se'}
        </Button>

        <button
          type="button"
          onClick={() => switchMode(isRegister ? 'login' : 'register')}
          disabled={loading}
          className="text-sm text-muted-foreground underline self-center"
        >
          {isRegister
            ? 'Máte účet? Přihlaste se'
            : 'Nemáte účet? Zaregistrujte se'}
        </button>
      </form>
    </div>
  )
}

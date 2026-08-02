/* eslint-disable react-refresh/only-export-components --
   t()/useI18n live next to the provider on purpose; the file rarely changes,
   losing hot-reload for it is not worth a third file. */
// Mini i18n without libraries: dictionaries in messages.ts, the context
// provides the language and re-renders on switch. {name} placeholders are
// filled from params.
//
// Two ways to translate:
// - in components: `const { t } = useI18n()` — subscribes to language changes;
// - in module-level functions (alert/confirm on click): import `t` directly —
//   hooks are unavailable there, and at click time the language is current.

import { createContext, useContext, useState, type ReactNode } from 'react'
import { dictionaries, type Lang, type MsgKey } from './messages'

const LANGS: Lang[] = ['cs', 'en', 'de']

function initialLang(): Lang {
  const saved = localStorage.getItem('lang')
  return LANGS.includes(saved as Lang) ? (saved as Lang) : 'en'
}

// The current language at module level — t() reads it. Changed only via the
// provider's setLang, which also triggers a re-render through the context.
let currentLang: Lang = initialLang()

export function t(key: MsgKey, params?: Record<string, string | number>): string {
  const template = dictionaries[currentLang][key] ?? dictionaries.en[key]
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    name in params ? String(params[name]) : match,
  )
}

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({
  lang: currentLang,
  setLang: () => {},
})

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(currentLang)

  function setLang(next: Lang) {
    currentLang = next
    localStorage.setItem('lang', next)
    setLangState(next)
    // The backend uses the language for error texts — send best-effort,
    // a failure does not block switching the UI.
    fetch('/api/settings/language', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: next }),
    }).catch(() => {})
  }

  return (
    <LangContext.Provider value={{ lang, setLang }}>
      {children}
    </LangContext.Provider>
  )
}

export function useI18n() {
  const { lang, setLang } = useContext(LangContext)
  return { lang, setLang, t }
}

// CZ / EN / DE switcher — in the app header and on the login page.
export function LangSwitcher() {
  const { lang, setLang } = useI18n()
  return (
    <div className="flex gap-1 text-xs">
      {LANGS.map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className={
            'px-1.5 py-0.5 rounded uppercase ' +
            (lang === l
              ? 'bg-foreground text-background font-medium'
              : 'text-muted-foreground hover:text-foreground')
          }
        >
          {l === 'cs' ? 'cz' : l}
        </button>
      ))}
    </div>
  )
}

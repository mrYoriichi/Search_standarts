/* eslint-disable react-refresh/only-export-components --
   t()/useI18n живут рядом с провайдером намеренно; файл почти не меняется,
   потеря hot-reload для него не стоит третьего файла. */
// Мини-i18n без библиотек: словари в messages.ts, контекст даёт язык
// и перерисовку при его смене. Плейсхолдеры {name} подставляются из params.
//
// Два способа перевода:
// - в компонентах: `const { t } = useI18n()` — подписывает на смену языка;
// - в модульных функциях (alert/confirm по клику): импорт `t` напрямую —
//   хуки там недоступны, а на момент клика язык всегда актуален.

import { createContext, useContext, useState, type ReactNode } from 'react'
import { dictionaries, type Lang, type MsgKey } from './messages'

const LANGS: Lang[] = ['cs', 'en', 'de']

function initialLang(): Lang {
  const saved = localStorage.getItem('lang')
  return LANGS.includes(saved as Lang) ? (saved as Lang) : 'cs'
}

// Текущий язык на уровне модуля — его читает t(). Меняется только через
// setLang провайдера, который заодно триггерит перерисовку через контекст.
let currentLang: Lang = initialLang()

export function t(key: MsgKey, params?: Record<string, string | number>): string {
  const template = dictionaries[currentLang][key] ?? dictionaries.cs[key]
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

// Переключатель CZ / EN / DE — в шапке приложения и на странице логина.
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

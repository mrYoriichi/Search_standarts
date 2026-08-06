// Shell chrome: logo, language, theme, the signed-in user and the tabs.
import { Logo } from '../Logo'
import { LangSwitcher, t } from '../i18n'
import type { View } from '../types'

export function AppHeader({
  username,
  view,
  theme,
  onView,
  onToggleTheme,
  onLogout,
}: {
  username: string
  view: View
  theme: 'light' | 'dark'
  onView: (view: View) => void
  onToggleTheme: () => void
  onLogout: () => void
}) {
  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-3xl">
          <Logo />
        </h1>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <LangSwitcher />
          <button
            onClick={onToggleTheme}
            title={theme === 'dark' ? t('theme.toLight') : t('theme.toDark')}
            className="text-base leading-none cursor-pointer"
          >
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
          <button
            onClick={() => onView('settings')}
            className={
              'cursor-pointer hover:text-foreground hover:underline ' +
              (view === 'settings' ? 'text-foreground font-medium' : '')
            }
            title={t('header.settingsTitle')}
          >
            👤 {username}
          </button>
          <button
            onClick={onLogout}
            className="cursor-pointer hover:text-foreground hover:underline"
          >
            {t('common.logout')}
          </button>
        </div>
      </div>

      <nav className="flex gap-1 border-b">
        <NavTab view="search" current={view} onView={onView} label={t('nav.search')} />
        <NavTab view="library" current={view} onView={onView} label={t('nav.library')} />
        <NavTab view="archive" current={view} onView={onView} label={t('nav.archive')} />
      </nav>
    </>
  )
}

function NavTab({
  view,
  current,
  label,
  onView,
}: {
  view: View
  current: View
  label: string
  onView: (view: View) => void
}) {
  return (
    <button
      onClick={() => onView(view)}
      className={
        'px-4 py-2 text-sm border-b-2 -mb-px cursor-pointer ' +
        (current === view
          ? 'border-foreground font-medium'
          : 'border-transparent text-muted-foreground hover:text-foreground')
      }
    >
      {label}
    </button>
  )
}

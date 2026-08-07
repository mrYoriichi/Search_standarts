// The shell: who is signed in, which tab is open, light or dark.
// Everything a tab does lives in that tab's own file.
import { useState } from 'react'

import ArchivePage from './ArchivePage'
import LibraryPage from './LibraryPage'
import LoginPage from './LoginPage'
import SearchPage from './SearchPage'
import SettingsPage from './SettingsPage'
import { AppHeader } from './components/AppHeader'
import { BlockedScreen } from './components/BlockedScreen'
import { UpdateBanner } from './components/UpdateBanner'
import { useAuth } from './hooks/useAuth'
import { useTheme } from './hooks/useTheme'
import { useI18n } from './i18n'
import type { View } from './types'

export default function App() {
  // Subscribe to language changes: a switch re-renders App and its whole tree.
  useI18n()
  const { auth, setAuth, logout } = useAuth()
  const { theme, toggle: toggleTheme } = useTheme()
  const [view, setView] = useState<View>('search')

  if (auth.phase === 'loading') {
    // A short flicker; a full spinner is overkill.
    return <div className="min-h-screen bg-background" />
  }
  if (auth.phase === 'anonymous') {
    return (
      <LoginPage
        onLoggedIn={(username) => setAuth({ phase: 'authenticated', username })}
      />
    )
  }
  if (auth.phase === 'blocked') {
    return (
      <BlockedScreen
        username={auth.username}
        reason={auth.reason}
        downloadUrl={auth.downloadUrl}
        onLogout={logout}
      />
    )
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-3xl mx-auto px-6 py-10 flex flex-col gap-6">
        <AppHeader
          username={auth.username}
          view={view}
          theme={theme}
          onView={setView}
          onToggleTheme={toggleTheme}
          onLogout={logout}
        />

        <UpdateBanner />

        {/* SearchPage hides itself instead of unmounting — see the comment
            there: a switch to another tab must not drop the answer. */}
        <SearchPage active={view === 'search'} />
        {view === 'library' && <LibraryPage />}
        {view === 'archive' && <ArchivePage />}
        {view === 'settings' && <SettingsPage />}
      </div>
    </div>
  )
}

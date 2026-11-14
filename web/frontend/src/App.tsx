import { createContext, useContext, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { formatTimestamp } from './api'
import Logo from './components/Logo'
import NavigationIcon from './components/NavigationIcon'
import { useInboxBadge } from './inboxBadge'

/** Screens publish their fetched_at for the footer. */
const FetchedAtContext = createContext<(iso: string | null) => void>(() => {})

export function useSetFetchedAt() {
  return useContext(FetchedAtContext)
}

const PRIMARY_LINKS = [
  { to: '/', label: 'Home', icon: 'home', end: true },
  { to: '/strategies', label: 'Strategies', icon: 'strategies', end: false },
  { to: '/inbox', label: 'Inbox', icon: 'inbox', end: false },
] as const

/** The moved Leaderboard keeps its wide board layout. */
export const LEADERBOARD_PATH = '/strategies/research/leaderboard'

export default function App() {
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const isDetail = location.pathname.startsWith('/s/') || location.pathname.startsWith('/strategy/')
  const isLeaderboard = location.pathname === LEADERBOARD_PATH
  const isHome = location.pathname === '/'
  const isList = location.pathname === '/strategies'
  const isInbox = location.pathname === '/inbox'
  const inboxBadge = useInboxBadge(location.pathname.startsWith('/inbox'))
  const shellClass = isLeaderboard ? 'shell leaderboard-shell' : isHome ? 'shell home-shell'
    : isList ? 'shell strats-shell' : isInbox ? 'shell inbox-shell' : isDetail ? 'shell detail-shell' : 'shell'

  return (
    <FetchedAtContext.Provider value={setFetchedAt}>
      <div className={shellClass}>
        {/* Home, the Strategies list and the Inbox draw their own titles; a strategy page has a
            "‹ Strategies" back control in place of the centered brand. */}
        {isDetail ? (
          <nav className="sd-nav" aria-label="Back">
            <button
              type="button"
              className="sd-back"
              onClick={() => {
                if (window.history.length > 1) navigate(-1)
                else navigate('/strategies')
              }}
            >
              <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
              Strategies
            </button>
          </nav>
        ) : !isHome && !isList && !isInbox && <header className="shell-header">
          <div className="topbar">
            <span aria-hidden="true" />
            <div className="brand"><Logo /></div>
            <span aria-hidden="true" />
          </div>
        </header>}
        <main className="content">
          <Outlet />
        </main>
        <footer className="app-footer" aria-label="Last updated">
          {fetchedAt !== null && <time dateTime={fetchedAt}>Updated {formatTimestamp(fetchedAt)}</time>}
        </footer>
        <nav className="bottom-nav" aria-label="Main navigation">
          {PRIMARY_LINKS.map(({ to, label, icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              // A strategy page sits under the Strategies tab.
              className={({ isActive }) =>
                isActive || (to === '/strategies' && isDetail) ? 'bottom-link active' : 'bottom-link'}
            >
              <span className="bottom-icon">
                <NavigationIcon name={icon} />
                {to === '/inbox' && inboxBadge > 0 && (
                  <span className="bottom-badge" data-testid="inbox-badge" aria-hidden="true">{inboxBadge}</span>
                )}
              </span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </FetchedAtContext.Provider>
  )
}

import { createContext, useContext, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { formatTimestamp } from './api'
import Logo from './components/Logo'
import NavigationIcon from './components/NavigationIcon'

/** Screens publish their fetched_at for the footer. */
const FetchedAtContext = createContext<(iso: string | null) => void>(() => {})

export function useSetFetchedAt() {
  return useContext(FetchedAtContext)
}

const PRIMARY_LINKS = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', end: true },
  { to: '/research', label: 'Research', icon: 'research', end: false },
  { to: '/fleet', label: 'Fleet', icon: 'fleet', end: false },
  { to: '/money', label: 'Portfolio', icon: 'portfolio', end: false },
  { to: '/now', label: 'System', icon: 'system', end: false },
] as const

export default function App() {
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const isDetail = location.pathname.startsWith('/s/') || location.pathname.startsWith('/strategy/')
  const isLeaderboard = location.pathname === '/'

  return (
    <FetchedAtContext.Provider value={setFetchedAt}>
      <div className={isLeaderboard ? 'shell leaderboard-shell' : 'shell'}>
        <header className="shell-header">
          <div className="topbar">
            {isDetail ? (
              <button
                type="button"
                className="back-btn"
                aria-label="Back"
                onClick={() => {
                  if (window.history.length > 1) navigate(-1)
                  else navigate('/')
                }}
              >
                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m14 5-7 7 7 7" /></svg>
              </button>
            ) : <span aria-hidden="true" />}
            <div className="brand"><Logo /></div>
            <span aria-hidden="true" />
          </div>
        </header>
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
              className={({ isActive }) => isActive ? 'bottom-link active' : 'bottom-link'}
            >
              <NavigationIcon name={icon} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </FetchedAtContext.Provider>
  )
}

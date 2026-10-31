import { createContext, useContext, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { formatTimestamp } from './api'
import Logo from './components/Logo'

/** Screens push the envelope's fetched_at into the header slot through this. */
const FetchedAtContext = createContext<(iso: string | null) => void>(() => {})

export function useSetFetchedAt() {
  return useContext(FetchedAtContext)
}

const SECONDARY_LINKS = [
  { to: '/now', label: 'Ops', end: false },
  { to: '/fleet', label: 'Fleet', end: false },
  { to: '/money', label: 'Money', end: false },
  { to: '/research', label: 'Research', end: false },
]

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
                onClick={() => {
                  if (window.history.length > 1) navigate(-1)
                  else navigate('/')
                }}
              >
                back
              </button>
            ) : (
              <NavLink to="/" className="brand" aria-label="Algua strategy leaderboard">
                <Logo />
                <span className="brand-descriptor">monitor</span>
              </NavLink>
            )}
            {fetchedAt !== null && (
              <span className="fetched-at">fetched {formatTimestamp(fetchedAt)}</span>
            )}
          </div>
          <nav className="secondary-nav" aria-label="Secondary monitoring">
            {SECONDARY_LINKS.map(({ to, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => isActive ? 'secondary-link active' : 'secondary-link'}
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </FetchedAtContext.Provider>
  )
}

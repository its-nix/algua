import { Link } from 'react-router-dom'
import { LEADERBOARD_PATH } from '../App'

/** Interim Strategies tab until its list lands: the moved research views stay one tap away. */
export function StrategiesSoon() {
  return (
    <div className="decision-page">
      <header className="page-heading"><h1>Strategies</h1></header>
      <nav className="soon-links" aria-label="Research views">
        <Link to={LEADERBOARD_PATH} className="text-link">Leaderboard</Link>
        <Link to="/strategies/research" className="text-link">Research</Link>
      </nav>
    </div>
  )
}

/** Interim Inbox tab until the Inbox screen lands. */
export function InboxSoon() {
  return (
    <div className="decision-page">
      <header className="page-heading"><h1>Inbox</h1></header>
      <p className="dim-note">Everything you send feeds the next leap run.</p>
    </div>
  )
}

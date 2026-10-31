import OperationalHealth from '../components/OperationalHealth'
import StrategyBoard from '../components/StrategyBoard'

export default function Leaderboard() {
  return (
    <div className="leaderboard-page">
      <header className="leaderboard-intro">
        <h1>Strategy leaderboard</h1>
        <p>
          Latest identity-bound out-of-sample evidence. Rows are deliberately unranked until the
          API supplies a comparable period and data tier.
        </p>
      </header>
      <OperationalHealth updateHeader />
      <StrategyBoard />
    </div>
  )
}

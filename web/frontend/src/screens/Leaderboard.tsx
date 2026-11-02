import OperationalHealth from '../components/OperationalHealth'
import StrategyBoard from '../components/StrategyBoard'

export default function Leaderboard() {
  return (
    <div className="leaderboard-page">
      <header className="leaderboard-intro">
        <h1>Strategy leaderboard</h1>
        <p>
          Latest identity-bound evidence. Public WF windows are in-sample; gate OOS observations are separate.
          Compare within a recorded cohort; unknown and incompatible evidence stays unranked.
        </p>
      </header>
      <OperationalHealth updateHeader />
      <StrategyBoard />
    </div>
  )
}

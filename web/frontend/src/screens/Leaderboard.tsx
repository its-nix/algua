import OperationalHealth from '../components/OperationalHealth'
import StrategyBoard from '../components/StrategyBoard'
import RetainedExperiments from '../components/RetainedExperiments'

export default function Leaderboard() {
  return (
    <div className="leaderboard-page">
      <header className="leaderboard-intro">
        <h1>Strategy leaderboard</h1>
        <details className="context-disclosure">
          <summary>About these results</summary>
          <p>
          Latest identity-bound evidence. Public WF windows are in-sample; gate OOS observations are separate.
          Compare within a recorded cohort; unknown and incompatible evidence stays unranked.
          </p>
        </details>
      </header>
      <OperationalHealth updateHeader compact />
      <StrategyBoard />
      <RetainedExperiments compact />
    </div>
  )
}

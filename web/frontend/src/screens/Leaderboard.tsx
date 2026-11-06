import OperationalHealth from '../components/OperationalHealth'
import StrategyBoard from '../components/StrategyBoard'
import RetainedExperiments from '../components/RetainedExperiments'

export default function Leaderboard() {
  return (
    <div className="leaderboard-page">
      <header className="leaderboard-intro">
        <h1>Leaderboard</h1>
      </header>
      <StrategyBoard hideEmpty />
      <RetainedExperiments compact />
      <OperationalHealth updateHeader compact />
    </div>
  )
}

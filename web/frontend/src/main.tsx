// The Drive brand kit supplies self-hosted Lato and adaptive light/dark colors.
import './theme.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import App, { LEADERBOARD_PATH } from './App'
import Fleet from './screens/Fleet'
import Home from './screens/Home'
import Leaderboard from './screens/Leaderboard'
import Now from './screens/Now'
import Research from './screens/Research'
import StrategyDetail from './screens/StrategyDetail'
import StrategyIdResolver from './screens/StrategyIdResolver'
import { InboxSoon } from './screens/Soon'
import Strategies from './screens/Strategies'

// PROD only — a dev service worker would fight the Vite proxy. With registerType
// 'autoUpdate' the virtual module owns activation AND the post-update reload; a second
// manual controllerchange listener would be a duplicate reload path.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  registerSW({ immediate: true })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Home />} />
          <Route path="strategies" element={<Strategies />} />
          <Route path="strategies/research" element={<Research />} />
          <Route path={LEADERBOARD_PATH.slice(1)} element={<Leaderboard />} />
          <Route path="inbox" element={<InboxSoon />} />
          <Route path="now" element={<Now />} />
          <Route path="fleet" element={<Fleet />} />
          {/* Old addresses (bookmarks, triage routes) land on their new homes. */}
          <Route path="money" element={<Navigate to="/" replace />} />
          <Route path="research" element={<Navigate to="/strategies/research" replace />} />
          <Route path="funnel" element={<Navigate to="/strategies/research" replace />} />
          <Route path="strategy/:id" element={<StrategyIdResolver />} />
          <Route path="s/:name" element={<StrategyDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)

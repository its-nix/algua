import type { StrategyBoardRow } from '../types'

export const FIXTURE_LABEL = 'Synthetic fixture · not market data · not qualification'

export function declaredTier(row: StrategyBoardRow): string | undefined {
  return row.evidence?.snapshot_provenance?.value?.data_tier
}

export function matchesTier(row: StrategyBoardRow, tier: string): boolean {
  const declared = declaredTier(row)
  if (tier === 'synthetic_fixture') return declared === tier
  if (tier === 'unknown') return declared === undefined
  return declared !== 'synthetic_fixture'
}

export default function BoardDataTier({ value, onChange }: {
  value: string
  onChange: (value: string) => void
}) {
  return <label className="board-cohort-control">
    data tier
    <select aria-label="data tier" value={value} onChange={e => onChange(e.target.value)}>
      <option value="pilot_real_proxy">Real proxy and unknown evidence</option>
      <option value="synthetic_fixture">Synthetic fixture · not market data · not qualification</option>
      <option value="unknown">Unknown data tier only</option>
    </select>
  </label>
}

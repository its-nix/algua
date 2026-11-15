/** Demo `/api/inbox` payload: made-up items (no real sources or owner data), shaped like
 * `research inbox list`, timed against the fixture's FETCHED_AT and covering every journey
 * tone the CLI emits (pending, progressed, refuted, neutral). */
import type { ApiEnvelope, InboxItem, InboxPayload } from '../types'
import { envelope } from './steady-state'

const item = (over: Partial<InboxItem> & Pick<InboxItem, 'id' | 'created_at' | 'kind'>): InboxItem => ({
  url: null, title: null, note: null, file_path: null, text: null,
  status: 'taken', taken_at: null, inspiration_id: null, journey: [], ...over,
})

export const INBOX: ApiEnvelope<InboxPayload> = envelope({
  ok: true,
  items: [
    item({
      id: 6, created_at: '2026-08-27T09:14:40+00:00', kind: 'link', status: 'queued',
      url: 'https://www.youtube.com/watch?v=demo-small-caps',
      title: 'Why small caps rebound after index deletions',
      journey: [{ label: 'Queued for the next leap', tone: 'pending' }],
    }),
    item({
      id: 5, created_at: '2026-08-27T06:10:00+00:00', kind: 'link', taken_at: '2026-08-27T06:30:00+00:00',
      url: 'https://x.com/demo_quant/status/1000000000000000005', inspiration_id: 'insp-demo-5',
      title: 'Thread on overnight vs intraday momentum',
      journey: [{ label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #34', tone: 'pending' }],
    }),
    item({
      id: 4, created_at: '2026-08-25T08:40:00+00:00', kind: 'file', taken_at: '2026-08-25T10:30:00+00:00',
      file_path: '/srv/algua/inbox/demo4/betting-against-beta-revisited.pdf', inspiration_id: 'insp-demo-4',
      title: 'Betting against beta, revisited.pdf',
      journey: [{ label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #31', tone: 'neutral' },
        { label: 'Candidate', tone: 'progressed' }],
    }),
    item({
      id: 3, created_at: '2026-08-23T07:05:00+00:00', kind: 'link', taken_at: '2026-08-23T08:30:00+00:00',
      url: 'https://quantpedia.com/strategies/turn-of-the-month-in-small-caps', inspiration_id: 'insp-demo-3',
      title: 'Quantpedia: turn of the month in small caps',
      journey: [{ label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #27', tone: 'neutral' },
        { label: 'Refuted: no edge after costs', tone: 'refuted' }],
    }),
    item({
      id: 2, created_at: '2026-08-19T18:20:00+00:00', kind: 'file', taken_at: '2026-08-19T20:30:00+00:00',
      file_path: '/srv/algua/inbox/demo2/earnings-drift-in-illiquid-names.pdf', inspiration_id: 'insp-demo-2',
      title: 'Earnings drift in illiquid names.pdf',
      journey: [{ label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #45', tone: 'neutral' },
        { label: 'Duplicate of idea #19', tone: 'neutral' }],
    }),
    item({
      id: 1, created_at: '2026-08-12T12:00:00+00:00', kind: 'text', taken_at: '2026-08-12T14:30:00+00:00',
      text: 'Does the pre-FOMC drift survive in sector ETFs after 2015?', inspiration_id: 'insp-demo-1',
      journey: [{ label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #22', tone: 'neutral' },
        { label: 'Backtested', tone: 'neutral' }],
    }),
  ],
})

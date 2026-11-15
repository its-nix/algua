/** Pure view helpers for one Inbox row. */
import type { InboxIconName } from '../components/InboxIcons'
import type { InboxItem } from '../types'

function parseUrl(url: string | null): URL | null {
  if (!url) return null
  try {
    return new URL(url)
  } catch {
    return null
  }
}

const host = (u: URL) => u.hostname.replace(/^www\./, '').replace(/^m\./, '')

const basename = (path: string | null) => (path ? path.split('/').at(-1) ?? path : '')

const isPdf = (item: InboxItem) =>
  /\.pdf$/i.test(item.title ?? '') || /\.pdf$/i.test(item.file_path ?? '')

/** Title, else the URL's host + path, else the file's name or the text's first line. */
export function itemTitle(item: InboxItem): string {
  if (item.title?.trim()) return item.title.trim()
  const u = parseUrl(item.url)
  if (u) return host(u) + u.pathname.replace(/\/$/, '')
  if (item.kind === 'file') return basename(item.file_path) || 'File'
  return item.text?.trim().split('\n')[0] || item.url || 'Untitled'
}

/** Where it came from: the link's domain, "Paper" for a PDF, "File" or "Note". */
export function itemSource(item: InboxItem): string {
  const u = parseUrl(item.url)
  if (u) return host(u)
  if (item.kind === 'file') return isPdf(item) ? 'Paper' : 'File'
  return 'Note'
}

export function itemTile(item: InboxItem): InboxIconName {
  const u = parseUrl(item.url)
  const h = u ? host(u) : ''
  if (h === 'youtube.com' || h.endsWith('.youtube.com') || h === 'youtu.be') return 'video'
  if (h === 'x.com' || h === 'twitter.com') return 'chat'
  if (item.kind === 'file') return 'document'
  if (item.kind === 'text') return 'chat'
  return 'link'
}

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'} ago`

/** "just now", "3 hours ago", "2 days ago", "last week" ... measured from `nowIso` (the
 * envelope's fetched_at, so a demo build reads the same as its fixtures). */
export function relativeTime(iso: string, nowIso: string): string {
  const then = Date.parse(iso)
  const now = Date.parse(nowIso)
  if (Number.isNaN(then) || Number.isNaN(now)) return ''
  const s = Math.max(0, (now - then) / 1000)
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return plural(m, 'minute')
  const h = Math.floor(m / 60)
  if (h < 24) return plural(h, 'hour')
  const d = Math.floor(h / 24)
  if (d === 1) return 'yesterday'
  if (d < 7) return plural(d, 'day')
  if (d < 14) return 'last week'
  if (d < 60) return plural(Math.floor(d / 7), 'week')
  if (d < 365) return plural(Math.floor(d / 30), 'month')
  return plural(Math.floor(d / 365), 'year')
}

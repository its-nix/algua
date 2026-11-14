import { useEffect } from 'react'
import { useFetch } from './api'
import type { ApiEnvelope } from './types'

/** One `research inbox list` item, as far as the tab badge needs it. */
export interface InboxBadgeItem {
  id: number
  status: string
  journey: { label: string; tone: string }[]
}

export interface InboxListPayload {
  ok?: boolean
  items: InboxBadgeItem[]
}

const KEY = 'algua.inbox.seen'

const signature = (item: InboxBadgeItem) => `${item.status}|${item.journey.at(-1)?.label ?? ''}`

/** Per-viewer "last seen" journeys. Browser storage can be absent or throw (private mode,
 * previews); the badge then simply stays at 0. */
export function readSeen(): Record<string, string> | null {
  try {
    const raw = window.localStorage.getItem(KEY)
    return raw === null ? null : (JSON.parse(raw) as Record<string, string>)
  } catch {
    return null
  }
}

export function markSeen(items: InboxBadgeItem[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(items.map((i) => [i.id, signature(i)]))))
  } catch {
    // storage unavailable: the badge just never counts
  }
}

/** Items whose journey moved since the Inbox was last viewed. A never-seen item counts once it
 * has left the queue (the owner already knows about the items they just added). With no record
 * at all (first visit) nothing counts. */
export function unreadCount(items: InboxBadgeItem[], seen: Record<string, string> | null): number {
  if (seen === null) return 0
  return items.filter((i) => {
    const before = seen[String(i.id)]
    return before === undefined ? i.status !== 'queued' : before !== signature(i)
  }).length
}

export function useInboxBadge(onInbox: boolean): number {
  const { data } = useFetch<ApiEnvelope<InboxListPayload>>('/api/inbox', { ttlMs: 60_000 })
  const items = data?.data.items
  useEffect(() => {
    if (onInbox && items !== undefined) markSeen(items)
  }, [onInbox, items])
  if (onInbox || items === undefined) return 0
  return unreadCount(items, readSeen())
}

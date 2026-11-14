/** The Inbox composer's send: POST /api/inbox (JSON for a link or text, multipart for a file).
 * Lives beside push.ts at the src root because `./transport` is the specifier the production
 * build aliases to its fixture-free stub (vite.config.ts); `../transport` would pull the real
 * module, and with it the fixtures, into the production graph. */
import { ApiError } from './api'
import { DEMO } from './transport'

/** The backend's per-upload limit (web/backend/inbox.py); checked here first so a too-large
 * file fails before it is uploaded. */
export const MAX_FILE_BYTES = 20 * 1024 * 1024

export type InboxSend = { url: string } | { text: string } | { file: File; note?: string }

/** A whole-field http(s) link is sent as a link; anything else as text. */
export function sendFor(value: string): InboxSend | null {
  const v = value.trim()
  if (!v) return null
  return /^https?:\/\/\S+$/i.test(v) ? { url: v } : { text: v }
}

export interface InboxAddResult {
  ok: boolean
  duplicate?: boolean
}

/** POST /api/inbox: JSON for a link or text, multipart for a file. Throws ApiError. */
export async function addToInbox(send: InboxSend): Promise<InboxAddResult> {
  if (DEMO) throw new ApiError(0, 'demo', 'This demo build has no backend, so nothing was sent')
  let init: RequestInit
  if ('file' in send) {
    if (send.file.size > MAX_FILE_BYTES) throw new ApiError(413, 'too_large', 'over 20 MB')
    const form = new FormData()
    form.append('file', send.file)
    if (send.note?.trim()) form.append('note', send.note.trim())
    init = { method: 'POST', body: form, headers: { accept: 'application/json' } }
  } else {
    init = {
      method: 'POST',
      body: JSON.stringify(send),
      headers: { 'content-type': 'application/json', accept: 'application/json' },
    }
  }
  let res: Response
  try {
    res = await fetch('/api/inbox', init)
  } catch {
    throw new ApiError(0, 'network', 'the server could not be reached')
  }
  type Body = { code?: unknown; error?: unknown; duplicate?: unknown } | null
  const body: Body = await res.json().then((b: unknown) => b as Body, () => null)
  if (!res.ok) {
    const code = typeof body?.code === 'string' ? body.code : null
    const message = typeof body?.error === 'string' && body.error ? body.error : `HTTP ${res.status}`
    throw new ApiError(res.status, code, message)
  }
  return { ok: true, duplicate: body?.duplicate === true }
}

/** What the owner reads when a send fails. */
export function sendErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403 || e.code === 'forbidden') return 'Only the owner can add to the Inbox'
    if (e.status === 413 || e.code === 'too_large') return 'That file is over 20 MB'
    if (e.code === 'demo') return 'This demo build has no backend, so nothing was sent'
    if (e.code === 'network') return 'Could not reach Algua. Check the connection and try again'
    if (e.status === 422) return `Not added: ${e.message}`
    return 'Could not add it right now. Try again in a moment'
  }
  return 'Could not add it right now. Try again in a moment'
}

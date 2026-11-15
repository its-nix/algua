import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useFetch } from '../api'
import { useSetFetchedAt } from '../App'
import InboxIcon from '../components/InboxIcons'
import { markSeen } from '../inboxBadge'
import type { ApiEnvelope, InboxItem, InboxPayload } from '../types'
import { addToInbox, sendErrorMessage, sendFor, type InboxSend } from '../inboxSend'
import { itemSource, itemTile, itemTitle, relativeTime } from './inboxItem'
import './inbox.css'

const TOAST_MS = 3000
const ACCEPT = 'application/pdf,text/*,image/*'

/** The share sheet only offers an installed PWA as a target on Android. */
const isAndroid = () => typeof navigator !== 'undefined' && /android/i.test(navigator.userAgent)

function InboxRow({ item, now }: { item: InboxItem; now: string }) {
  const when = relativeTime(item.created_at, now)
  return (
    <li className="inbox-item">
      <span className="inbox-src" data-src={itemTile(item)}><InboxIcon name={itemTile(item)} /></span>
      <div className="inbox-body">
        <div className="inbox-title">{itemTitle(item)}</div>
        <div className="inbox-meta">{when ? `${itemSource(item)} · ${when}` : itemSource(item)}</div>
        <div className="inbox-journey">
          {item.journey.map((step, i) => (
            <span key={`${i}-${step.label}`} className="inbox-tag" data-tone={step.tone}>{step.label}</span>
          ))}
        </div>
      </div>
    </li>
  )
}

export default function Inbox() {
  const { data, error, loading, refetch } = useFetch<ApiEnvelope<InboxPayload>>('/api/inbox', { ttlMs: 0 })
  const setFetchedAt = useSetFetchedAt()
  const [params, setParams] = useSearchParams()
  const [value, setValue] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  // `n` restarts the timer when the same message is shown twice in a row.
  const [toast, setToastState] = useState<{ text: string; n: number } | null>(null)
  const showToast = (text: string) => setToastState((t) => ({ text, n: (t?.n ?? 0) + 1 }))
  const fileInput = useRef<HTMLInputElement>(null)
  const field = useRef<HTMLInputElement>(null)
  const items = data?.data.items

  useEffect(() => { setFetchedAt(data?.fetched_at ?? null) }, [data?.fetched_at, setFetchedAt])

  // Viewing the Inbox marks every item seen, so the tab badge only counts later moves.
  useEffect(() => { if (items !== undefined) markSeen(items) }, [items])

  // Back from the Android share sheet (`/share` redirects to /inbox?shared=1). The flag is
  // consumed so a reload does not toast again.
  useEffect(() => {
    if (params.get('shared') !== '1') return
    setToastState((t) => ({ text: 'Added to Inbox', n: (t?.n ?? 0) + 1 }))
    const next = new URLSearchParams(params)
    next.delete('shared')
    setParams(next, { replace: true })
  }, [params, setParams])

  useEffect(() => {
    if (toast === null) return
    const t = window.setTimeout(() => setToastState(null), TOAST_MS)
    return () => window.clearTimeout(t)
  }, [toast])

  const pickFile = (f: File | null | undefined) => {
    if (!f) return
    setFile(f)
    setSendError(null)
  }

  const clearFile = () => {
    setFile(null)
    if (fileInput.current) fileInput.current.value = ''
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (sending) return
    const send: InboxSend | null = file ? { file, note: value } : sendFor(value)
    if (send === null) {
      field.current?.focus()
      return
    }
    setSending(true)
    setSendError(null)
    try {
      const result = await addToInbox(send)
      setValue('')
      clearFile()
      showToast(result.duplicate ? 'Already in your Inbox' : 'Added to Inbox')
      refetch()
    } catch (err) {
      setSendError(sendErrorMessage(err))
    } finally {
      setSending(false)
    }
  }

  const onDrop = (e: DragEvent) => {
    if (!e.dataTransfer.types.includes('Files')) return
    e.preventDefault()
    pickFile(e.dataTransfer.files[0])
  }

  return (
    <div className="inbox" onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() }}
      onDrop={onDrop}>
      <h1 className="inbox-heading">Inbox</h1>
      <p className="inbox-sub">Everything you send feeds the next leap run.</p>

      {items === undefined ? (
        error !== null && !loading
          ? <p className="inbox-empty" role="alert">Could not load the Inbox. Pull to refresh or try again later.</p>
          : <div className="inbox-card skeleton-block inbox-skeleton" data-state="loading" aria-label="Loading" />
      ) : items.length === 0 ? (
        <p className="inbox-empty">Nothing here yet. Paste a link below{isAndroid() ? ' or share one from any app' : ''}.</p>
      ) : (
        <ul className="inbox-card inbox-list">
          {items.map((item) => <InboxRow key={item.id} item={item} now={data?.fetched_at ?? new Date().toISOString()} />)}
        </ul>
      )}

      {isAndroid() && (
        <div className="inbox-card inbox-tip">
          <span className="inbox-src inbox-src-accent"><InboxIcon name="share" /></span>
          <div>
            <div className="inbox-title">Share straight from any app</div>
            <div className="inbox-meta">In X, YouTube or Files, tap Share, then Algua.</div>
          </div>
        </div>
      )}

      <div className="inbox-dock">
        {toast !== null && <div key={toast.n} className="inbox-toast" role="status">{toast.text}</div>}
        {sendError !== null && <div className="inbox-error" role="alert">{sendError}</div>}
        <form className="inbox-composer" onSubmit={(e) => void submit(e)}>
          <label className="inbox-iconbtn" title="Attach a file">
            <InboxIcon name="paperclip" size={20} />
            <input ref={fileInput} type="file" accept={ACCEPT} aria-label="Attach a file"
              className="sr-only" onChange={(e) => pickFile(e.target.files?.[0])} />
          </label>
          {file !== null && (
            <span className="inbox-file">
              <span className="inbox-file-name">{file.name}</span>
              <button type="button" className="inbox-file-x" aria-label={`Remove ${file.name}`} onClick={clearFile}>×</button>
            </span>
          )}
          <input ref={field} className="inbox-field" type="text" enterKeyHint="send" autoComplete="off"
            aria-label={file ? 'Add a note' : 'Paste a link or drop a file'}
            placeholder={file ? 'Add a note' : 'Paste a link or drop a file'}
            value={value} onChange={(e) => { setValue(e.target.value); setSendError(null) }} />
          <button type="submit" className="inbox-send" aria-label="Send" disabled={sending}>
            <span><InboxIcon name="send" size={20} /></span>
          </button>
        </form>
      </div>
    </div>
  )
}

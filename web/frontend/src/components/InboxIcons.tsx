/** Lucide geometry (play, message-square-text, file-text, link-2, paperclip, arrow-up, share)
 * inlined like NavigationIcon, so the app takes no icon dependency. */
export type InboxIconName = 'video' | 'chat' | 'document' | 'link' | 'paperclip' | 'send' | 'share'

const PATHS: Record<InboxIconName, string[]> = {
  video: ['M6 3 20 12 6 21Z'],
  chat: ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z', 'M13 8H7', 'M17 12H7'],
  document: ['M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z', 'M14 2v4a2 2 0 0 0 2 2h4',
    'M10 9H8', 'M16 13H8', 'M16 17H8'],
  link: ['M9 17H7A5 5 0 0 1 7 7h2', 'M15 7h2a5 5 0 1 1 0 10h-2', 'M8 12h8'],
  paperclip: ['m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48'],
  send: ['m5 12 7-7 7 7', 'M12 19V5'],
  share: ['M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8', 'm16 6-4-4-4 4', 'M12 2v13'],
}

const STROKE: Partial<Record<InboxIconName, number>> = { send: 2.6, share: 2.2 }

export default function InboxIcon({ name, size = 18 }: { name: InboxIconName; size?: number }) {
  const filled = name === 'video'
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" focusable="false"
      fill={filled ? 'currentColor' : 'none'} stroke={filled ? 'none' : 'currentColor'}
      strokeWidth={STROKE[name] ?? 2} strokeLinecap="round" strokeLinejoin="round">
      {PATHS[name].map((d) => <path key={d} d={d} />)}
    </svg>
  )
}

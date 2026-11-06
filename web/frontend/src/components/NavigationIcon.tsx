type IconName = 'dashboard' | 'research' | 'fleet' | 'portfolio' | 'system'

const paths: Record<IconName, string> = {
  dashboard: 'M4 14h4v6H4z M10 9h4v11h-4z M16 4h4v16h-4z',
  research: 'M9 3h6 M10 3v7l-5 8a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-8V3 M8 15h8',
  fleet: 'M3 4h7v7H3z M14 4h7v7h-7z M3 15h7v6H3z M14 15h7v6h-7z',
  portfolio: 'M4 8h16v12H4z M9 8V4h6v4 M4 12h16 M10 12v3h4v-3',
  system: 'M2 12h5l3-7 4 14 3-7h5',
}

export default function NavigationIcon({ name }: { name: IconName }) {
  return <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
    stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>
}

/** Small stroke icons for Home (lucide-style geometry, drawn inline so the app takes no icon
 * dependency). Decorative: always aria-hidden. */
type Name = 'alert' | 'chevron-right' | 'chevron-down' | 'chevron-left' | 'check' | 'x'

const PATHS: Record<Name, string> = {
  alert: 'm21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3 M12 9v4 M12 17h.01',
  'chevron-right': 'm9 18 6-6-6-6',
  'chevron-down': 'm6 9 6 6 6-6',
  'chevron-left': 'm15 18-6-6 6-6',
  check: 'M20 6 9 17l-5-5',
  x: 'M18 6 6 18 M6 6l12 12',
}

export default function HomeIcon({ name, size = 18, className }: { name: Name; size?: number; className?: string }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
    strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={className}
    aria-hidden="true" focusable="false"><path d={PATHS[name]} /></svg>
}

import wordmark from '../assets/wordmark.png'
import inverse from '../assets/wordmark-reversed.png'

/** Supplied Drive wave artwork, exported without redrawing the logo. */
export default function Logo() {
  return <picture className="brand-lockup">
    <source media="(prefers-color-scheme: dark)" srcSet={inverse} />
    <img src={wordmark} width="120" height="48" alt="Algua" />
  </picture>
}

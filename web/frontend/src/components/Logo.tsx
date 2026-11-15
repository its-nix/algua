import inverse from '../assets/wordmark-reversed.png'

/** Supplied Drive wave artwork, exported without redrawing the logo. The app is black-only, so
 * the reversed (light-on-dark) lockup is the only one ever shown. */
export default function Logo() {
  return <picture className="brand-lockup">
    <img src={inverse} width="120" height="48" alt="Algua" />
  </picture>
}

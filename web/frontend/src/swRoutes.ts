/** Paths the service worker's navigation fallback must leave to the network. Workbox matches
 * pathname+search, so each rule also stops at ? and #.
 *
 * - /api and /healthz: a monitor must never answer them from the precached shell.
 * - /share: the Android share target. The navigation route is registered for GET only, so the
 *   share sheet's POST already reaches the backend; denying /share too means a stray GET to it
 *   is never answered with the app shell either. */
export const NAV_DENYLIST: RegExp[] = [
  /^\/api(?:[/?#]|$)/,
  /^\/healthz(?:[?#]|$)/,
  /^\/share(?:[/?#]|$)/,
]

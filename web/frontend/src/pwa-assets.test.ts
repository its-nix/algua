import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// The manifest in vite.config.ts references these by absolute URL; they must
// exist in public/ or installs get broken icons.
describe('pwa assets', () => {
  it.each([
    'icon-192.png',
    'icon-512.png',
    'icon-maskable-512.png',
    'apple-touch-icon.png',
    'favicon.svg',
  ])('public/%s exists', (name) => {
    // vitest runs with cwd = web/frontend (where vite.config.ts lives).
    expect(existsSync(join(process.cwd(), 'public', name))).toBe(true)
  })
})

describe('pwa manifest', () => {
  it('manifest declares share_target POST /share multipart', async () => {
    const { manifest } = await import('./pwaManifest')
    expect(manifest.share_target).toEqual({
      action: '/share',
      method: 'POST',
      enctype: 'multipart/form-data',
      params: {
        title: 'title',
        text: 'text',
        url: 'url',
        files: [{ name: 'files', accept: ['application/pdf', 'text/*', 'image/*'] }],
      },
    })
  })

  it('the service worker navigation fallback never takes /share', async () => {
    const { NAV_DENYLIST } = await import('./swRoutes')
    for (const path of ['/share', '/share?x=1', '/api/inbox', '/healthz', '/oauth2', '/oauth2/start?rd=%2F', '/oauth2/callback?code=x']) {
      expect(NAV_DENYLIST.some((re) => re.test(path))).toBe(true)
    }
    for (const path of ['/inbox', '/inbox?shared=1', '/shared-things', '/']) {
      expect(NAV_DENYLIST.some((re) => re.test(path))).toBe(false)
    }
  })
})

import type { ManifestOptions } from 'vite-plugin-pwa'

/** The web app manifest (vite.config.ts hands it to VitePWA). Its own module so a test can read
 * it without loading the whole Vite config. */
export const manifest: Partial<ManifestOptions> & Pick<ManifestOptions, 'share_target'> = {
  name: 'Algua',
  short_name: 'Algua',
  description: 'Research and portfolio dashboard',
  display: 'standalone',
  start_url: '/',
  scope: '/',
  theme_color: '#000000',
  background_color: '#000000',
  icons: [
    { src: '/icon-192.png?v=20261106-wave', sizes: '192x192', type: 'image/png' },
    { src: '/icon-512.png?v=20261106-wave', sizes: '512x512', type: 'image/png' },
    {
      src: '/icon-maskable-512.png?v=20261106-wave',
      sizes: '512x512',
      type: 'image/png',
      purpose: 'maskable',
    },
  ],
  // Android: Share -> Algua posts the shared link, text or files to the backend's /share, which
  // adds them to the Inbox and redirects to /inbox?shared=1. iOS Safari ignores this member.
  share_target: {
    action: '/share',
    method: 'POST',
    enctype: 'multipart/form-data',
    params: {
      title: 'title',
      text: 'text',
      url: 'url',
      files: [{ name: 'files', accept: ['application/pdf', 'text/*', 'image/*'] }],
    },
  },
}

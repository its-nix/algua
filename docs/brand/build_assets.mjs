/** Export the supplied Drive artwork without tracing or redrawing it.
 * Run from the repo root after installing web/frontend dependencies:
 * node docs/brand/build_assets.mjs
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { chromium } from '../../web/frontend/node_modules/playwright/index.mjs'

const root = fileURLToPath(new URL('.', import.meta.url))
const publicDir = fileURLToPath(new URL('../../web/frontend/public/', import.meta.url))
const exportsDir = join(root, 'exports')
const assetsDir = fileURLToPath(new URL('../../web/frontend/src/assets/', import.meta.url))
mkdirSync(assetsDir, { recursive: true })
mkdirSync(exportsDir, { recursive: true })
const image = name => 'data:image/png;base64,' + readFileSync(join(root, 'sources', name)).toString('base64')
const wordmark = image('algua-wordmark-black-transparent.png')
const mark = image('algua-logo-mark-black-transparent.png')
// The supplied white wordmark has holes in its alpha channel. This presentation
// filter uses the intact black artwork: neutral ink becomes white, blue stays blue,
// and geometry/alpha stay unchanged. No AI redraw or substituted wordmark.
const inverse = '<defs><filter id="inverse" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="1 0 -1 0 1 0 1 -1 0 1 0 0 0 0 1 0 0 0 1 0"/></filter></defs>'
const art = (src, width, height, dark) => `${dark ? inverse : ''}<image width="${width}" height="${height}" href="${src}"${dark ? ' filter="url(#inverse)"' : ''}/>`
const svg = (viewBox, title, body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" role="img"><title>${title}</title>${body}</svg>\n`
const lockup = dark => svg('260 50 1650 660', 'Algua', art(wordmark, 2172, 724, dark))
const logoMark = dark => svg('210 210 840 840', 'Algua wave mark', art(mark, 1254, 1254, dark))
const nested = (source, box, x, y, width, height, dark) => `<svg x="${x}" y="${y}" width="${width}" height="${height}" viewBox="${box}">${art(source, source === wordmark ? 2172 : 1254, source === wordmark ? 724 : 1254, dark)}</svg>`
const tile = (size, inset = .16, rounded = true) => svg(`0 0 ${size} ${size}`, 'Algua app icon',
  `<rect width="${size}" height="${size}" rx="${rounded ? size * .2 : 0}" fill="#0B0B0D"/>` +
  nested(mark, '210 210 840 840', size * inset, size * inset, size * (1 - 2 * inset), size * (1 - 2 * inset), true))
const banner = dark => svg('0 0 1600 480', 'Algua',
  `<rect width="1600" height="480" rx="28" fill="${dark ? '#0B0B0D' : '#EAF4FB'}"/>` +
  nested(wordmark, '260 50 1650 660', 375, 70, 850, 340, dark))

for (const [name, body] of Object.entries({
  'logo-horizontal': lockup(false), 'logo-horizontal-reversed': lockup(true),
  'logo-mark': logoMark(false), 'logo-mark-reversed': logoMark(true),
  'favicon': tile(512), 'social-avatar': tile(1024),
  'readme-banner': banner(false), 'readme-banner-dark': banner(true),
})) writeFileSync(join(root, name + '.svg'), body)

const browser = await chromium.launch({ channel: 'chrome' })
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 })
  const render = async (source, width, height, target, transparent = true) => {
    await page.setViewportSize({ width, height })
    await page.setContent(`<html><style>*{margin:0}html,body{width:100%;height:100%;background:transparent}body>svg{display:block;width:100%;height:100%}</style>${source}</html>`)
    await page.waitForFunction(() => [...document.querySelectorAll('image')].every(el => el.href.baseVal.startsWith('data:')))
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await page.screenshot({ path: target, omitBackground: transparent })
  }
  for (const dark of [false, true]) {
    const suffix = dark ? '-reversed' : ''
    await render(lockup(dark), 480, 192, join(exportsDir, `logo-horizontal${suffix}.png`))
    await render(lockup(dark), 480, 192, join(assetsDir, `wordmark${suffix}.png`))
    await render(logoMark(dark), 1024, 1024, join(exportsDir, `logo-mark${suffix}-1024.png`))
    await render(banner(dark), 1600, 480, join(exportsDir, `readme-banner${dark ? '-dark' : ''}.png`))
  }
  for (const [name, size, inset, rounded] of [
    ['icon-192.png', 192, .16, false], ['icon-512.png', 512, .16, false],
    ['icon-maskable-512.png', 512, .22, false], ['apple-touch-icon.png', 180, .16, false],
  ]) await render(tile(size, inset, rounded), size, size, join(publicDir, name), false)
  await render(tile(512), 512, 512, join(exportsDir, 'favicon-512.png'))
  await render(tile(1024), 1024, 1024, join(exportsDir, 'social-avatar.png'))
  const favicon = readFileSync(join(exportsDir, 'favicon-512.png')).toString('base64')
  writeFileSync(join(publicDir, 'favicon.svg'), svg('0 0 512 512', 'Algua', `<image width="512" height="512" href="data:image/png;base64,${favicon}"/>`))
  console.log('Exported current Drive wave branding for dashboard, repository, and app icons.')
} finally { await browser.close() }

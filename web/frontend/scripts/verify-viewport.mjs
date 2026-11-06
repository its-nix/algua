/** Spec §5.1 — the /money bug was a 483px 5-column table sizing its scroll parent instead of
 * scrolling inside it, so the PAGE grew to 500px at a 390px viewport. This turns that class of
 * defect into a test: no route may overflow horizontally at 390px.
 *
 * Serves the DEMO build, so every route has rich data — an empty screen cannot overflow and
 * would make this check vacuous. THAT CLAIM IS ITSELF ASSERTED BELOW (FIX 6, 2026-08-27 fix
 * wave): before measuring overflow on a route, this checks one known fixture string actually
 * landed in the page. Without it, an unfixtured endpoint (demoJSON throws -> the screen renders
 * its error panel, which is narrow and never overflows) would pass this whole script silently —
 * exactly the "new screen's overflow never measured" failure the header comment already warned
 * about but nothing enforced. Mirrors the same idea as the word-budget test's "actually renders
 * fixture data" block. */
import { createServer } from 'node:http'
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { extname, join, normalize } from 'node:path'
import { chromium } from 'playwright'
import assert from 'node:assert/strict'

// Optional local production-build acceptance using tests/_gate_comparison_fixture.py.
// ALGUA_VIEWPORT_BASE_URL=http://127.0.0.1:18796 ALGUA_VIEWPORT_SCREENSHOT_DIR=/owned/path
// npm run verify:viewport. No fixture generation, API interception, or qualification occurs here.
const externalBase = process.env.ALGUA_VIEWPORT_BASE_URL
if (externalBase !== undefined) {
  const url = new URL(externalBase)
  assert(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    && !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash,
  'external acceptance requires a plain localhost HTTP origin')
  const output = process.env.ALGUA_VIEWPORT_SCREENSHOT_DIR
  assert(output, 'external acceptance requires ALGUA_VIEWPORT_SCREENSHOT_DIR')
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ channel: 'chrome' })
  const page = await browser.newPage()
  try {
    page.setDefaultTimeout(45_000)
    page.setDefaultNavigationTimeout(90_000)
    const fixtures = ['high52_proximity', 'path_efficiency_quality_momentum']
    const rows = page.getByTestId('board-row')
    const layout = async (name, width) => {
      await page.locator('[data-state="loading"]:visible, .skeleton-block:visible').first()
        .waitFor({ state: 'hidden' })
      await page.evaluate(() => {
        window.scrollTo(0, 0)
        return new Promise(resolve => requestAnimationFrame(resolve))
      })
      const state = await page.evaluate(() => ({
        width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth,
        bottomBars: [...document.querySelectorAll('.bottom-nav')].filter(el => {
          const r = el.getBoundingClientRect()
          return getComputedStyle(el).position === 'fixed' && r.width > innerWidth * .6
            && r.top > innerHeight / 2 && r.bottom <= innerHeight && r.bottom >= innerHeight - 24
        }).length,
      }))
      assert.equal(state.width, width)
      assert(state.scrollWidth <= width, `${name}: horizontal overflow ${JSON.stringify(state)}`)
      assert.equal(state.bottomBars, 1, `${name}: bottom navigation missing`)
      assert.equal(await page.locator('.bottom-nav a').count(), 3)
      assert.equal(await page.locator('.bottom-nav svg').count(), 3)
      await page.screenshot({ path: join(output, `${name}-${width}.png`), fullPage: true })
      console.log(`ok ${name} ${JSON.stringify(state)}`)
    }
    for (const width of [390, 1440, 360]) {
      await page.setViewportSize({ width, height: 900 })
      await page.goto(url.origin, { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: 'Leaderboard', exact: true }).waitFor()
      await page.getByRole('button', { name: 'Gate OOS', exact: true }).click()
      await page.getByText(/Synthetic fixture evidence is hidden/).waitFor()
      assert.equal(await rows.count(), 0, 'fixture evidence must be hidden by default')
      await page.getByRole('button', { name: /board controls/ }).click()
      await page.getByRole('combobox', { name: 'data tier', exact: true }).selectOption('synthetic_fixture')
      for (const [i, name] of fixtures.entries()) {
        const row = page.locator(`[data-strategy="${name}"]`)
        await row.waitFor()
        assert.equal(await row.getAttribute('href'), `/strategy/${i + 1}`)
        assert.equal((await row.locator('.stage-chip').innerText()).toLowerCase(), 'backtested')
        assert.equal((await row.locator('.board-tags .pass-mark').innerText()).toLowerCase(), 'fail')
        const entry = row.locator('..')
        await entry.locator('.board-evidence-disclosure > summary').click()
        assert.match(await entry.innerText(), /synthetic_not_market_data/)
        assert.match(await entry.innerText(), /Research cohort/)
        assert.match(await entry.innerText(), /not payload or PIT proof/)
      }
      assert.equal(await rows.count(), 2)
      const order = page.getByRole('button', { name: 'oos sharpe', exact: true })
      assert.equal(await order.isEnabled(), false, 'sorting requires explicit cohort')
      const cohort = page.getByRole('combobox', { name: 'comparison cohort', exact: true })
      assert.equal(await cohort.locator('option').count(), 2, 'exactly one two-strategy cohort')
      const lifecycle = await rows.evaluateAll(els => els.map(el => el.getAttribute('href')))
      await cohort.selectOption(await cohort.locator('option').nth(1).getAttribute('value'))
      await order.click()
      assert.equal(await order.getAttribute('aria-pressed'), 'true')
      const values = await rows.locator('.board-metric:first-child').allTextContents()
      const sharpe = values.map(text => Number(text.replace('sharpe', '').trim()))
      assert(sharpe.length === 2 && sharpe.every(Number.isFinite) && sharpe[0] >= sharpe[1])
      console.log(`ok cohort sort ${JSON.stringify({ lifecycle,
        observed: await rows.evaluateAll(els => els.map(el => el.getAttribute('href'))) })}`)
      await page.getByRole('group', { name: 'strategy stage', exact: true })
        .getByRole('button', { name: /backtested/ }).click()
      const family = page.getByRole('group', { name: 'strategy family', exact: true })
      // This gate fixture has family lineage, but no legacy registry display-family labels.
      const unknownFamily = family.getByRole('button', { name: /unknown family/ })
      await unknownFamily.click()
      assert.equal(await unknownFamily.getAttribute('aria-pressed'), 'true')
      assert.equal(await rows.count(), 2)
      await family.getByRole('button', { name: /all families/ }).click()
      assert.equal(await rows.count(), 2)
      await layout('board', width)
      if (width === 360) continue
      const link = rows.first()
      const target = await link.getAttribute('href')
      const name = await link.getAttribute('data-strategy')
      await link.focus()
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('href')), target)
      await page.keyboard.press('Enter')
      await page.waitForURL(url.origin + target)
      await page.getByRole('heading', { name, exact: true }).waitFor()
      await page.getByRole('region', { name: 'recorded gate comparison', exact: true }).waitFor()
      await layout('detail', width)
      await page.getByRole('link', { name: 'Research', exact: true }).click()
      const retained = page.locator('#retained-experiments')
      await retained.getByText('No retained archive references recorded.', { exact: true }).waitFor()
      await retained.getByText('Unverified research', { exact: true }).click()
      assert.match(await retained.innerText(), /UNVERIFIED_WORKER · authority: none · cycle-only association/)
      await layout('research', width)
      console.log(`ok native Enter ${target}; retained index empty; distinct-family exclusion and populated archive not exercised`)
    }
  } catch (error) {
    await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {})
    throw error
  } finally {
    await browser.close()
  }
  console.log('ok: local production-build synthetic acceptance; no deployed production or qualification claim')
  process.exit(0)
}

const ROUTES = ['/', '/now', '/fleet', '/money', '/research', '/strategy/1', '/s/liquid10_adj_momentum']

// One string per route that only appears if the real fixture data rendered — picked from
// src/fixtures/steady-state.ts (kept as literals here rather than imported: this script runs
// as plain Node against the BUILT demo bundle, not through the TS/Vitest module graph).
const ROUTE_CONTENT = {
  '/': 'liquid10_adj_momentum', // BOARD.data.rows[0], proving the leaderboard rendered
  '/now': 'cross_horizon_low_vol', // TRIAGE.items[0].title after the worst-first sort
  '/fleet': 'liquid10_adj_momentum', // a real "every strategy" row (FLEET.data.rows)
  '/money': 'liquid10_adj_momentum', // BOOK.data.slices[0].strategy
  '/research': 'Turn-of-month seasonal drift, liquid10', // Actual default idea-pool fixture.
  '/strategy/1': 'Cross-sectional momentum over the liquid10 universe', // ID resolver -> detail
  '/s/liquid10_adj_momentum': 'Cross-sectional momentum over the liquid10 universe', // registry.description
}
const DIR = 'dist-demo'
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
                '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
                '.woff2': 'font/woff2', '.woff': 'font/woff', '.webmanifest': 'application/manifest+json' }

const server = createServer((req, res) => {
  const url = req.url.split('?')[0]
  const candidate = join(DIR, normalize(url).replace(/^(\.\.[/\\])+/, ''))
  const file = existsSync(candidate) && extname(candidate) ? candidate : join(DIR, 'index.html')
  res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' })
  res.end(readFileSync(file))
})

await new Promise((r) => server.listen(0, '127.0.0.1', r))
const base = `http://127.0.0.1:${server.address().port}`

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
const failures = []

const cases = [
  ...ROUTES.map((route) => ({ route, width: 390 })),
  { route: '/', width: 860 },
  { route: '/', width: 1440 },
]
for (const { route, width } of cases) {
  await page.setViewportSize({ width, height: 900 })
  await page.goto(base + route, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)

  const expected = ROUTE_CONTENT[route]
  const bodyText = await page.evaluate(() => document.body.innerText)
  if (expected === undefined || !bodyText.includes(expected)) {
    failures.push(
      `${route}: expected fixture text "${expected}" not found in the rendered page — the ` +
        'route likely errored/emptied instead of rendering real data, which would make the ' +
        'overflow check below vacuous',
    )
    console.log(`FAIL ${route} missing expected content "${expected}"`)
    continue
  }

  if (route === '/') {
    // Public is the default mode. Its demo has no ordinary WF records; do not manufacture
    // gate-backed public windows to satisfy the separate gate-ledger checks below.
    await page.getByText('In-sample research · not independent OOS', { exact: true }).waitFor()
    const publicWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    if (publicWidth > width) failures.push(`${route} public WF: scrollWidth=${publicWidth} vw=${width}`)
    console.log(`ok   / public WF vw=${width} scrollWidth=${publicWidth}`)
    await page.getByRole('button', { name: 'Gate OOS', exact: true }).click()
    await page.getByText(/latest gate run each/).waitFor()
    await page.waitForLoadState('networkidle')
    // Synthetic demo evidence is deliberately hidden until its tier is explicitly selected.
    await page.getByRole('button', { name: /board controls/i }).click()
    await page.getByRole('combobox', { name: 'data tier', exact: true }).selectOption('synthetic_fixture')
    // The redesigned rows disclose complete methodology beside their native navigation link.
    // Open every disclosure before retaining the existing visible-warning/limitation checks.
    for (const summary of await page.locator('.board-evidence-disclosure > summary').all()) {
      await summary.click()
    }
  }

  const m = await page.evaluate((currentRoute) => {
    const vw = window.innerWidth
    // An element clipped by an ancestor's own horizontal scrollport (overflow-x: auto/scroll/
    // hidden) is the INTENDED "scrolls inside its own container" pattern, not page overflow —
    // its bounding rect can legitimately extend past the viewport without the PAGE growing.
    // Walking the ancestor chain (not just the immediate parent) catches a clip several levels up.
    function clippedByScrollAncestor(el) {
      for (let node = el.parentElement; node && node !== document.documentElement; node = node.parentElement) {
        const ox = getComputedStyle(node).overflowX
        if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return true
      }
      return false
    }
    const offenders = []
    document.querySelectorAll('*').forEach((el) => {
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.right > vw + 1 && !clippedByScrollAncestor(el)) {
        offenders.push(`${el.tagName}.${String(el.className).slice(0, 40)} right=${Math.round(r.right)}`)
      }
    })
    const shortTargets = [...document.querySelectorAll('.bottom-link, .back-btn')]
      .map((el) => ({ name: el.className, height: el.getBoundingClientRect().height }))
      .filter(({ height }) => height < 44)
    const ideaDates = currentRoute === '/research'
      ? [...document.querySelectorAll('.idea-date')].map((el) => ({
          text: el.textContent,
          display: getComputedStyle(el).display,
          height: el.getBoundingClientRect().height,
        }))
      : []
    const evidence = currentRoute === '/'
      ? [...document.querySelectorAll('.board-evidence')].map((block) => ({
          trustVisible: [...block.querySelectorAll('.board-evidence-trust')].some((el) => {
            const style = getComputedStyle(el)
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              el.getBoundingClientRect().height > 0 && el.textContent.includes('not payload or PIT proof')
          }),
          limitations: [...block.querySelectorAll('.board-evidence-limitations li')].map((el) => {
            const style = getComputedStyle(el)
            return {
              text: el.textContent.trim(),
              visible: style.display !== 'none' && style.visibility !== 'hidden' &&
                el.getBoundingClientRect().height > 0,
              hiddenInTitle: el.hasAttribute('title'),
            }
          }),
        }))
      : []
    return {
      vw,
      scrollWidth: document.documentElement.scrollWidth,
      offenders: offenders.slice(0, 5),
      shortTargets,
      ideaDates,
      evidence,
    }
  }, route)
  // scrollWidth is the authoritative signal for "did the PAGE overflow" (the actual /money
  // symptom: the viewport itself widens/zooms out). offenders names the culprit when it does.
  const overflow = m.scrollWidth > m.vw
  console.log(`${overflow ? 'FAIL' : 'ok  '} ${route} vw=${m.vw} scrollWidth=${m.scrollWidth}`)
  if (overflow) failures.push(`${route}: scrollWidth=${m.scrollWidth} vw=${m.vw}\n    ${m.offenders.join('\n    ')}`)
  if (m.shortTargets.length > 0) {
    failures.push(`${route}: interactive targets below 44px: ${JSON.stringify(m.shortTargets)}`)
  }
  if (route === '/research' && (
    m.ideaDates.length === 0
    || m.ideaDates.some(({ display, height }) => display === 'none' || height === 0)
  )) {
    failures.push(`${route}: idea created_at is not visibly reachable at 390px`)
  }
  if (route === '/') {
    const expectedLimitations = [
      'synthetic_not_market_data',
    ]
    if (m.evidence.length === 0) {
      failures.push(`${route} at ${width}px: no evidence ledger rendered`)
    }
    for (const [index, block] of m.evidence.entries()) {
      if (!block.trustVisible) {
        failures.push(`${route} at ${width}px: evidence ${index} lacks visible metadata-only warning`)
      }
      const visible = block.limitations.filter((item) => item.visible).map((item) => item.text)
      if (JSON.stringify(visible) !== JSON.stringify(expectedLimitations)) {
        failures.push(
          `${route} at ${width}px: evidence ${index} limitations are missing/hidden/order-drifted: ` +
            JSON.stringify(visible),
        )
      }
      if (block.limitations.some((item) => item.hiddenInTitle)) {
        failures.push(`${route} at ${width}px: evidence ${index} hides a limitation in title`)
      }
    }
  }
}

// Native row links are the preserved keyboard seam: focus one, activate it with Enter, and
// require the stable-ID resolver route rather than a name-derived path.
await page.setViewportSize({ width: 390, height: 844 })
await page.goto(base + '/', { waitUntil: 'networkidle' })
const firstStrategyLink = page.locator('[data-testid="board-row"]').first()
await firstStrategyLink.focus()
const keyboardTarget = await page.evaluate(() => document.activeElement?.getAttribute('href'))
if (!/^\/strategy\/\d+$/.test(keyboardTarget ?? '')) {
  failures.push(`/: first strategy row did not receive stable-ID keyboard focus: ${keyboardTarget}`)
} else {
  await page.keyboard.press('Enter')
  await page.waitForURL(new RegExp(`${keyboardTarget.replace('/', '\\/')}$`))
  console.log(`ok   / keyboard Enter -> ${new URL(page.url()).pathname}`)
}

await browser.close()
server.close()

if (failures.length) {
  console.error(`\nHorizontal overflow:\n  ${failures.join('\n  ')}`)
  process.exit(1)
}
console.log(`\nok: ${cases.length} route/viewport cases, no horizontal overflow (390/860/1440px)`)

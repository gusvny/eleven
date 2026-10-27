/**
 * browser-t261028-18-chart-render.test.mjs — the two Metrics charts in a REAL
 * browser against the plugin's own harness (L3 scenario; isolated kernel port,
 * never 3099/7233).
 *
 * Host report 261028: 'the Metrics tab shows Throughput and Where the tokens go
 * as "charts could not load"'. This leg is the coverage that did not exist: no
 * test loaded the panel page in a browser and asserted that a chart drew.
 *
 * What it locks (all user-visible; no internals are read):
 *   1. the host's own flow — open the page, come back to the Metrics tab LATER
 *      than the 4s load budget, and both charts still draw. Today's defect was
 *      the page-load armed guard: it fired on an empty queue four seconds after
 *      load and latched, so this tab never asked for the module at all;
 *   2. one transient module failure is survivable — the empty state names the
 *      route, and the next draw retries and draws both charts;
 *   3. a served-but-throwing module names the module class (not the route one),
 *      so a reader can tell a supply problem from a code problem.
 *
 * The metrics endpoints are stubbed per request (the chart payloads only): this
 * leg is about the chart bridge, not the metrics API.
 */
import { createRequire } from 'node:module'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { assert, done, freshDir, cleanup } from './lib.mjs'
import { startPluginHarness, PANEL_ROUTE } from '../harness.mjs'

const require = createRequire(import.meta.url)
function findPlaywrightCore() {
  let dir = import.meta.dirname
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  throw new Error('playwright-core not found: expected server/ui-check/node_modules in this checkout or a sibling of the lane root')
}
const playwright = require(findPlaywrightCore())
async function launchBrowser() {
  try { return await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
  catch { return await playwright.chromium.launch({ headless: true }) }
}

// The two chart faces the tab reads (view=health / view=token), in the shape
// the workbench metrics endpoint serves: charts.primary {categories, series}.
const HEALTH = { charts: { primary: { categories: ['2026-10-20', '2026-10-21'], series: [{ name: 'opened', data: [3, 5] }, { name: 'closed', data: [2, 4] }] } } }
const TOKEN = { charts: { primary: { title: 'tokens per stage', categories: ['plan', 'implement'], series: [{ name: 'in', data: [10, 20] }, { name: 'out', data: [5, 7] }] } } }
const EMPTY_PHRASE = 'charts could not load'
const VENDOR = PANEL_ROUTE + '/vendor/echarts.mjs'

let n = 0
const pan = freshDir('ep-chart-')
const H = await startPluginHarness({ panelDir: pan })
const browser = await launchBrowser()

/** One page in the host's position: metrics endpoints stubbed, optional vendor
 *  route handler, then the Metrics tab opened. Returns the page plus a log. */
async function openMetrics(vendorRoute) {
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  page.setDefaultTimeout(20000)
  const log = { vendor: [] }
  page.on('response', (r) => { if (r.url().includes('/vendor/')) log.vendor.push(r.request().method() + ' ' + r.status() + ' ' + (r.headers()['content-type'] || '')) })
  await page.route('**/sandbar-workbench/api/wf/metrics**', (route) => {
    const u = route.request().url()
    const body = u.endsWith('view=health') ? HEALTH : u.endsWith('view=token') ? TOKEN : { ok: true }
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  if (vendorRoute) await page.route('**/vendor/echarts.mjs', vendorRoute)
  await page.goto(H.base + PANEL_ROUTE + '/?project=sandbar')
  return { page, ctx, log }
}

/** What the reader sees in the two chart cards. */
async function chartFaces(page) {
  return page.evaluate(() => {
    const face = (id) => {
      const e = document.getElementById(id)
      if (!e) return { text: '(no element)', canvas: false, w: 0, h: 0 }
      const c = e.querySelector('canvas')
      return { text: e.textContent.trim(), canvas: !!c, w: c ? c.width : 0, h: c ? c.height : 0 }
    }
    return { throughput: face('mtThroughput'), tokens: face('mtTokens') }
  })
}
const drew = (f) => f.canvas && f.w > 100 && f.h > 100 && !f.text.includes(EMPTY_PHRASE)

try {
  // ---- 1. the host's flow: Metrics opened LATER than the 4s load budget ----
  {
    const { page, ctx, log } = await openMetrics()
    // The host loads the console, then clicks Metrics after reading something
    // else. 5s > the 4s one-attempt budget: with the page-load guard this tab
    // was already dead and never asked for the module.
    await page.waitForTimeout(5000)
    await page.click('label[for=t-metrics]')
    await page.waitForFunction(() => !!document.querySelector('#mtThroughput canvas') && !!document.querySelector('#mtTokens canvas'))
    const f = await chartFaces(page)
    assert(drew(f.throughput), 'Throughput draws a chart when the tab is opened 5s after page load (the host\'s flow)')
    assert(drew(f.tokens), 'Where the tokens go draws a chart when the tab is opened 5s after page load')
    const gets = log.vendor.filter((l) => l.startsWith('GET '))
    assert(gets.length === 1 && gets[0].includes(' 200 ') && gets[0].includes('text/javascript'),
      'the page asked the vendor route once and got 200 text/javascript (the module is reachable, no latch)')
    await ctx.close()
    n += 3
  }

  // ---- 2. one transient failure is survivable: named cause, then retry ----
  {
    // Fail the import AND the route probe (the two requests one attempt makes),
    // then let the route serve: a transient window, the shape of a console
    // restart or a dropped connection.
    let failLeft = 2
    const { page, ctx, log } = await openMetrics((route) => {
      if (failLeft > 0) { failLeft -= 1; return route.abort() }
      return route.continue()
    })
    await page.click('label[for=t-metrics]')
    await page.waitForFunction((phrase) => document.getElementById('mtThroughput').textContent.includes(phrase),
      EMPTY_PHRASE)
    const failed = await chartFaces(page)
    assert(failed.throughput.text.includes('could not be reached'),
      'a failed load names the route class in the empty state (not just "charts could not load")')
    assert(!failed.throughput.canvas && !failed.tokens.canvas, 'no chart is claimed while the library is missing')
    // The later draw: the tab re-renders on a window change (any later draw does).
    await page.selectOption('#metricsWindow', '7d')
    await page.waitForFunction(() => !!document.querySelector('#mtThroughput canvas') && !!document.querySelector('#mtTokens canvas'))
    const recovered = await chartFaces(page)
    assert(drew(recovered.throughput) && drew(recovered.tokens),
      'the next draw retries the load and both charts draw (one transient failure no longer kills the tab)')
    assert(log.vendor.filter((l) => l.startsWith('GET 200')).length >= 1,
      'the retry really re-fetched the module over the vendor route')
    await ctx.close()
    n += 5
  }

  // ---- 3. a served-but-throwing module names the module class ----
  {
    const { page, ctx } = await openMetrics((route) => {
      if (route.request().method() === 'HEAD') return route.fulfill({ status: 200, contentType: 'text/javascript', body: '' })
      return route.fulfill({ status: 200, contentType: 'text/javascript', body: 'throw new Error("vendor build is broken")' })
    })
    await page.click('label[for=t-metrics]')
    await page.waitForFunction((phrase) => document.getElementById('mtThroughput').textContent.includes(phrase),
      EMPTY_PHRASE)
    const f = await chartFaces(page)
    assert(f.throughput.text.includes('failed to run'),
      'a module that runs and throws names the module class (a code problem, not a supply one)')
    assert(!f.throughput.text.includes('could not be reached'),
      'the module class is not confused with the route class')
    await ctx.close()
    n += 2
  }
} finally {
  await browser.close()
  await H.close()
  cleanup([pan])
}

done(n)

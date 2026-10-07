// capture_panel_height.mjs — t261008-05 acceptance evidence (one-shot, NOT a
// registered scenario; pattern per t261004-19/capture_open_epics_states.mjs).
// Boots an isolated bench console (lib_fix17: own free port, temp DSH_HOME,
// fixture registry; the host 3099 console is never touched), clicks the
// fixture project row in the sidebar, then measures the middle-column height
// chain and screenshots the column. Usage:
//   node integration/t261008-05/capture_panel_height.mjs <before|after>
import { mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const TAG = process.argv[2] === 'after' ? 'after' : 'before'
const REPO = resolve(import.meta.dirname, '../..')
const OUT = join(REPO, '.sandbar', 'screenshots')
mkdirSync(OUT, { recursive: true })

const fix = await import(pathToFileURL(join(REPO, 'integration/t260904-17/lib_fix17.mjs')))
const { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, loadPlaywright, gotoConsole, dismissNotice } = fix

let bench = null
try {
  const projectsRoot = makeRegistryRoot(`t261008-05-${TAG}-`)
  writeProjectEntry(projectsRoot, 'fixture-alpha', 'fixture-alpha', ['/tmp/fx-alpha'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] bench console unavailable: ${String(e).slice(0, 200)}`)
  process.exit(2)
}

const playwright = await loadPlaywright()
if (!playwright) { console.log('[ENV_FAIL] playwright-core not found'); process.exit(2) }
let browser
try {
  browser = await playwright.chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.setDefaultTimeout(20000)
  await gotoConsole(page, bench, { waitUntil: 'domcontentloaded' })
  await dismissNotice(page)
  await page.getByText('fixture-alpha', { exact: true }).first().click({ timeout: 15000, force: true })
  await page.waitForSelector('[data-wb-executor-frame]', { timeout: 15000 })
  await page.waitForTimeout(600)
  const m = await page.evaluate(() => {
    const h = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const r = el.getBoundingClientRect()
      const cs = getComputedStyle(el)
      return { rect: Math.round(r.height), flex: cs.flex, minHeight: cs.minHeight, height: cs.height }
    }
    return {
      rightContent: h('.wb-right-content'),
      root: h('.wb-right-content > .wb-root'),
      view: h('.wb-executor-view'),
      frame: h('.wb-executor-frame'),
      frameOverflowBottom: (() => {
        const f = document.querySelector('.wb-executor-frame')
        return f ? Math.round(f.getBoundingClientRect().bottom - window.innerHeight) : null
      })(),
    }
  })
  console.log(`[${TAG}] measurements: ` + JSON.stringify(m))
  const col = page.locator('.wb-right-content')
  await col.screenshot({ path: join(OUT, `t261008-05-${TAG}-middle-column.png`) })
  console.log(`[${TAG}] screenshot -> .sandbar/screenshots/t261008-05-${TAG}-middle-column.png`)
} finally {
  await browser?.close().catch(() => {})
  bench?.teardown()
}

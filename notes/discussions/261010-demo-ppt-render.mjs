/**
 * Render the demo deck and check its layout.
 *
 * Run:  node notes/discussions/261010-demo-ppt-render.mjs
 * Out:  notes/discussions/261010-demo-ppt.pdf  (one page per slide, notes included)
 *
 * The deck itself is one self-contained HTML file. Open it in a browser to present it.
 * Keys: arrow keys move between slides, N shows the speaker notes, F toggles fullscreen,
 * and a URL fragment like #12 jumps straight to a slide.
 *
 * playwright-core is resolved from server/ui-check/node_modules (the UI evidence tool
 * already installs it). This script does not touch the console on port 3099.
 */
import { createRequire } from 'module'

const require = createRequire(new URL('../../server/ui-check/', import.meta.url))
const { chromium } = require('playwright-core')

const here = new URL('.', import.meta.url)
const deck = new URL('261010-demo-ppt.html', here).href
const pdf = new URL('261010-demo-ppt.pdf', here).pathname

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
await page.goto(deck)
await page.waitForTimeout(400)

// Any slide whose content is taller than the viewport would be cut off on screen.
const overflow = await page.evaluate(() =>
  [...document.querySelectorAll('.slide')].flatMap((slide, index) => {
    slide.classList.add('active')
    const over = slide.scrollHeight - slide.clientHeight
    slide.classList.remove('active')
    return over > 4 ? [[index + 1, over]] : []
  }),
)
console.log('slides:', await page.evaluate(() => document.querySelectorAll('.slide').length))
console.log('overflow:', JSON.stringify(overflow))

await page.pdf({
  path: pdf,
  width: '1600px',
  height: '900px',
  printBackground: true,
  margin: { top: '0', right: '0', bottom: '0', left: '0' },
})
await browser.close()
console.log('written:', pdf)

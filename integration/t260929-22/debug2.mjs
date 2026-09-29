import { ensureStageConsole } from '../lib_stage_console.mjs';
const BASE = (await ensureStageConsole()).base
const { pathToFileURL } = await import('node:url')
const pw = await import(pathToFileURL(process.env.PWCORE).href)
let b
for (const o of [{channel:'chrome',headless:true},{headless:true}]) { try { b = await pw.chromium.launch(o); break } catch {} }
const page = await b.newPage()
page.on('console', m => { if (m.type()==='error') console.log('CERR:', m.text().slice(0,120)) })
await page.route('**/*', (route) => route.fallback())
await page.route('**/sandbar-workbench/api/wf/projects', (route) => route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,result:{projects:[{key:'entryproj',name:'Entry Project',dirs:[]}],quarantined:[]}})}))
await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,result:{tickets:[]}})}))
await page.route('**/sandbar-executor-panel/**', (route) => route.fulfill({contentType:'text/html',body:'<html><body>PANELSTUB:entryproj</body></html>'}))
await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 })
for (let i=0;i<5;i++){ const d=page.locator('[role="dialog"]').first(); if(!(await d.count()))break; const bt=d.locator('button:enabled').first(); if(await bt.count()) await bt.click({timeout:3000}).catch(()=>{}); else await page.keyboard.press('Escape').catch(()=>{}); await page.waitForTimeout(600) }
await page.waitForTimeout(5000)
await page.locator('.wb-group-head').first().click({ position:{x:40,y:9}, force:true })
await page.waitForTimeout(2500)
console.log('open?', await page.evaluate(() => !!document.querySelector('[data-wb-executor-view]')))
const chatSeg = page.locator('[data-wb-chat-seg]').first()
console.log('chatSeg count', await chatSeg.count(), 'visible', await chatSeg.isVisible().catch(()=>'?'))
await chatSeg.click({ timeout: 5000 }).catch(e => console.log('click err', String(e).slice(0,100)))
await page.waitForTimeout(1500)
console.log('after chat click', JSON.stringify(await page.evaluate(() => ({
  on: document.querySelector('[data-wb-chat-seg]')?.getAttribute('data-on'),
  exSegOn: document.querySelector('[data-wb-executor-seg]')?.getAttribute('data-on'),
  iframes: document.querySelectorAll('[data-wb-executor-frame]').length,
  chatPane: !!document.querySelector('[data-wb-chat-pane]'),
}))))
await b.close()

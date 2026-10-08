#!/usr/bin/env node
// sc_t26100823_changes_english_dedup.mjs —— Changes/Changeset 去重 + 空态英文
// （t261008-23 缺陷 ③）。
//
// intent（灰盒 L3，browser-free 池，真浏览器 + page-boundary API 打桩，零 docker，
// 红线零接触 3099）：变更面两处各司其职不重叠——紧凑 Changes 面只给事实（文件行/
// 状态/大小/合计），全文 diff 只活在列尾唯一可折叠块；「Changeset」字样不再是第二个
// 摘要位；空态文案全英文且点名缺的前置（base_ref vs write_set，不许含糊单因）；
// 永不伪造 diff（无据可证的 base=诚实空态）。
// intent 分界：diff 内容正确性/review 动作归既有 diff 面条目；本条独占去重面、
// 空态语言与精确性面。
// KI 对齐：KI-051（锚语义）；宿主令 260925（控制台界面文案英文）。实现未落地段红
// 属预期（TDD 信号）。
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  TID, fixtureTimeline, fixtureTicketDetail, routeDetail,
  loadPlaywright, launchBrowser, bootFixture, recorder, waitFor, dismissIntroModal,
} from './lib_fix23.mjs'

const REPO = process.cwd()
const { record, rec, summarize } = recorder()
let bench = null, stub = null
// 夹具 A：无据可证 base（worktree 缺 + 缺 write_set）→ 必须诚实英文空态，点名缺因。
const detail = fixtureTicketDetail(fixtureTimeline())
delete detail.write_set
delete detail.base_ref
try {
  const b = await bootFixture(REPO, 't26100823-changes')
  bench = b.bench; stub = b.stub
  // the real host's diff face reads the ticket through the stub's show op —
  // fix17's default is mode:'fail' (injected error, Chinese copy) which the
  // user would see verbatim; register the fixture ticket and allow show.
  const ctrl = JSON.parse(readFileSync(stub.ctrlPath, 'utf8'))
  ctrl.tickets = [detail]
  ctrl.show = { [TID]: { mode: 'ok' } }
  stub.setCtrl(ctrl)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

const pw = await loadPlaywright(REPO)
const browser = pw ? await launchBrowser(pw) : null
if (!browser) {
  console.log('[ENV_FAIL] playwright-core/chromium unavailable (KI-036 family)')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  try { await bench.teardown() } catch { /* down */ }
  process.exit(2)
}

const ctx = await browser.newContext()
const pageErrors = []
const page = await ctx.newPage()
page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
let diffAsked = 0
// The diff face is NOT stubbed: the empty-state copy under test is computed by
// the real host (changes.ts) and passed through verbatim by the client, so the
// assertion must read the real host's answer on this fixture (no lane
// worktree, base_ref set, write_set set -> honest "base ref invalid" family).
await routeDetail(page, detail, {
  passThrough: (path) => path === `/sandbar-workbench/api/wf/tickets/${TID}/diff`,
})
await bench.goto(page, { waitUntil: 'networkidle' })
await dismissIntroModal(page)
await page.waitForTimeout(2000)

const opened = await waitFor(async () => {
  const row = await page.$(`[data-ticket-id="${TID}"]`)
  if (!row) return false
  await row.click()
  await page.waitForTimeout(1500)
  return !!(await page.$('[data-testid="detail-columns"]'))
}, 10000)
if (!opened) {
  record('S1 precheck', 'env_fail', `detail drawer never opened for ${TID}`)
  await browser.close(); await bench.teardown()
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2)
}
record('S1 precheck', 'pass', 'detail drawer open')

// The full diff lives in the one collapsible fold at the end of the column
// (LazyFold: mounted only once opened) — open it, then assert on the whole
// drawer text (fixture-gap: the fold and its empty state sit outside
// [data-testid="detail-columns"]).
const foldBtn = await page.$('[data-testid="fold-changes"], button')
const openFold = await waitFor(async () => {
  const btns = await page.$$('[data-testid="fold-changes"]')
  const btn = btns[0]
  if (!btn) return false
  await btn.click().catch(() => {})
  await page.waitForTimeout(1200)
  diffAsked += 1
  // mounted content check: the fold's region should now carry diff-face words
  const txt = await page.evaluate(() => document.body.textContent || '')
  return /full diff|Diff|changes/i.test(txt)
}, 8000)
record('S2 fold present', openFold ? 'pass' : 'fail', openFold ? 'fold-changes control found' : 'Changes fold control never rendered')

const FACE = `(() => {
  // innerText: user-perceived text only — CSS <style> bodies carry Chinese
  // comments (design tokens) that textContent would misread as UI copy.
  const text = document.body.innerText || ''
  const changesetWord = /Changeset/.test(text)
  const cjk = /[\\u4e00-\\u9fff]/.test(text)
  // count fold CONTAINERS (details) and standalone buttons; a <summary> inside
  // its <details> is the same fold, not a second one.
  const folds = [...document.body.querySelectorAll('details,summary,button,[role="button"]')]
    .filter(el => /full diff|diff and review/i.test(el.textContent || ''))
    .filter(el => el.tagName !== 'SUMMARY')
  return { changesetWord, cjk, hasDiffFold: folds.length > 0,
    foldCount: folds.length,
    emptyish: /no change record|base ref invalid|no git change/i.test(text) }
})()`

let face = null
await waitFor(async () => {
  // lib waitFor returns only true, never the cond value — capture via outer
  // variable (fixture gap: face was always true).
  const v = await page.evaluate(FACE)
  if (v && (v.hasDiffFold || v.emptyish || v.cjk)) { face = v; return true }
  return false
}, 10000)
if (!face) {
  record('S3 changes face', 'fail', 'changes face never rendered any fold or empty state')
  await browser.close(); await bench.teardown(); summarize()
}

// T1 去重：'Changeset' 字样退场（不再有第二个摘要位）。
rec('T1 the word Changeset no longer names a second summary block', !face.changesetWord,
  `changesetWord=${face.changesetWord}`)

// T2 全文 diff 只有一个折叠位（列尾唯一）。
rec('T2 exactly one full-diff fold at the end of the column', face.hasDiffFold && face.foldCount === 1,
  `hasDiffFold=${face.hasDiffFold} diffFolds=${face.foldCount}`)

// T3 空态全英文：夹具后端即使回中文，用户可见文案也不得出现 CJK（前端映射为英文）。
rec('T3 changes-face empty state is English (no CJK reaches the user)', !face.cjk,
  `cjk=${face.cjk}${face.cjk ? ' body=' + (await page.evaluate(FACE)).body || '' : ''}`)

// T4 空态精确：点名缺的前置/失败原因（base_ref / write_set / base ref invalid
// 其一说清），不许含糊或空白。
const EMPTY = `(() => {
  const t = document.body.innerText || ''
  const i = t.search(/no change record|base ref invalid/i)
  return i < 0 ? '' : t.slice(i, i + 220).trim()
})()`
const emptyMsg = await page.evaluate(EMPTY)
rec('T4 empty state names the missing precondition (precise, not a vague single cause)',
  /base_ref|write_set|base ref invalid|base ref/i.test(emptyMsg),
  JSON.stringify(emptyMsg))

// T5 不伪造：无可证 base → 不出现编造的文件行（夹具票无 worktree、base 不可证，
// 面内不得有冒充的 diff 文件行）。
const fabricated = await page.evaluate(`(() => {
  const t = document.body.textContent || ''
  return /lane-map\\.tsx/.test(t) && /files?\\s*[:：]/i.test(t)
})()`)
rec('T5 never fabricates a diff (honest empty state, no invented file rows)', !fabricated,
  `fabricated=${fabricated}`)

rec('T6 no pageerror on the changes face', pageErrors.length === 0, pageErrors.join(' | ').slice(0, 200))

await browser.close()
try { await bench.teardown() } catch { /* down */ }
summarize()

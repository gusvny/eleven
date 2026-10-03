// sc_panel_expand_survives_poll —— t261003-14 集成场景①：展开态跨轮询存续（灰盒 L3，
// 真 harness + 真 Chromium 全隔离，端口 0 零碰 3099/7233）。
//
// Intent（用户可感知契约，工单验收口径）：宿主在「Needs your answer」点开的条目，
// 经过任意多个 5s 刷新周期后**仍然展开**，直到宿主自己点收起；已答（Answered）区的
// 条目同理；宿主正在读的长 detail 的滚动位置跨刷新保持；修复不得以停掉刷新为代价
// ——新投递的请求仍在一个周期内出现在面板上（刷新活性反向锚）。
//
// high-level steps：真 API 投递请求 → 打开面板 → 点开展开 → 等真实轮询周期 →
// 断言展开态/收起态/滚动位置仍在 → 中途再投一条断言徽标增长（活性）→ 应答一条
// 展开中的请求断言行迁移无页错。
//
// 执行契约（t260904-12 三态）：SUMMARY 行收尾；FAIL>0 或全 na → exit 1；env_fail → exit 2。

import { openPanel, record, summarize, envFail, waitRow, waitRowEl, doneRowEl, doneHead, LONG_DETAIL } from './lib_panel_state.mjs'

const KEY = 't26100314a'
const results = []

let C
try {
  C = await openPanel({
    KEY,
    seed: [
      { kind: 'sign', question: 'Option request for expand persistence?', detail: 'Has buttons.', options: ['Approve', 'Reject'] },
      { kind: 'question', question: 'Free-text request for expand persistence?', detail: 'Has an input box.' },
      { kind: 'question', question: 'Long detail to read while it refreshes?', detail: LONG_DETAIL },
    ],
  })
} catch (e) {
  if (e.envMissing) envFail(results, e.message)
  console.error('FAIL boot —', e?.message || e)
  results.push({ name: 'boot', status: 'fail', detail: String(e) })
  summarize(results)
}
const { page, post, waitPoll, close, pageErrors } = C

function row(page, sel) { return page.locator(sel) }
async function isOpen(sel) { return (await row(page, sel).getAttribute('data-open')) === 'true' }

try {
  // 取 fixture id（真投递面回执）。
  const list = await fetch(`${C.H.base}/sandbar-executor-panel/api/requests?project=${KEY}`).then((r) => r.json())
  const byQ = (q) => list.rows.find((r) => r.question === q)
  const opt = byQ('Option request for expand persistence?')
  const free = byQ('Free-text request for expand persistence?')
  const long = byQ('Long detail to read while it refreshes?')
  if (!opt || !free || !long) throw new Error('fixture rows missing from ledger read-back')

  // A1 无选项行点开 → 跨**两个**轮询周期仍展开（「arbitrary number of poll cycles」主面）。
  await page.click(waitRow(free.id))
  if (!(await isOpen(waitRowEl(free.id)))) record(results, 'A1 expand takes effect', 'fail', 'data-open != true after click')
  else {
    await waitPoll(); await waitPoll()
    record(results, 'A1 expand survives two polls', (await isOpen(waitRowEl(free.id))) ? 'pass' : 'fail',
      (await isOpen(waitRowEl(free.id))) ? '' : 'row re-collapsed by a poll cycle')
  }

  // A2 宿主收起 → 跨一个轮询周期仍收起（收起也是宿主意志，不得被渲染翻回）。
  await page.click(waitRow(free.id))
  await waitPoll()
  record(results, 'A2 collapse survives a poll', !(await isOpen(waitRowEl(free.id))) ? 'pass' : 'fail',
    (await isOpen(waitRowEl(free.id))) ? 'collapsed row popped back open' : '')

  // A3 选项行同样跨周期保持展开。
  await page.click(waitRow(opt.id))
  await waitPoll()
  record(results, 'A3 options row stays expanded across a poll', (await isOpen(waitRowEl(opt.id))) ? 'pass' : 'fail')

  // A4 长 detail 读到一半滚下去 → 跨周期滚动位置保持（宿主正在读的面）。
  await page.click(waitRow(long.id))
  await page.waitForSelector(waitRowEl(long.id) + ' .detail')
  await page.evaluate((sel) => { document.querySelector(sel + ' .detail').scrollTop = 120 }, waitRowEl(long.id))
  await waitPoll()
  const st = await page.evaluate((sel) => document.querySelector(sel + ' .detail')?.scrollTop ?? -1, waitRowEl(long.id))
  record(results, 'A4 detail scroll position survives a poll', st === 120 ? 'pass' : 'fail', 'scrollTop after poll = ' + st)

  // A5 刷新活性反向锚：面板开着时新投递的请求在一个周期内出现、徽标增长
  // （修复不得靠停刷新/冻结渲染达成——那会让 A1-A4 假绿）。
  const before = Number(await page.textContent('#reqBadge'))
  const nr = await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'question', question: 'Late request delivered while the host reads?', detail: 'Liveness probe.' })
  if (nr.status !== 200) record(results, 'A5 refresh stays live', 'fail', 'seed POST rejected: ' + JSON.stringify(nr.json))
  else {
    await waitPoll()
    const grew = await page.waitForFunction((b) => Number(document.getElementById('reqBadge').textContent) === b + 1, before, { timeout: 8000, polling: 250 }).then(() => true, () => false)
    record(results, 'A5 refresh stays live (new request appears within a poll)', grew ? 'pass' : 'fail',
      grew ? '' : `badge stayed ${before}; render is frozen or polling stopped`)
  }

  // A6 展开中的行被（外部）应答 → 行迁移到 Answered，无页错、无僵尸展开态。
  await post('/sandbar-executor-panel/api/requests/answer', { project: KEY, id: free.id, answer: 'Answered while expanded', by: 'host' })
  await waitPoll()
  const moved = (await row(page, waitRowEl(free.id)).count()) === 0 && (await row(page, doneRowEl(free.id)).count()) === 1
  record(results, 'A6 answered-while-expanded row migrates cleanly', moved ? 'pass' : 'fail',
    moved ? '' : 'waiting row did not migrate to Answered')

  // A7 已答行展开 + 跨周期保持（工单点名：wipe 同样打在 answered 行上）。
  // Answered 折叠区默认整区收起（doneWrap data-open=false），宿主先点区头展开区，再点行。
  await page.click('#doneHeadBtn')
  await page.click(doneHead(free.id))
  await waitPoll()
  record(results, 'A7 answered row stays expanded across a poll', (await isOpen(doneRowEl(free.id))) ? 'pass' : 'fail')

  // 页错零发生（整旅程，含每次刷新边界）。
  record(results, 'A8 zero page errors across all poll boundaries', pageErrors.length === 0 ? 'pass' : 'fail',
    pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  record(results, 'scenario body', 'fail', String(e?.message || e))
} finally {
  await close()
}
summarize(results)

// sc_panel_draft_survives_poll —— t261003-14 集成场景②：草稿与「Type an answer」揭示态
// 跨轮询存续（灰盒 L3，真 harness + 真 Chromium 全隔离，端口 0 零碰 3099/7233）。
//
// Intent（用户可感知契约，工单验收口径）：宿主在展开条目里打到一半的回答，跨 5s 刷新
// 周期**不丢**；收起再展开后仍在；只有宿主显式发送（或显式清空）才消失——绝不静默丢失；
// 选项行的「Type an answer」揭示态与其中草稿同理跨周期存续；发送成功后台面照常迁移
// 到 Answered 且答案可见（草稿销毁有因）。畸形/空值输入不炸、不静默吞。
//
// high-level steps：真 API 投递请求 → 打开面板 → 展开 → 打字 → 等真实轮询周期 →
// 断言输入值仍在 → 收起/再展开断言仍在 → 空值点 Send 断言不吞 → 发送断言迁移 +
// 草稿面关闭 → 揭示框跨周期断言 → 畸形 options 行展开零页错。
//
// 执行契约（t260904-12 三态）：SUMMARY 行收尾；FAIL>0 或全 na → exit 1；env_fail → exit 2。

import { openPanel, record, summarize, envFail, waitRow, waitRowEl, doneRowEl, LONG_DETAIL } from './lib_panel_state.mjs'

const KEY = 't26100314b'
const results = []

let C
try {
  C = await openPanel({
    KEY,
    seed: [
      { kind: 'question', question: 'Free-text draft persistence probe?', detail: 'Type here.' },
      { kind: 'sign', question: 'Reveal-the-input probe (options row)?', detail: 'Click Type an answer first.', options: ['Approve', 'Reject'] },
      // API 投递面对空数组/空白项已 fail-closed 拒收（实测 400 点名）；边界内畸形面：
      // 重复项 options + 缺 detail + 非词表 kind，必须渲染、可展开、零页错。
      { kind: 'weird-kind', question: 'Odd-shape but accepted probe?', options: ['Approve', 'Approve'] },
    ],
  })
} catch (e) {
  if (e.envMissing) envFail(results, e.message)
  console.error('FAIL boot —', e?.message || e)
  results.push({ name: 'boot', status: 'fail', detail: String(e) })
  summarize(results)
}
const { page, post, waitPoll, close, pageErrors } = C

async function inputValue(sel) { return page.locator(sel).inputValue() }
const boxSel = (id) => waitRowEl(id) + ' input[data-answerbox]'
const revealedSel = (id) => waitRowEl(id) + ' .opts ~ .answer input, ' + waitRowEl(id) + ' div.answer input'

try {
  const list = await fetch(`${C.H.base}/sandbar-executor-panel/api/requests?project=${KEY}`).then((r) => r.json())
  const byQ = (q) => list.rows.find((r) => r.question === q)
  const free = byQ('Free-text draft persistence probe?')
  const opt = byQ('Reveal-the-input probe (options row)?')
  const mal = byQ('Odd-shape but accepted probe?')
  if (!free || !opt || !mal) throw new Error('fixture rows missing from ledger read-back')

  // B1 打到一半的回答跨轮询周期保留（主面：5 秒窗口内文字消失=本票病灶）。
  await page.click(waitRow(free.id))
  const DRAFT = 'half-typed answer that must survive the 5s refresh '
  await page.fill(boxSel(free.id), DRAFT)
  await waitPoll()
  const v1 = await inputValue(boxSel(free.id))
  record(results, 'B1 half-typed draft survives a poll', v1 === DRAFT ? 'pass' : 'fail', 'input held: "' + v1 + '"')

  // B2 收起再展开（+再一个周期）草稿仍在（工单口径：survives a poll and a later collapse）。
  await page.click(waitRow(free.id)) // collapse
  await page.click(waitRow(free.id)) // re-expand
  await waitPoll()
  const v2 = await inputValue(boxSel(free.id))
  record(results, 'B2 draft survives collapse + re-expand + a poll', v2 === DRAFT ? 'pass' : 'fail', 'input held: "' + v2 + '"')

  // B3 空白输入点 Send：不发送、不吞字、焦点回输入框（「not silently lost」反面）。
  await page.fill(boxSel(free.id), '   ')
  await page.click(waitRowEl(free.id) + ' button[data-sendbox]')
  const v3 = await inputValue(boxSel(free.id))
  const focused = await page.evaluate((sel) => document.activeElement === document.querySelector(sel), boxSel(free.id))
  record(results, 'B3 blank send is a no-op that keeps the field', (v3 === '   ' && focused) ? 'pass' : 'fail',
    `value="${v3}" focused=${focused}`)

  // B4 发送成功：草稿面按因关闭（值清空/行迁移），Answered 区可见所答文案。
  await page.fill(boxSel(free.id), DRAFT + 'final')
  await page.click(waitRowEl(free.id) + ' button[data-sendbox]')
  await waitPoll()
  const migrated = (await page.locator(waitRowEl(free.id)).count()) === 0
    && (await page.locator(doneRowEl(free.id)).count()) === 1
  const shown = await page.locator(doneRowEl(free.id)).textContent()
  record(results, 'B4 successful send migrates row and shows the answer',
    migrated && shown.includes(DRAFT + 'final') ? 'pass' : 'fail',
    `migrated=${migrated} answeredTextHasDraft=${shown.includes(DRAFT + 'final')}`)

  // B5 选项行「Type an answer」：揭示态与草稿各跨一个轮询周期存续，随后发送成功。
  await page.click(waitRow(opt.id))
  await page.click(waitRowEl(opt.id) + ' button[data-reveal]')
  await page.fill(revealedSel(opt.id), 'revealed draft across polls')
  await waitPoll()
  const rv = await inputValue(revealedSel(opt.id))
  record(results, 'B5 revealed input and its draft survive a poll', rv === 'revealed draft across polls' ? 'pass' : 'fail',
    'revealed input held: "' + rv + '"')
  await page.press(revealedSel(opt.id), 'Enter')
  await waitPoll()
  const optMigrated = (await page.locator(doneRowEl(opt.id)).count()) === 1
  const optShown = await page.locator(doneRowEl(opt.id)).textContent()
  record(results, 'B6 revealed draft send migrates row with the answer',
    optMigrated && optShown.includes('revealed draft across polls') ? 'pass' : 'fail')

  // B7 边界内畸形行（重复 options、缺 detail、非词表 kind——外部投递者数据可到达面板
  // 的形状）：渲染、可展开、零页错。（空数组/空白项在 API 投递面已 fail-closed 拒收，
  // 实测 400 点名——那段契约归 developer L1，此处只测能到达浏览器的畸形面。）
  await page.click(waitRow(mal.id))
  await waitPoll()
  const malOpen = (await page.locator(waitRowEl(mal.id)).getAttribute('data-open')) === 'true'
  const malBtns = await page.locator(waitRowEl(mal.id) + ' button[data-answer]').count()
  record(results, 'B7 odd-shape request renders, expands, no crash', (malOpen && malBtns >= 1) ? 'pass' : 'fail',
    `open=${malOpen} optionButtons=${malBtns}`)

  // 页错零发生（整旅程，含每次刷新边界与发送边界）。
  record(results, 'B8 zero page errors across the whole draft journey', pageErrors.length === 0 ? 'pass' : 'fail',
    pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  record(results, 'scenario body', 'fail', String(e?.message || e))
} finally {
  await close()
}
summarize(results)

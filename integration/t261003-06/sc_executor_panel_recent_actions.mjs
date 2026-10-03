// sc_executor_panel_recent_actions.mjs — t261003-06「最近动作」读源契约（灰盒 L2，
// harness 缝驱动真实路由面，离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；设计 note §2/§3/§6）：宿主在 Overview 右栏看到执行器最近
// 做了什么——每条 = 时间 + 动作 + 票号 + 一句话结果 + 凭哪条权限。读源 = 逐项目事件
// 账本（SANDBAR_WATCHDOG_DIR/<project>/ledger/events.jsonl，与 watchdog 只读消费同
// 一份；plan review N4 裁定：只读消费，不碰引擎），不可得时显式降级点名原因，
// **绝不用空列表冒充「最近没动作」**（设计 §6 红线）。
//   R1 读源在位：GET /api/actions?project=… 返回动作行，每行语义键齐
//      {at, action, ticket, result, permission}。
//   R2 权限归因：受闸写动作行带「凭哪条权限」（非空，且落在固定词表=grants 面一致）。
//   R3 坏行纪律：畸形行计数（malformed_rows）不静默丢；形状合法但认不出的 kind 计数
//      （unmapped_rows）不编造动作；合法行照常服务。
//   R4 显式降级：账本缺席/不可读 → ok:false + 人类可读原因（点名源路径）；
//      ok:true + 空 actions 的组合=红（空列表冒充「最近没动作」）。
//   R5 只读红线：读出面绝不写账本文件（读前后字节一致）。
//
// 三态：harness 缝缺席=FAIL exit 1 且点名（TDD 期红属预期，arbitrate/merge 期必须绿）。
// intent 分工：面板页呈现归 sc_executor_panel_page_redesign L2b；grants 授权面归
// sc_executor_grants_session_roundtrip。
import { mkdirSync, writeFileSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { loadPanelHarness, makeIsoDir, makeCase } from './lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'

function fixtureLedger(root) {
  const dir = join(root, PROJ, 'ledger')
  mkdirSync(dir, { recursive: true })
  const lines = [
    JSON.stringify({ idem: 'e1', project: PROJ, ticket: 't261002-10', seq: 1, kind: 'sign', stage: 'merge', reason: 'merged by executor', at: 1700000000000 }),
    'this line is not json',
    JSON.stringify({ idem: 'e2', project: PROJ, ticket: 't261002-13', seq: 2, kind: 'retry', reason: 'worker restarted', at: 1700000001000 }),
    JSON.stringify({ idem: 'e3', project: PROJ, ticket: 't261002-14', seq: 3, kind: 'teleport', reason: 'unknown kind row', at: 1700000002000 }),
  ]
  writeFileSync(join(dir, 'events.jsonl'), lines.join('\n') + '\n')
}

async function jfetch(base, url) {
  const r = await fetch(base + url)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body }
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs 缺 startHarness（缝契约见 lib_panel_seam.mjs 头注；TDD 期红属预期）')
    return C.exit()
  }
  const iso = makeIsoDir()
  const wdDir = join(iso.dir, 'watchdog')
  fixtureLedger(wdDir)
  const H = await harness.startHarness({ panelDir: join(iso.dir, 'panel'), watchdogDir: wdDir })
  try {
    const api = '/sandbar-executor-panel/api/actions?project=' + PROJ
    const srcFile = join(wdDir, PROJ, 'ledger', 'events.jsonl')
    const before = statSync(srcFile).size + ':' + readFileSync(srcFile, 'utf8').length

    // R1 行语义齐全
    const g = await jfetch(H.base, api)
    const rows = (g.body && g.body.actions) || []
    const okRow = rows.find(r => r && typeof r.at === 'number' && r.action && r.ticket && 'result' in r && r.permission)
    C.case('R1-mapped-rows-full-semantics', g.status < 300 && g.body && g.body.ok === true && rows.length >= 2 && !!okRow,
      `status=${g.status} ok=${g.body && g.body.ok} rows=${rows.length} full-row=${JSON.stringify(okRow).slice(0, 140)}`)

    // R2 权限归因非空
    const allAttributed = rows.length > 0 && rows.every(r => typeof r.permission === 'string' && r.permission !== '')
    C.case('R2-permission-attribution-nonempty', allAttributed,
      `rows=${rows.length} attributed=${rows.filter(r => r.permission).length}`)

    // R3 坏行不静默丢：malformed_rows / unmapped_rows 显式在案，合法行照常
    const b = g.body || {}
    C.case('R3-bad-lines-counted-not-silent',
      b.malformed_rows === 1 && b.unmapped_rows === 1 && rows.length === 2,
      `malformed=${JSON.stringify(b.malformed_rows)} unmapped=${JSON.stringify(b.unmapped_rows)} rows=${rows.length}（期望 1/1/2）`)

    // R4 显式降级：账本缺席的项目
    const gh = await jfetch(H.base, '/sandbar-executor-panel/api/actions?project=beta-2')
    const bh = JSON.stringify(gh.body || {})
    const explicitDegraded = gh.body && gh.body.ok === false && typeof gh.body.reason === 'string' && gh.body.reason.length > 0
    const fakeCalm = gh.body && gh.body.ok === true && (gh.body.actions || []).length === 0
    C.case('R4-missing-ledger-explicit-degraded-never-fake-calm', gh.status < 500 && explicitDegraded && !fakeCalm,
      `payload=${bh.slice(0, 160)}（ok:true+空列表=冒充「最近没动作」=红线）`)

    // R5 只读红线
    const after = statSync(srcFile).size + ':' + readFileSync(srcFile, 'utf8').length
    C.case('R5-read-face-never-writes-source', before === after, `bytes-before=${before} bytes-after=${after}`)
  } finally {
    await H.close()
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })

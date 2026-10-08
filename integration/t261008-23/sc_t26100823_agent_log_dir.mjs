#!/usr/bin/env node
// sc_t26100823_agent_log_dir.mjs —— agent 日志目录解析面（t261008-23 缺陷 ④）。
//
// intent（灰盒 L2，browser-free 池，隔离台 + 真 HTTP API 面，零浏览器零 docker，
// 红线零接触 3099）：agent-log 块对「盘上有日志」的夹具返回非空文件清单——
// A 新目录优先：日志只在 <ws>/.sandbar → 清单非空、回执 base=实际探测的 .sandbar
//   绝对路径（回执点名探测目录）；B 旧名兼容：日志只在 <ws>/.suyou → 仍可读、
//   base=.suyou；C 两处皆无 → 诚实 exists=false 非空清单不伪造；D 负面断言
// （票面要求）：合并票 worktree 已删、隔离工作区仍在 → 仍经幸存路径解析出日志。
// 读者侧验收纪律：证据全部从 API 读面（读者那一侧）取，不取写者回执。
// 引擎 DOT_DIR 常量不在本票写集——本条只锁读面行为。
// KI 对齐：KI-051（锚=回执 base 后缀与文件名，不锚内部实现）；输入三态（两目录
// 皆缺/畸形夹具不炸）。实现未落地段红属预期（TDD 信号）。
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。

import { mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import {
  PROJ, TID, bootFixture, recorder,
} from './lib_fix23.mjs'
import { benchAuthUrl } from '../t260904-17/lib_fix17.mjs'
import { readFileSync } from 'node:fs'

const REPO = process.cwd()
const { record, rec, summarize } = recorder()
let bench = null, stub = null
try {
  const b = await bootFixture(REPO, 't26100823-agentlog')
  bench = b.bench; stub = b.stub
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

// Fixture workspaces MUST live under /tmp/sandbar-ws/ — that literal prefix is
// the resolver's workspace-dir gate (engine shared.py WS_DIR_BASE, same source);
// a temp dir anywhere else falls through to the no-workspace default branch and
// the scenario would exercise the wrong face (arbitrate-round fixture gap).
const WS_BASE = '/tmp/sandbar-ws'
function mkwsDir(tag) {
  const dir = join(WS_BASE, `sc23-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`)
  mkdirSync(dir, { recursive: true })
  return dir
}
const LOGS = ['agent_create_plan_gen0.log', 'agent_implement_gen0.log', 'agent_arbitrate_gen0.log']
function seedLogs(root, dot) {
  mkdirSync(join(root, dot), { recursive: true })
  for (const f of LOGS) writeFileSync(join(root, dot, f), `log ${f}\n`)
}

// 工单夹具：worktree 为空（合并/主树道形态），workspace.dir 指向受控临时目录。
function ticketWithWs(dir) {
  return {
    id: TID, project: PROJ, title: 'agent-log dir fixture', status: 'MERGED',
    workflow: 'dev-lane', stage: 'merge', stage_state: 'done',
    worktree: '', workspace: { type: 'dir', path: dir },
    handoff_count: 0, pending_count: 0,
  }
}

async function main() {
  // 认证：token 首页兑换 cookie，后续 API 用同一 cookie（无浏览器，node fetch 面）。
  const authUrl = await benchAuthUrl(bench)
  const first = await fetch(authUrl, { redirect: 'manual' })
  const cookies = (first.headers.getSetCookie ? first.headers.getSetCookie() : [first.headers.get('set-cookie')])
    .filter(Boolean).map(c => c.split(';')[0])
  const cookie = cookies.join('; ')
  const API = `${bench.base}/sandbar-workbench/api/wf/tickets/${TID}/agent-logs`

  async function listLogs() {
    const res = await fetch(API, { headers: cookie ? { cookie } : {} })
    if (res.status === 401) return { env: true }
    const body = await res.json().catch(() => null)
    // The read-face contract (same envelope the client consumes, index.tsx
    // apiGet + `r.ok !== true` guard): {ok:true, result:<AgentLogsResult>} —
    // assert on result, not on the envelope (fixture-envelope gap, root-caused
    // via live probe: bare-field reads returned {} for every assertion).
    const payload = body && body.ok === true ? body.result : body
    return { env: false, body: payload, raw: body }
  }

  function pushTicket(dir) {
    pushTicketObj(ticketWithWs(dir))
  }

  function pushTicketObj(ticket) {
    const ctrl = JSON.parse(readFileSync(stub.ctrlPath, 'utf8'))
    ctrl.tickets = [ticket]
    // fix17 stub's show op defaults to mode:'fail' (injected 503) — the detail
    // face must be explicitly allowed, otherwise all four assertions read the
    // stub's injected error instead of the product receipt (arbitrate-round
    // fixture gap, root-caused via live probe).
    ctrl.show = { [TID]: { mode: 'ok' } }
    stub.setCtrl(ctrl)
  }

  // A 新目录优先：日志只在 .sandbar。
  const dirA = mkwsDir('a')
  seedLogs(dirA, '.sandbar')
  pushTicket(dirA)
  const a = await listLogs()
  if (a.env) { record('A .sandbar preferred', 'env_fail', 'console API returned 401 — cookie exchange failed'); }
  else {
    rec('A logs under .sandbar are listed, base reports the probed .sandbar path',
      a.body && a.body.exists === true && Array.isArray(a.body.files) && a.body.files.length >= LOGS.length
        && typeof a.body.base === 'string' && a.body.base.endsWith('.sandbar'),
      JSON.stringify({ exists: a.body && a.body.exists, files: a.body && a.body.files && a.body.files.length, base: a.body && a.body.base }))
  }

  // B 旧名兼容：日志只在 .suyou（改名前的存量票不丢）。
  const dirB = mkwsDir('b')
  seedLogs(dirB, '.suyou')
  pushTicket(dirB)
  const b2 = await listLogs()
  if (!b2.env) {
    rec('B logs under .suyou stay readable via the compat fallback, base reports .suyou',
      b2.body && b2.body.exists === true && b2.body.files && b2.body.files.length >= LOGS.length
        && typeof b2.body.base === 'string' && b2.body.base.endsWith('.suyou'),
      JSON.stringify({ exists: b2.body && b2.body.exists, base: b2.body && b2.body.base }))
  }

  // C 两处皆无：诚实空（不伪造文件清单），回执仍点名探测目录。
  const dirC = mkwsDir('c')
  pushTicket(dirC)
  const c = await listLogs()
  if (!c.env) {
    rec('C no logs anywhere: honest exists=false with an empty list',
      c.body && c.body.exists === false && Array.isArray(c.body.files) && c.body.files.length === 0
        && typeof c.body.base === 'string' && c.body.base.length > 0,
      JSON.stringify({ exists: c.body && c.body.exists, base: c.body && c.body.base }))
  }

  // D 负面断言（票面要求）：合并票——worktree 已随合并除名（字段空、无显式
  // workspace），日志只在默认隔离目录 /tmp/sandbar-ws/<id>/.sandbar → 仍解析出日志。
  // （仲裁轮实锤：旧写法 pushTicket 内部新建对象，gone 的变异从未进桩——D 实际
  // 重复了 A 的 dir 支；本形态=合并后真实落盘形态，走 resolver 默认支。另注：
  // worktree 字段仍在但目录已删的形态，resolver 按候选序探测后诚实 exists=false
  // 并点名候选——「精确说明为何读不到」，不伪造回落，票面允许该归宿。）
  const mergedTicket = { ...ticketWithWs(''), worktree: '', workspace: null }
  mkdirSync(join(WS_BASE, TID, '.sandbar'), { recursive: true })
  for (const f of LOGS) writeFileSync(join(WS_BASE, TID, '.sandbar', f), `log ${f}\n`)
  pushTicketObj(mergedTicket)
  const d = await listLogs()
  if (!d.env) {
    rec('D merged ticket with lane references gone still resolves logs via the default isolated workspace',
      d.body && d.body.exists === true && d.body.files && d.body.files.length >= LOGS.length
        && typeof d.body.base === 'string' && d.body.base.startsWith(join(WS_BASE, TID)),
      JSON.stringify({ exists: d.body && d.body.exists, files: d.body && d.body.files && d.body.files.length, base: d.body && d.body.base }))
  }
  try { rmSync(join(WS_BASE, TID), { recursive: true, force: true }) } catch { /* best effort */ }

  // 收尾：临时夹具目录回收（资源生命周期纪律）。
  for (const dir of [dirA, dirB, dirC]) {
    try { rmSync(dir, { recursive: true, force: true }) } catch { /* best effort */ }
  }

  if (a.env) { try { await bench.teardown() } catch { /* down */ } ; console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2) }
  try { await bench.teardown() } catch { /* down */ }
  summarize()
}

await main()

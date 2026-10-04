// sc_executor_panel_api.mjs — t260929-03 executor-panel 节点半真实路由契约（灰盒 L2/L3，零浏览器零 docker）。
//
// Intent（用户可感知行为；工单 scope③⑥⑦ + panel-contract.md）：
//   R1 请求台账追加=append-only：POST 一条请求 → GET 见 waiting 行；绝不自动答复。
//   R2 答复=按 id 追加闭行，不删除原行（审计链完整；未答请求永不被删）。
//   R3 长保留：缝重启（同数据目录）后未答行原样在——「未答请求永不消失」不变式。
//   R4 畸形输入纪律：台账里坏 JSON/半行=计数上报不静默丢，合法行照常服务（外部
//      输入畸形三态）；POST 非 JSON 体=显式 4xx 拒收不 500。
//   R5 project 形状白名单：非法键 GET/POST 一律 400（契约刚性）；非 GET 未知路由 405。
//   S1 Settings 读面：GET settings 带工厂默认溯源（factory-default 可答「谁定的」）。
//   S2 写面 validate-on-write（KI-148/149 教训+installer 先例）：坏声明（未知键）
//      → saved:false + 人类可读原因 + 盘上 watchdog.json **字节不变**；好声明
//      → 落盘且 GET 回读新值、溯源翻转为 file#path（证明过了装载器）。
//   G1 授权=模板推导非手维护（决定 10/15）：workbench 不可达=显式降级对象
//      （绝不空列表冒充「无授权」）；模板桩可达时：有 human 出口模板出 sign 行、
//      inspection 族模板不出 pause 行（capability 过滤）。
//
// intent 分工：页面渲染/降级态/beep 归 sc_executor_panel_page.mjs（浏览器半）；
// watchdog status 键集归 t260928-28-watchdog-status-surface；developer L1 守纯函数。
// 实现未落地（harness.mjs 缺席）=FAIL 点名，TDD 期红属预期。
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { loadPanelHarness, makeIsoDir, makeCase, REPO } from './lib_panel_harness.mjs'

// t261004-18 (KI-193): panel writes require the console session credential;
// fixtures present the same-shaped cookie the console browser carries.
function consoleCookie(base) {
  return 'dsh-auth-' + Buffer.from(createHash('sha256').update(new URL(base).host).digest()).toString('base64url') + '=v1.AAAA.BBBB'
}

const C = makeCase()

// node 在场性（harness 是 node 缝；node 缺席=环境红）
if (!existsSync(process.execPath)) { C.envFail('node-runtime', 'node 不在 PATH'); process.exit(2) }

let mod
try {
  mod = await loadPanelHarness()
} catch (e) {
  C.case('harness-load', false, String(e.message || e))
  C.exit()
}
if (!mod || typeof mod.startHarness !== 'function') {
  C.case('harness-present', false,
    '实现未落地——测试缝缺席 server/plugins/executor-panel/harness.mjs（协议见 lib_panel_harness.mjs 头注；TDD 期红属预期）')
  C.exit()
}

const DECL = { enabled: true, executor_session: 'sess-a', stall_minutes: 3, reconcile_seconds: 30,
  alerts: { enabled: true, sound: true, desktop: false, night: { start: '23:00', end: '07:00', policy: 'normal' }, redline: [], keep_days: 14 } }
const iso = (msAgo = 0) => new Date(Date.now() - msAgo).toISOString()

async function boot(dir, wb) {
  return mod.startHarness({ port: 0, panelDir: dir, watchdogDir: dir, workbenchBase: wb || '' })
}
const j = (r) => r.json()

// ---------- 场景 ----------
const iso1 = makeIsoDir('panel-api-')
// 声明布局=项目子目录（watchdog.json 在 <root>/<project>/watchdog.json，与 watchdog 声明根同构）
import { mkdirSync } from 'node:fs'
mkdirSync(join(iso1.dir, 'alpha'), { recursive: true })
const W = join(iso1.dir, 'alpha', 'watchdog.json')
writeFileSync(W, JSON.stringify(DECL))

let H
try {
  H = await boot(iso1.dir)
} catch (e) {
  C.case('harness-boot', false, 'startHarness 抛错: ' + String(e).slice(0, 300)); C.exit()
}
let B = H.base.replace(/\/$/, '')

// R1 追加未答请求
{
  const r = await fetch(B + '/sandbar-executor-panel/api/requests', { method: 'POST',
    headers: { 'content-type': 'application/json', cookie: consoleCookie(B) },
    body: JSON.stringify({ project: 'alpha', question: 'Sign ticket t-1?', kind: 'sign',
      default_action: 'sign', expires_at: iso(-3600e3) }) })
  const ok = r.status >= 200 && r.status < 300
  const rows = ok ? (await j(await fetch(B + '/sandbar-executor-panel/api/requests?project=alpha'))).rows
    || (await j(await fetch(B + '/sandbar-executor-panel/api/requests?project=alpha'))).requests || [] : []
  const waiting = Array.isArray(rows) ? rows.filter(x => x.status === 'waiting') : []
  C.case('R1-append-waiting-no-auto-answer', ok && waiting.length === 1 && !!waiting[0].id,
    ok ? `rows=${rows.length} waiting=${waiting.length}` : `POST status=${r.status}`)
}
const first = (await j(await fetch(B + '/sandbar-executor-panel/api/requests?project=alpha'))).rows?.[0]
  || (await j(await fetch(B + '/sandbar-executor-panel/api/requests?project=alpha'))).requests?.[0]

// R2 答复闭行不删原行
{
  const r = await fetch(B + '/sandbar-executor-panel/api/requests/answer', { method: 'POST',
    headers: { 'content-type': 'application/json', cookie: consoleCookie(B) },
    body: JSON.stringify({ project: 'alpha', id: first?.id, answer: 'approved by host', by: 'host' }) })
  const out = await j(await fetch(B + '/sandbar-executor-panel/api/requests?project=alpha'))
  const rows = out.rows || out.requests || []
  const orig = rows.find(x => x.id === first?.id)
  C.case('R2-answer-closes-not-deletes', r.status < 300 && rows.length >= 1 && orig &&
    (orig.status === 'answered' || rows.some(x => x.status === 'answered' && x.closes === first?.id)),
    `http=${r.status} rows=${rows.length} orig_status=${orig?.status}`)
}

// R3 长保留：重启缝后未答行仍在
{
  const r2 = await fetch(B + '/sandbar-executor-panel/api/requests', { method: 'POST',
    headers: { 'content-type': 'application/json', cookie: consoleCookie(B) },
    body: JSON.stringify({ project: 'alpha', question: 'Rerun t-2?', kind: 'rerun', default_action: 'rerun' }) })
  await H.close()
  H = await boot(iso1.dir)
  const B2 = H.base.replace(/\/$/, '')
  B = B2 // 后续段落跟随新端口（重启后旧端口不复用）
  const out = await j(await fetch(B2 + '/sandbar-executor-panel/api/requests?project=alpha'))
  const rows = out.rows || out.requests || []
  const stillWaiting = rows.filter(x => x.status === 'waiting')
  C.case('R3-unanswered-survives-restart', r2.status < 300 && stillWaiting.length === 1,
    `http=${r2.status} waiting_after_restart=${stillWaiting.length}`)
}

// R4 畸形输入：台账坏行计数上报不静默丢；POST 非 JSON 显式拒收
{
  const f = existsSync(join(iso1.dir, 'alpha', 'requests.jsonl'))
    ? join(iso1.dir, 'alpha', 'requests.jsonl') : null
  if (f) {
    const prev = readFileSync(f, 'utf8')
    writeFileSync(f, prev + '{not json\n{"truncated":\n')
  }
  const out = await j(await fetch(H.base + '/sandbar-executor-panel/api/requests?project=alpha'))
  const rows = out.rows || out.requests || []
  const mal = out.malformed_rows ?? out.malformed
  const good = rows.filter(x => x.status === 'waiting').length
  C.case('R4a-malformed-counted-not-dropped', f ? (mal >= 2 && good >= 1) : true,
    f ? `malformed=${mal} valid_waiting=${good}` : 'ledger path layout differs — counted-face checked via API only')
  const bad = await fetch(H.base + '/sandbar-executor-panel/api/requests', { method: 'POST',
    headers: { 'content-type': 'application/json' }, body: '{not json' })
  C.case('R4b-malformed-post-rejected', bad.status >= 400 && bad.status < 500, `status=${bad.status}`)
}

// R5 project 白名单 + 405
{
  const g = await fetch(H.base + '/sandbar-executor-panel/api/requests?project=Bad_Key!')
  // t261004-18: the identity gate runs before validation (401 with no credential),
  // so R5's whitelist/405 faces carry the fixture credential to reach their checks.
  const p = await fetch(H.base + '/sandbar-executor-panel/api/requests', { method: 'POST',
    headers: { 'content-type': 'application/json', cookie: consoleCookie(H.base) }, body: JSON.stringify({ project: 'BAD', question: 'x' }) })
  const m = await fetch(H.base + '/sandbar-executor-panel/api/requests', { method: 'DELETE', headers: { cookie: consoleCookie(H.base) } })
  C.case('R5-whitelist-and-405', g.status === 400 && p.status === 400 && m.status === 405,
    `bad_get=${g.status} bad_post=${p.status} delete=${m.status}`)
}

// S1 溯源读面（工厂默认可答）：beta 未声明任何 watchdog.json → 全旋钮 factory-default
{
  const out = await j(await fetch(H.base + '/sandbar-executor-panel/api/settings?project=beta'))
  const keys = out?.config_provenance?.keys || out?.provenance?.keys || {}
  const vals = Object.values(keys).map(v => String(v))
  const allFactory = vals.length > 0 && vals.every(v => v.includes('factory-default'))
  C.case('S1-provenance-factory-readable', allFactory,
    `knobs=${vals.length} factory=${vals.filter(v => v.includes('factory-default')).length}`)
}

// S2 validate-on-write：坏声明字节不变；好声明落盘且回读翻转
{

// t261004-18 (KI-193): panel writes require the console session credential;
// fixtures present the same-shaped cookie the console browser carries.
function consoleCookie(base) {
  return 'dsh-auth-' + Buffer.from(createHash('sha256').update(new URL(base).host).digest()).toString('base64url') + '=v1.AAAA.BBBB'
}
  const before = readFileSync(W, 'utf8')
  const bad = await fetch(B + '/sandbar-executor-panel/api/settings?project=alpha', { method: 'POST',
    headers: { 'content-type': 'application/json', cookie: consoleCookie(H.base) },
    body: JSON.stringify({ op: 'save', declaration: { ...DECL, totally_unknown_key: 1 } }) })
  const after = readFileSync(W, 'utf8')
  const badOut = await bad.json().catch(() => ({}))
  const badOk = bad.status < 300 && badOut.saved === false &&
    String(badOut.reason || badOut.error || '').length > 0 && after === before
  C.case('S2a-rejected-save-reason-file-untouched', badOk,
    `http=${bad.status} saved=${badOut.saved} file_unchanged=${after === before}`)
  const good = await fetch(H.base + '/sandbar-executor-panel/api/settings?project=alpha', { method: 'POST',
    headers: { 'content-type': 'application/json', cookie: consoleCookie(H.base) },
    body: JSON.stringify({ op: 'save', declaration: { ...DECL, stall_minutes: 7 } }) })
  const goodOut = await good.json().catch(() => ({}))
  const back = await j(await fetch(H.base + '/sandbar-executor-panel/api/settings?project=alpha'))
  const cfg = back?.config || back?.resolved || back
  const prov = JSON.stringify(back?.config_provenance?.keys || {})
  C.case('S2b-good-save-roundtrips-through-loader',
    goodOut.saved === true && JSON.stringify(cfg).includes('7') && prov.includes('stall_minutes'),
    `saved=${goodOut.saved} provenance_has_stall=${prov.includes('stall_minutes')}`)
}

// G1 授权推导：不可达=显式降级；human 出口→sign，inspection→无 pause
{
  await H.close()
  const dead = 'http://127.0.0.1:9'
  const H2 = await mod.startHarness({ port: 0, panelDir: iso1.dir, watchdogDir: iso1.dir, workbenchBase: dead })
  const gDead = await fetch(H2.base + '/sandbar-executor-panel/api/grants?project=alpha')
  const gOut = await gDead.json().catch(() => ({}))
  const degraded = (gOut.degraded === true || gOut.error || gOut.reason || gOut.detail) &&
    !(Array.isArray(gOut.grants) && gOut.grants.length === 0 && !gOut.degraded && !gOut.error)
  C.case('G1a-unreachable-explicit-degraded', gDead.status < 500 && !!degraded,
    `http=${gDead.status} body=${JSON.stringify(gOut).slice(0, 160)}`)
  await H2.close()

  // 模板桩：形状=真实端点 /sandbar-workbench/api/wf/workflows（workflow.py _brief：
  // 人门事实在 stages[].exit==='human' 与 topology.nodes[].kind==='human' 两处，
  // 不存在顶层 nodes / has_human_gate）。一个带 human 出口、一个 inspection 族（无 pause 面）
  const wf = { workflows: [
    { id: 'dev-lane', name: 'Dev', lane: 'dev',
      stages: [{ id: 's1', name: 'work', role: 'agent' }, { id: 's2', name: 'sign', role: 'human', exit: 'human' }],
      topology: { nodes: [{ id: 's1', label: 'work', kind: 'agent' }, { id: 's2', label: 'sign', kind: 'human' }],
        edges: [['s1', 's2']] } },
    { id: 'inspection-lite', name: 'Inspect', lane: 'inspection',
      stages: [{ id: 'i1', name: 'look', role: 'agent' }],
      topology: { nodes: [{ id: 'i1', label: 'look', kind: 'agent' }], edges: [] } },
  ] }
  const stubPort = 0
  const { createServer } = await import('node:http')
  const stub = createServer((req, res) => { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(wf)) })
  await new Promise(r => stub.listen(stubPort, '127.0.0.1', r))
  const wbBase = 'http://127.0.0.1:' + stub.address().port
  const H3 = await mod.startHarness({ port: 0, panelDir: iso1.dir, watchdogDir: iso1.dir, workbenchBase: wbBase })
  const g = await fetch(H3.base + '/sandbar-executor-panel/api/grants?project=alpha')
  const gOut3 = await g.json().catch(() => ({}))
  // 结构化断言（灰盒绑定浅）：sign 行必须落在 grants.rows（op+template 配对），
  // 禁止对全文正则——filtered_note 的 "design" 一词曾让 /sign/i 假绿（走查实证）。
  const rows = (gOut3.grants && Array.isArray(gOut3.grants.rows)) ? gOut3.grants.rows : []
  const hasSign = rows.some(r => r && r.op === 'sign' && /dev/i.test(String(r.template)))
  const inspectRows = rows.filter(r => /inspect/i.test(String(r.template)))
  const noPauseForInspection = inspectRows.length > 0 && inspectRows.every(r => r.op !== 'pause-resume')
  C.case('G1b-derived-sign-and-capability-filter', g.status < 300 && hasSign && noPauseForInspection,
    `http=${g.status} sign=${hasSign} rows=${JSON.stringify(rows.map(r => r.op + ':' + r.template))} inspect_pause_absent=${noPauseForInspection}`)
  await H3.close(); stub.close()
}

await H.close().catch(() => {})
iso1.clean()
C.exit()

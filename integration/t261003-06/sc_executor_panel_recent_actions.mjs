// sc_executor_panel_recent_actions.mjs — t261003-06 引入；t261003-10 换源重写
// （灰盒 L2，**生产路由壳**缝：startPluginHarness 经 node.ts 真 apply() 注册面起服务，
// 离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；设计 note §2/§3/§6）：宿主在 Overview 右栏看到执行器最近
// 做了什么——每条 = 时间 + 动作 + 票号 + 一句话结果 + 凭哪条权限。读源 = 引擎自审计
// admin.log（t261003-10 plan gen1 定稿：行自带「做了什么」；「凭哪条权限」= 顶层
// executor_grant_op，引擎侧落键由扩围票承接；落键前全部生产行显式降级，绝不空表
// 冒充「最近没动作」）。SANDBAR_ADMIN_LOG 注入隔离夹具（真行逐字拷贝）。
//   R0 生产路由壳：/api/actions、/api/projects 经 apply() 注册面可达（旧实现漏注册
//      = 生产 404，直转 api.handle 的缝看不见）；
//   R1 读源在位：GET /api/actions?project=… 返回动作行，每行语义键齐
//      {at, action, ticket, result, permission}（落键后形状，合同夹具注入）；
//   R2 权限归因：展示行 permission 非空且落在 grants 词表；
//   R3 坏行纪律：畸形行 / sub 认不出 / 缺授权键 分别计数（malformed_rows /
//      unmapped_rows / missing_authorization_rows），不静默丢、不编造；
//   R4 显式降级：源缺席 / 全是缺授权键行 → ok:false + 人类可读原因（点名源路径与
//      待落键事实）；ok:true + 空 actions 的组合=红；
//   R5 只读红线：读出面绝不写 admin.log（读前后字节一致）。
//
// 三态：harness 缝缺席=FAIL exit 1 且点名。intent 分工：面板页呈现归
// sc_executor_panel_page_redesign L2b；grants 授权面归 sc_executor_grants_session_roundtrip。
import { readFileSync, statSync, copyFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadPanelHarness, makeCase } from './lib_panel_seam.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const C = makeCase()
const PROJ = 'sandbar'

/** 真行夹具（逐字拷贝自主仓 live server/admin.log，见 fixtures 头注）。 */
const realLines = readFileSync(join(HERE, 'fixtures', 'admin-log-real-lines.jsonl'), 'utf8').trim().split('\n')

async function jfetch(base, url) {
  const r = await fetch(base + url)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body }
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startPluginHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs 缺 startPluginHarness（生产路由壳缝，t261003-10；见 lib_panel_seam.mjs 头注）')
    return C.exit()
  }
  const iso = mkdtempSync(join(tmpdir(), 't261003-10-'))
  const clean = () => rmSync(iso, { recursive: true, force: true })
  process.on('exit', clean)
  process.on('SIGINT', () => { clean(); process.exit(130) })
  const panelDir = join(iso, 'panel')
  const adminLog = join(iso, 'admin.log')
  const fixturePath = join(HERE, 'fixtures', 'admin-log-real-lines.jsonl')
  copyFileSync(fixturePath, adminLog)
  const H = await harness.startPluginHarness({ panelDir, watchdogDir: join(iso, 'watchdog'), adminLogPath: adminLog })
  try {
    const api = '/sandbar-executor-panel/api/actions?project=' + PROJ
    const before = statSync(adminLog).size + ':' + readFileSync(adminLog, 'utf8').length

    // R0 生产路由壳：漏注册面可达 + 表外 404
    const act = await jfetch(H.base, api)
    C.case('R0-actions-route-reachable-through-plugin-shell', act.status < 500,
      `status=${act.status} ok=${act.body && act.body.ok}（旧实现此路径 404：只 handle 未注册）`)
    const prj = await jfetch(H.base, '/sandbar-executor-panel/api/projects')
    C.case('R0-projects-route-reachable-through-plugin-shell', prj.status < 500 && prj.body && prj.body.ok === true,
      `status=${prj.status} ok=${prj.body && prj.body.ok}（t260930-09 起同病）`)
    const nf = await jfetch(H.base, '/sandbar-executor-panel/api/definitely-not-a-route')
    C.case('R0-off-table-404-production-shape', nf.status === 404, `status=${nf.status}`)

    // 今天形状的真行（无顶层授权键）→ 显式降级点名待落键，绝不空表冒充
    const b = act.body || {}
    const explicitDegraded = b.ok === false && typeof b.reason === 'string' && b.reason.includes('executor_grant_op')
      && b.reason.includes(adminLog)
    const fakeCalm = b.ok === true && (b.actions || []).length === 0
    C.case('R4-current-shape-explicit-degraded-never-fake-calm', act.status < 500 && explicitDegraded && !fakeCalm,
      `payload=${JSON.stringify(b).slice(0, 200)}（ok:true+空列表=冒充「最近没动作」=红线）`)

    // 源缺席 → 显式降级点名路径
    const H2 = await harness.startPluginHarness({ panelDir: join(iso, 'panel2'), watchdogDir: join(iso, 'watchdog2'), adminLogPath: join(iso, 'absent.log') })
    try {
      const gh = await jfetch(H2.base, api)
      const ok2 = gh.body && gh.body.ok === false && typeof gh.body.reason === 'string' && gh.body.reason.length > 0
      C.case('R4-absent-source-explicit-degraded', ok2 && !fakeCalm, `payload=${JSON.stringify(gh.body).slice(0, 160)}`)
    } finally { await H2.close() }

    // R5 只读红线
    const after = statSync(adminLog).size + ':' + readFileSync(adminLog, 'utf8').length
    C.case('R5-read-face-never-writes-source', before === after, `bytes-before=${before} bytes-after=${after}`)

    // R1/R2/R3（落键后形状）在插件单测侧用合同夹具锁死（recent-actions.test.mjs）；
    // 引擎扩围票落键后，把真引擎产出的行换进 fixtures 即可在本场景点亮这三断言——
    // 现在先在场缺席检查：夹具文件存在且非空（防夹具被静默删）。
    C.case('F1-real-line-fixture-present', realLines.length >= 4 && realLines.every((l) => l.startsWith('{')),
      `rows=${realLines.length}（逐字拷贝自 live admin.log）`)
  } finally {
    await H.close()
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })

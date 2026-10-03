/**
 * grants-readout.test.mjs —— t261001-21 读出面诚实 UT：
 *  - 派生能力矩阵每行带 granted（真声明定；缺席/坏声明=全 false）；
 *  - granted_count + readout_note：零授予一眼可读「NOTHING is granted」；
 *  - 顶层 granted_ops / declaration_state：消费方不用拆表；
 *  - 夜间档活跃=全行 granted；'reject' 显示名 ↔ 'send-back' 声明键映射；
 *  - 页面源级锁：声明状态 banner 先行 + granted 列 + 「行存在≠已授予」文案。
 * 畸形输入用例（声明 JSON 坏 / 未知形状）走桩文件，不靠真外部源。零真网络、零 3099。
 */
import { assert, done, freshDir, cleanup, fakeClock } from './lib.mjs'
import { createApi } from '../src/host/api.ts'
import { declarationPath } from '../src/host/executor-grants.ts'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

const wd = freshDir(), pan = freshDir()
const env = { HOME: '/nonexistent-home', SANDBAR_WATCHDOG_DIR: wd, SANDBAR_PANEL_DIR: pan, SANDBAR_PROJECTS_DIR: wd }
const clock = fakeClock()
const Q = (s = '') => new URLSearchParams(s)
const PATH = '/sandbar-executor-panel/api/grants'
let n = 0

// 真端点形状（result 直接是数组；260930 直修口径）——一有人门 dev 模板，固定 op 全显。
const WF_PAYLOAD = { ok: true, result: [{ name: 'dev-lane', kind: 'dev', has_human_gate: true }] }
const restore = (() => {
  const orig = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify(WF_PAYLOAD), { status: 200 })
  return () => { globalThis.fetch = orig }
})()

const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }) })

try {
  // ---- ① 零声明项目：派生行照常（能力矩阵），但全部 granted:false + 「NOTHING is granted」 ----
  {
    const r = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    const g = r.json.grants
    assert(r.status === 200 && g.ok === true && g.rows.length >= 1, `zero-decl: derived rows intact (${++n})`)
    assert(g.rows.every((row) => row.granted === false), `zero-decl: every row granted:false (${++n})`)
    assert(g.granted_count === 0, `zero-decl: granted_count 0 (${++n})`)
    assert(/NOTHING is granted/.test(g.readout_note) && /capability matrix/.test(g.readout_note),
        `zero-decl: readout_note names nothing-granted + matrix semantics (${++n})`)
    assert(Array.isArray(r.json.granted_ops) && r.json.granted_ops.length === 0,
        `zero-decl: top-level granted_ops empty (${++n})`)
    assert(r.json.declaration_state.kind === 'absent', `zero-decl: declaration_state kind=absent (${++n})`)
  }

  // ---- ② 声明 sign:true → 只有 sign 行 granted:true，其余仍 false ----
  {
    const p = await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: { sign: true }, by: 'host' }), '')
    assert(p.status === 200 && p.json.saved === true, `grant sign: saved (${++n})`)
    const r = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    const g = r.json.grants
    const sign = g.rows.filter((row) => row.op === 'sign')
    assert(sign.length >= 1 && sign.every((row) => row.granted === true), `grant sign: sign rows granted (${++n})`)
    assert(g.rows.filter((row) => row.op !== 'sign').every((row) => row.granted === false),
        `grant sign: non-sign rows stay not-granted (${++n})`)
    assert(g.granted_count === 1, `grant sign: granted_count counts DISTINCT ops, not rows (${++n})`)
    assert(/Permissions: 1 of 6 granted/.test(g.readout_note), `grant sign: readout names 1 of 6 (${++n})`)
    assert(r.json.granted_ops.includes('sign') && r.json.granted_ops.every((op) => op === 'sign'),
        `grant sign: top-level granted_ops = [sign] (${++n})`)
  }

  // ---- ③ 显示名 'reject' ↔ 声明键 'send-back'：按声明键授予后 reject 行 granted ----
  {
    const p = await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: { 'send-back': true }, by: 'host' }), '')
    assert(p.json.saved === true, `alias: send-back saved (${++n})`)
    const r = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    const rej = r.json.grants.rows.filter((row) => row.op === 'reject')
    assert(rej.length >= 1 && rej.every((row) => row.granted === true),
        `alias: reject row granted via send-back key (${++n})`)
  }

  // ---- ④ 夜间档活跃（until 在未来）→ 全行 granted；过期夜间档=不授予 ----
  {
    const p = await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: {}, night_tier: { enabled: true, until: clock.now() + 60_000 }, by: 'host' }), '')
    assert(p.json.saved === true, `night: saved (${++n})`)
    const r = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    const g = r.json.grants
    assert(g.rows.length >= 1 && g.rows.every((row) => row.granted === true), `night: active tier grants all rows (${++n})`)
    // 过期：until 在过去 → 全 false（不静默沿用）
    await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: {}, night_tier: { enabled: true, until: clock.now() - 1 }, by: 'host' }), '')
    const r2 = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    assert(r2.json.grants.rows.every((row) => row.granted === false), `night: expired tier grants nothing (${++n})`)
    assert(r2.json.grants.readout_note.includes('NOTHING is granted'), `night: expired tier falls back to nothing-granted note (${++n})`)
  }

  // ---- ⑤ 畸形声明（桩文件直接落盘坏 JSON）→ granted 全 false + kind=malformed（fail-closed 读出面） ----
  {
    const file = declarationPath('sandbar', env)
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, '{not json at all', 'utf8')
    const r = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    const g = r.json.grants
    assert(r.json.declaration_state.kind === 'malformed', `malformed: declaration_state kind (${++n})`)
    assert(g.ok === true && g.rows.every((row) => row.granted === false),
        `malformed: no row reads as granted (fail-closed) (${++n})`)
    assert(r.json.granted_ops.length === 0, `malformed: granted_ops empty (${++n})`)
    assert(/NOTHING is granted/.test(g.readout_note), `malformed: nothing-granted note present (${++n})`)
  }

  // ---- ⑥ 页面源级锁（t261003-06 改版）：读出句在案、矩阵≠授予 caveat、声明状态 banner 先行 ----
  {
    assert(PANEL_PAGE_HTML.includes('session_readout'), `page consumes the session readout (three-state face) (${++n})`)
    assert(PANEL_PAGE_HTML.includes('A row here is not a grant'), `page: matrix≠grant caveat (${++n})`)
    assert(PANEL_PAGE_HTML.includes('No grants declaration exists yet'), `page: absent-declaration banner (${++n})`)
    assert(PANEL_PAGE_HTML.includes('cannot be read ('), `page: unusable-declaration banner (${++n})`)
    assert(PANEL_PAGE_HTML.includes('Permissions: 0 of 6'), `page: distinct-permission chip (N of 6) (${++n})`)
    // banner 必须在权限开关区之前渲染（先看到「授了什么」再操作开关）。
    const bannerAt = PANEL_PAGE_HTML.indexOf('id="grantsBanner"')
    const permsAt = PANEL_PAGE_HTML.indexOf('id="permList"')
    assert(bannerAt !== -1 && bannerAt < permsAt, `page: grants banner precedes the switches (${++n})`)
  }
} finally {
  restore()
  cleanup([wd, pan])
}
done(n)

/**
 * integration/t260916-23/sc_session_dualname_ts_faces.mjs
 * —— 会话文件双名兼容读侧·workbench 三消费面接线（t260916-23 场景②，池=ro）。
 *
 * intent（守护的用户可感知行为，灰盒 L3；dsh-upgrade T1——dsh 0.1.5 把泳道会话档换名
 * session.v3.jsonl.zstd，workbench 宿主三端点的会话发现必须双名化，否则升级后用量页/
 * 实时面板/KB 徽标齐齐「找不到会话」——agent-logs.ts:243 旧扁平布局前科同族的第二代）：
 *   T1 用量页 resolveAllSessionFiles：双名并存逐 <sub> 目录恰取 mtime 最新一份、
 *      多 sub 全收、别工单不混入（防双计/防漏）；
 *   T2 两代方向各一子用例：仅新名收新名、仅旧名收旧名（对照）；
 *   T3 实时面板 resolveSessionFile：exact 角色优先不破 + exact sub 内取最新代
 *      （升级后活水面的选中语义不断）；
 *   T4 KB 徽标 _sessionKbFast：取全局 mtime 最新代（升级后徽标跟着新档走）+
 *      旧扁平 session-*.zstd 兜底不破（260825「升级后静默恒 0」前科的回归钉）；
 *   T5 零会话 reason 含新名字面（文案与实现一致，验收④）。
 *
 * 断言面=导出端点函数返回值（path 集合/选中路径/kb），不锚内部 helper——
 * 与 developer 五态 UT 不同面：彼守 helper 单元语义，本条守三端点接线
 * （helper 建了没接线/接错面，在此现形）。
 *
 * 直跑：node integration/t260916-23/sc_session_dualname_ts_faces.mjs（node ≥22.18）。
 * zstd 不在 PATH / node 过旧 → ENV_FAIL 环境红退 2（三态 §7.3，原因上屏）。
 * 末行 SUMMARY pass=<n> fail=<k> env_fail=<e> na=0。
 */

import { execFile } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { utimesSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { projectDirKey, resolveSessionFile } from '../../server/plugins/workbench/src/host/agent-live.ts'
import { resolveAllSessionFiles } from '../../server/plugins/workbench/src/host/agent-usage.ts'
import { _sessionKbFast } from '../../server/plugins/workbench/src/host/agent-logs.ts'

const execFileP = promisify(execFile)

let pass = 0, fail = 0, envFail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t} ==`) }

const OLD = 'session.jsonl.zstd'
const NEW = 'session.v3.jsonl.zstd'
const TICKET = 't260916-23'
const T0 = Date.parse('2026-08-28T10:00:00')

const nodeMajor = Number(process.versions.node.split('.')[0])
let zstdOk = true
try { await execFileP('zstd', ['--version']) } catch { zstdOk = false }
const envBad = []
if (nodeMajor < 22) envBad.push(`node ${process.versions.node} 过旧（原生 type-stripping 需 ≥22.18）`)
if (!zstdOk) envBad.push('zstd 不在 PATH（会话桩依赖真 zstd 帧）')

/** 会话桩：事件列表压成 zstd 会话档；pad=不可压填充（KB 徽标子用例要用可感知体积）。 */
async function zpack(events, dst, pad = 0) {
  const payload = pad
    ? [{ type: 'assistant/message', data: { note: randomBytes(pad).toString('hex') } }, ...events]
    : events
  const raw = payload.map(e => JSON.stringify(e)).join('\n') + '\n'
  const src = dst + '.raw'
  await writeFile(src, raw, 'utf8')
  await execFileP('zstd', ['-f', '-q', '-o', dst, src])
  await rm(src, { force: true })
}
const usage = (i, o, c) => ({ type: 'assistant/message', data: { usage: { inputTokens: i, outputTokens: o, cacheReadTokens: c } } })
const stamp = (p, ms) => utimesSync(p, new Date(ms), new Date(ms))

const tmp = await mkdtemp(join(tmpdir(), 't260916-23-tsfaces-'))
try {
  if (envBad.length > 0) {
    console.log(`ENV_FAIL: ${envBad.join('；')}——环境红退 2（恢复后自动真跑）`)
    envFail++
  } else {
    const repo = join(tmp, 'repo')
    const wt = join(repo, '.worktrees', 'wt')
    const slug = projectDirKey(wt)
    const sessRoot = join(wt, '.dsh', 'sessions')
    const sub = (name) => join(sessRoot, slug, name)
    for (const d of [sub(`${TICKET}-developer`), sub(`${TICKET}-integration`), sub(`${TICKET}-solo`), sub('other-ticket-developer')]) {
      await mkdir(d, { recursive: true })
    }
    const flatSlug = join(sessRoot, `${slug}-flat`)
    await mkdir(flatSlug, { recursive: true })

    // dev sub：双名并存（旧 X、新 Y 且更新）；int sub：仅旧名；solo sub：仅新名；别工单：旧名（不混入）
    const devOld = join(sub(`${TICKET}-developer`), OLD)
    const devNew = join(sub(`${TICKET}-developer`), NEW)
    await zpack([usage(10, 20, 5)], devOld)
    await zpack([usage(100, 200, 50)], devNew, 3000)
    stamp(devOld, T0); stamp(devNew, T0 + 2000)  // 整秒错开：_sessionKbFast 沿用既有秒级 mtime 比较（260825 语义，本票不动其精度）
    const intOld = join(sub(`${TICKET}-integration`), OLD)
    await zpack([usage(22, 4, 0)], intOld)
    stamp(intOld, T0)
    const soloNew = join(sub(`${TICKET}-solo`), NEW)
    await zpack([usage(11, 22, 33)], soloNew)
    stamp(soloNew, T0 + 1000)
    await zpack([usage(999, 999, 999)], join(sub('other-ticket-developer'), OLD))
    stamp(join(sub('other-ticket-developer'), OLD), T0)  // KB 徽标面全 slug 扫描——不打进测试时间轴会压过断言
    const flatFile = join(flatSlug, 'session-flat123.zstd')
    await writeFile(flatFile, 'flat legacy stub', 'utf8')
    stamp(flatFile, T0 + 500)

    section('T1/T2 用量页 resolveAllSessionFiles 双名发现')
    const r = await resolveAllSessionFiles(repo, TICKET, { worktree: '.worktrees/wt' })
    ok((r.paths ?? []).length === 3, `三 sub 各恰一份（实得 ${(r.paths ?? []).length}，双名并存不翻倍）`)
    const devPick = (r.paths ?? []).find(p => p.includes(`${TICKET}-developer`))
    ok(devPick !== undefined && devPick.endsWith(NEW), 'dev sub 双名并存取 mtime 最新（新名胜出）')
    const intPick = (r.paths ?? []).find(p => p.includes(`${TICKET}-integration`))
    ok(intPick !== undefined && intPick.endsWith(OLD), '仅旧名 sub 收旧名（两代方向对照子用例）')
    const soloPick = (r.paths ?? []).find(p => p.includes(`${TICKET}-solo`))
    ok(soloPick !== undefined && soloPick.endsWith(NEW), '仅新名 sub 收新名（升级后新会话可发现）')
    ok((r.paths ?? []).every(p => p.includes(TICKET)), '别工单会话不混入')

    section('T3 实时面板 resolveSessionFile')
    const rExact = await resolveSessionFile(repo, TICKET, { worktree: '.worktrees/wt', role: 'developer' })
    ok(rExact.path !== undefined && rExact.path.includes(`${TICKET}-developer`) && rExact.path.endsWith(NEW),
      'exact 角色优先不破 + exact sub 内取最新代')
    const rAny = await resolveSessionFile(repo, TICKET, { worktree: '.worktrees/wt' })
    ok(rAny.path !== undefined && rAny.path.endsWith(NEW), '无角色 → 全局 mtime 最新（dev 新名 T0+2000 胜 solo 新名 T0+1000）')

    section('T4 KB 徽标 _sessionKbFast')
    const kf = await _sessionKbFast(sessRoot)
    ok(kf.path.endsWith(NEW) && kf.kb >= 3, `双名并存取最新代（path=${kf.path.split('/').pop()} kb=${kf.kb}；pad 压后 3256B→3KB）`)
    stamp(flatFile, T0 + 99999)
    const kf2 = await _sessionKbFast(sessRoot)
    ok(kf2.path.includes('session-flat123.zstd'), '旧扁平 session-*.zstd 兜底不破（260825 前科回归钉）')

    section('T5 零会话文案与实现一致')
    const rNone = await resolveAllSessionFiles(repo, 't-absent', { worktree: '.worktrees/wt' })
    ok((rNone.paths ?? []).length === 0 && (rNone.reason ?? '').includes(NEW),
      '零会话 → reason 含新名字面（双名表述，验收④）')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=0`)
process.exit(fail > 0 ? 1 : envFail > 0 ? 2 : 0)

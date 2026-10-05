/**
 * lib.mjs —— executor-panel UT 公共件：临时目录 / 假时钟 / 内存账本 io / 断言。
 * 零真实 ~/.sandbar、零 3099/7233 触碰（fixture + 注入全走桩；/tmp 基座纪律同 watchdog）。
 */
import { mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'

let seq = 0
const TMP_BASE = '/tmp'
export function freshDir(prefix = 'ep-') {
  return mkdtempSync(join(TMP_BASE, prefix + String(++seq) + '-'))
}
export function cleanup(dirs) {
  for (const d of dirs) rmSync(d, { recursive: true, force: true })
}
export function assert(cond, name) {
  if (!cond) throw new Error('FAIL: ' + name)
  console.log('ok   ' + name)
}
export function done(count) {
  console.log(`done ${count}`)
  if (process.exitCode) process.exit(process.exitCode)
}

/** 假时钟：手动拨动。 */
export function fakeClock(startMs = 1_700_000_000_000) {
  let now = startMs
  return {
    now: () => now,
    advance(ms) { now += ms },
    set(ms) { now = ms },
  }
}

/** 内存账本 io：files[file] = 整文件字符串；测试直接改/删。 */
export function memLedgerIo(files = {}) {
  return {
    files,
    existsSync: (f) => f in files,
    readFileSync: (f) => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f] },
    appendFileSync: (f, line) => { files[f] = (files[f] || '') + line },
    mkdirSync: () => {},
  }
}

/** 隔离 env（SANDBAR_WATCHDOG_DIR / SANDBAR_PANEL_DIR 指进临时目录）。 */
export function isolatedEnv(...dirs) {
  return {
    HOME: '/nonexistent-home',
    SANDBAR_WATCHDOG_DIR: dirs[0],
    SANDBAR_PANEL_DIR: dirs[1] || dirs[0],
  }
}

/**
 * KI-193 测试凭据：按 dsh cookieName 算法拼一枚形状合法的会话 cookie
 * （'dsh-auth-' + base64url(sha256(host))；值 v1.<b64>.<b64> 只过形状门——
 * 本仓不验 HMAC，UT 里形状合法即可过 defaultAuthFace）。
 */
import { createHash } from 'node:crypto'
export function panelCookieFor(host) {
  const name = 'dsh-auth-' + createHash('sha256').update(host).digest('base64url')
  return name + '=v1.cGFuZWwtdGVzdA.c2lnbmF0dXJlLXNoYXBlLW9ubHk'
}

/** KI-193：API 级 UT 的凭据桩（defaultAuthFace 的判定本身由 auth-gate.test.mjs 专测）。 */
export const authPass = () => ({ ok: true, why: '' })

/**
 * KI-193：引擎写面桩——面板 POST /api/grants、settings revoke 走引擎入口；
 * UT 里用它把载荷落回真 TS 写核（saveGrantsDecl：同校验/原子写/审计），
 * 不真 spawn python3。引擎 spawn 面与引擎侧判定由 engine-grants-write 测试与
 * pytest 各自专测。
 */
export function engineWriteStub(env, nowMs = () => Date.now()) {
  // t261004-41 返工：逐字透传 payload（只换写核，不重建载荷）——逐字段重建会把
  // 新字段丢在缝里（与 harness.mjs 同一故障形状，本票 L3 红的根因即此）。
  return async (p) => {
    const { saveGrantsDecl } = await import('../src/host/executor-grants.ts')
    return saveGrantsDecl(p.key, p, p.by, env, nowMs(), '', p.source)
  }
}

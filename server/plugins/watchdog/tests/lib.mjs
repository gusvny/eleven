/**
 * lib.mjs —— watchdog UT 公共件：内存 io 桩 / 临时目录 / 假时钟。
 * 零真实 ~/.sandbar、零引擎 CLI、零 3099/7233 触碰（fixture + 注入全走桩）。
 */
import { mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'

let seq = 0
// 固定 /tmp 基座（不用 os.tmpdir()）：沙箱 vfs shim 对 /var/folders 的读可见性有
// 实证不稳（写后 readdir 空洞），/tmp 全程稳定；测试只要求「存在且可读写」的隔离目录。
const TMP_BASE = '/tmp'
export function freshDir(prefix = 'wd-') {
  return mkdtempSync(join(TMP_BASE, prefix + String(++seq) + '-'))
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

/** 内存账本 io：files[name] = {size, ino, content}，测试直接改。 */
export function memTailIo(files) {
  return {
    async stat(p) {
      const f = files[p]
      if (!f) throw Object.assign(new Error('ENOENT: ' + p), { code: 'ENOENT' })
      return { size: f.content.length, ino: f.ino }
    },
    async read(p, a, b) {
      const f = files[p]
      if (!f) throw Object.assign(new Error('ENOENT: ' + p), { code: 'ENOENT' })
      return f.content.slice(a, Math.min(b, f.content.length))
    },
    async listArchives(activePath) {
      const dir = activePath.slice(0, activePath.lastIndexOf('/'))
      return Object.keys(files)
        .filter(n => n.startsWith(dir + '/') && n !== activePath && n.endsWith('.jsonl'))
        .map(n => n.slice(dir.length + 1))
    },
  }
}

/** 内存 core io：账/心跳都在内存串，appendAlarm 断言面暴露。 */
export function memCoreIo() {
  const store = new Map()
  const appended = []
  return {
    appended,
    store,
    tail: {
      async stat() { throw new Error('not used in core stub') },
      async read() { throw new Error('not used in core stub') },
    },
    heartbeat: {
      async write(p, d) { store.set(p, d) },
      async read(p) {
        if (!store.has(p)) throw new Error('ENOENT')
        return store.get(p)
      },
      async mtimeMs() { return null },
    },
    async appendAlerts(p, line) { appended.push({ p, line }); store.set(p, (store.get(p) || '') + line + '\n') },
    async listAlerts(p) {
      const raw = store.get(p) || ''
      return raw.split('\n').filter(l => l !== '')
    },
  }
}

/** 一行合法账本事件。 */
export function ledgerLine(over = {}) {
  const r = {
    schema: 'event-ledger-v1',
    idem: `sandbar|t${Math.random().toString(36).slice(2, 8)}|run1|${over.seq ?? 1}`,
    project: 'sandbar',
    ticket: 't260901-01',
    seq: 1,
    kind: 'stage-transition',
    stage: 'implement',
    stage_state: 'running',
    at: 1_700_000_000_000,
    ...over,
  }
  if (over.__drop) { for (const k of over.__drop) delete r[k] }
  const { __drop, ...rest } = r
  return JSON.stringify(rest)
}

/** 组一个 Watchdog 的测试依赖（全部桩；configDirEnv 指向临时目录）。 */
export async function testEnv({ configByProject = {}, ledgerByProject = {}, alertsByProject = {}, board = { ok: true, rows: [] }, clock = fakeClock() } = {}) {
  // 写面走动态 import 的 fs（沙箱 vfs shim 下静态导入的写句柄偶发不落盘——实证差异，
  // 动态面每次实测即现；两口径等价，只为测试稳定性）。
  const fs = await import('node:fs')
  const { join: j } = await import('node:path')
  const cfgDir = freshDir('wdcfg-')
  const dataDir = freshDir('wddata-')
  const ledgerDir = freshDir('wdledg-')
  for (const [k, raw] of Object.entries(configByProject)) {
    fs.mkdirSync(j(cfgDir, k), { recursive: true })
    fs.writeFileSync(j(cfgDir, k, 'watchdog.json'), typeof raw === 'string' ? raw : JSON.stringify(raw))
  }
  for (const [k, content] of Object.entries(ledgerByProject)) {
    fs.writeFileSync(j(ledgerDir, `${k}.jsonl`), content)
  }
  for (const [k, content] of Object.entries(alertsByProject)) {
    fs.writeFileSync(j(dataDir, `${k}.alerts.jsonl`), content)
  }
  const env = { SANDBAR_WATCHDOG_DIR: cfgDir, SANDBAR_WATCHDOG_DATA: dataDir, SANDBAR_EVENT_LEDGER_DIR: ledgerDir, HOME: '/nonexistent-home' }
  return { cfgDir, dataDir, ledgerDir, env, clock }
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

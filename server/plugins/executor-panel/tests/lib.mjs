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

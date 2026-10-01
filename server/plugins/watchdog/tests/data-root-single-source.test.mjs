// 数据根单一真源缝锁（260930 直修，宿主令·不开票）：写侧（Watchdog 实例）与读侧（状态接口，
// 面板消费同一路径）必须落在**同一个**心跳文件上。
//
// 病灶（真机实报）：实例的数据根兜底读 `deps.configDirEnv`，而生产 ensureWatchdog 恒不传该
// deps ⇒ HOME 取空 ⇒ 退化成相对路径 `.sandbar/watchdog`（落控制台进程 cwd=仓根），而读侧看的是
// `~/.sandbar/watchdog` ⇒ 面板恒报「无心跳文件（守望者从未起过或已死）」——**写侧活着、读侧说它死**。
// 为什么以前全绿：测试一律注入 SANDBAR_WATCHDOG_DATA / dataDir（tests/lib.mjs），生产那条兜底
// 表达式一次都没被执行（注入即绕过）。故本棒**按生产形态构造**（不注入 dataDir / configDirEnv，
// 只给 HOME），并顺带钉住「除单一真源外无人再各算一份」。
import { mkdtempSync, rmSync, readFileSync, writeFileSync, mkdirSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { Watchdog, defaultIo, readHeartbeatFile } from '../src/host/core.ts'
import { watchdogDataDir } from '../src/host/config.ts'
import { assert, done } from './lib.mjs'

let n = 0
const project = 'rootproj'
const home = mkdtempSync(join(tmpdir(), 'wd-data-root-'))
const NOW = 1_700_000_000_000
const savedHome = process.env.HOME
const savedData = process.env.SANDBAR_WATCHDOG_DATA
const writes = []

try {
  // —— 生产形态：只有 HOME、没有 SANDBAR_WATCHDOG_DATA；构造时不传 dataDir / configDirEnv ——
  process.env.HOME = home
  delete process.env.SANDBAR_WATCHDOG_DATA

  const io = {
    tail: { stat: async () => ({ size: 0, ino: 1 }), read: async () => '', listArchives: async () => [] },
    heartbeat: {
      write: async (p, d) => { writes.push(p); mkdirSync(dirname(p), { recursive: true }); writeFileSync(p, d) },
      read: async (p) => readFileSync(p, 'utf8'),
      mtimeMs: async (p) => { try { return statSync(p).mtimeMs } catch { return null } },
    },
    appendAlerts: async (p) => { writes.push(p) },
    listAlerts: async () => [],
  }
  const w = new Watchdog(project, {
    configLoader: () => ({
      declared: true, enabled: true, config_error: null,
      config: {
        enabled: true, executor_session: '', stall_minutes: 15, reconcile_seconds: 60,
        alerts: {
          enabled: true, sound: true, desktop: true,
          night: { start: '23:00', end: '07:30', policy: 'redline-only' },
          redline: ['stall'], keep_days: 14,
        },
      },
      provenance: { file: 'mem', keys: {} },
    }),
    io,
    boardReader: async () => ({ ok: true, rows: [] }),
    wakeIo: null,
    now: () => NOW,
  })
  await w.start()
  await w.tickOnce()

  const root = watchdogDataDir(process.env)
  const expected = join(root, `${project}.heartbeat.json`)
  assert(writes.includes(expected), '写侧落在单一真源（watchdogDataDir）推出的心跳路径上：' + expected)
  assert(writes.every((p) => p.startsWith(root)), '每一次写都落在同一数据根下（旧病灶=相对路径 .sandbar/watchdog 落仓根）')

  // 读侧 = 面板/状态接口同款（readHeartbeatFile + 同一表达式推出的路径）。
  const hb = await readHeartbeatFile(defaultIo, expected, NOW + 500)
  assert(hb.alive === true, '读侧在同一路径上读到心跳 → alive=true（写读同源缝锁成立）')
  n += 3
  w.dispose()
} finally {
  if (savedHome === undefined) delete process.env.HOME; else process.env.HOME = savedHome
  if (savedData === undefined) delete process.env.SANDBAR_WATCHDOG_DATA; else process.env.SANDBAR_WATCHDOG_DATA = savedData
  rmSync(home, { recursive: true, force: true })
}

// 单一真源锁（源级，机械）：除 config.ts 的 watchdogDataDir 外，不得再有人各算一份数据根。
{
  const files = ['node.ts', 'src/host/core.ts', 'src/host/liveness.ts', 'src/host/session-create.ts', 'src/host/ledger-tail.ts']
  const offenders = files.filter((f) => {
    let s = ''
    try { s = readFileSync(new URL(f, import.meta.url), 'utf8') } catch { return false }
    return /SANDBAR_WATCHDOG_DATA\s*\|\|/.test(s)
  })
  assert(offenders.length === 0, '除 config.ts 的 watchdogDataDir 外无人再各算一份数据根（违者：' + (offenders.join('、') || '无') + '）')
  n += 1
}

done(n)

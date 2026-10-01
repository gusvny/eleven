// 事件账本落盘位置（t261001-12）：读侧（watchdog）与写侧（event_ledger.py）逐字同径。
//
// 钉死两种形状，任一侧漂移即红：
//   - 缺省（生产形状）：<projects_root>/<project>/ledger/events.jsonl
//   - 平铺兼容缝（语义不变）：SANDBAR_EVENT_LEDGER_DIR ⇒ <dir>/<project>.jsonl
//
// 跨语言一致性锁：**跑真的 python 解析器**比对输出（共享字面量不算锁——两侧行内
// 各写一份字面量正是漂移的来路）。端到端 rod：python 写侧 append 进临时
// projects root，node 读侧用缺省解析路径 tail 回读同一行（write side == read
// side，全程 tmp 目录，零生产数据）。
//
// 对 pre-fix 代码是红的（anti-proof）：旧读侧缺省=<repo>/server/ledger、旧写侧
// 缺省=引擎仓内平铺——本文件每一条缺省形状断言都不等价于旧行为。
import { spawnSync } from 'node:child_process'
import { mkdirSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join, resolve, basename } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Watchdog } from '../src/host/core.ts'
import { eventLedgerFile, projectsRoot } from '../src/host/config.ts'
import { LedgerTailer } from '../src/host/ledger-tail.ts'
import { assert, done, freshDir } from './lib.mjs'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
// python 解析器必须能 import temporalio（event_ledger 顶层依赖）⇒ 用引擎 venv。
const PY = join(REPO, 'server/engine/.venv/bin/python')
let n = 0

/** 跑真 python 解析器：输出 event_ledger.ledger_path(project)（env 由调用方钉）。 */
function pyLedgerPath(project, env) {
  const p = spawnSync(PY, ['-c',
    "import sys; sys.path.insert(0, 'server/engine'); import event_ledger as el; print(el.ledger_path(sys.argv[1]))",
    project], { cwd: REPO, encoding: 'utf8', env })
  if (p.status !== 0 || p.error) throw new Error('python resolver failed: ' + String(p.error) + ' status=' + p.status + ' ' + (p.stderr || '').slice(-300))
  return p.stdout.trim()
}

function freshEnv(extra = {}) {
  const home = freshDir('wd-ledgloc-')
  const env = {
    HOME: home,
    SANDBAR_PROJECTS_DIR: join(home, 'projects'),
    SANDBAR_WATCHDOG_DIR: join(home, 'projects'),
    SANDBAR_WATCHDOG_DATA: join(home, 'wd-data'),
  }
  delete env.SANDBAR_EVENT_LEDGER_DIR
  return Object.assign(env, extra)
}

// ① 跨语言形状锁（缺省 + 平铺缝，双向各跑一次 python）。
{
  const env = freshEnv()
  assert(pyLedgerPath('proj', env) === eventLedgerFile('proj', env),
    'cross-language: default shape identical (python ledger_path == ts eventLedgerFile)')
  const flat = join(env.HOME, 'flat')
  mkdirSync(flat, { recursive: true })
  const env2 = freshEnv({ SANDBAR_EVENT_LEDGER_DIR: flat })
  assert(pyLedgerPath('proj', env2) === eventLedgerFile('proj', env2),
    'cross-language: flat env seam identical')
  assert(basename(eventLedgerFile('proj', env)) === 'events.jsonl',
    'default active file is events.jsonl')
  assert(basename(eventLedgerFile('proj', env2)) === 'proj.jsonl',
    'flat seam keeps <project>.jsonl')
  n += 4
}

// ② 端到端：python 写侧 append（缺省形状）→ watchdog 读侧 tail 回读同一行。
{
  const env = freshEnv()
  const root = projectsRoot(env)
  // 写侧 enabled 闸需要「引擎所属项目」注册表条目（真规则：dirs 覆盖引擎仓根）。
  const alpha = join(root, 'alpha')
  mkdirSync(alpha, { recursive: true })
  writeFileSync(join(alpha, 'project.yaml'),
    'schema: v1\nproject:\n  - key: engine-owner\n    dirs:\n      - ' + REPO +
    '\nevent_ledger:\n  enabled: true\n  keep_days: 14\n  max_mb: 0\n')
  const p = spawnSync(PY, ['-c',
    "import sys; sys.path.insert(0, 'server/engine'); import event_ledger as el; " +
    "print(el.append_event({'project': 'proj', 'ticket': 't1', 'scope': 'project', 'state': 'running', 'seq': 7, 'run_id': 'r1', 'idem': 'k1'}))"],
    { cwd: REPO, encoding: 'utf8', env })
  if (p.status !== 0) throw new Error('python append failed: ' + (p.stderr || '').slice(-300))
  if (!p.stdout.includes("'emitted': True")) throw new Error('append not emitted: ' + p.stdout)

  // 读侧：watchdog 尾随器自己解析缺省路径（不经任何注入）。
  const active = eventLedgerFile('proj', env)
  const t = new LedgerTailer(dirname(active), 'proj', defaultIoTail(), 4096, { activeFile: basename(active) })
  const out = await t.poll()
  assert(out.unreadable === null && out.rows.length === 1 && out.rows[0].idem === 'k1' && out.rows[0].seq === 7,
    'e2e: python-written default-shape row read back by watchdog tailer')

  // 同一 env 下 Watchdog 状态面报的账本路径与写侧落点逐字同径。
  const savedEnv = { ...process.env }
  Object.assign(process.env, env)
  try {
    const w = new Watchdog('proj', {
      configLoader: () => ({
        declared: true, enabled: true, config_error: null,
        config: { enabled: true, executor_session: 's', stall_minutes: 15, reconcile_seconds: 60,
          alerts: { enabled: true, sound: true, desktop: true,
            night: { start: '23:00', end: '07:30', policy: 'silent' }, redline: ['stall'], keep_days: 14 } },
        provenance: { file: 'mem', keys: {} },
      }),
      io: undefined, boardReader: async () => ({ ok: true, rows: [] }), wakeIo: null,
    })
    assert(w.status().ledger.path === active, 'watchdog status ledger.path == python append target')
  } finally {
    process.env = savedEnv
  }
  n += 2
}

// ③ 平铺缝（SANDBAR_EVENT_LEDGER_DIR）：读侧语义不变（存量场景/夹具形状）。
{
  const flat = freshDir('wd-ledgflat-')
  const env = freshEnv({ SANDBAR_EVENT_LEDGER_DIR: flat })
  writeFileSync(join(flat, 'proj.jsonl'),
    JSON.stringify({ v: 'event-ledger-v1', idem: 'x1', project: 'proj', ticket: 't9', seq: 1, ts: '2026-10-01T00:00:00' }) + '\n')
  const savedEnv = { ...process.env }
  Object.assign(process.env, env)
  try {
    const w = new Watchdog('proj', {
      configLoader: () => ({
        declared: true, enabled: true, config_error: null,
        config: { enabled: true, executor_session: 's', stall_minutes: 15, reconcile_seconds: 60,
          alerts: { enabled: true, sound: true, desktop: true,
            night: { start: '23:00', end: '07:30', policy: 'silent' }, redline: ['stall'], keep_days: 14 } },
        provenance: { file: 'mem', keys: {} },
      }),
      boardReader: async () => ({ ok: true, rows: [] }), wakeIo: null,
    })
    await w.start()
    await w.tickOnce()
    const st = w.status()
    assert(st.ledger.path === join(flat, 'proj.jsonl'), 'flat seam: status path is <dir>/<project>.jsonl')
    assert(st.ledger.rows_seen === 1, 'flat seam: legacy shape still read unchanged')
    w.dispose()
  } finally {
    process.env = savedEnv
  }
  n += 2
}

// 真实 fs 的 TailIo（与 core.ts defaultIo.tail 同式，读缺省形状文件用）。
function defaultIoTail() {
  return {
    stat: async (p) => {
      if (!existsSync(p)) throw Object.assign(new Error('ENOENT: ' + p), { code: 'ENOENT' })
      const { statSync } = await import('node:fs')
      const s = statSync(p)
      return { size: s.size, ino: s.ino }
    },
    read: async (p, a, b) => {
      const { readFileSync, openSync, readSync, closeSync } = await import('node:fs')
      const fh = openSync(p, 'r')
      try {
        const buf = Buffer.alloc(b - a)
        const got = readSync(fh, buf, 0, b - a, a)
        return buf.toString('utf8', 0, got)
      } finally { closeSync(fh) }
    },
    listArchives: async () => [],
  }
}

done(n)

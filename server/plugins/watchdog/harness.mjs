/**
 * harness.mjs —— t260928-28 watchdog 集成场景的测试缝（一行 JSON 一命令，stdin/stdout）。
 *
 * 契约：integration/t260928-28/lib_watchdog_harness.py 头注（这是测试缝，不是产品行为）。
 * 驱动真实的 Watchdog 实例（src/host/core.ts 全注入）：注入时钟 / 内存账本 io /
 * board·engine·待办交互·会话投递四桩 / alerts 内存账——零 docker、零 3099/7233。
 *
 * 命令面：start / status / tick / restart / exit / append_ledger / rotate_ledger /
 * board_set / board_fail / engine_fail / session_face_set / session_progress /
 * session_digest / delivered_wakes / force_alert / clock_set / status_method_probe。
 *
 * 全终态：exit / restart 都 dispose 旧实例（清定时器）；进程收到 stdin EOF 同样收口。
 */

import { createInterface } from 'node:readline'
import { Watchdog, defaultIo, readHeartbeatFile } from './src/host/core.ts'
import { makeWakeIo } from './node.ts'

// ---------- 注入式时钟（ISO 字符串 ↔ ms；跨午夜/夜间窗用它拨） ----------
function makeClock(startMs) {
  let now = startMs
  return { now: () => now, set: (ms) => { now = ms }, advance: (ms) => { now += ms } }
}
function parseIso(s, fallback) {
  const t = Date.parse(s)
  return Number.isFinite(t) ? t : fallback
}

// ---------- 内存账本 io（harness 持有文件真值；轮转=真 rename 语义模拟） ----------
function memTail() {
  const files = new Map() // path -> {ino, content}
  let inoSeq = 1
  const archives = new Map() // project -> [{name, content}]
  const archiveCounter = new Map() // project -> int（轮转序号）
  return {
    files, archives, archiveCounter,
    io: {
      async stat(p) {
        const f = files.get(p)
        if (!f) throw Object.assign(new Error('ENOENT: ' + p), { code: 'ENOENT' })
        return { size: f.content.length, ino: f.ino }
      },
      async read(p, a, b) {
        const f = files.get(p)
        if (!f) throw Object.assign(new Error('ENOENT: ' + p), { code: 'ENOENT' })
        return f.content.slice(a, Math.min(b, f.content.length))
      },
      async listArchives(activePath) {
        const project = projectOf(activePath)
        return (archives.get(project) || []).map(a => a.name)
      },
    },
    activePath: (project) => '/ledg/' + project + '.jsonl',
    ensureActive(project) {
      const p = '/ledg/' + project + '.jsonl'
      if (!files.has(p)) files.set(p, { ino: ++inoSeq, content: '' })
      return p
    },
    append(project, line) {
      const p = this.ensureActive(project)
      files.get(p).content += line + '\n'
    },
    rotate(project, forcedIdx = null) {
      const p = this.ensureActive(project)
      const old = files.get(p)
      if (old.content.length > 0) {
        const counter = (archiveCounter.get(project) || 0) + 1
        const idx = forcedIdx ?? counter
        archiveCounter.set(project, idx)
        const name = `20260928-100000-${idx.toString(16)}.jsonl`
        const list = archives.get(project) || []
        list.push({ name, content: old.content })
        archives.set(project, list)
      }
      files.set(p, { ino: ++inoSeq, content: '' })
    },
  }
}
function projectOf(activePath) {
  return activePath.replace(/^\/ledg\//, '').replace(/\.jsonl$/, '')
}

// ---------- 内存 core io（alerts/heartbeat 账跨 restart 持久） ----------
function memCore() {
  const store = new Map()
  return {
    store,
    heartbeat: {
      async write(p, d) { store.set(p, d) },
      async read(p) { if (!store.has(p)) throw new Error('ENOENT'); return store.get(p) },
      async mtimeMs() { return null },
    },
    async appendAlerts(p, line) { store.set(p, (store.get(p) || '') + line + '\n') },
    async listAlerts(p) {
      const raw = store.get(p) || ''
      return raw.split('\n').filter(l => l !== '')
    },
  }
}

const tail = memTail()
const core = memCore()
const clock = makeClock(Date.parse('2026-09-28T10:00:00+08:00'))
const instances = new Map() // project -> Watchdog

// ---- 桩面（每个项目可覆写） ----
const boardStub = { rows: [], failMode: 'off' } // failMode: off | timeout
const engineStub = { fail: false }
const sessionStub = { pending: null, unreadable: false, reason: '', progressStopped: false, queueOccupied: false }

function boardReader() {
  return async () => {
    if (boardStub.failMode !== 'off') {
      return { ok: false, rows: [], error: `board 桩注入故障（${boardStub.failMode}）——真源不可达` }
    }
    return { ok: true, rows: boardStub.rows }
  }
}
function engineProbe() {
  return async () => engineStub.fail
    ? { online: false, detail: '引擎探针桩注入故障——显式 down，不假绿' }
    : { online: true, detail: '引擎探针桩在线' }
}
function pendingProvider() {
  return async () => {
    if (sessionStub.unreadable) return { available: false, pending: null, reason: sessionStub.reason || 'face probe stub down' }
    if (sessionStub.pending === null) return { available: true, pending: [] }
    const sid = 'executor-' + currentProject
    const pending = sessionStub.pending.map(p => ({
      raisedBy: p.raised_by_executor ? sid : (p.raised_by || 'other-session'),
      kind: p.kind || 'approval',
      target: p.id || p.target || 'unknown',
      sessionRunning: p.session_running ?? false,
    }))
    return { available: true, pending }
  }
}
function sessionStat() {
  return async () => ({ advanced: !sessionStub.progressStopped, mtimeMs: clock.now() })
}

// ---- t260929-04 协议缝：桩 sessionController（真实 makeWakeIo 的驱动对象） ----
// 契约=integration/t260929-04/lib_wake_harness.py 头注：session_stub_set /
// control_seed / control_frame / control_fail / delivered_wakes（收紧）。
// 灰盒锚公开契约（prompt 请求形状、SessionQueuedItem 的 id/placement/rpcId），
// 不锚 dsh 内部。prompt accepted 时桩按宿主语义把项入权威队列并广播 queue 帧
// （rpcId=prompt requestId 回显）——已消化判定由此可判定。
const stub = {
  present: true,
  promptResult: { accepted: true }, // {accepted:true} | {accepted:false,error} | 'throw'
  calls: [], // 每次 prompt 调用 {at, requestId, sessionId, mode, content, accepted, error?}
  queues: new Map(), // sessionId -> [SessionQueuedItem 形状]（权威队列真值）
  subscribers: new Set(), // 活跃 control 流订阅者（单进程内多路广播）
  idSeq: 1,
}
function stubBroadcast(frame) {
  for (const sub of stub.subscribers) sub.push(frame)
}
const stubController = {
  async prompt(req /* , signal */) {
    const pr = stub.promptResult
    if (pr === 'throw') throw new Error('session stub prompt injected failure')
    const accepted = !(pr && pr.accepted === false)
    const rec = {
      at: clock.now(), requestId: req.requestId, sessionId: req.sessionId,
      mode: req.mode, content: (req.content || []).map(c => (c && c.text) || '').join(''), accepted,
    }
    if (!accepted) rec.error = (pr && pr.error) || 'stub refused'
    stub.calls.push(rec)
    if (!accepted) {
      // 宿主拒绝形态=抛错（生产 prompt 捕获后转 accepted:false + 错误文本透传）
      throw new Error(rec.error)
    }
    const items = stub.queues.get(req.sessionId) ?? []
    const id = 'q-' + stub.idSeq++
    items.push({ id, placement: req.mode === 'steer' ? 'steering' : 'queued', rpcId: req.requestId, message: { id, content: req.content } })
    stub.queues.set(req.sessionId, items)
    stubBroadcast({ type: 'queue', sessionId: req.sessionId, items: [...items] })
    return { accepted: true }
  },
  control() { return makeControlStream() },
}
function stubValidItem(it) {
  return it !== null && typeof it === 'object' && typeof it.id === 'string'
}
/** control 流：订阅即推当前权威队列 baseline，之后广播增量 queue 帧；
 *  control_fail = 对在场订阅者注入流错误（一次性；新订阅照常=宿主侧恢复）。 */
function makeControlStream() {
  const sub = {
    pending: [], err: null, done: false, woke: null,
    push(frame) { this.pending.push(frame); if (this.woke) { const r = this.woke; this.woke = null; r() } },
    fail(e) { this.err = e; if (this.woke) { const r = this.woke; this.woke = null; r() } },
    end() { this.done = true; if (this.woke) { const r = this.woke; this.woke = null; r() } },
  }
  stub.subscribers.add(sub)
  const it = {
    next: async () => {
      for (;;) {
        if (sub.pending.length > 0) return { value: sub.pending.shift(), done: false }
        if (sub.err) throw sub.err
        if (sub.done) return { value: undefined, done: true }
        await new Promise(r => { sub.woke = r })
      }
    },
    return: async () => { stub.subscribers.delete(sub); return { value: undefined, done: true } },
  }
  const stream = { [Symbol.asyncIterator]: () => it }
  // 订阅即播种 baseline（权威队列当前快照）
  sub.push({ type: 'baseline', value: { queues: Object.fromEntries(stub.queues) } })
  return stream
}
// 生产 wakeIo：驱动真 makeWakeIo（请求形状/镜像语义/排除规则全在产品代码里）
const stubCtx = { get: (k) => (k === 'sessionController' ? (stub.present ? stubController : undefined) : undefined) }
const prodWakeIo = makeWakeIo(stubCtx)
function wakeIoFactory() {
  return prodWakeIo
}
function configLoaderFor(project, cfg) {
  const file = `/cfg/${project}/watchdog.json`
  const keys = {}
  for (const k of ['enabled', 'executor_session', 'stall_minutes', 'reconcile_seconds']) {
    keys[k] = cfg[k] !== undefined ? `${file}#${k}` : 'factory-default'
  }
  for (const k of Object.keys(cfg.alerts || {})) keys[`alerts.${k}`] = `${file}#alerts.${k}`
  return () => ({
    declared: true, enabled: cfg.enabled !== false, config_error: null,
    config: {
      enabled: cfg.enabled !== false,
      executor_session: cfg.executor_session !== undefined ? cfg.executor_session : ('executor-' + project),
      stall_minutes: cfg.stall_minutes ?? 15,
      reconcile_seconds: cfg.reconcile_seconds ?? 60,
      alerts: {
        enabled: cfg.alerts?.enabled !== false,
        sound: cfg.alerts?.sound !== false,
        desktop: cfg.alerts?.desktop !== false,
        night: cfg.alerts?.night || { start: '23:00', end: '07:30', policy: 'redline-only' },
        redline: cfg.alerts?.redline || ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'],
        keep_days: cfg.alerts?.keep_days ?? 14,
      },
    },
    provenance: { file, keys },
  })
}

let currentProject = null
const started = new Map() // project -> cfgOverride（restart 无参时按原样重启全部）
const cfgKey = (c) => JSON.stringify(c ?? null)

async function ensureInstance(project, cfgOverride = null) {
  let entry = instances.get(project)
  if (entry) {
    if (cfgKey(entry.cfgOverride) !== cfgKey(cfgOverride)) { entry.w.dispose(); instances.delete(project); entry = null }
  }
  if (!entry) {
    const cfg = cfgOverride || {}
    const w = new Watchdog(project, {
      configLoader: configLoaderFor(project, cfg),
      io: { tail: tail.io, heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
      boardReader: boardReader(),
      engineProbe: engineProbe(),
      wakeIo: wakeIoFactory(),
      pendingProvider: pendingProvider(),
      sessionStat: sessionStat(),
      now: clock.now,
      dataDir: '/memdata',
      ledgerDir: '/ledg',
    })
    entry = { w, cfgOverride }
    instances.set(project, entry)
    await w.start()
  }
  return entry.w
}

function statusPayload(project) {
  if (!instances.has(project)) {
    // 未声明：显式 declared:false（零行为，不冒充有数据）
    return {
      declared: false, enabled: false, phase: 'stopped', config_error: null,
      config_provenance: { file: null, keys: {} },
      heartbeat: { last_beat: null, age_seconds: null, alive: false, reason: '项目未声明守望者' },
      ledger: { path: '', watermark_offset: 0, rows_seen: 0, dupes_skipped: 0, malformed_rows: 0, gaps_seen: 0, last_row_at: null, unreadable: '项目未声明守望者' },
      liveness: { engine: { online: null, detail: '未探测', checked_at: null }, executor: null },
      self_lock: null, reconcile: null,
      startup: { missing_rows: null, replayed_rows: null, dedupe_keys: 0 },
      wakes: [], alerts: [], notify: { beep: false, unseen_redline: 0 }, last_error: null,
    }
  }
  return instances.get(project).w.status()
}

const LEVELS = { self_lock: 'redline', stall: 'redline', engine_down: 'redline', reconcile_mismatch: 'redline', ledger_unreadable: 'redline', reconcile_degraded: 'redline' }

async function handle(cmd) {
  const op = cmd.op
  if (op === 'exit') return { ok: true, bye: true }
  if (op === 'start') {
    currentProject = cmd.project
    if (!started.has(cmd.project)) started.set(cmd.project, cmd.config || null)
    else if (cmd.config) started.set(cmd.project, cmd.config)
    tail.ensureActive(cmd.project)
    const w = await ensureInstance(cmd.project, cmd.config || null)
    return { ok: true, project: cmd.project, phase: w.status().phase }
  }
  if (op === 'status') {
    const st = statusPayload(cmd.project)
    // 与 node.ts statusFor 同一 overlay：status() 的心跳占位由读盘面覆盖（缝契约=
    // 「status 回端点会返回的同一个对象」——arbitrate TS-1）
    if (instances.has(cmd.project)) {
      st.heartbeat = await readHeartbeatFile({ heartbeat: core.heartbeat }, `/memdata/${cmd.project}.heartbeat.json`, clock.now())
    }
    return { ok: true, status: st }
  }
  if (op === 'status_method_probe') {
    // 只读面刚性：非 GET 一律 405 形状（node.ts 路由同口径）
    if (cmd.method && cmd.method !== 'GET') return { rejected: true, code: 405 }
    return { rejected: false, code: 200, status: statusPayload(cmd.project) }
  }
  if (op === 'tick') {
    clock.advance((cmd.seconds || 0) * 1000)
    // 泵一拍（对账节拍按冷却与单飞语义收敛——多次 tick 只会在有新事实时再动）
    for (const [, entry] of instances) await entry.w.tickOnce()
    return { ok: true, now: clock.now() }
  }
  if (op === 'clock_set') {
    clock.set(parseIso(cmd.now, clock.now()))
    return { ok: true, now: clock.now() }
  }
  if (op === 'restart') {
    for (const [, entry] of instances) entry.w.dispose()
    instances.clear()
    if (cmd.project) {
      // 指定项目=换配置重启；否则按各自原配置重启全部（重启不重播语义的载体）
      if (cmd.config !== undefined) started.set(cmd.project, cmd.config)
      await ensureInstance(cmd.project, started.get(cmd.project))
    } else {
      for (const [proj, cfg] of started) await ensureInstance(proj, cfg)
    }
    return { ok: true }
  }
  if (op === 'append_ledger') {
    const line = cmd.raw !== undefined ? String(cmd.raw) : JSON.stringify(cmd.row)
    tail.append(cmd.project, line)
    if (cmd.skip_archive_no !== undefined) {
      // 造一个归档序号跳号：把当前活动账轮转进序号 N+1 的归档（N 从未存在）
      tail.rotate(cmd.project, cmd.skip_archive_no + 1)
    }
    return { ok: true }
  }
  if (op === 'rotate_ledger') {
    tail.rotate(cmd.project)
    return { ok: true }
  }
  if (op === 'board_set') {
    boardStub.rows = cmd.rows || []
    return { ok: true }
  }
  if (op === 'board_fail') {
    boardStub.failMode = cmd.mode || 'off'
    return { ok: true }
  }
  if (op === 'engine_fail') {
    engineStub.fail = Boolean(cmd.on)
    return { ok: true }
  }
  if (op === 'session_face_set') {
    if (cmd.unreadable) {
      sessionStub.unreadable = true
      sessionStub.reason = cmd.reason || ''
    } else {
      sessionStub.unreadable = false
      sessionStub.pending = cmd.pending || []
    }
    return { ok: true }
  }
  if (op === 'session_progress') {
    sessionStub.progressStopped = Boolean(cmd.stop)
    return { ok: true }
  }
  if (op === 'session_digest') {
    // 已消化=权威队列清空（广播空 queue 帧；镜像认领随之翻 false）
    for (const [sid, items] of stub.queues) {
      if (items.length > 0) {
        stub.queues.set(sid, [])
        stubBroadcast({ type: 'queue', sessionId: sid, items: [] })
      }
    }
    return { ok: true }
  }
  if (op === 'session_stub_set') {
    // 夹具 sessionController 形态注入：present:false = 宿主服务缺席（headless 形态）；
    // prompt_result = {accepted:true} | {accepted:false,error} | 'throw'。
    if (cmd.present !== undefined) stub.present = Boolean(cmd.present)
    if (cmd.prompt_result !== undefined) stub.promptResult = cmd.prompt_result
    return { ok: true, present: stub.present }
  }
  if (op === 'control_seed') {
    // 注入 baseline（整表替换）并广播到在场订阅者
    stub.queues = new Map(Object.entries(cmd.queues || {}))
    stubBroadcast({ type: 'baseline', value: { queues: Object.fromEntries(stub.queues) } })
    return { ok: true }
  }
  if (op === 'control_frame') {
    // 注入增量 queue 帧（整会话替换语义）；畸形项逐个计数显式回执，不入流
    const items = Array.isArray(cmd.items) ? cmd.items : []
    const good = items.filter(stubValidItem)
    const bad = items.length - good.length
    stub.queues.set(cmd.sessionId, good)
    stubBroadcast({ type: 'queue', sessionId: cmd.sessionId, items: good })
    return { ok: true, bad_items: bad, applied: good.length }
  }
  if (op === 'control_fail') {
    // 镜像流故障注入：在场订阅者收流错误（镜像终态 unreadable，显式 no-signal）；
    // 宿主侧活态随之丢失（权威队列清空）——新订阅照常=宿主恢复，故障不粘滞。
    for (const sub of stub.subscribers) sub.fail(new Error('control stream injected failure (' + (cmd.mode || 'error') + ')'))
    stub.queues = new Map()
    return { ok: true }
  }
  if (op === 'delivered_wakes') {
    // 排水面（t260929-04 收紧）：回全部**成功**投递并清（失败走 wake_failed alert 面，
    // 不冒充投递）；行带 requestId/sessionId（client-minted 锚），delivered=别名键。
    const all = stub.calls.splice(0, stub.calls.length)
    const wakes = all.filter(c => c.accepted).map(c => ({ ...c, session: c.sessionId }))
    return { ok: true, wakes, delivered: wakes }
  }
  if (op === 'force_alert') {
    const project = cmd.project || currentProject
    const entry = instances.get(project)
    if (!entry) return { ok: false, error: '项目未 start' }
    const w = entry.w
    const kind = cmd.kind || 'stall'
    const cfg = w.status().config_provenance // 只为判空
    const st = w.status()
    if (!st.enabled || st.declared === false) return { ok: true, spoken: false, muted: 'watchdog disabled' }
    const alertsEnabled = (currentCfgOf(project) || {})?.alerts?.enabled
    if (alertsEnabled === false) return { ok: true, spoken: false, muted: 'alerts disabled (config)' }
    // 直接走 core 的报警口：临时用一次 tick 之外的路（raise 为私有，这里等价复刻：
    // 通过注入的 appendAlerts 落账 + status.alerts 反映）
    const level = LEVELS[kind] || 'warn'
    const rec = { at: clock.now(), key: `${kind}:executor-${project}`, rule: kind, target: `executor-${project}`, level, title: `forced ${kind}`, detail: 'harness force_alert', night_muted: null }
    // 夜间口径判定（与 alert-rules 同规则）
    const night = st.config_provenance && null // 占位：真实判定在 core；此处按配置算
    const hour = new Date(clock.now()).getHours() + new Date(clock.now()).getMinutes() / 60
    const inNight = (() => {
      const p = (currentCfgOf(project) || {}).alerts?.night || { start: '23:00', end: '07:30', policy: 'redline-only' }
      const cur = new Date(clock.now()).getHours() * 60 + new Date(clock.now()).getMinutes()
      const toMin = (s) => { const [h, m] = s.split(':').map(Number); return h * 60 + m }
      const s = toMin(p.start), e = toMin(p.end)
      if (s === e) return false
      return s < e ? (cur >= s && cur < e) : (cur >= s || cur < e)
    })()
    const redlineList = (currentCfgOf(project) || {}).alerts?.redline || []
    const isRedline = level === 'redline' && redlineList.includes(kind)
    let muted
    if (!inNight) muted = false
    else {
      const policy = ((currentCfgOf(project) || {}).alerts?.night || {}).policy || 'redline-only'
      muted = policy === 'silent' ? true : policy === 'normal' ? false : !isRedline
    }
    rec.night_muted = muted
    void night; void hour; void cfg
    await core.appendAlerts(`/memdata/${project}.alerts.jsonl`, JSON.stringify(rec))
    return { ok: true, spoken: !muted, rec }
  }
  return { ok: false, error: '未知命令：' + op }
}

// start 时把 config 存一份给 force_alert 的夜间判定用
const cfgByProject = new Map()
const _ensureInstance = ensureInstance
ensureInstance = async function (project, cfgOverride = null) {
  if (cfgOverride) cfgByProject.set(project, cfgOverride)
  return _ensureInstance(project, cfgOverride)
}
function currentCfgOf(project) {
  return cfgByProject.get(project) || null
}

// ---------- stdin 主循环（EOF = 全终态收口） ----------
const rl = createInterface({ input: process.stdin })
// 命令严格串行（start 的异步启动面必须先于后续命令完成——协议是锁步协议）
let q = Promise.resolve()
rl.on('line', (line) => {
  if (line.trim() === '') return
  let cmd
  try { cmd = JSON.parse(line) } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: '命令不是合法 JSON: ' + e.message }) + '\n')
    return
  }
  q = q.then(() => handle(cmd)).then((reply) => {
    process.stdout.write(JSON.stringify(reply) + '\n')
    if (cmd.op === 'exit') {
      for (const [, entry] of instances) entry.w.dispose()
      process.exit(0)
    }
  }).catch((e) => {
    process.stdout.write(JSON.stringify({ ok: false, error: String(e && e.message || e) }) + '\n')
  })
})
rl.on('close', () => {
  for (const [, entry] of instances) entry.w.dispose()
  process.exit(0)
})
void defaultIo

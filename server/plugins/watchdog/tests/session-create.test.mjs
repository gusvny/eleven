// session-create UT（t260930-09）：按需代建决策矩阵 / preset 缺失点名拒绝 / cwd 真源 /
// 事件账形状与幂等 / 畸形输入显式拒绝 / 声明回写纪律。全部走桩，零真实宿主、零 3099/7233。
import {
  decideExecutorSession, ensureExecutorSession, presetReady, projectMainDir,
  readSessionEvents, appendSessionEventIo, sessionEventPath, EXECUTOR_PRESET_NAME,
} from '../src/host/session-create.ts'
import { writeExecutorSession } from '../src/host/config.ts'
import { assert, done, freshDir, cleanup } from './lib.mjs'

let n = 0
const okPreset = { ok: true }
const mainDir = { ok: true, cwd: '/tmp/proj-main' }

{
  // 纯决策矩阵（scope 1/2/4）。
  const d = decideExecutorSession
  let r = d({ declaredSessionId: '', knownSessionIds: [], hasWork: true, presetOk: true })
  assert(r.action === 'create', 'work + undeclared + preset ok = create')
  r = d({ declaredSessionId: '', knownSessionIds: [], hasWork: false, presetOk: true })
  assert(r.action === 'none', 'no work = no session (frozen legacy project stays untouched)')
  r = d({ declaredSessionId: '', knownSessionIds: [], hasWork: true, presetOk: false })
  assert(r.action === 'refused-preset', 'no usable preset = explicit refusal')
  r = d({ declaredSessionId: 'human-1', knownSessionIds: ['human-1'], hasWork: true, presetOk: true })
  assert(r.action === 'adopt', 'declared + present in host list = adopt')
  r = d({ declaredSessionId: 'human-1', knownSessionIds: null, hasWork: true, presetOk: true })
  assert(r.action === 'adopt', 'declared + host list unreadable = still adopt (never guess)')
  r = d({ declaredSessionId: 'human-1', knownSessionIds: ['other'], hasWork: true, presetOk: true })
  assert(r.action === 'recreate', 'declared id gone from host list + work = recreate')
  r = d({ declaredSessionId: 'human-1', knownSessionIds: ['other'], hasWork: false, presetOk: true })
  assert(r.action === 'none', 'declared id gone but no work = do NOT recreate')
  n += 7
}

function stubIo(created = 'new-session-1', list = null, fail = null) {
  let createCalls = 0
  return {
    io: {
      async create(input) {
        createCalls += 1
        if (fail) return { ok: false, error: fail }
        return { ok: true, sessionId: created, agentPreset: input.agentPreset }
      },
      async listSessionIds() { return list },
      calls: () => createCalls,
    },
    count: () => createCalls,
  }
}

function memEvents() {
  const store = new Map()
  return {
    eventIo: {
      async append(p, line) { store.set(p, (store.get(p) || '') + line + '\n') },
      async read(p) { return store.get(p) ?? '' },
    },
    store,
  }
}

async function ensure(over = {}) {
  const s = over.ioStub ?? stubIo()
  const ev = memEvents()
  const out = await ensureExecutorSession({
    project: 'p1', declaredSessionId: '', hasWork: true, env: {},
    io: s.io, eventIo: ev.eventIo, dataDir: '/tmp/wd-data', nowMs: 1234, presetName: EXECUTOR_PRESET_NAME,
    mainDir, preset: okPreset, ...over,
  })
  return { out, s, ev }
}

{
  // create：一条事件 + 声明回写 + 幂等（同输入不产生第二次 create）。
  const { out, s, ev } = await ensure()
  assert(out.action === 'create' && out.sessionId === 'new-session-1', 'create returns new session id')
  assert(s.count() === 1, 'exactly one host create call')
  assert(out.declaredWritten === true, 'created id written back to declaration')
  const raw = ev.store.get(sessionEventPath('/tmp/wd-data', 'p1')) || ''
  const rows = raw.split('\n').filter(Boolean).map((l) => JSON.parse(l))
  assert(rows.length === 1, 'exactly ONE provenance event for the create (scope 3/6)')
  assert(rows[0].action === 'create' && rows[0].by === 'watchdog' && rows[0].preset === EXECUTOR_PRESET_NAME && rows[0].at === 1234 && rows[0].cwd === '/tmp/proj-main', 'event names who/when/preset/cwd')
  const readBack = await readSessionEvents(ev.eventIo, sessionEventPath('/tmp/wd-data', 'p1'))
  assert(readBack.events.length === 1 && readBack.malformed_rows === 0, 'event ledger reads back clean')
  n += 6
}
{
  // preset 缺失：显式拒绝 + 点名 preset；绝不触碰宿主 create。
  const { out, s } = await ensure({ preset: { ok: false, error: 'executor preset 未安装：sandbar-executor（缺 /x/preset.yml）——显式拒绝' } })
  assert(out.action === 'refused-preset' && out.sessionId === null, 'missing preset = refused, no session')
  assert(out.reason.includes('sandbar-executor'), 'refusal names the missing preset')
  assert(s.count() === 0 && out.declaredWritten === false, 'no host create, no declaration write on refusal')
  n += 3
}
{
  // cwd 真源缺席：显式拒绝（绝不拿仓根/HOME 冒充项目主目录）。
  const { out, s } = await ensure({ mainDir: { ok: false, error: '项目注册表缺席：p1' } })
  assert(out.action === 'refused-cwd' && s.count() === 0, 'no project main dir = refused before any host call')
  n += 1
}
{
  // 宿主 create 失败：显式 refused + 原因透传（含宿主点名的 preset 错误族）。
  const { out } = await ensure({ ioStub: stubIo('', [], 'agent-preset/not-found: sandbar-executor (available: sandbar-integration)') })
  assert(out.action === 'refused' && out.reason.includes('agent-preset/not-found') && out.reason.includes('sandbar-executor'), 'host create failure surfaces the host-named preset error')
  n += 1
}
{
  // adopt：人的声明绝不替换（回归杆），事件恰好一条、declaredWritten=false。
  const { out, s } = await ensure({ declaredSessionId: 'human-1' })
  assert(out.action === 'adopt' && out.sessionId === 'human-1' && out.declaredWritten === false, 'adopt: human declaration never replaced')
  assert(s.count() === 0, 'adopt makes NO host create call')
  n += 2
}
{
  // recreate：声明 id 已从宿主消失且有活 → 建新会话 + 回写 + recreate 事件。
  const { out } = await ensure({ declaredSessionId: 'human-1', ioStub: stubIo('recreated-1', ['recreated-1']) })
  assert(out.action === 'recreate' && out.sessionId === 'recreated-1' && out.declaredWritten === true, 'recreate writes the new id back')
  n += 1
}
{
  // 无活：连事件都不落（彻底安静，非拒绝）。
  const { out, s } = await ensure({ hasWork: false })
  assert(out.action === 'none' && out.event === null && s.count() === 0, 'no work = fully silent, not even a refusal event')
  n += 1
}
{
  // 事件账坏行：显式计数，绝不冒充无事件/全好。
  const ev = memEvents()
  await appendSessionEventIo(ev.eventIo, '/x/events.jsonl', { at: 1, project: 'p', action: 'create', session_id: 's', preset: 'p', by: 'watchdog', cwd: '/c', reason: 'r' })
  const bad = {
    async append() {}, async read() { return '{"at":1,"action":"create"}\nnot-json\n' },
  }
  const r = await readSessionEvents(bad, '/x/events.jsonl')
  assert(r.events.length === 1 && r.malformed_rows === 1, 'malformed event rows counted explicitly')
  n += 1
}

{
  // presetReady：缺失/名字不符/就绪三种态（畸形输入用例——不靠真外部源）。
  const home = freshDir('preset-')
  const env = { DSH_HOME: home }
  let r = presetReady('sandbar-executor', env)
  assert(r.ok === false && r.error.includes('sandbar-executor'), 'preset missing = refusal naming it')
  const fs = await import('node:fs')
  const { join: j } = await import('node:path')
  fs.mkdirSync(j(home, '.agent-presets', 'sandbar-executor'), { recursive: true })
  fs.writeFileSync(j(home, '.agent-presets', 'sandbar-executor', 'preset.yml'), 'name: other\n')
  r = presetReady('sandbar-executor', env)
  assert(r.ok === false, 'name mismatch = refusal')
  assert(r.error.includes('other'), 'refusal names the actual name found')
  fs.writeFileSync(j(home, '.agent-presets', 'sandbar-executor', 'preset.yml'), 'name: sandbar-executor\ndescription: x\n')
  r = presetReady('sandbar-executor', env)
  assert(r.ok === true, 'well-formed preset = ready')
  cleanup([home])
  n += 4
}
{
  // projectMainDir：解析 project.yaml dirs 首项；缺席/无 dirs/空列表显式拒绝。
  const root = freshDir('projreg-')
  const env = { SANDBAR_WATCHDOG_DIR: root }
  const fs = await import('node:fs')
  const { join: j } = await import('node:path')
  fs.mkdirSync(j(root, 'p1'), { recursive: true })
  fs.writeFileSync(j(root, 'p1', 'project.yaml'), 'schema: v1\nproject:\n  - key: p1\n    dirs:\n      - /tmp/main-dir\n      - /tmp/second\n')
  let r = projectMainDir('p1', env)
  assert(r.ok === true && r.cwd === '/tmp/main-dir', 'main dir = first dirs entry')
  fs.writeFileSync(j(root, 'p1', 'project.yaml'), 'schema: v1\nproject:\n  - key: p1\n')
  r = projectMainDir('p1', env)
  assert(r.ok === false && r.error.includes('dirs'), 'no dirs list = explicit refusal')
  fs.writeFileSync(j(root, 'p1', 'project.yaml'), 'not: []{{{')
  r = projectMainDir('p1', env)
  assert(r.ok === false, 'malformed project.yaml = explicit refusal (no guessed cwd)')
  r = projectMainDir('BAD KEY!', env)
  assert(r.ok === false && r.error.includes('形状不合法'), 'invalid project key = refusal')
  cleanup([root])
  n += 4
}

{
  // writeExecutorSession：回写一键、幂等、畸形既有声明拒写、坏 id 拒写。
  const root = freshDir('wdecl-')
  const env = { SANDBAR_WATCHDOG_DIR: root }
  const fs = await import('node:fs')
  const { join: j } = await import('node:path')
  let r = writeExecutorSession('p1', 'sid-1', env)
  assert(r.written === true, 'write on undeclared project enrolls the declaration')
  let cfg = JSON.parse(fs.readFileSync(j(root, 'p1', 'watchdog.json'), 'utf8'))
  assert(cfg.executor_session === 'sid-1' && Object.keys(cfg).length === 1, 'file contains exactly the executor_session key')
  fs.writeFileSync(j(root, 'p1', 'watchdog.json'), JSON.stringify({ enabled: false, stall_minutes: 9 }))
  r = writeExecutorSession('p1', 'sid-1', env)
  assert(r.written === true, 'idempotent rewrite = ok')
  assert(JSON.parse(fs.readFileSync(j(root, 'p1', 'watchdog.json'), 'utf8')).enabled === false, 'other knobs preserved untouched')
  fs.writeFileSync(j(root, 'p1', 'watchdog.json'), '{broken json')
  r = writeExecutorSession('p1', 'sid-2', env)
  assert(r.written === false && (r.reason || '').includes('拒绝'), 'malformed existing declaration = refuse to write on top')
  r = writeExecutorSession('p1', '', env)
  assert(r.written === false, 'empty session id never written')
  r = writeExecutorSession('bad key', 'sid', env)
  assert(r.written === false, 'invalid project key never written')
  cleanup([root])
  n += 7
}
done(n)

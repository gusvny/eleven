/**
 * engine-grants-write.test.mjs —— KI-193 引擎写面（spawn 缝）UT（t261004-18）。
 *
 * 覆盖面（消费外部输入 ⇒ 畸形输入用例必带；spawn 四终态全收口）：
 *  - spawnEngineGrantsWrite 正常回执：saved:true 透传 file/resolved；
 *  - 非零退出（引擎拒收/缺依赖）：saved:false 点名原因，绝不回退；
 *  - 超时 kill（execFile timeout）：saved:false 点名 timeout；
 *  - spawn 异常（解释器不存在）：saved:false；
 *  - 回执畸形（非 JSON / 缺 saved 位）：saved:false 显式点名，不猜；
 *  - enginePython：env SANDBAR_ENGINE_PYTHON 优先，缺省 venv 在场用 venv。
 * 全部注入假 execFile，零真进程、零真实 ~/.sandbar、零 3099。
 */
import { assert, done } from './lib.mjs'
import { spawnEngineGrantsWrite, parseEngineReceipt, engineClientPath, enginePython } from '../src/host/executor-grants.ts'
import { existsSync } from 'node:fs'

let n = 0
const PAYLOAD = { key: 'alpha', by: 'host', grants: { sign: true }, source: { surface: 'panel-api' } }

function fakeExec(stdout, err) {
  let captured = null
  const fn = (cmd, args, opts, cb) => {
    captured = { cmd, args, opts }
    if (err && err.throwInSpawn) throw err.errno === 'THROW' ? new Error('spawn ENOENT') : err
    setTimeout(() => cb(err ?? null, stdout ?? ''), 0)
    return {}
  }
  fn.captured = () => captured
  return fn
}

// ---- 正常回执 ----
{
  const fn = fakeExec(JSON.stringify({ saved: true, file: '/x/executor-grants.json', resolved: { version: 1, grants: { sign: true } } }))
  const r = await spawnEngineGrantsWrite(PAYLOAD, { execFileFn: fn })
  assert(r.saved === true && r.file === '/x/executor-grants.json', `ok receipt passes through (${++n})`)
  const c = fn.captured()
  assert(c.args[1] === 'executor-grants-write' && c.args[2].includes('"key":"alpha"'), `cli invoked with the payload (${++n})`)
  assert(typeof c.opts.timeout === 'number' && c.opts.timeout > 0, `spawn carries a timeout (full-termination discipline) (${++n})`)
}

// ---- 非零退出（引擎拒收也要如实透传 saved:false + 引擎原因）----
{
  const fn = fakeExec(JSON.stringify({ saved: false, reason: '执行器元权限反锁' }), Object.assign(new Error('exit 1'), { killed: false }))
  const r = await spawnEngineGrantsWrite(PAYLOAD, { execFileFn: fn })
  assert(r.saved === false && r.reason.includes('元权限反锁'), `engine refusal text passes through (${++n})`)
}

// ---- 超时 kill ----
{
  const err = Object.assign(new Error('killed'), { killed: true })
  const fn = fakeExec('', err)
  const r = await spawnEngineGrantsWrite(PAYLOAD, { execFileFn: fn })
  assert(r.saved === false && r.reason.includes('timed out'), `timeout kill → saved:false naming the timeout (${++n})`)
}

// ---- spawn 异常（解释器不存在等）----
{
  const fn = fakeExec('', { throwInSpawn: true, errno: 'THROW' })
  const r = await spawnEngineGrantsWrite(PAYLOAD, { execFileFn: fn })
  assert(r.saved === false && r.reason.includes('could not spawn'), `spawn error → saved:false (${++n})`)
}

// ---- 回执畸形：非 JSON / 空 stdout / 缺 saved 位 ----
{
  const r1 = parseEngineReceipt('Traceback (most recent call last): ...')
  assert(r1.saved === false && r1.reason.includes('not valid JSON'), `malformed receipt (traceback) refused (${++n})`)
  const r2 = parseEngineReceipt('')
  assert(r2.saved === false && r2.reason.includes('KI-193'), `empty receipt refused (${++n})`)
  const r3 = parseEngineReceipt(JSON.stringify({ ok: true }))
  assert(r3.saved === false && r3.reason.includes('unexpected shape'), `receipt without saved bit refused (${++n})`)
  n += 0
}

// ---- enginePython：env 优先；venv 在场用 venv（本仓检出带 engine/.venv）----
{
  assert(enginePython({ SANDBAR_ENGINE_PYTHON: '/opt/py/bin/python' }) === '/opt/py/bin/python', `env interpreter wins (${++n})`)
  const venvExpected = engineClientPath().replace('client.py', '.venv/bin/python')
  if (existsSync(venvExpected)) {
    assert(enginePython({}) === venvExpected, `engine venv interpreter used when present (${++n})`)
  } else {
    assert(enginePython({}) === 'python3', `no venv in checkout → system python3 (${++n})`)
  }
}

// ---- t261004-41: component contract — every writable field round-trips the panel handler ----
{
  const { createApi } = await import('../src/host/api.ts')
  const { declarationPath } = await import('../src/host/executor-grants.ts')
  const { freshDir, cleanup, fakeClock, authPass } = await import('./lib.mjs')
  const { readFileSync } = await import('node:fs')
  const wd = freshDir(), pan = freshDir()
  const env = { HOME: '/nonexistent-home', SANDBAR_WATCHDOG_DIR: wd, SANDBAR_PANEL_DIR: pan, SANDBAR_PROJECTS_DIR: wd }
  const clock = fakeClock()
  const Q = (s) => new URLSearchParams(s)
  const PATH = '/sandbar-executor-panel/api/grants'
  const onDisk = () => JSON.parse(readFileSync(declarationPath('alpha', env), 'utf8'))
  // Capturing engine stub: records the payload the handler forwards, then writes it
  // through the real TS write core (same validation / atomic write as the engine side).
  const captured = []
  const api = createApi(env, {
    now: () => clock.now(),
    declaredEnabled: () => ({ declared: true, enabled: true }),
    authFace: authPass,
    engineGrantsWrite: async (p) => {
      captured.push(p)
      const { saveGrantsDecl } = await import('../src/host/executor-grants.ts')
      return saveGrantsDecl(p.key, p, p.by, env, clock.now(), '', p.source)
    },
  })
  try {
    // full-field save: every key the writable set declares travels and lands on disk
    const full = { grants: { sign: true }, night_tier: { enabled: true, until: clock.now() + 60_000 }, executor_sessions: ['sess-1'],
                   open_ticket_epics: ['epic-a', 'epic-b'], open_ticket_cap: 5, by: 'host' }
    const r = await api.handle('POST', PATH, Q('project=alpha'), JSON.stringify(full), '')
    assert(r.status === 200 && r.json.saved === true, `full-field save succeeds (${++n})`)
    const p = captured[captured.length - 1]
    assert(p.grants.sign === true, `payload carries grants (${++n})`)
    assert(p.executor_sessions[0] === 'sess-1', `payload carries executor_sessions (${++n})`)
    assert(JSON.stringify(p.open_ticket_epics) === '["epic-a","epic-b"]', `payload carries open_ticket_epics verbatim (${++n})`)
    assert(p.open_ticket_cap === 5, `payload carries open_ticket_cap verbatim (${++n})`)
    const d1 = onDisk()
    assert(JSON.stringify(d1.open_ticket_epics) === '["epic-a","epic-b"]' && d1.open_ticket_cap === 5, `declaration round-trips epics + cap (${++n})`)

    // inherited-when-absent: a partial edit must not wipe the epics or reset the cap
    const r2 = await api.handle('POST', PATH, Q('project=alpha'), JSON.stringify({ grants: { rerun: true }, by: 'host' }), '')
    assert(r2.json.saved === true, `partial save succeeds (${++n})`)
    const p2 = captured[captured.length - 1]
    assert(JSON.stringify(p2.open_ticket_epics) === '["epic-a","epic-b"]' && p2.open_ticket_cap === 5,
      `absent keys are inherited from the on-disk declaration, never wiped (${++n})`)
    const d2 = onDisk()
    assert(d2.open_ticket_epics.length === 2 && d2.open_ticket_cap === 5, `on-disk epics + cap survive a partial edit (${++n})`)

    // master toggle (both directions) must leave the epic list and cap untouched
    await api.handle('POST', PATH, Q('project=alpha'), JSON.stringify({ op: 'master', enabled: false, by: 'host' }), '')
    const d3 = onDisk()
    assert(d3.open_ticket_epics.length === 2 && d3.open_ticket_cap === 5, `master off keeps epics + cap (${++n})`)
    await api.handle('POST', PATH, Q('project=alpha'), JSON.stringify({ op: 'master', enabled: true, by: 'host' }), '')
    const d4 = onDisk()
    assert(d4.open_ticket_epics.length === 2 && d4.open_ticket_cap === 5, `master on keeps epics + cap (${++n})`)

    // explicit clear-all: the page always sends the key, so [] must land as []
    const r5 = await api.handle('POST', PATH, Q('project=alpha'), JSON.stringify({ grants: { sign: true }, open_ticket_epics: [], by: 'host' }), '')
    assert(r5.json.saved === true && onDisk().open_ticket_epics.length === 0, `explicit [] is a real clear-all (${++n})`)

    // malformed body: explicit refusal, no partial write, cap/epics keep prior values
    await api.handle('POST', PATH, Q('project=alpha'), JSON.stringify({ grants: { sign: true }, open_ticket_epics: ['epic-a'], open_ticket_cap: 5, by: 'host' }), '')
    const r6 = await api.handle('POST', PATH, Q('project=alpha'),
      JSON.stringify({ grants: { sign: true }, open_ticket_epics: 'all', by: 'host' }), '')
    assert(r6.status === 200 && r6.json.saved === false, `malformed epics value refused (${++n})`)
    const r7 = await api.handle('POST', PATH, Q('project=alpha'),
      JSON.stringify({ grants: { sign: true }, open_ticket_cap: true, by: 'host' }), '')
    assert(r7.json.saved === false, `boolean cap refused (${++n})`)
    const d7 = onDisk()
    assert(d7.open_ticket_epics.length === 1 && d7.open_ticket_cap === 5, `refusals leave the declaration untouched (${++n})`)
  } finally {
    cleanup([wd, pan])
  }
}

done(n)

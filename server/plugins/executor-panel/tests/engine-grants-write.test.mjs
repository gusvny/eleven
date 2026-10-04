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

done(n)

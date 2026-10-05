// one-shot-view UT（t261004-30）：结算账/运行记录/锁表三读面的显式降级、畸形行
// 计数、SETTLE_CAP 截断与 older_rows、路径词表与引擎 executor_oneshot.py 的漂移锁、
// cap 唯一旋钮（缺席=缺省 2 / 1-10 / unlimited / 畸形显式 error）、路由在表内可
// 达（GET 200，畸形 project 400）。全内存桩，零 3099。
import assert from 'node:assert'
import { readOneShotFace, fsOneShotIo, oneShotSettleFile } from '../src/host/one-shot-view.ts'
import { PANEL_API_ROUTES, createApi } from '../src/host/api.ts'
import { SETTLE_CAP } from '../src/host/one-shot-view.ts'

const KEY = 'proj-alpha'
const settleRow = { v: 1, at: 1000, project: KEY, ticket: 't-1', session: 's1', result: 'did it', surface: 'engine-oneshot' }
const runRow = { session_id: 's1', project: KEY, object_key: 'ticket:t1', started_at: 900, ended_at: 1000, outcome: 'ok', summary: 'did it' }

function stubIo(files) {
  return {
    existsSync: (f) => f in files,
    readFileSync: (f) => {
      if (!(f in files)) throw new Error('ENOENT ' + f)
      return files[f]
    },
  }
}

function filesFor(env) {
  return {
    [oneShotSettleFile(env, KEY)]: JSON.stringify(settleRow) + '\n',
    [env._dataDir + '/' + KEY + '.one-shot-runs.jsonl']: JSON.stringify(runRow) + '\n',
    [env._dataDir + '/' + KEY + '.one-shot-locks.json']: JSON.stringify({ v: 1, locks: [{ object_key: 'ticket:t1', session_id: 's1', acquired_at: 1, heartbeat_at: 2 }] }) + '\n',
  }
}

{
  // 全空项目：结算账/运行记录显式「还没有」，锁 = 真实空，cap = 缺省 2。
  const env = { SANDBAR_ONESHOT_SETTLE_DIR: '/t', SANDBAR_WATCHDOG_DIR: '/cfg', HOME: '/h', _dataDir: '/data' }
  // watchdogDataDir(env) 用 DSH_HOME/HOME 推导——把 data 目录钉到同一处。
  env.DSH_HOME = '/data/dsh'
  const dataDir = env._dataDir
  const files = {} // 全缺席：结算账 / 锁 / 运行记录都没有
  const face = readOneShotFace(stubIo(files), env, KEY)
  assert.equal(face.settles.ok, false, 'absent settle ledger degrades explicitly')
  assert.ok(face.settles.reason.includes('no bounded unit'), 'settle absence is named as "nothing finished yet", not an error')
  assert.equal(face.locks.ok, true, 'absent lock file = no in-flight session (ok, empty)')
  assert.equal(face.locks.entries.length, 0, 'no locks')
  assert.equal(face.runs.ok, false, 'absent runs journal degrades explicitly')
  assert.equal(face.cap.limit, 2, 'absent concurrency.json = default 2')
  void dataDir
}

{
  // 全量在场：行形读出、锁读出、cap 声明读出；畸形行计数。
  const env = { SANDBAR_ONESHOT_SETTLE_DIR: '/t', SANDBAR_WATCHDOG_DIR: '/cfg', HOME: '/h', DSH_HOME: '/dd/dsh', SANDBAR_WATCHDOG_DATA: '/wd' }
  const files = {
    [oneShotSettleFile(env, KEY)]: JSON.stringify(settleRow) + '\ngarbage\n',
    ['/wd/' + KEY + '.one-shot-runs.jsonl']: JSON.stringify(runRow) + '\n',
    ['/wd/' + KEY + '.one-shot-locks.json']: JSON.stringify({ v: 1, locks: [{ object_key: 'ticket:t1', session_id: 's1', acquired_at: 1, heartbeat_at: 2 }] }) + '\n',
    ['/cfg/' + KEY + '/concurrency.json']: JSON.stringify({ max_running: 5 }),
  }
  const face = readOneShotFace(stubIo(files), env, KEY)
  assert.equal(face.settles.ok, true, 'settle rows read')
  assert.equal(face.settles.rows[0].ticket, 't-1', 'settle row fields')
  assert.equal(face.settles.malformed_rows, 1, 'malformed settle row counted')
  assert.equal(face.locks.entries.length, 1, 'lock entry read')
  assert.equal(face.runs.rows.length, 1, 'run row read')
  assert.equal(face.cap.limit, 5, 'declared cap read')
  assert.ok(face.cap.source.endsWith('concurrency.json'), 'cap source named')
}

{
  // 畸形 cap 声明：显式 error，不冒充缺省。
  const env = { SANDBAR_ONESHOT_SETTLE_DIR: '/t', SANDBAR_WATCHDOG_DIR: '/cfg', HOME: '/h', DSH_HOME: '/dd/dsh', SANDBAR_WATCHDOG_DATA: '/wd' }
  const files = {
    ['/cfg/' + KEY + '/concurrency.json']: '{"max_running": 42}',
  }
  const face = readOneShotFace(stubIo(files), env, KEY)
  assert.equal(face.cap.limit, null, 'invalid cap = null limit')
  assert.ok(face.cap.error.includes('0-10'), 'invalid cap names the rule')
}

{
  // SETTLE_CAP 截断：老行进 older_rows，新行在前。
  const env = { SANDBAR_ONESHOT_SETTLE_DIR: '/t' }
  const many = Array.from({ length: SETTLE_CAP + 3 }, (_, i) =>
    JSON.stringify({ ...settleRow, at: i, ticket: 't-' + i }) + '\n').join('')
  const face = readOneShotFace(stubIo({ [oneShotSettleFile(env, KEY)]: many }), env, KEY)
  assert.equal(face.settles.rows.length, SETTLE_CAP, 'capped to SETTLE_CAP')
  assert.equal(face.settles.older_rows, 3, 'older rows counted')
  assert.equal(face.settles.rows[0].ticket, 't-' + (SETTLE_CAP + 2), 'newest first')
}

{
  // 漂移锁：面板读面路径词表 = 引擎 executor_oneshot.settle_file（<root>/<key>/one-shot-settle.jsonl）。
  const src = await import('node:fs').then(fs => fs.readFileSync(new URL('../../../engine/executor_oneshot.py', import.meta.url), 'utf8'))
  assert.ok(src.includes('executor-settle.jsonl'), 'engine settle file name unchanged')
  assert.ok(oneShotSettleFile({ SANDBAR_PROJECTS_DIR: '/p' }, KEY).endsWith('/p/' + KEY + '/ledger/executor-settle.jsonl'), 'panel reader follows the same path shape')
  assert.ok(oneShotSettleFile({ SANDBAR_PANEL_DIR: '/q' }, KEY).endsWith('/q/' + KEY + '/ledger/executor-settle.jsonl'), 'panel seam root still honored')
}

{
  // 路由：表内有 /api/one-shot（GET 可达），畸形 project 400，非 GET 405。
  assert.ok(PANEL_API_ROUTES.some(r => r.path === '/sandbar-executor-panel/api/one-shot'), 'route in table')
  const api = createApi({ SANDBAR_ONESHOT_SETTLE_DIR: '/t', HOME: '/h' }, {})
  const ok = await api.handle('GET', '/sandbar-executor-panel/api/one-shot', new URLSearchParams('project=' + KEY), '')
  assert.equal(ok.status, 200, 'GET one-shot reachable')
  assert.equal(ok.json.ok, true, 'face returned')
  const bad = await api.handle('GET', '/sandbar-executor-panel/api/one-shot', new URLSearchParams('project=BAD KEY'), '')
  assert.equal(bad.status, 400, 'malformed project key rejected')
  const m = await api.handle('POST', '/sandbar-executor-panel/api/one-shot', new URLSearchParams('project=' + KEY), '{}')
  // post-merge the panel write gate (401) refuses POSTs before the route branch;
  // either way a POST must never be served as a read (405 is the no-gate shape).
  assert.ok(m.status === 405 || m.status === 401, 'read-only: POST refused (' + m.status + ')')
}

console.log('one-shot-view ok')

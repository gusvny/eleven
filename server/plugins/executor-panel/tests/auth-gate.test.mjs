/**
 * auth-gate.test.mjs —— KI-193 写面凭据门 UT（t261004-18）。
 *
 * 覆盖面（工单 requirement 1 + review #3）：
 *  - 每个 POST 写端点无凭据 → 401，账本/声明/watchdog 字节逐位不动（硬保证在盘上字节，
 *    不在响应旗标）；
 *  - 401 先于输入解析：非 JSON 体 + 无凭据 = 401 不是 400；
 *  - 伪造 by + 无凭据 = 401（凭据门先于一切写逻辑）；
 *  - GET 不设门（读面开放，页面要能加载）；
 *  - defaultAuthFace 判定面：无 Host / cookie 缺席 / 名字不对 / 形状不对 / 形状合法。
 * 零真实 ~/.sandbar、零 3099、零网络。
 */
import { assert, done, freshDir, cleanup, isolatedEnv, memLedgerIo, fakeClock } from './lib.mjs'
import { createApi, defaultAuthFace } from '../src/host/api.ts'
import { createHash } from 'node:crypto'
import { readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'

let n = 0
const clock = fakeClock()
const Q = (s = '') => new URLSearchParams(s)

// ---- defaultAuthFace 判定面 ----
{
  const name = 'dsh-auth-' + createHash('sha256').update('127.0.0.1:3099').digest('base64url')
  const good = name + '=v1.cGF5bG9hZA.c2lnbmF0dXJl'
  assert(defaultAuthFace({ host: '127.0.0.1:3099', cookie: good }).ok === true, `auth face: well-shaped console cookie passes (${++n})`)
  assert(defaultAuthFace({}).ok === false, `auth face: no Host refused (${++n})`)
  assert(defaultAuthFace({ host: '127.0.0.1:3099' }).ok === false, `auth face: no cookie refused (${++n})`)
  assert(defaultAuthFace({ host: '127.0.0.1:3099', cookie: 'other=v1.a.b' }).ok === false, `auth face: wrong cookie name refused (${++n})`)
  assert(defaultAuthFace({ host: '127.0.0.1:3099', cookie: name + '=tok' }).ok === false, `auth face: malformed value shape refused (${++n})`)
  assert(defaultAuthFace({ host: 'other-host:1', cookie: good }).ok === false, `auth face: cookie bound to another authority refused (${++n})`)
}

// ---- 写端点 401 + 盘上字节不动 ----
const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
mkdirSync(join(wd, 'alpha'), { recursive: true })
const ledgerLine = JSON.stringify({ type: 'request', id: 'req-1', kind: 'sign', question: 'q?', detail: '', default_action: 'hold', options: [], expires_at: null, raised_by: '', at: 1 }) + '\n'
const ledgerFiles = { [join(pan, 'alpha', 'requests.jsonl')]: ledgerLine }
const declFile = join(wd, 'alpha', 'executor-grants.json')
const watchdogFile = join(wd, 'alpha', 'watchdog.json')
writeFileSync(declFile, '{"version":1,"grants":{"sign":true}}\n')
writeFileSync(watchdogFile, '{"enabled":true}\n')

// 授权写面走引擎入口桩（记录是否被调到——无凭据时必须一次都不调）。
let engineCalls = 0
const api = createApi(env, {
  now: () => clock.now(),
  ledgerIo: memLedgerIo(ledgerFiles),
  fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'stub' }),
  authFace: defaultAuthFace,
  engineGrantsWrite: async (p) => { engineCalls += 1; return { saved: true, file: declFile } },
})

const WRITE_CASES = [
  ['append', 'POST', '/sandbar-executor-panel/api/requests', '', JSON.stringify({ project: 'alpha', kind: 'sign', question: 'q?' })],
  ['answer', 'POST', '/sandbar-executor-panel/api/requests/answer', '', JSON.stringify({ project: 'alpha', id: 'req-1', answer: 'ok', by: 'someone-else' })],
  ['answer-malformed-body', 'POST', '/sandbar-executor-panel/api/requests/answer', '', 'not json'],
  ['settings-revoke', 'POST', '/sandbar-executor-panel/api/settings?project=alpha', '', JSON.stringify({ op: 'revoke' })],
  ['settings-save', 'POST', '/sandbar-executor-panel/api/settings?project=alpha', '', JSON.stringify({ op: 'save', config: { enabled: false } })],
  ['grants-save', 'POST', '/sandbar-executor-panel/api/grants?project=alpha', '', JSON.stringify({ grants: { sign: true } })],
  ['grants-master-on', 'POST', '/sandbar-executor-panel/api/grants?project=alpha', '', JSON.stringify({ op: 'master', enabled: true })],
]

for (const [label, method, path, , body] of WRITE_CASES) {
  const before = {
    ledger: JSON.stringify(ledgerFiles),
    decl: readFileSync(declFile, 'utf8'),
    watchdog: readFileSync(watchdogFile, 'utf8'),
  }
  const r = await api.handle(method, path.split('?')[0], new URLSearchParams(path.split('?')[1] ?? ''), body, '', {})
  assert(r.status === 401, `${label}: no credential → 401 (${++n})`)
  assert(typeof r.json.error === 'string' && r.json.error.length > 0, `${label}: refusal names a reason (${++n})`)
  assert(JSON.stringify(ledgerFiles) === before.ledger, `${label}: ledger bytes unchanged (${++n})`)
  assert(readFileSync(declFile, 'utf8') === before.decl, `${label}: grants declaration unchanged (${++n})`)
  assert(readFileSync(watchdogFile, 'utf8') === before.watchdog, `${label}: watchdog declaration unchanged (${++n})`)
}
assert(engineCalls === 0, `no-credential requests never reach the engine write face (${++n})`)

// ---- GET 不设门 ----
{
  const r = await api.handle('GET', '/sandbar-executor-panel/api/requests', Q('project=alpha'), '', '', {})
  assert(r.status === 200 && r.json.ok === true, `GET requests stays open (read surface) (${++n})`)
  const g = await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=alpha'), '', '', {})
  assert(g.status === 200, `GET grants stays open (${++n})`)
}

// ---- 带合法形状 cookie：写面放行（到达引擎写面）----
{
  const name = 'dsh-auth-' + createHash('sha256').update('127.0.0.1:3099').digest('base64url')
  const cookie = name + '=v1.cGF5bG9hZA.c2lnbmF0dXJl'
  const r = await api.handle('POST', '/sandbar-executor-panel/api/grants', Q('project=alpha'), JSON.stringify({ grants: { rerun: true } }), '', { host: '127.0.0.1:3099', cookie })
  assert(r.status === 200 && r.json.saved === true, `shaped cookie passes the gate and the write proceeds (${++n})`)
  assert(engineCalls === 1, `authed write reaches the engine write face exactly once (${++n})`)
}

cleanup([wd, pan])
done(n)

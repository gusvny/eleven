// t261009-03 场景：左栏拖拽的写脸落地——面板 POST reorder 真链穿到引擎
// （灰盒 L3，browser-free 池；隔离台 bootConsole + 真 admin.py/ticket.py/引擎，
// 离线秒级，零 docker 零 Temporal 零浏览器，零 3099 接触）。
//
// 用户场景（261009 宿主实报）：人在左栏拖一张排队票调优先级——面板把整排列
// POST 到 /sandbar-workbench/api/wf/concurrency/reorder；宿主路由把它转成
// {op:'concurrency', project, order} 经 runAdminCli spawn 到 ticket.py；引擎
// reorder 本已存在（排列校验、锁内落账、回新队列），但 ticket.py 只认
// reconcile，order 键被静默丢弃——拖拽看着就是「没反应」。本场景锁的用户
// 可感知契约：POST 落地（队列真换序）、随后 GET 同脸读回新序（一个读者面，
// 本地不另记顺序）、拒绝必现于响应体（侧栏 orderNotice 原样渲染的那段文本，
// 不假成功）、且任何拒绝路径账面字节不动、holder 槽位/队列条数永不变。
//
// 两层：
//   S0 隔离台：lib_fix17 bootConsole（临时 DSH_HOME + 随机高端口，freePort 拒
//      3099；teardownOnExit 全终态回收）。夹具 shim python3 与 fix17 同缝
//      （PATH 解析 + SANDBAR_REPO 夹具仓 .venv 软链），差异：op=concurrency
//      的 ticket call **不桩**——把 argv 里的夹具仓路径替换回真仓后透传真
//      解释器，真 admin.py→真 ticket.py→真引擎在 SANDBAR_PROJECTS_DIR 隔离
//      根上落账（KI-161：零生产写入）。其余 ticket op / ticket-list 桩空，
//      保证控制台其余脸离线（SANDBAR_TARGET_HOST 钉死端口）。
//   S1 断言面：node fetch + token 换 cookie 后直打路由 API——POST 响应体
//      （侧栏 notice 消费的同一形状）与 GET 读脸 + 磁上 state 文件三条读者
//      面互证；拒绝路径以 state 文件字节哈希锁「账面原封不动」。
//
// intent 分界（防 intent 级重复，核对全局用例清单后落界）：
//   - sc_t26100618_order_to_next_start.py（W1-W6）锁**引擎模块面**的真值表
//     与拒绝矩阵——本条不复断其任何一面；本条独占 **CLI op 面 + 宿主路由
//     POST 链**（ticket.py op=concurrency 吃下 order 键、runAdminCli 缝、
//     路由比较、响应体可达的具名拒绝），正是 261009 实报断掉的那一节；
//   - sc_t26100618_left_column_order.mjs（A1-A10）锁浏览器 DOM 面（API 在
//     页边界打桩）——notice 的渲染形态归它；本条在 HTTP 面锁「notice 将
//     原样渲染的那段具名拒绝文本确实到达客户端」，零浏览器；
//   - t261004-32-decl-fail-closed D5 锁只读 CLI 脸形状——本条不重复断其
//     形状细节，只把「读脸/对账行为不因写脸落地而变」作为回归面。
//
// KI 对齐：KI-161（隔离根零生产写入）；KI-188 族（拒绝路径绝不半写——字节
// 哈希锁）；KI-072（零墙钟断言——waited/position 只断在场不断数值）；
// KI-193（插件写端点身份面缺位的家族债：本条只在响应体断具名拒绝可达，
// 不新造身份闸——该债归其治本票）。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。实现段落地
// 前红属预期（TDD 信号：order 键被丢弃 → T2/T3 红）；arbitrate/merge 须绿。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, benchAuthUrl } from '../t260904-17/lib_fix17.mjs'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, writeFileSync, chmodSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const REPO = process.cwd()
const KEY = 'reorderface'
const CONC_GET = `/sandbar-workbench/api/wf/concurrency?project=${KEY}`
const CONC_POST = '/sandbar-workbench/api/wf/concurrency/reorder'

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
const j = (v) => JSON.stringify(v ?? null)
function rec(name, cond, detail = '') {
  record(name, cond ? 'pass' : 'fail', detail)
}

/** 真 python3（夹具 shim 透传目标）。 */
function realPython() {
  const r = spawnSync('which', ['python3'], { encoding: 'utf8' })
  const p = (r.stdout || '').trim()
  if (r.status !== 0 || !p) return null
  return p
}

/**
 * t261009-03 夹具 shim：与 fix17 同缝（PATH python3 + 夹具仓 .venv 软链；t261009-72
 * 起夹具仓经 config.repo 锚补丁声明，bootConsole 兜底建在同款路径），差异=
 * op=concurrency 的 ticket call 透传真链。返回 makeTicketStub 同形状对象（bootConsole
 * 只用 dir/ctrlPath/tracePath，engineRepo 由兜底 buildEngineRepo 现造）。
 */
function makeConcurrencyPassthroughStub(realPy) {
  // bootConsole 兜底在 stub.dir/engine-repo 现造夹具仓并经 config.repo 钉锚——锚取
  // 同一路径，shim 源码里按它做真仓替换（与兜底建仓路径必然一致）。
  const dir = mkdtempSync(join(tmpdir(), 't26100903-shim-'))
  const fakeRepoAnchor = join(dir, 'engine-repo')
  const ctrlPath = join(dir, 'ctrl.json')
  const tracePath = join(dir, 'trace.jsonl')
  writeFileSync(ctrlPath, JSON.stringify({}))
  writeFileSync(tracePath, '')
  const shim = `#!${realPy}
import sys, json, os
REAL = ${JSON.stringify(realPy)}
REPO = ${JSON.stringify(REPO)}
args = sys.argv[1:]
isAdmin = any(a.endswith('admin.py') for a in args)
isEngineList = (not isAdmin) and any(a.endswith('client.py') for a in args) and ('ticket-list' in args)
def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.exit(0)
if isEngineList:
    emit({'ok': True, 'result': {'count': 0, 'tickets': []}})
if not isAdmin:
    os.execv(REAL, [REAL] + args)
tool = None
payload = {}
try:
    i = args.index('call')
    tool = args[i + 1] if i + 1 < len(args) else None
    if i + 2 < len(args):
        payload = json.loads(args[i + 2])
except (ValueError, IndexError, json.JSONDecodeError):
    tool = None
if tool != 'ticket':
    os.execv(REAL, [REAL] + args)
op = str(payload.get('op', ''))
try:
    with open(os.environ['FIX17_TRACE'], 'a') as f:
        f.write(json.dumps({'op': op}) + chr(10))
except OSError:
    pass
if op == 'concurrency':
    # 被测真链：argv 里的夹具仓锚替换回真仓（admin.py 真身），解释器环境原样
    # 继承（SANDBAR_PROJECTS_DIR=隔离根已由台进程 env 带入）——真 ticket.py →
    # 真引擎在隔离根落账，被测缝与生产同构。
    newargs = [a.replace(${JSON.stringify(fakeRepoAnchor)}, REPO) for a in args]
    os.execv(REAL, [REAL] + newargs)
if op == 'list':
    emit({'ok': True, 'result': {'count': 0, 'tickets': []}})
emit({'ok': False, 'error': 't261009-03 fixture: ticket op ' + op + ' is not under test (stubbed)'})
`
  writeFileSync(join(dir, 'python3'), shim)
  chmodSync(join(dir, 'python3'), 0o755)
  return {
    dir, ctrlPath, tracePath, fakeRepoAnchor,
    readTrace() {
      return readFileSync(tracePath, 'utf8').split('\n').filter(Boolean)
        .map((l) => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
    },
  }
}

/** 布景：隔离根上用真引擎模块摆账（limit=2，t0 在跑、tH human-hold、t1/t2/t3 排队）。 */
function seed(root) {
  const py = realPython()
  const script = `
import sys, json, os
sys.path.insert(0, ${JSON.stringify(join(REPO, 'server', 'engine'))})
import shared, concurrency as cc
k = ${JSON.stringify(KEY)}
os.makedirs(os.path.join(os.environ['SANDBAR_PROJECTS_DIR'], k), exist_ok=True)
with open(os.path.join(os.environ['SANDBAR_PROJECTS_DIR'], k, 'concurrency-limit.json'), 'w') as f:
    json.dump({'version': 1, 'limit': 2}, f)
cc.acquire(k, 't0')
cc.acquire(k, 'tH')
cc.renew(k, 'tH', 'human-hold')
cc.acquire(k, 't1')
cc.acquire(k, 't2')
cc.acquire(k, 't3')
face = cc.read_state(k)
print(json.dumps({'queue': [e.get('ticket') for e in face['queue']],
                  'holders': sorted(h.get('ticket') for h in face['holders'])}))
`
  const r = spawnSync(py, ['-B', '-c', script], {
    cwd: REPO, encoding: 'utf8', timeout: 60000,
    env: { ...process.env, SANDBAR_PROJECTS_DIR: root },
  })
  if (r.status !== 0) throw new Error(`seed failed: ${(r.stderr || r.stdout || '').slice(0, 300)}`)
  return JSON.parse(r.stdout.trim().split('\n').pop())
}

const statePath = (root) => join(root, KEY, 'concurrency-state.json')
const sha = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')

async function main() {
  const realPy = realPython()
  if (!realPy) {
    console.log('ENV_FAIL: python3 unavailable — the real ticket.py chain cannot run')
    console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
    process.exit(2)
  }

  const projectsRoot = makeRegistryRoot('t26100903-registry-')
  writeProjectEntry(projectsRoot, KEY, KEY, ['/tmp/fx-reorderface'])
  const seeded = seed(projectsRoot)

  // 夹具 stub：dir/engine-repo 即 benchEnv 将造的夹具仓锚（shim 内已按同一路径
  // 固化真仓替换），dir 顶层的 python3 即 PATH shim 与 .venv 软链目标。
  const stub = makeConcurrencyPassthroughStub(realPy)

  let bench = null
  let cookie = ''
  try {
    bench = await bootConsole(projectsRoot, stub)
    teardownOnExit(bench.teardown)
    const authUrl = await benchAuthUrl(bench)
    const first = await fetch(authUrl, { redirect: 'manual' })
    const cookies = (first.headers.getSetCookie ? first.headers.getSetCookie() : [first.headers.get('set-cookie')])
      .filter(Boolean).map((c) => c.split(';')[0])
    cookie = cookies.join('; ')
  } catch (e) {
    console.log(`ENV_FAIL: stage console unavailable: ${String(e).slice(0, 200)}`)
    console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
    process.exit(2)
  }

  async function getConc() {
    const r = await fetch(`${bench.base}${CONC_GET}`, { headers: cookie ? { cookie } : {}, signal: AbortSignal.timeout(60000) })
    return { status: r.status, body: await r.json().catch(() => null) }
  }
  async function postReorder(order) {
    const r = await fetch(`${bench.base}${CONC_POST}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...(cookie ? { cookie } : {}) },
      body: JSON.stringify({ project: KEY, order }),
      signal: AbortSignal.timeout(120000),
    })
    return { status: r.status, body: await r.json().catch(() => null) }
  }
  const qOf = (face) => (Array.isArray(face?.body?.result?.queue) ? face.body.result.queue.map((e) => String(e?.ticket ?? e)) : null)
  const holdersOf = (face) => (Array.isArray(face?.body?.result?.holders) ? face.body.result.holders.map((h) => String(h?.ticket ?? h)).sort() : null)

  // T0 布景自证：读脸健康（261009 实报的半边——读脸本就好，本条只作前置）。
  const face0 = await getConc()
  rec('T0 pre: read face serves the seeded queue and holders (fixture sanity)',
    face0.status === 200 && face0.body?.ok === true
      && JSON.stringify(qOf(face0)) === JSON.stringify(['t1', 't2', 't3'])
      && JSON.stringify(holdersOf(face0)) === JSON.stringify(['t0', 'tH']),
    `status=${face0.status} ok=${face0.body?.ok} queue=${JSON.stringify(qOf(face0))} holders=${JSON.stringify(holdersOf(face0))} seeded=${JSON.stringify(seeded)}`)

  const bytes0 = sha(statePath(projectsRoot))
  const holdersBefore = holdersOf(await getConc())

  // T1（工单验收 L3 半边一）：面板 POST 全排列 → ok:true，响应队列=请求序。
  const want = ['t3', 't2', 't1']
  const p1 = await postReorder(want)
  rec('T1 POST reorder lands: ok:true, reply queue equals the requested order (route comparison can pass)',
    p1.status === 200 && p1.body?.ok === true && JSON.stringify(qOf(p1)) === JSON.stringify(want),
    `status=${p1.status} ok=${p1.body?.ok} body=${JSON.stringify(p1.body).slice(0, 300)}`)

  // T2（L3 半边二）：随后 GET 同一条读脸吐回新序——一个读者面，本地无第二份顺序。
  const face1 = await getConc()
  rec('T2 subsequent GET returns the NEW order from the one reader face',
    JSON.stringify(qOf(face1)) === JSON.stringify(want),
    `queue=${JSON.stringify(qOf(face1))}`)
  const positions = (face1.body?.result?.queue ?? []).map((e) => e?.position)
  rec('T2b read-face queue entries keep position numbers, renumbered 1-based in face order',
    positions.length === 3 && positions.every((p) => Number.isFinite(p)) && positions[0] === 1,
    `positions=${JSON.stringify(positions)}`)

  // T3 磁上读者面：state 文件真换了序（写者回执 ok 不算证据——读者侧真路径读出）。
  const disk = JSON.parse(readFileSync(statePath(projectsRoot), 'utf8'))
  const diskQ = (disk.queue ?? []).map((e) => String(e?.ticket ?? e))
  rec('T3 the on-disk state file carries the new order (reader-side disk face, not the writer receipt)',
    JSON.stringify(diskQ) === JSON.stringify(want), `disk queue=${JSON.stringify(diskQ)}`)

  // T4 语义不变量：holders 槽位原封不动（重排永不把排队票提成 holder），
  // 队列条数恒等（引擎不发明、不丢条目）。
  const holdersAfter = holdersOf(await getConc())
  rec('T4 reorder changes ONLY the queue order: holders keep their slots, no queued ticket promoted',
    JSON.stringify(holdersBefore) === JSON.stringify(holdersAfter) && holdersAfter.length === 2,
    `before=${JSON.stringify(holdersBefore)} after=${JSON.stringify(holdersAfter)}`)
  rec('T4b queue entry count never changes across a reorder',
    qOf(face1).length === 3, `len=${qOf(face1).length}`)

  // T5（409/拒绝路径，故意陈旧单）：读后让队列**成员集**变化——释放 t0 槽位把
  // 队首晋升出队（真引擎 release，非手改账）——此刻再 POST 旧的全排列单：
  // 成员已不齐，引擎必须具名拒绝（同成员集的换序本就是合法排列，引擎照收是
  // 对的，不构成本用例）；拒绝后绝不假成功、账面字节不动。
  function mutateMembership() {
    const py = realPython()
    const script = `
import sys, json, os
sys.path.insert(0, ${JSON.stringify(join(REPO, 'server', 'engine'))})
import concurrency as cc
k = ${JSON.stringify(KEY)}
print(json.dumps(cc.release(k, 't0', cause='paused')))
`
    const r = spawnSync(py, ['-B', '-c', script], {
      cwd: REPO, encoding: 'utf8', timeout: 60000,
      env: { ...process.env, SANDBAR_PROJECTS_DIR: projectsRoot },
    })
    if (r.status !== 0) throw new Error(`membership mutation failed: ${(r.stderr || r.stdout || '').slice(0, 300)}`)
  }
  mutateMembership()
  const afterMutation = qOf(await getConc())
  const bytes5 = sha(statePath(projectsRoot))
  const stale = await postReorder(want)
  const staleOk = stale.body?.ok === true
  const faceStale = await getConc()
  rec('T5 stale order (queue membership changed between read and POST) is REFUSED by name, never faked as success',
    staleOk === false && typeof stale.body?.error === 'string'
      && stale.body.error.includes('not a permutation of the current queue'),
    `status=${stale.status} ok=${staleOk} error=${j(stale.body?.error).slice(0, 220)}`)
  rec('T5b after the stale refusal the queue is UNCHANGED on the reader face',
    JSON.stringify(qOf(faceStale)) === JSON.stringify(afterMutation),
    `queue=${j(qOf(faceStale))} expected=${j(afterMutation)}`)
  rec('T5c the stale refusal leaves the state file byte-identical',
    sha(statePath(projectsRoot)) === bytes5, `bytes unchanged=${sha(statePath(projectsRoot)) === bytes5}`)

  // T6 拒绝文本可达面：POST 响应体的 error 就是侧栏 orderNotice 原样渲染的
  // 那段文本（A7 归浏览器场景；本条锁「文本确实到达客户端响应体」）。
  rec('T6 the named refusal reaches the client response body verbatim (the notice renders r.error as-is)',
    typeof stale.body?.error === 'string' && stale.body.error.length > 20,
    `error=${j(stale.body?.error).slice(0, 160)}`)

  // T7 负面注入：队列外的 id 塞不进 order——具名拒绝，账面字节不动，holder 不变。
  const bytes7 = sha(statePath(projectsRoot))
  const inj = await postReorder(['t3', 't2', 't1', 'tX'])
  rec('T7 an id NOT in the queue cannot be injected: named refusal, zero byte change',
    inj.body?.ok !== true && typeof inj.body?.error === 'string'
      && inj.body.error.includes('not a permutation of the current queue')
      && sha(statePath(projectsRoot)) === bytes7,
    `ok=${inj.body?.ok} error=${j(inj.body?.error).slice(0, 200)}`)

  // T8 空单对非空队=非排列，具名拒绝，字节不动。
  const bytes8 = sha(statePath(projectsRoot))
  const empty = await postReorder([])
  rec('T8 an empty order on a non-empty queue is refused (not a permutation), bytes unchanged',
    empty.body?.ok !== true && sha(statePath(projectsRoot)) === bytes8,
    `ok=${empty.body?.ok} status=${empty.status}`)

  // T9 全链真迹：被测缝确实走过真 ticket.py（trace 里有 op=concurrency 的
  // 透传记录）——防「桩替身假绿」（写者说成功、读者看不见的对面：测的其实
  // 不是被测链）。
  rec('T9 the route truly reached the real ticket.py chain (passthrough trace holds op=concurrency)',
    stub.readTrace().some((t) => t.op === 'concurrency'),
    `trace=${j(stub.readTrace()).slice(0, 200)}`)

  const p = results.filter((r) => r.status === 'pass').length
  const f = results.filter((r) => r.status === 'fail').length
  const e = results.filter((r) => r.status === 'env_fail').length
  const na = results.filter((r) => r.status === 'na').length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${na}`)
  process.exit(f > 0 ? 1 : (e > 0 || (p === 0 && f === 0 && na > 0) ? 2 : 0))
}

main().catch((e) => {
  console.log(`ENV_FAIL: scenario harness error: ${String(e && e.stack || e).slice(0, 300)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
})

// real-signals UT（t260929-08）：node.ts 三个真源接线的可单测面。
// 会话推进（list 形状走 mock controller——真宿主锁在 bench）；pending（真 fs 临时目录
// 走真 append/readRequests——真文件锁）；引擎探针（真本机 socket：本进程开的 listener
// 在线 / 关掉的端口离线）。零 3099/7233 触碰，零真实 ~/.sandbar。
import { assert, done, freshDir } from './lib.mjs'
import { appendRequest, fsLedgerIo } from '../../executor-panel/src/host/requests.ts'
import { detectSelfLock } from '../src/host/self-lock.ts'
import { judgeExecutor } from '../src/host/liveness.ts'
import { makePendingProvider, makeEngineProbe, makeSessionStat } from '../node.ts'

let n = 0
const EX = 'executor-sb'

// ── pending 真源：真文件（SANDBAR_PANEL_DIR 指进临时目录 + fsLedgerIo 真 fs）──
{
  const dir = freshDir('wd-panel-')
  process.env.SANDBAR_PANEL_DIR = dir
  const prov = makePendingProvider('projx', () => true)
  // 账不存在 = 真读过、确实没有挂起（available:true, 空 pending），不是 unknown。
  let r = await prov()
  assert(r.available === true && Array.isArray(r.pending) && r.pending.length === 0, 'missing ledger = genuinely no pending requests, not unknown')
  // 真追加两条：一条带归属 waiting、一条已应答——只有 waiting 进 pending。
  const a = appendRequest(fsLedgerIo, process.env, 'projx', { kind: 'approval', question: 'Merge T-1?', raised_by: EX }, Date.now())
  assert(a.ok === true, 'real append with attribution lands on the real file')
  const b = appendRequest(fsLedgerIo, process.env, 'projx', { kind: 'sign', question: 'Sign T-2?', raised_by: 'someone-else' }, Date.now())
  const { answerRequest } = await import('../../executor-panel/src/host/requests.ts')
  answerRequest(fsLedgerIo, process.env, 'projx', b.row.id, 'signed', 'host', Date.now())
  r = await prov()
  assert(r.available === true && r.pending.length === 1, 'only waiting rows surface as pending')
  const p = r.pending[0]
  assert(p.raisedBy === EX && p.target === a.row.id && p.sessionRunning === true, 'pending maps raised_by/target/sessionRunning from real sources')
  // 自锁端到端（真文件证据 → 纯判定）：归属 = executor → waiting_on_itself，不等超时。
  const v = detectSelfLock(r.pending, EX, Date.now())
  assert(v.state === 'waiting_on_itself' && v.target === a.row.id, 'real-file pending + attribution = waiting_on_itself immediately')
  // 未归属行（真追加无 raised_by）→ 判定不认空归属，显式点名。（独立 key：排除前一条归属行的干扰。）
  appendRequest(fsLedgerIo, process.env, 'projy', { kind: 'question', question: 'Legacy shape?' }, Date.now())
  const provY = makePendingProvider('projy')
  const r2 = await provY()
  const v2 = detectSelfLock(r2.pending, EX, Date.now())
  assert(v2.state === 'none' && v2.reason.includes('raised_by'), 'unattributed real row named explicitly, never fake none')
  // 坏 project key = 显式不可读（available:false），不冒充空。
  const bad = await makePendingProvider('../evil')()
  assert(bad.available === false && (bad.reason ?? '').length > 0, 'invalid project key = explicit unavailable with reason')
  n += 7
}

// ── 引擎探针：真本机 socket（自开 listener=在线；弃端口=离线）。──
{
  const net = await import('node:net')
  const srv = net.createServer()
  await new Promise(res => srv.listen(0, '127.0.0.1', res))
  const port = srv.address().port
  const up = await makeEngineProbe(port)()
  assert(up.online === true && up.detail.includes(String(port)), 'open local port probes online with named detail')
  srv.close()
  await new Promise(res => srv.close(res))
  const down = await makeEngineProbe(port)()
  assert(down.online === false && down.detail.length > 0, 'closed port probes offline with reason (refused = offline, inherited semantics)')
  n += 2
}

// ── 会话推进：list 形状走 mock controller（真宿主锁在 bench/host-session-signals-bench）。──
{
  const items = [{ sessionId: EX, updatedAt: 1000, running: true }]
  const ctx = { get: () => ({ list: async () => ({ items }) }) }
  const { stat, snapshot } = makeSessionStat(ctx)
  const s1 = await stat(EX, 500)
  assert(s1.advanced === true && s1.mtimeMs === 1000, 'updatedAt newer than watermark = advanced')
  const s2 = await stat(EX, 2000)
  assert(s2.advanced === false, 'updatedAt older than watermark = not advanced (real comparison, not constant)')
  assert(snapshot.runningOf(EX) === true, 'snapshot carries running bit from the same list read')
  assert((await stat('ghost-session', 0)).advanced === null, 'undeclared session = explicit null, not false')
  const emptyCtx = { get: () => undefined }
  const solo = makeSessionStat(emptyCtx)
  assert((await solo.stat(EX, 0)).advanced === null, 'host service absent = explicit null (honest no_signal)')
  // 宿主缺席时 judgeExecutor 落 no_signal（停摆判据退化为显式 no-signal，绝不假 stalled）。
  const j = judgeExecutor({ sessionKnown: true, ledgerAdvanced: false, sessionProgress: null, lastWakeAt: null }, 99_000, 15, 1000)
  assert(j.state === 'no_signal', 'unreadable session keeps judge honest (no_signal, never fake stalled)')
  n += 6
}
done(n)

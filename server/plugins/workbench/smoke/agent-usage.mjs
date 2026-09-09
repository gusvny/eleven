/**
 * smoke/agent-usage.mjs —— t260828-07「token 消耗聚合」冒烟（observability 立项）。
 *
 * 直跑：node smoke/agent-usage.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. stageWindowsFromTimeline（src/host/agent-usage.ts）：timeline running 条目 →
 *      时间窗（第 i 窗=[from_i, from_{i+1})，末窗开放式）；同 stage 重入多窗；
 *      非法/缺 at 过滤；空 timeline → 空数组。
 *   B. aggregateTicketUsage：真 zstd 压自制 jsonl 桩（zstd 不在 PATH 则整段跳过并说明）——
 *      usage 加总与 assistant/chunk 同名 usage 不计（防翻倍，review 意见 1）；
 *      模型归因（request/context，request/header 兜底）；按窗口落 stage；
 *      首窗前事件只进 total；畸形输入（坏 JSON/usage 缺字段/非数值/无 time）不炸；
 *      多文件加总；文件缺失/无 usage → exists=false + 人话 reason。
 *   C. resolveAllSessionFiles + agent-usage 路由：多角色全取（别工单不混入）；
 *      worktree='..' 越界 → 400（防穿，review 意见 2）；坏 id → 400；
 *      正常 → 200 带 byStage/models；无会话 → 200 {exists:false,reason}。
 */

import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { projectDirKey } from '../src/host/agent-live.ts'
import {
  aggregateTicketUsage, resolveAllSessionFiles, stageWindowsFromTimeline,
} from '../src/host/agent-usage.ts'
import { apply } from '../node.ts'

const execFileP = promisify(execFile)

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** 压一串事件成 session.jsonl.zstd（真 zstd；桩固定文件，不靠真外部会话）。 */
async function zpack(events, outPath) {
  const plain = join(tmp, `fix-${Math.random().toString(36).slice(2)}.jsonl`)
  await writeFile(plain, events.map(e => JSON.stringify(e)).join('\n') + '\n', 'utf8')
  await execFileP('zstd', ['-q', '-f', plain, '-o', outPath])
}

const tmp = await mkdtemp(join(tmpdir(), 'wb-usage-'))
try {
  /* ---------------------------------------------- A. stageWindowsFromTimeline */
  section('A stageWindowsFromTimeline（阶段时间窗派生）')
  {
    const tl = [
      { at: '2026-08-28T10:00:00', stage: 'create_plan', state: 'running' },
      { at: '2026-08-28T11:00:00', stage: 'implement', state: 'running' },
      { at: '2026-08-28T12:00:00', stage: 'review_plan', state: 'running' },
      { at: '2026-08-28T13:00:00', stage: 'implement', state: 'running' }, // rework 重入
      { at: '2026-08-28T14:00:00', stage: 'implement', state: 'blocked' }, // 非 running 不成窗
    ]
    const w = stageWindowsFromTimeline(tl)
    ok(w.length === 4, `4 条 running → 4 窗（实得 ${w.length}）`)
    ok(w[0].stage === 'create_plan' && w[0].toMs === new Date('2026-08-28T11:00:00').getTime(),
      '第 1 窗到第 2 窗起点（阶段迁移即边界）')
    ok(w[2].stage === 'review_plan' && w[2].toMs === new Date('2026-08-28T13:00:00').getTime(),
      '同角色跨 stage：第 3 窗 review_plan')
    ok(w[3].stage === 'implement' && w[3].toMs === null, '末窗开放式（toMs=null，晚到事件不落空）')
    ok(w[0].fromMs === new Date('2026-08-28T10:00:00').getTime(), 'fromMs=ISO 转 ms epoch')
    ok(stageWindowsFromTimeline([]).length === 0, '空 timeline → 空数组（整单加总不切段）')
    ok(stageWindowsFromTimeline([{ at: '垃圾', stage: 'x', state: 'running' }]).length === 0,
      '非法 at 过滤不炸')
    ok(stageWindowsFromTimeline(undefined).length === 0, 'undefined → 空数组')
    // 乱序输入按时间排序
    const w2 = stageWindowsFromTimeline([tl[2], tl[0], tl[1]])
    ok(w2.length === 3 && w2[0].stage === 'create_plan' && w2[2].stage === 'review_plan', '乱序按时间排序')
  }

  /* ---------------------------------------------------- B. aggregateTicketUsage */
  section('B aggregateTicketUsage（真 zstd 桩：加总/防翻倍/归因/窗口/畸形）')
  let hasZstd = true
  try { await execFileP('zstd', ['--version']) } catch { hasZstd = false }
  if (!hasZstd) {
    console.log('  （跳过 B/C 段：zstd 不在 PATH）')
  } else {
    const T0 = new Date('2026-08-28T10:00:00').getTime()
    const T1 = new Date('2026-08-28T11:00:00').getTime()
    const T2 = new Date('2026-08-28T12:00:00').getTime()
    const windows = [
      { stage: 'create_plan', fromMs: T0, toMs: T1 },
      { stage: 'implement', fromMs: T1, toMs: T2 },
      { stage: 'review_plan', fromMs: T2, toMs: null },
    ]
    const ev1 = [
      // 模型归因源：request/context
      { type: 'request/context', seq: 1, time: T0 + 1000, data: { provider: 'deepseek', model: 'm-alpha' } },
      // 窗口 1 的一条 usage……
      { type: 'assistant/message', seq: 2, time: T0 + 2000, data: { usage: { inputTokens: 100, outputTokens: 10, cacheReadTokens: 1000 } } },
      // ……以及它的 chunk 镜像（同一份 usage，加了就翻倍——review 意见 1 的防呆用例）
      { type: 'assistant/chunk', seq: 3, time: T0 + 2000, data: { chunk: { type: 'usage', usage: { inputTokens: 100, outputTokens: 10, cacheReadTokens: 1000 } } } },
      // 窗口 2（implement），换模型
      { type: 'request/context', seq: 4, time: T1 + 1000, data: { provider: 'deepseek', model: 'm-beta' } },
      { type: 'assistant/message', seq: 5, time: T1 + 2000, data: { usage: { inputTokens: 200, outputTokens: 20 } } },
      // 畸形输入一堆：坏 JSON、usage 缺字段、usage 非数值、无 time、usage 非对象——都不炸不多算
      { type: 'assistant/message', seq: 6, time: T1 + 3000, data: { usage: { inputTokens: 'abc', outputTokens: null } } },
      { type: 'assistant/message', seq: 7, data: { usage: { inputTokens: 5 } } }, // 无 time → 不落段
    ]
    const file1 = join(tmp, 'f1.zstd')
    await zpack(ev1, file1)

    const r1 = await aggregateTicketUsage([file1], windows)
    ok(r1.exists === true, '有 usage → exists=true')
    ok(r1.total.input === 305 && r1.total.output === 30, `total in=305/out=30（chunk usage 未计防翻倍；无 time 的畸形条也进 total）实得 in=${r1.total.input}/out=${r1.total.output}`)
    ok(r1.total.cacheRead === 1000, 'cacheRead 计入（UI 收悬停）')
    ok(r1.byStage.create_plan?.input === 100 && r1.byStage.create_plan?.cacheRead === 1000, '窗口 1 落 create_plan')
    ok(r1.byStage.implement?.input === 200 && r1.byStage.implement?.output === 20, '窗口 2 落 implement（同角色跨 stage 切分）')
    ok(r1.byStage.review_plan === undefined, '无事件的段不出现')
    // 模型分账：m-alpha 100/10、m-beta 200/20；畸形那条 0（值非法当 0）——分账总账对得上
    ok(r1.models.length === 2, `两个模型（多模型才显模型名的依据）实得 ${r1.models.length}`)
    const alpha = r1.models.find(m => m.model === 'm-alpha')
    const beta = r1.models.find(m => m.model === 'm-beta')
    ok(alpha?.input === 100 && beta?.input === 205, '模型归因跟 request/context 走（无 time 的畸形条归当前模型 beta）')
    ok(alpha.provider === 'deepseek' && beta.provider === 'deepseek', 'provider 一并归因')
    // 无 time 的畸形条（input 5）：进 total（300+5=305？不——inputTokens='abc' 非数值是 0；
    // seq7 的 5 无 time 只是不落段，total 仍收）→ total.input=305, byStage 合计 300
    ok(r1.total.input === 305, `无 time 的事件进 total 不落段（total 305 ≥ Σstage 300）实得 ${r1.total.input}`)

    // 首窗之前的事件：只进 total 不落段
    const evEarly = [
      { type: 'assistant/message', seq: 1, time: T0 - 60_000, data: { usage: { inputTokens: 50, outputTokens: 5 } } },
    ]
    const fEarly = join(tmp, 'early.zstd')
    await zpack(evEarly, fEarly)
    const rEarly = await aggregateTicketUsage([fEarly], windows)
    ok(rEarly.total.input === 50 && Object.keys(rEarly.byStage).length === 0, '首窗前事件只进 total（total ≥ ΣbyStage 口径）')

    // request/header 兜底（无 request/context 时）
    const fHdr = join(tmp, 'hdr.zstd')
    await zpack([
      { type: 'request/header', seq: 1, time: T0, data: { header: { config: { provider: 'zai', model: 'm-fallback' } } } },
      { type: 'assistant/message', seq: 2, time: T0 + 1, data: { usage: { inputTokens: 7, outputTokens: 1 } } },
    ], fHdr)
    const rHdr = await aggregateTicketUsage([fHdr], windows)
    ok(rHdr.models[0]?.model === 'm-fallback' && rHdr.models[0]?.input === 7, '无 request/context → request/header 兜底归因')

    // 多文件加总（多角色各一份）
    const rMulti = await aggregateTicketUsage([file1, fHdr], windows)
    ok(rMulti.files === 2 && rMulti.total.input === 305 + 7, `多角色文件加总（in=${rMulti.total.input}）`)
    ok(rMulti.exists === true, '多文件任一有 usage → exists')

    // 降级：文件不存在 / 压根无 usage / 全是坏行
    const rMiss = await aggregateTicketUsage([join(tmp, 'nope.zstd')], windows)
    ok(rMiss.exists === false && (rMiss.reason ?? '').includes('不存在'), '文件缺失 → exists=false + 人话 reason')
    const fEmpty = join(tmp, 'empty.zstd')
    await zpack([{ type: 'session', seq: 1 }], fEmpty)
    const rEmpty = await aggregateTicketUsage([fEmpty], windows)
    ok(rEmpty.exists === false && (rEmpty.reason ?? '') !== '', '无 usage 事件 → exists=false + reason')
    const fBad = join(tmp, 'bad.zstd')
    await writeFile(fBad, '这不是zstd内容'.repeat(100), 'utf8')
    const rBad = await aggregateTicketUsage([fBad], windows)
    ok(rBad.exists === false && (rBad.reason ?? '').includes('解压失败'), '坏文件 → 解压失败人话降级')
    // 混合：一份好 + 一份坏 → 好的照常出数
    const rMix = await aggregateTicketUsage([file1, fBad], windows)
    ok(rMix.exists === true && rMix.total.input === 305, '一份坏不毁整体加总')
    // 入参防呆（t260829-05）：paths 缺参/空数组不裸炸（原实现读 paths.length 会 TypeError），
    // 与「无会话文件」同一软降级出口（畸形输入用例，消费外部输入的实现必带）
    const rUndef = await aggregateTicketUsage(undefined, windows)
    ok(rUndef.exists === false && rUndef.files === 0 && (rUndef.reason ?? '') !== '', 'paths=undefined → exists=false 不炸（入参防呆）')
    const rNull = await aggregateTicketUsage(null, [])
    ok(rNull.exists === false && rNull.files === 0, 'paths=null → exists=false 不炸')
    const rNone = await aggregateTicketUsage([], [])
    ok(rNone.exists === false && rNone.files === 0 && (rNone.reason ?? '') !== '', 'paths=[] → exists=false + reason')
  }

  /* ---------------------------------------------------- C. resolveAll + 路由 */
  section('C resolveAllSessionFiles + agent-usage 路由')
  const repo = join(tmp, 'repo')
  const wt = join(repo, '.worktrees', 'wt')
  const slug = projectDirKey(wt)
  const sessDir = join(wt, '.dsh', 'sessions', slug)
  await mkdir(join(sessDir, 't-c-developer'), { recursive: true })
  await mkdir(join(sessDir, 't-c-integration'), { recursive: true })
  await mkdir(join(sessDir, 'other-ticket-developer'), { recursive: true })

  // 造带 usage 的会话桩（放在 resolveAll 之前：空目录 → 无文件降级路径已在 B/rNone 覆盖）
  {
    const T0 = Date.parse('2026-08-28T10:00:00')
    const T1 = Date.parse('2026-08-28T11:00:00')
    await zpack([
      { type: 'request/context', seq: 1, time: T0, data: { provider: 'deepseek', model: 'm-alpha' } },
      { type: 'assistant/message', seq: 2, time: T0 + 60_000, data: { usage: { inputTokens: 11, outputTokens: 2, cacheReadTokens: 33 } } },
    ], join(sessDir, 't-c-developer', 'session.jsonl.zstd'))
    await zpack([
      { type: 'assistant/message', seq: 1, time: T1 + 60_000, data: { usage: { inputTokens: 22, outputTokens: 4 } } },
    ], join(sessDir, 't-c-integration', 'session.jsonl.zstd'))
  }

  const rAll = await resolveAllSessionFiles(repo, 't-c', { worktree: '.worktrees/wt' })
  ok(rAll.refused === undefined && rAll.paths.length === 2, `多角色会话全取（实得 ${rAll.paths.length} 份）`)
  ok(rAll.paths.every(p => p.includes('t-c-')), '只取本工单会话（别工单不混入）')

  const rEsc = await resolveAllSessionFiles(repo, 't-c', { worktree: '..' })
  ok(rEsc.refused === true && (rEsc.reason ?? '').includes('越界'), 'worktree=.. → refused（防穿）')

  const rNone = await resolveAllSessionFiles(repo, 't-absent', { worktree: '.worktrees/wt' })
  ok(rNone.paths.length === 0 && (rNone.reason ?? '').includes('无本工单会话'), '无会话 → reason 降级')

  if (hasZstd) {
    await mkdir(join(repo, 'server'), { recursive: true })
    await writeFile(join(repo, 'server', 'admin.py'), `import json, sys
if len(sys.argv) >= 4 and sys.argv[1] == 'call' and sys.argv[2] == 'ticket':
    args = json.loads(sys.argv[3])
    if args.get('op') == 'show':
        tid = args.get('id')
        if tid == 't-escape':
            print(json.dumps({"ok": True, "result": {"id": tid, "worktree": ".."}}))
            sys.exit(0)
        print(json.dumps({"ok": True, "result": {"id": tid, "worktree": ".worktrees/wt", "role": "developer",
            "timeline": [
                {"at": "2026-08-28T10:00:00", "stage": "create_plan", "state": "running"},
                {"at": "2026-08-28T11:00:00", "stage": "implement", "state": "running"}
            ]}}))
        sys.exit(0)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`, 'utf8')

    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const prefix = routes.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/wf/tickets')
    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET') => ({ url, method, async *[Symbol.asyncIterator]() {} })
    const call = async (url) => {
      const res = mockRes()
      await prefix.handler(mockReq(url), res)
      return res
    }
    const pre = '/sandbar-workbench/api/wf/tickets'

    let r = await call(`${pre}/${encodeURIComponent('..%2F..%2Fetc')}/agent-usage`)
    ok(r.status === 400, '坏 id（../ 逃逸）→ 400（防穿）')

    r = await call(`${pre}/t-escape/agent-usage`)
    ok(r.status === 400, '工单 worktree=.. 逃逸 → 400（验收 4 硬项）')

    r = await call(`${pre}/t-c/agent-usage`)
    ok(r.status === 200 && r.body.ok === true, 'GET 200')
    ok(r.body.result.exists === true && r.body.result.files === 2, '多角色两份文件聚合')
    ok(r.body.result.total.input === 33 && r.body.result.total.output === 6,
      `total 加总 in=33/out=6（实得 in=${r.body.result.total?.input}）`)
    ok(r.body.result.models.length === 2, '两模型（developer 带 request/context 归因、integration 无 → 未知/未知）')

    r = await call(`${pre}/t-c/agent-usage`)
    ok(r.status === 200 && r.body.result.byStage.create_plan?.input === 11,
      '带 timeline → developer 的 usage 落 create_plan 窗（时间窗切分走通）')
    ok(r.body.result.byStage.implement?.input === 22, 'integration 无归因事件落 implement 窗（total 加总不受归因影响）')

    r = await call(`${pre}/t-no-session/agent-usage`)
    ok(r.status === 200 && r.body.result.exists === false && r.body.result.reason !== undefined,
      '无会话文件 → 200 {exists:false,reason} 软降级（验收 4）')
    // 只读端点无写分支：POST 不进 agent-usage 分支（落在路由层其它白名单路径上，此处不深究，
    // 写操作防护由 OPS 操作白名单把守——见 node.ts OPS）。
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)

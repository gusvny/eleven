/**
 * delivery-recovery.mjs —— t260903-09 S4：delivery/token 蒸发补账（KI-017①②③）。
 *
 * 覆盖（对码 C1 修正后的真实蒸发路径）：
 *  ① 泳道 git 失败（泳道拆了）→ 主仓归档口径回落（票 id grep 提交集，绕开
 *     base_ref/worktree 早退——直并收口票无这两字段也能补账）；
 *  ② 版本失配+重算失败（C1 绑定的真实覆盖路径）：engine_version 失配只作废
 *     时间维，delivery/tokens 存量降维保留+delivery_frozen 置位；
 *  ③ KI-017① 注入：泳道中途并 main 的膨胀区间 diff（8 万）不算进回落口径
 *     （提交集口径只数引用本票的提交）；
 *  ④ W4 双算面：一 commit 引用两票 id 时提交集口径双算（记录为已知行为，
 *     reason 不静默）；
 *  ⑤ 畸形 numstat（非数字/二进制'-'行）不计入不崩；token 泳道会话陪葬→
 *     prev.tokens 存量保留；账本缝（SUYOU_USAGE_LEDGER_DIR）探测。
 *
 * Run: node server/dsh/workbench/tests/delivery-recovery.mjs  (cwd = repo root)
 */
import {
  freshDir, writeStub, baseStub, closedTicket, NOW, STAGES, ok, summary,
} from './lib.mjs'
import { computeDelivery } from './../src/host/metrics.ts'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

const { buildMetricsResponse, defaultDeps, engineVersionOf, SOURCE_VERSION } = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)

/** 缓存目录布局（契约路径约定）：<SUYOU_METRICS_DIR>/<project>/data/metrics/。 */
async function mkCacheDir(prefix) {
  // env 语义 = 根（SUYOU_METRICS_DIR），实现内部再拼 <project>/data/metrics/
  const root = freshDir(prefix)
  const dir = join(root, 'demo', 'data', 'metrics')
  await mkdir(dir, { recursive: true })
  return { root, dir }
}

const savedStub = process.env.SUYOU_METRICS_STUB
const savedDir = process.env.SUYOU_METRICS_DIR
const savedLedger = process.env.SUYOU_USAGE_LEDGER_DIR

const gitDeps = (pairs, repo = '/stub-repo') => ({
  repo,
  git: async (cwd, args) => {
    const key = `${cwd}::${args.join(' ')}`
    if (!(key in pairs)) throw new Error(`stub git 未备：${key}`)
    return pairs[key]
  },
  now: () => NOW,
})

// ---- ① 泳道在：活口径不变（frozen=false）
{
  console.log('① 泳道在且 git 可读：三点 diff 活口径，frozen=false')
  const repo = '/stub-repo'
  const lane = `${repo}/.worktrees/lane1`
  const d = await computeDelivery(gitDeps({
    [`${lane}::diff main...HEAD --numstat`]: '100\t20\ta.ts\n30\t5\tb.ts',
    [`${lane}::rev-list --count main..HEAD`]: '3\n',
  }, repo), { id: 't09-lane1', base_ref: 'main', worktree: '.worktrees/lane1' })
  ok('泳道口径 add/del/commits', d.delivery.add === 130 && d.delivery.del === 25 && d.delivery.commits === 3, JSON.stringify(d))
  ok('活口径不冻结', d.frozen === false)
}

// ---- ①b 直并票（无 base_ref/worktree）→ 主仓回落成功
{
  console.log('①b 直并票：字段缺失不再早退，主仓 grep 提交集补账，frozen=true')
  const d = await computeDelivery(gitDeps({
    '/stub-repo::log --format=%H --grep t09-squash': 'h1\nh2\n',
    '/stub-repo::log --grep t09-squash --numstat --format=': '500\t120\ta.ts\n50\t30\tb.ts',
  }), { id: 't09-squash' })
  ok('回落口径 add/del', d.delivery.add === 550 && d.delivery.del === 150, JSON.stringify(d))
  ok('commits=提交集大小', d.delivery.commits === 2)
  ok('frozen=true（归档口径）', d.frozen === true)
  ok('reason 显式标注归档口径', String(d.reason ?? '').includes('归档口径'), String(d.reason))
}

// ---- ③ KI-017① 注入：泳道中途并 main → 回落口径不计 main 进度
{
  console.log('③ KI-017①：泳道区间 8 万膨胀 vs 提交集 550 —— 回落不吃 main 进度')
  const repo = '/stub-repo'
  const lane = `${repo}/.worktrees/t09-ki`
  // 泳道拆了：git 抛错（目录消失同路径）——活区间 diff 若还在会吸收 main 进度（8 万），
  // 但回落口径只数引用本票的提交（550 行）。
  const d = await computeDelivery(gitDeps({
    [`${lane}::diff main...HEAD --numstat`]: Promise.reject(new Error('ENOENT: lane gone')),
    '/stub-repo::log --format=%H --grep t09-ki': 'h1\n',
    '/stub-repo::log --grep t09-ki --numstat --format=': '500\t120\ta.ts\n50\t30\tb.ts',
  }, repo), { id: 't09-ki', base_ref: 'main', worktree: '.worktrees/t09-ki' })
  ok('回落 add=550（≠ 泳道区间会显示的 80000+）', d.delivery.add === 550, JSON.stringify(d))
  ok('KI-017① 收口：frozen=true + 归档 reason', d.frozen === true && String(d.reason).includes('归档口径'))
}

// ---- ④ W4 双算面：一 commit 引用两票 id → 提交集口径两票各计一次（已知行为）
{
  console.log('④ W4：一 commit 双票 id 双算（记录为已知行为，reason 不静默）')
  const pairs = {
    '/stub-repo::log --format=%H --grep t09-mA': 'shared-h\n',
    '/stub-repo::log --grep t09-mA --numstat --format=': '100\t10\ta.ts',
    '/stub-repo::log --format=%H --grep t09-mB': 'shared-h\n',
    '/stub-repo::log --grep t09-mB --numstat --format=': '100\t10\ta.ts',
  }
  const da = await computeDelivery(gitDeps(pairs), { id: 't09-mA' })
  const db = await computeDelivery(gitDeps(pairs), { id: 't09-mB' })
  ok('双票各计同一提交（add 均 100，双算面存在）', da.delivery.add === 100 && db.delivery.add === 100)
  ok('两票 reason 都显式标注提交集口径', String(da.reason).includes('归档口径') && String(db.reason).includes('归档口径'))
  console.log('    注：双算面=提交集口径已知边界（契约文档已注明），根治需 per-commit 归属归档（引擎侧 KI-017③ 同批）')
}

// ---- ⑤ 畸形 numstat + 双路全失败
{
  console.log('⑤ 畸形 numstat 忽略不崩；双路全失败 null+人话 reason')
  const d1 = await computeDelivery(gitDeps({
    '/stub-repo::log --format=%H --grep t09-bad': 'h1\n',
    '/stub-repo::log --grep t09-bad --numstat --format=': 'abc\tdef\tweird.txt\n-\t-\tbinary.png\n12\t3\tok.ts',
  }), { id: 't09-bad' })
  ok('畸形行忽略、二进制行计 0、正常行计入', d1.delivery.add === 12 && d1.delivery.del === 3, JSON.stringify(d1))
  const d2 = await computeDelivery(gitDeps({}), { id: 't09-nothing' })
  ok('双路失败：delivery=null', d2.delivery === null)
  ok('双路失败 reason 人话（含泳道+主仓）', String(d2.reason ?? '').includes('git 读取失败') || String(d2.reason ?? '').includes('主仓无引用'), String(d2.reason))
}

// ---- ② 版本失配+重算失败：降维保留 + frozen 置位（C1 绑定路径）
{
  console.log('② 版本失配+重算失败：delivery/tokens 存量保留、时间维重算、frozen 置位')
  const { root: cacheRoot, dir: cacheDir } = await mkCacheDir('t09-del-cache-')
  const stubDir = freshDir('t09-del-stub-')
  const oldEngine = 'old-engine-000'
  const prevRec = {
    ticket_id: 't09-stale', template: 'dev-lane',
    durations: { by_stage: { ghost_stage: 999 }, by_round: { ghost_stage: 999 }, human_wait: 0 },
    delivery: { base: 'main', add: 777, del: 55, commits: 4 },
    tokens: { by_stage: {}, by_model: { 'x/y': 12345 }, in: 9000, out: 3345, cacheRead: 0 },
    open: false, delivery_frozen: false,
    source_version: SOURCE_VERSION, engine_version: oldEngine,
    updated_ts: new Date(NOW - 86400e3).toISOString(), computed_at: new Date(NOW - 86400e3).toISOString(),
  }
  await mkdir(cacheDir, { recursive: true })
  await writeFile(join(cacheDir, 't09-stale.json'), JSON.stringify(prevRec), 'utf8')
  // 现行 stages 链与 stub 同源 → engineVersionOf(STAGES) ≠ oldEngine → engineStale
  process.env.SUYOU_METRICS_DIR = cacheRoot
  process.env.SUYOU_METRICS_STUB = writeStub(stubDir, baseStub({
    tickets: [closedTicket('t09-stale', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })],
  }))
  // 泳道会话已拆（stub repo 无 .dsh/sessions）+ 无账本 → token 现算失败 → 存量保留
  delete process.env.SUYOU_USAGE_LEDGER_DIR
  const deps = defaultDeps('/stub-repo', () => NOW)
  const r = await buildMetricsResponse({ view: 'time', window: '7d' }, deps)
  ok('200', r.status === 200, JSON.stringify(r.body).slice(0, 300))
  ok('tokens 存量保留（tokens_total=12345）', r.body.kpis.tokens_total === 12345, JSON.stringify(r.body.kpis))
  ok('reason 带「归档口径」标注（KI-017②）', String(r.body.reason ?? '').includes('归档口径'), String(r.body.reason ?? '').slice(0, 200))
  const after = JSON.parse(await readFile(join(cacheDir, 't09-stale.json'), 'utf8'))
  ok('落盘 rec：delivery 存量保留', after.delivery?.add === 777)
  ok('落盘 rec：delivery_frozen 置 true（死字段激活）', after.delivery_frozen === true)
  ok('落盘 rec：时间维已按现行链重算（ghost_stage 消失）', after.durations.by_stage.ghost_stage === undefined)
  ok('落盘 rec：engine_version 已刷新', after.engine_version === engineVersionOf(STAGES))
  ok('落盘 rec：锚点已入缓存（created_ms/closed_ms）', Number.isFinite(after.created_ms) && Number.isFinite(after.closed_ms))
}

// ---- 账本缝：SUYOU_USAGE_LEDGER_DIR 探测
{
  console.log('⑥ 项目级 usage 账本缝：未配置显式 reason、配置后可聚合（前向契约）')
  const { resolveLedgerSessionFiles } = await import(new URL('./../src/host/agent-usage.ts', import.meta.url).pathname)
  delete process.env.SUYOU_USAGE_LEDGER_DIR
  const r1 = await resolveLedgerSessionFiles('t09-led')
  ok('未配置：paths 空 + reason 提 KI-017③', r1.paths.length === 0 && String(r1.reason).includes('KI-017③'), String(r1.reason))
  const ledger = freshDir('t09-ledger-')
  await mkdir(join(ledger, 't09-led'), { recursive: true })
  await writeFile(join(ledger, 't09-led', 's.jsonl.zstd'), 'not-zstd-but-probed', 'utf8')
  process.env.SUYOU_USAGE_LEDGER_DIR = ledger
  const r2 = await resolveLedgerSessionFiles('t09-led')
  ok('配置后：探测到文件（聚合通路复用同参）', r2.paths.length === 1 && r2.reason === undefined, JSON.stringify(r2))
  const r3 = await resolveLedgerSessionFiles('t09-absent')
  ok('账本无本票目录：人话 reason', r3.paths.length === 0 && String(r3.reason).includes('无本票目录'))
  delete process.env.SUYOU_USAGE_LEDGER_DIR
}

process.env.SUYOU_METRICS_STUB = savedStub
process.env.SUYOU_METRICS_DIR = savedDir
if (savedLedger === undefined) delete process.env.SUYOU_USAGE_LEDGER_DIR
else process.env.SUYOU_USAGE_LEDGER_DIR = savedLedger
process.exit(summary('delivery-recovery') ? 0 : 1)

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
 *     prev.tokens 存量保留；账本缝（SANDBAR_USAGE_LEDGER_DIR）探测。
 *
 * Run: node server/plugins/workbench/tests/delivery-recovery.mjs  (cwd = repo root)
 */
import {
  freshDir, writeStub, baseStub, closedTicket, NOW, STAGES, ok, summary,
} from './lib.mjs'
import { computeDelivery } from './../src/host/metrics.ts'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

const { buildMetricsResponse, defaultDeps, engineVersionOf, SOURCE_VERSION } = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)

/** 缓存目录布局（契约路径约定）：<SANDBAR_METRICS_DIR>/<project>/data/metrics/。 */
async function mkCacheDir(prefix) {
  // env 语义 = 根（SANDBAR_METRICS_DIR），实现内部再拼 <project>/data/metrics/
  const root = freshDir(prefix)
  const dir = join(root, 'demo', 'data', 'metrics')
  await mkdir(dir, { recursive: true })
  return { root, dir }
}

// t260904-09：归档口径收窄为「subject 首行以票号开头」——stub 的 %H 必须 40 位
// （实现按 idx41 取 subject），常量桩供各用例复用。
const H = (n) => String(n).repeat(39) + String(n)
const SQ = (h, id, tail = 'squash 收口（一单一提交，KI-006）') => `${h} ${id} ${tail}`

const savedStub = process.env.SANDBAR_METRICS_STUB
const savedDir = process.env.SANDBAR_METRICS_DIR
const savedLedger = process.env.SANDBAR_USAGE_LEDGER_DIR

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
    '/stub-repo::log --format=%H %s --grep t09-squash': `${SQ(H(1), 't09-squash')}\n${H(2)} 教训引用 t09-squash 收口\n`,
    [`/stub-repo::show --numstat --format= ${H(1)}`]: '500\t120\ta.ts\n50\t30\tb.ts',
  }), { id: 't09-squash' })
  ok('回落口径 add/del', d.delivery.add === 550 && d.delivery.del === 150, JSON.stringify(d))
  ok('commits=前缀提交集大小（他账 1 条被剔）', d.delivery.commits === 1)
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
    '/stub-repo::log --format=%H %s --grep t09-ki': SQ(H(3), 't09-ki') + '\n',
    [`/stub-repo::show --numstat --format= ${H(3)}`]: '500\t120\ta.ts\n50\t30\tb.ts',
  }, repo), { id: 't09-ki', base_ref: 'main', worktree: '.worktrees/t09-ki' })
  ok('回落 add=550（≠ 泳道区间会显示的 80000+）', d.delivery.add === 550, JSON.stringify(d))
  ok('KI-017① 收口：frozen=true + 归档 reason', d.frozen === true && String(d.reason).includes('归档口径'))
}

// ---- ④ W4 双算面：一 commit 引用两票 id → 提交集口径两票各计一次（已知行为）
{
  console.log('④ 前缀收窄（t260904-09）：引用性提及他票 id 的提交不再双算')
  const pairs = {
    '/stub-repo::log --format=%H %s --grep t09-mA': `${SQ(H(4), 't09-mA')}\n${H(5)} 教训引用 t09-mA 的收口\n`,
    [`/stub-repo::show --numstat --format= ${H(4)}`]: '100\t10\ta.ts',
    '/stub-repo::log --format=%H %s --grep t09-mB': `${H(5)} 教训引用 t09-mB 的收口\n`,
  }
  const da = await computeDelivery(gitDeps(pairs), { id: 't09-mA' })
  const db = await computeDelivery(gitDeps(pairs), { id: 't09-mB' })
  ok('t09-mA 只计前缀提交（add=100，他账 1 条被剔）', da.delivery.add === 100 && da.delivery.commits === 1, JSON.stringify(da))
  ok('t09-mB 仅他账引用 → null + reason 点名剔除', db.delivery === null && String(db.reason).includes('他账'), JSON.stringify(db))
  console.log('    注：前缀收窄正面关闭 W4 双算面（一 commit 只归唯一前缀票）；契约增补段成文')
}

// ---- ⑤ 畸形 numstat + 双路全失败
{
  console.log('⑤ 畸形 numstat 忽略不崩；双路全失败 null+人话 reason')
  const d1 = await computeDelivery(gitDeps({
    '/stub-repo::log --format=%H %s --grep t09-bad': SQ(H(6), 't09-bad') + '\n',
    [`/stub-repo::show --numstat --format= ${H(6)}`]: 'abc\tdef\tweird.txt\n-\t-\tbinary.png\n12\t3\tok.ts',
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
  process.env.SANDBAR_METRICS_DIR = cacheRoot
  process.env.SANDBAR_METRICS_STUB = writeStub(stubDir, baseStub({
    tickets: [closedTicket('t09-stale', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })],
  }))
  // 泳道会话已拆（stub repo 无 .dsh/sessions）+ 无账本 → token 现算失败 → 存量保留
  delete process.env.SANDBAR_USAGE_LEDGER_DIR
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

// ---- 账本缝：SANDBAR_USAGE_LEDGER_DIR 探测
{
  console.log('⑥ 项目级 usage 账本缝：未配置显式 reason、配置后可聚合（前向契约）')
  const { resolveLedgerSessionFiles } = await import(new URL('./../src/host/agent-usage.ts', import.meta.url).pathname)
  delete process.env.SANDBAR_USAGE_LEDGER_DIR
  const r1 = await resolveLedgerSessionFiles('t09-led')
  ok('未配置：paths 空 + reason 提 KI-017③', r1.paths.length === 0 && String(r1.reason).includes('KI-017③'), String(r1.reason))
  const ledger = freshDir('t09-ledger-')
  await mkdir(join(ledger, 't09-led'), { recursive: true })
  await writeFile(join(ledger, 't09-led', 's.jsonl.zstd'), 'not-zstd-but-probed', 'utf8')
  process.env.SANDBAR_USAGE_LEDGER_DIR = ledger
  const r2 = await resolveLedgerSessionFiles('t09-led')
  ok('配置后：探测到文件（聚合通路复用同参）', r2.paths.length === 1 && r2.reason === undefined, JSON.stringify(r2))
  const r3 = await resolveLedgerSessionFiles('t09-absent')
  ok('账本无本票目录：人话 reason', r3.paths.length === 0 && String(r3.reason).includes('无本票目录'))
  delete process.env.SANDBAR_USAGE_LEDGER_DIR
}

// ---- ⑦ t260904-04 KI-041：绝对路径 worktree 直接用（join 毒路径归一）
{
  console.log('⑦ KI-041：worktree 绝对路径 → cwd 直接用，不拼毒路径')
  const absLane = '/abs/lane-t09-ki041'
  const d = await computeDelivery(gitDeps({
    [`${absLane}::diff main...HEAD --numstat`]: '10\t2\ta.ts',
    [`${absLane}::rev-list --count main..HEAD`]: '1\n',
  }, '/stub-repo'), { id: 't09-ki041', base_ref: 'main', worktree: absLane })
  ok('绝对路径活口径出数（add=10）', d.delivery?.add === 10, JSON.stringify(d))
  ok('活口径不冻结', d.frozen === false)
}

// ---- ⑧ t260904-04 KI-040：缓存命中条件化（null 重探 TTL 门 + open 陈旧刷新）
{
  console.log('⑧ KI-040：缓存命中不再固化失败维/open 陈旧')
  const { root: cacheRoot, dir: cacheDir } = await mkCacheDir('t09-heal-cache-')
  const stubDir = freshDir('t09-heal-stub-')
  const curEngine = engineVersionOf(STAGES)
  const mkRec = (id, overrides = {}) => ({
    ticket_id: id, template: 'dev-lane',
    durations: { by_stage: { plan: 1000 }, by_round: { plan: 1000 }, human_wait: 0 },
    delivery: null, tokens: { by_stage: {}, by_model: {}, in: 1, out: 1, cacheRead: 0 },
    open: false, delivery_frozen: false,
    source_version: SOURCE_VERSION, engine_version: curEngine,
    updated_ts: new Date(NOW).toISOString(), computed_at: new Date(NOW).toISOString(),
    created_ms: Date.parse('2026-08-30T01:00:00Z'), closed_ms: Date.parse('2026-08-30T04:00:00Z'),
    ...overrides,
  })
  const writeRec = async (id, rec) => {
    await mkdir(cacheDir, { recursive: true })
    await writeFile(join(cacheDir, `${id}.json`), JSON.stringify(rec), 'utf8')
  }
  const healTicket = (id) => closedTicket(id, baseStub(), {
    t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z'),
  })
  /** defaultDeps（stub 缝）+ git 计数桩：gitCalls 记录每次 cwd。 */
  const mkDeps = (pairs) => {
    const gitCalls = []
    const deps = {
      ...defaultDeps('/stub-repo', () => NOW),
      git: async (cwd, args) => {
        gitCalls.push(cwd)
        const key = `${cwd}::${args.join(' ')}`
        if (!(key in pairs)) throw new Error(`stub git 未备：${key}`)
        return pairs[key]
      },
    }
    return { deps, gitCalls }
  }
  const grepPairs = (id, numstat = '10\t2\ta.ts') => ({
    // t260904-09 收窄后格式：%H %s + 前缀命中 + 按提交 show numstat
    [`/stub-repo::log --format=%H %s --grep ${id}`]: `${H(9)} ${id} squash 收口（一单一提交，KI-006）\n`,
    [`/stub-repo::show --numstat --format= ${H(9)}`]: numstat,
  })
  const run = (deps, query = { view: 'delivery', window: 'all' }) => buildMetricsResponse(query, deps)

  process.env.SANDBAR_METRICS_DIR = cacheRoot
  process.env.SANDBAR_METRICS_STUB = writeStub(stubDir, baseStub({
    tickets: [healTicket('t09-heal-old'), healTicket('t09-heal-fresh'), healTicket('t09-open-stale'), healTicket('t09-nof-ts'), healTicket('t09-null-frozen')],
  }))
  delete process.env.SANDBAR_USAGE_LEDGER_DIR
  process.env.SANDBAR_METRICS_REPROBE_TTL_MIN = '60'

  // ⑧a 过 TTL null 记录：重探出数 + frozen + updated_ts 前移
  await writeRec('t09-heal-old', mkRec('t09-heal-old', { updated_ts: new Date(NOW - 2 * 3600e3).toISOString() }))
  const a = mkDeps(grepPairs('t09-heal-old'))
  const ra = await run(a.deps)
  const recA = JSON.parse(await readFile(join(cacheDir, 't09-heal-old.json'), 'utf8'))
  ok('⑧a 过 TTL null 重探出数（add=10）', recA.delivery?.add === 10, JSON.stringify(recA.delivery))
  ok('⑧a 重探成功冻结（主仓归档口径）', recA.delivery_frozen === true)
  ok('⑧a updated_ts 前移（节流锚点刷新）', recA.updated_ts === new Date(NOW).toISOString(), recA.updated_ts)
  ok('⑧a 重探 git cwd=引擎仓', a.gitCalls.every(c => c === '/stub-repo'))
  ok('⑧a 响应 reason 带归档口径标注', String(ra.body.reason ?? '').includes('归档口径'), String(ra.body.reason ?? '').slice(0, 200))

  // ⑧b 新鲜 null 记录（TTL 内）：不重探，零 git spawn
  await writeRec('t09-heal-fresh', mkRec('t09-heal-fresh'))
  const b = mkDeps({})
  await run(b.deps)
  ok('⑧b TTL 内 null 不重探（零 git spawn）', b.gitCalls.length === 0, JSON.stringify(b.gitCalls))
  const recB = JSON.parse(await readFile(join(cacheDir, 't09-heal-fresh.json'), 'utf8'))
  ok('⑧b 记录未被改写（delivery 仍 null）', recB.delivery === null)

  // ⑧c open 陈旧（rec.open=true vs list closed）：不受 TTL 门，刷新 open/closed_ms
  await writeRec('t09-open-stale', mkRec('t09-open-stale', { open: true, delivery: { base: 'main', add: 5, del: 1, commits: 1 }, delivery_frozen: true, closed_ms: undefined }))
  const c = mkDeps({})
  const rc = await run(c.deps)
  const recC = JSON.parse(await readFile(join(cacheDir, 't09-open-stale.json'), 'utf8'))
  ok('⑧c open 陈旧触发刷新（open=false）', recC.open === false, JSON.stringify(recC.open))
  ok('⑧c closed_ms 补齐（归窗锚点从 timeline 来，非内存改 flag）', Number.isFinite(recC.closed_ms), String(recC.closed_ms))
  ok('⑧c delivery 非 null 不重算（零 git spawn）', c.gitCalls.length === 0, JSON.stringify(c.gitCalls))
  ok('⑧c 响应 closed 计数含本票（time/health 分叉收敛面）', rc.body.kpis.closed >= 1, JSON.stringify(rc.body.kpis))

  // ⑧d updated_ts 缺失/坏值：视为过期必探（NaN 比较恒 false 的反方向）
  await writeRec('t09-nof-ts', mkRec('t09-nof-ts', { updated_ts: undefined }))
  const d = mkDeps(grepPairs('t09-nof-ts'))
  await run(d.deps)
  ok('⑧d updated_ts 缺失视为过期 → 重探', d.gitCalls.length === 2, JSON.stringify(d.gitCalls))

  // ⑧e null+frozen 脏态：条件 A 不看 frozen 位，重算门同步丢位 → 自愈
  await writeRec('t09-null-frozen', mkRec('t09-null-frozen', { delivery_frozen: true, updated_ts: new Date(NOW - 2 * 3600e3).toISOString() }))
  const e = mkDeps(grepPairs('t09-null-frozen'))
  await run(e.deps)
  const recE = JSON.parse(await readFile(join(cacheDir, 't09-null-frozen.json'), 'utf8'))
  ok('⑧e null+frozen 脏态重探自愈（add=10）', recE.delivery?.add === 10, JSON.stringify(recE.delivery))

  // ⑧f TTL=0：每次必探（仅测试语义）
  await writeRec('t09-heal-fresh', mkRec('t09-heal-fresh'))
  process.env.SANDBAR_METRICS_REPROBE_TTL_MIN = '0'
  const f = mkDeps(grepPairs('t09-heal-fresh'))
  await run(f.deps)
  ok('⑧f TTL=0 每次必探', f.gitCalls.length === 2, JSON.stringify(f.gitCalls))
  delete process.env.SANDBAR_METRICS_REPROBE_TTL_MIN
}

// ---- ⑨ t260904-04 KI-043①：per-project repo 解析（repoForProject 换根）
{
  console.log('⑨ KI-043①：project=suyou → git cwd 指向项目主目录（双门同吃 defaultDeps）')
  const { root: cacheRoot } = await mkCacheDir('t09-rp-cache-')
  const stubDir = freshDir('t09-rp-stub-')
  process.env.SANDBAR_METRICS_DIR = cacheRoot
  process.env.SANDBAR_METRICS_STUB = writeStub(stubDir, baseStub({
    tickets: [closedTicket('t09-rp', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })],
  }))
  delete process.env.SANDBAR_USAGE_LEDGER_DIR
  const gitCalls = []
  const base = {
    ...defaultDeps('/sandbar-repo', () => NOW),
    git: async (cwd, args) => {
      gitCalls.push(cwd)
      const key = `${cwd}::${args.join(' ')}`
      const pairs = {
        '/suyou-root::log --format=%H %s --grep t09-rp': SQ(H(7), 't09-rp') + '\n',
        [`/suyou-root::show --numstat --format= ${H(7)}`]: '671\t43\ta.ts',
      }
      if (!(key in pairs)) throw new Error(`stub git 未备：${key}`)
      return pairs[key]
    },
  }
  // 模拟 defaultDeps 缺省实现（findProject→primaryDir）的注入面
  const deps = { ...base, repoForProject: (key) => (key === 'suyou' ? '/suyou-root' : null) }
  const r = await buildMetricsResponse({ view: 'delivery', window: 'all', project: 'suyou' }, deps)
  ok('⑨ project=suyou git cwd=/suyou-root（换根生效）', gitCalls.length > 0 && gitCalls.every(c => c === '/suyou-root'), JSON.stringify(gitCalls))
  ok('⑨ suyou 票交付维出数（tickets=1）', r.status === 200 && r.body.kpis.tickets === 1, JSON.stringify(r.body.kpis))
  // 未知 key：repoForProject 返回 null → 回退传入 repo（checkProject 桩放行）
  gitCalls.length = 0
  const deps2 = { ...base, repoForProject: () => null }
  const r2 = await buildMetricsResponse({ view: 'delivery', window: 'all', project: 'suyou' }, deps2)
  ok('⑨ repoForProject null 回退传入 repo', gitCalls.every(c => c === '/sandbar-repo') && r2.status === 200, JSON.stringify(gitCalls))
}

// ---- ⑩ t260904-04 验收打回修复：F1 首拍人口塌缩 + F2 归档票 open 无真源显式化
{
  console.log('⑩ F1/F2：归档票重探首拍即在人口；open 无外部真源 → notices 显式计数')
  const { root: cacheRoot, dir: cacheDir } = await mkCacheDir('t09-f1-cache-')
  const stubDir = freshDir('t09-f1-stub-')
  const curEngine = engineVersionOf(STAGES)
  // 归档票：不在工单列表（stub tickets 空）→ collectArchivedRows 从缓存并入；
  // showTicket（stubDeps find）恒 null → show 回退合成行（F2 结构面）。
  const prevRec = {
    ticket_id: 't09-arch', template: 'dev-lane',
    durations: { by_stage: { plan: 1000 }, by_round: { plan: 1000 }, human_wait: 0 },
    delivery: null, tokens: { by_stage: {}, by_model: {}, in: 1, out: 1, cacheRead: 0 },
    open: true, delivery_frozen: false,
    source_version: SOURCE_VERSION, engine_version: curEngine,
    updated_ts: new Date(NOW - 2 * 3600e3).toISOString(), computed_at: new Date(NOW - 2 * 3600e3).toISOString(),
  }
  await mkdir(cacheDir, { recursive: true })
  await writeFile(join(cacheDir, 't09-arch.json'), JSON.stringify(prevRec), 'utf8')
  process.env.SANDBAR_METRICS_DIR = cacheRoot
  process.env.SANDBAR_METRICS_STUB = writeStub(stubDir, baseStub({ tickets: [] }))
  delete process.env.SANDBAR_USAGE_LEDGER_DIR
  process.env.SANDBAR_METRICS_REPROBE_TTL_MIN = '0' // 强制首拍重探（复现 F1 的触发条件）
  const mkDeps = (pairs) => ({
    ...defaultDeps('/stub-repo', () => NOW),
    git: async (cwd, args) => {
      const key = `${cwd}::${args.join(' ')}`
      if (!(key in pairs)) throw new Error(`stub git 未备：${key}`)
      return pairs[key]
    },
  })
  const pairs = {
    '/stub-repo::log --format=%H %s --grep t09-arch': SQ(H(8), 't09-arch') + '\n',
    [`/stub-repo::show --numstat --format= ${H(8)}`]: '10\t2\ta.ts',
  }
  // F1：首拍（重探拍）治愈票必须在人口内——近似锚点基线=重算前 computed_at（过去时刻）
  const r1 = await buildMetricsResponse({ view: 'delivery', window: 'all' }, mkDeps(pairs))
  ok('⑩F1 首拍人口含治愈票（tickets=1，不塌缩）', r1.body.kpis.tickets === 1, JSON.stringify(r1.body.kpis))
  ok('⑩F1 open 票按 created 基线归窗（closed=0，未误计闭单）', r1.body.kpis.closed === 0, JSON.stringify(r1.body.kpis))
  ok('⑩F1 首拍交付维出数（add+del=12）', JSON.stringify(r1.body.charts).includes('"data":[12]'), JSON.stringify(r1.body.charts).slice(0, 200))
  // F2：归档票 open 无外部真源 → flag 不漂白 + notices 显式计数（重算拍）
  const recAfter = JSON.parse(await readFile(join(cacheDir, 't09-arch.json'), 'utf8'))
  ok('⑩F2 open 不被合成行洗白（仍 true，不误翻）', recAfter.open === true, String(recAfter.open))
  ok('⑩F2 重算拍 notice 显式计数（closed 可能低计）', String(r1.body.reason ?? '').includes('open 标志无外部真源'), String(r1.body.reason ?? '').slice(0, 200))
  // F2：第二拍（纯命中）notice 仍在（显式化不随拍漂移）
  process.env.SANDBAR_METRICS_REPROBE_TTL_MIN = '60'
  const r2 = await buildMetricsResponse({ view: 'delivery', window: 'all' }, mkDeps({}))
  ok('⑩F2 命中拍 notice 仍在', String(r2.body.reason ?? '').includes('open 标志无外部真源'), String(r2.body.reason ?? '').slice(0, 200))
  ok('⑩F2 命中拍人口仍在（tickets=1）', r2.body.kpis.tickets === 1, JSON.stringify(r2.body.kpis))
  delete process.env.SANDBAR_METRICS_REPROBE_TTL_MIN
}

process.env.SANDBAR_METRICS_STUB = savedStub
process.env.SANDBAR_METRICS_DIR = savedDir
if (savedLedger === undefined) delete process.env.SANDBAR_USAGE_LEDGER_DIR
else process.env.SANDBAR_USAGE_LEDGER_DIR = savedLedger
process.exit(summary('delivery-recovery') ? 0 : 1)

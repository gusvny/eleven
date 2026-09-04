/**
 * lib_integration.mjs —— t260903-09 集成场景共享夹具（非 sc_ 前缀=共享代码，
 * 按 run_scenarios.py 命名铁律不登记、不报警）。
 *
 * 接缝口径（灰盒：锚定公开面，不绑实现内部）：
 * - API 前门 = buildMetricsResponse(query, deps)（CLI/HTTP 同款直调面）；
 * - 数据缝 = SUYOU_METRICS_STUB/SUYOU_METRICS_DIR env + defaultDeps（与 workbench
 *   tests 同款），或手组 MetricsDeps（真 git 场景用）；
 * - 缓存 fixture = 先跑一次实现自己落盘缓存，再对缓存文件做复制/篡改/删除——
 *   不手写 engine_version 等内部派生值，实现演进零耦合；
 * - spec 查找按 title 关键词遍历，不绑 charts 树形结构（primary/secondaries 演进不破）。
 */
import { mkdir, writeFile, rm, readdir } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const pexec = promisify(execFile)

export const HERE = dirname(fileURLToPath(import.meta.url))
const METRICS_TS = new URL('../../server/dsh/workbench/src/host/metrics.ts', import.meta.url)

/** 固定 now：窗口归窗跨日可复现（与 workbench tests/golden.mjs 同纪律）。 */
export const NOW = Date.parse('2026-09-03T00:30:00Z')
export const DAY = 86_400_000
export const iso = (ms) => new Date(ms).toISOString()

let metricsMod = null
export async function loadMetrics() {
  if (metricsMod === null) metricsMod = await import(METRICS_TS.href)
  return metricsMod
}

/** 临时目录固定落票目录 tmp/ 内（产物不出工作空间），用完由调用方 finally 清理。 */
export async function freshTmp(prefix) {
  const dir = join(HERE, 'tmp', `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`)
  await mkdir(dir, { recursive: true })
  return dir
}
export async function rmRf(dir) {
  if (dir) await rm(dir, { recursive: true, force: true })
}

/** 模板/stage 表：exit=human 的 stage 参与 human_wait 口径。 */
export const STAGES = [
  { id: 'plan', exit: 'human' },
  { id: 'code', exit: 'agent' },
  { id: 'review', exit: 'human' },
]
export const WORKFLOWS = [{ id: 'dev-lane', name: 'dev-lane', stages: STAGES }]

/** 票行（list 行自带 timeline=stub 零成本，show 同款形状）。 */
export function ticketRow(id, { createdAt, closedAt, extra = {} }) {
  const tl = [{ at: iso(createdAt), stage: 'plan', state: 'running' }]
  if (closedAt != null) tl.push({ at: iso(closedAt), stage: 'plan', state: 'closed' })
  const status = closedAt != null ? 'closed' : 'running'
  return { id, workflow: 'dev-lane', status, timeline: tl, ...extra }
}

/**
 * stub 缝包裹：写 stub JSON + 设 env → 跑 fn → 恢复 env + 清理。
 * fn 内可多次调 metrics（缓存留在 cacheRoot 内，供篡改/删除类用例）。
 */
export async function withStub(stubObj, fn) {
  const tmp = await freshTmp('m09')
  const stubPath = join(tmp, 'stub.json')
  const cacheRoot = join(tmp, 'cache')
  await writeFile(stubPath, JSON.stringify(stubObj), 'utf8')
  const saved = { STUB: process.env.SUYOU_METRICS_STUB, DIR: process.env.SUYOU_METRICS_DIR }
  process.env.SUYOU_METRICS_STUB = stubPath
  process.env.SUYOU_METRICS_DIR = cacheRoot
  try {
    const m = await loadMetrics()
    const deps = m.defaultDeps('/stub-repo', () => NOW)
    return await fn({ deps, cacheRoot, tmp })
  } finally {
    if (saved.STUB === undefined) delete process.env.SUYOU_METRICS_STUB
    else process.env.SUYOU_METRICS_STUB = saved.STUB
    if (saved.DIR === undefined) delete process.env.SUYOU_METRICS_DIR
    else process.env.SUYOU_METRICS_DIR = saved.DIR
    await rmRf(tmp)
  }
}

/** 调 API 前门。query 用对象形（契约参数名）。 */
export async function callMetrics(deps, query) {
  const m = await loadMetrics()
  return m.buildMetricsResponse({ project: 'demo', window: '7d', ...query }, deps)
}

/** 缓存根下全部 .json（缓存记录=磁盘持久契约面，供 fixture 造存量/清冷缓存）。 */
export async function listCacheFiles(cacheRoot) {
  const hits = []
  async function walk(d) {
    let entries = []
    try { entries = await readdir(d, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      const p = join(d, e.name)
      if (e.isDirectory()) await walk(p)
      else if (e.name.endsWith('.json')) hits.push(p)
    }
  }
  await walk(cacheRoot)
  return hits
}

/** 在缓存根下递归找 <ticketId>.json（不硬编码目录层级，路径演进零耦合）。 */
export async function findCacheFile(cacheRoot, ticketId) {
  const hits = []
  async function walk(d) {
    let entries = []
    try { entries = await readdir(d, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      const p = join(d, e.name)
      if (e.isDirectory()) await walk(p)
      else if (e.name === `${ticketId}.json`) hits.push(p)
    }
  }
  await walk(cacheRoot)
  return hits[0] ?? null
}

/** 遍历响应树找 title 含关键词的 ChartSpec（契约字面锚定，不绑 charts 树形）。 */
export function findSpecs(node, kw, out = []) {
  if (Array.isArray(node)) { for (const n of node) findSpecs(n, kw, out); return out }
  if (node && typeof node === 'object') {
    if (typeof node.title === 'string' && node.title.includes(kw)) out.push(node)
    for (const v of Object.values(node)) if (v && typeof v === 'object') findSpecs(v, kw, out)
  }
  return out
}

/** donut/图 spec 的数据合计（契约 series:[{name,data:[num]}]）。 */
export function specDataSum(spec) {
  const rows = Array.isArray(spec?.series) ? spec.series : []
  return rows.reduce((s, r) => s + (Array.isArray(r?.data) ? r.data.reduce((a, b) => a + (Number(b) || 0), 0) : 0), 0)
}

/* ---------------- 真 git 缝（KI-017① 回归：stub git 算不出真 git 口径事实） ---------------- */

export async function git(cwd, args) {
  const r = await pexec('git', args, { cwd, encoding: 'utf8' })
  return r.stdout
}
/** init + 本地身份（沙箱无全局 git 身份也能 commit）。 */
export async function gitInit(dir) {
  const { mkdir } = await import('node:fs/promises')
  await mkdir(dir, { recursive: true })
  await git(dir, ['init'])
  await git(dir, ['config', 'user.email', 't260903-09@test.invalid'])
  await git(dir, ['config', 'user.name', 't260903-09'])
  await git(dir, ['config', 'commit.gpgsign', 'false'])
}
export async function gitCommitAll(dir, message) {
  await git(dir, ['add', '-A'])
  await git(dir, ['commit', '-m', message])
}
/** 写 n 行文件并提交。 */
export async function commitFile(dir, rel, lineCount, message, prefix = 'line') {
  const { writeFile, mkdir } = await import('node:fs/promises')
  const p = join(dir, rel)
  await mkdir(dirname(p), { recursive: true })
  await writeFile(p, Array.from({ length: lineCount }, (_, i) => `${prefix} ${i + 1}\n`).join(''), 'utf8')
  await gitCommitAll(dir, message)
}

/* ---------------- 结果口径（三态契约，定稿 §7.3「闸内无旧跳过语义」：
   0=PASS / 1=FAIL 产品红或全 na / 2=ENV_FAIL 环境红；SUMMARY 末行四计数） ---------------- */

export function makeChecker() {
  let pass = 0, fail = 0, envFail = 0, na = 0
  return {
    ok(cond, label, detail = '') {
      if (cond) { pass++; console.log(`  ok ${label}`) } else { fail++; console.log(`  FAIL ${label}${detail ? ' — ' + detail : ''}`) }
    },
    /** 环境红：缺被测环境依赖（非产品缺陷）时计入 env_fail，绝不静默放行。 */
    envFail(label, reason = '') {
      envFail++; console.log(`  ENV_FAIL ${label}${reason ? ' — ' + reason : ''}`)
    },
    /** 系统状态条件腿 N/A（不以测试环境为条件）；全腿 N/A 视同产品红。 */
    na(label) {
      na++; console.log(`  N/A ${label}`)
    },
    done(name) {
      console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=${na}`)
      if (fail > 0) console.log(`[${name}] 存在失败断言（实现未落地段预期红；落地后应全绿）`)
      const allNa = na > 0 && pass + fail + envFail === 0
      return fail > 0 || allNa ? 1 : envFail > 0 ? 2 : 0
    },
  }
}

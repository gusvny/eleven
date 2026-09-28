/**
 * 项目注册表（sandbar M1-1 出仓后真源 = ~/.sandbar/projects/<key>/project.yaml）。
 *
 * 形状：一项目一目录，注册条目 = 目录内 project.yaml，装载 = 扫描根目录下
 * 各项目子目录里的 project.yaml。
 * env 优先级（每次调用现读，仿 SANDBAR_PROJECTS_YAML 既有语义，smoke「先 import 后设 env」依赖）：
 *   SANDBAR_PROJECTS_YAML  >  SANDBAR_PROJECTS_DIR  >  ~/.sandbar/projects
 * - SANDBAR_PROJECTS_YAML（legacy 单文件模式）：指向旧格式注册表文件（projects: 列表），
 *   行为与 260823 多项目化版本完全一致——providers/knowledge 两个既有 smoke 依赖此模式。
 * - SANDBAR_PROJECTS_DIR / 默认根目录（per-key 目录模式，契约① schema v1）：
 *   扫描根目录下各项目子目录的 project.yaml；单条目畸形/版本不支持 = 该项目隔离（fail-closed 可见，
 *   不炸其他项目）；目录名必须过 PROJECT_KEY_RE，条目 key 必须与目录名全等。
 *
 * 迁移：per-key 根目录不存在、或存在但无 .migrated 标记时，从旧单文件
 * server/projects.yaml（本文件同目录，一次性迁移源）自动迁移——逐条写
 * <tmp>/project.yaml 后 rename 原子入位，全部落完后 wx 独占创建 .migrated。
 * 无标记且根里有内容时分三类现场（修订 v2.1）：纯种子字节子集=崩溃残留→续迁补齐；
 * 与种子零交集=人工注册表→接受；部分相关不可复现=混合现场→fail-closed 抛错。
 * 跳过判据只认 .migrated。并发首启：各条目内容全同（来源同一份旧表），
 * tmp+rename 收敛；.migrated wx 输家跳过；残余风险=旧表在毫秒级迁移窗口内被改，
 * 旧表由 git 管理，显式接受。
 *
 * 解析器是严格最小 YAML 子集：不吃任意 YAML，只认固定形状，写坏直接抛错，
 * 报错含 <文件>:<行号>，不静默容错。
 */

import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export interface ProjectEntry {
  key: string
  name: string
  dirs: string[]
}

/** 隔离条目：dir = 注册表根下出问题的项目目录，error = 含 <dir>/project.yaml 定位的原因。 */
export interface QuarantinedEntry {
  dir: string
  error: string
}

/** 项目 key 白名单形状：SA Keyword 值 + URL query 参数双安全（小写字母/数字/中划线）。 */
export const PROJECT_KEY_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

/** per-key 注册表根目录（每次调用现读 env：不做模块级常量化）。 */
function registryRoot(): string {
  return process.env.SANDBAR_PROJECTS_DIR ?? join(homedir(), '.sandbar', 'projects')
}

/** 旧单文件注册表（一次性迁移源；与 legacy env 模式的缺省指向一致）。 */
function legacySeedPath(): string {
  return join(dirname(fileURLToPath(import.meta.url)), 'projects.yaml')
}

/** legacy env 模式注册表路径（每次调用现读 env）。 */
function legacyRegistryPath(): string {
  return process.env.SANDBAR_PROJECTS_YAML ?? legacySeedPath()
}

/** 剥行尾注释 + 右空白；整行注释/空行返回 null（跳过）。 */
function stripLine(raw: string): string | null {
  // 本注册表值不含 #，遇 # 一律当注释起点
  const text = raw.replace(/#.*$/, '').replace(/\s+$/, '')
  if (text.trim() === '') return null
  return text
}

/** 顶层行校验：非缩进行只认给定根键（projects: / project:）。 */
function checkTopLine(raw: string, text: string, rootKey: 'projects:' | 'project:', fileLabel: string, lineNo: number): void {
  if (/^\s/.test(raw) === false && text !== rootKey && lineNo > 1) {
    throw new Error(`${fileLabel}:${lineNo} 顶层只认 ${rootKey}`)
  }
}

/** 旧格式单文件解析（projects: 列表）——原 parseProjectsYaml 原样保留：
 *  legacy env 模式与 workbench smoke/projects.mjs 直接消费，行为不得漂移。 */
export function parseProjectsYaml(text: string, fileLabel = 'projects.yaml'): ProjectEntry[] {
  const projects: ProjectEntry[] = []
  let cur: ProjectEntry | null = null
  let inDirs = false
  let sawRoot = false
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = stripLine(lines[i])
    if (line === null) continue
    checkTopLine(lines[i], line, 'projects:', fileLabel, i + 1)
    if (line === 'projects:') {
      if (sawRoot) throw new Error(`${fileLabel}:${i + 1} projects: 重复`)
      sawRoot = true
      continue
    }
    if (!sawRoot) throw new Error(`${fileLabel}:${i + 1} 首行必须是 projects:`)
    const itemMatch = line.match(/^\s+-\s+(.+)$/)
    const kvMatch = line.match(/^\s+([a-z]+):\s*(.*)$/)
    if (itemMatch) {
      const content = itemMatch[1].trim()
      const kv = content.match(/^([a-z]+):\s*(.*)$/)
      if (kv) {
        // 新条目：- key: <key>（优先于 dirs 成员判定——条目首键必须是 key）
        if (kv[1] !== 'key' || !kv[2]) throw new Error(`${fileLabel}:${i + 1} 条目首键必须是 key`)
        if (!PROJECT_KEY_RE.test(kv[2].trim())) throw new Error(`${fileLabel}:${i + 1} key 不合法：${kv[2]}`)
        cur = { key: kv[2].trim(), name: '', dirs: [] }
        projects.push(cur)
        inDirs = false
        continue
      }
      // dirs 列表成员：- /abs/path
      if (cur === null || !inDirs) throw new Error(`${fileLabel}:${i + 1} 列表项出现位置不对：${content}`)
      if (!content.startsWith('/')) throw new Error(`${fileLabel}:${i + 1} dirs 必须是绝对路径：${content}`)
      cur.dirs.push(content)
      continue
    }
    if (kvMatch && cur !== null) {
      const [, k, v] = kvMatch
      if (k === 'name') { cur.name = v.trim(); inDirs = false; continue }
      if (k === 'dirs') { if (v.trim() !== '') throw new Error(`${fileLabel}:${i + 1} dirs: 后必须换行给列表`); inDirs = true; continue }
      throw new Error(`${fileLabel}:${i + 1} 不认的键：${k}`)
    }
    throw new Error(`${fileLabel}:${i + 1} 解析失败：${line.trim()}`)
  }
  if (projects.length === 0) throw new Error(`${fileLabel}: 没有任何项目条目`)
  for (const p of projects) {
    if (!p.name) throw new Error(`${fileLabel}: 项目 ${p.key} 缺 name`)
    if (p.dirs.length === 0) throw new Error(`${fileLabel}: 项目 ${p.key} 缺 dirs`)
  }
  const keys = new Set(projects.map(p => p.key))
  if (keys.size !== projects.length) throw new Error(`${fileLabel}: key 重复`)
  return projects
}

/**
 * per-key 单条目解析（project.yaml，契约① schema v1 固定形状）：
 *
 *   schema: v1            （必带；缺失=畸形——版本是接入前提不猜；非 v1=版本不支持 fail-closed）
 *   project:
 *     - key: <key>
 *       name: <名>
 *       dirs:
 *         - /abs/path
 *
 * 顶层透传键（additive，t260916-21 起 python 侧同款）：paths: / admin_log: /
 * event_ledger: 三个节整体透传不解析——旧读器不会因为新字段落盘就炸；各节的语义
 * 归各自读面（paths → python project_paths；admin_log → engine audit.py；
 * event_ledger → engine event_ledger.py）。此处只容其存在。
 *
 * key 白名单校验在此做；key 与目录名全等的核对由装载方做（需要目录名上下文）。
 */
export function parseProjectYaml(text: string, fileLabel: string): ProjectEntry {
  let cur: ProjectEntry | null = null
  let inDirs = false
  let sawProject = false
  let schema: string | null = null
  let inPaths = false   // ①d 放开（t260903 切换夜）：顶层 paths: 透传不解析
  let inAdminLog = false     // t260916-21 同源：顶层 admin_log: 透传（读面在 engine audit.py）
  let inEventLedger = false  // t260928 同源：顶层 event_ledger: 透传（读面在 engine event_ledger.py）
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = stripLine(lines[i])
    if (line === null) continue
    if (inPaths) {
      if (/^\s/.test(lines[i])) continue        // ①d 放开：paths 节透传（python 侧 project_paths 负责语义）
      inPaths = false
    }
    if (inAdminLog) {
      if (/^\s/.test(lines[i])) continue
      inAdminLog = false
    }
    if (inEventLedger) {
      if (/^\s/.test(lines[i])) continue
      inEventLedger = false
    }
    if (line === 'paths:') { inPaths = true; continue }
    if (line === 'admin_log:') { inAdminLog = true; continue }
    if (line === 'event_ledger:') { inEventLedger = true; continue }
    if (!/^\s/.test(lines[i]) && line !== 'project:' && !line.startsWith('schema:') && i + 1 > 1) {
      throw new Error(`${fileLabel}:${i + 1} 顶层只认 schema:/project:/paths:/admin_log:/event_ledger:`)
    }
    if (line === 'project:') {
      if (sawProject) throw new Error(`${fileLabel}:${i + 1} project: 重复`)
      sawProject = true
      continue
    }
    const topKv = line.match(/^([a-z]+):\s*(.+)$/)
    if (topKv && !sawProject && !/^\s/.test(lines[i])) {
      // project: 之前的顶层键：只认 schema
      if (topKv[1] !== 'schema') throw new Error(`${fileLabel}:${i + 1} 顶层只认 schema: 与 project:`)
      schema = topKv[2].trim()
      if (schema !== 'v1') throw new Error(`${fileLabel}:${i + 1} schema 版本不支持：声明 ${schema}，支持集 {v1}`)
      continue
    }
    if (!sawProject) throw new Error(`${fileLabel}:${i + 1} 顶层只认 schema: 与 project:`)
    const itemMatch = line.match(/^\s+-\s+(.+)$/)
    const kvMatch = line.match(/^\s+([a-z]+):\s*(.*)$/)
    if (itemMatch) {
      const content = itemMatch[1].trim()
      const kv = content.match(/^([a-z]+):\s*(.*)$/)
      if (kv) {
        if (cur !== null) throw new Error(`${fileLabel}:${i + 1} 单条目文件出现第二个条目`)
        if (kv[1] !== 'key' || !kv[2]) throw new Error(`${fileLabel}:${i + 1} 条目首键必须是 key`)
        if (!PROJECT_KEY_RE.test(kv[2].trim())) throw new Error(`${fileLabel}:${i + 1} key 不合法：${kv[2]}`)
        cur = { key: kv[2].trim(), name: '', dirs: [] }
        inDirs = false
        continue
      }
      if (cur === null || !inDirs) throw new Error(`${fileLabel}:${i + 1} 列表项出现位置不对：${content}`)
      if (!content.startsWith('/')) throw new Error(`${fileLabel}:${i + 1} dirs 必须是绝对路径：${content}`)
      cur.dirs.push(content)
      continue
    }
    if (kvMatch && cur !== null) {
      const [, k, v] = kvMatch
      if (k === 'name') { cur.name = v.trim(); inDirs = false; continue }
      if (k === 'dirs') { if (v.trim() !== '') throw new Error(`${fileLabel}:${i + 1} dirs: 后必须换行给列表`); inDirs = true; continue }
      throw new Error(`${fileLabel}:${i + 1} 不认的键：${k}`)
    }
    throw new Error(`${fileLabel}:${i + 1} 解析失败：${line.trim()}`)
  }
  if (schema === null) throw new Error(`${fileLabel}: schema: 缺失（版本是接入前提，不猜）`)
  if (cur === null) throw new Error(`${fileLabel}: 没有任何项目条目`)
  if (!cur.name) throw new Error(`${fileLabel}: 项目 ${cur.key} 缺 name`)
  if (cur.dirs.length === 0) throw new Error(`${fileLabel}: 项目 ${cur.key} 缺 dirs`)
  return cur
}

/** per-key 条目序列化（迁移用）：严格子集可往返（值不含 # / 换行，迁移时校验）。 */
export function serializeProjectYaml(p: ProjectEntry, seedLabel: string): string {
  const lines = [
    `# 由 ${seedLabel} 自动迁移（sandbar M1-1），格式=契约① per-key 注册条目，勿手改`,
    'schema: v1',
    'project:',
    `  - key: ${p.key}`,
    `    name: ${p.name}`,
    '    dirs:',
    ...p.dirs.map(d => `      - ${d}`),
    '',
  ]
  return lines.join('\n')
}

/** 并发安全的临时文件名：进程唯一后缀（tmp+rename 收敛的前提——确定性 tmp 名会被
 *  并发双迁互踩，赢家 rename 后输家撞 ENOENT，t260901-14 集成测试实测）。 */
function tmpName(target: string): string {
  return `${target}.tmp.${process.pid}.${Math.random().toString(36).slice(2, 8)}`
}

/** 扫注册表根目录：好条目进 projects，坏条目进 quarantined（fail-closed 可见不炸全表）。 */
function scanRegistry(root: string): { projects: ProjectEntry[]; quarantined: QuarantinedEntry[] } {
  const projects: ProjectEntry[] = []
  const quarantined: QuarantinedEntry[] = []
  const dirs = readdirSync(root, { withFileTypes: true })
    .filter(e => e.isDirectory() && !e.name.startsWith('.'))
    .map(e => e.name)
    .sort()
  for (const name of dirs) {
    const dir = join(root, name)
    const file = join(dir, 'project.yaml')
    if (!existsSync(file)) continue // 无注册条目的目录（如 data/ 保留位）跳过
    const label = `${dir}/project.yaml`
    if (!PROJECT_KEY_RE.test(name)) {
      quarantined.push({ dir, error: `${label}: 目录名不合法（key 白名单：小写字母/数字/中划线）：${name}` })
      continue
    }
    try {
      const p = parseProjectYaml(readFileSync(file, 'utf8'), label)
      if (p.key !== name) {
        throw new Error(`${label}: key 与目录名不等：${p.key} ≠ ${name}`)
      }
      projects.push(p)
    } catch (err) {
      quarantined.push({ dir, error: String(err instanceof Error ? err.message : err) })
    }
  }
  return { projects, quarantined }
}

/** 一次性迁移：旧单文件 → per-key 目录。tmp+rename 原子入位；.migrated wx 独占创建。
 *  任一步失败抛错（fail-closed）；已入位条目留在现场，下次启动命中半迁移分支显式报出。 */
export function migrateRegistry(root: string, seedFile: string): void {
  const seedLabel = String(seedFile)
  const projects = parseProjectsYaml(readFileSync(seedFile, 'utf8'), seedLabel)
  for (const p of projects) {
    for (const [field, value] of [['key', p.key], ['name', p.name], ...p.dirs.map((d): [string, string] => ['dirs', d])]) {
      if (/#|\n/.test(value)) {
        throw new Error(`迁移源 ${seedLabel}：项目 ${p.key} 的 ${field} 含 # 或换行，严格子集无法表示，拒绝迁移（请人工改源表）`)
      }
    }
  }
  mkdirSync(root, { recursive: true })
  for (const p of projects) {
    const dir = join(root, p.key)
    mkdirSync(dir, { recursive: true })
    const content = serializeProjectYaml(p, seedLabel)
    const target = join(dir, 'project.yaml')
    // 幂等：已有同字节条目直接跳过（二次调用零重写；并发双迁亦收敛）
    if (existsSync(target) && readFileSync(target, 'utf8') === content) continue
    const tmp = tmpName(target)
    writeFileSync(tmp, content, 'utf8')
    renameSync(tmp, target)
  }
  try {
    writeFileSync(join(root, '.migrated'), `source: ${seedLabel}\nmigrated_at: ${new Date().toISOString()}\n`, { flag: 'wx' })
  } catch (err) {
    // 并发首启：另一个进程已写标记，内容等价，忽略
    if ((err as NodeJS.ErrnoException).code !== 'EEXIST') throw err
  }
}

/** 迁移期望表：种子每条目 → 迁移会写出的精确字节（续迁判等用）。导出供自测直用。 */
export function expectedEntries(projects: ProjectEntry[], seedLabel: string): Map<string, string> {
  const map = new Map<string, string>()
  for (const p of projects) map.set(p.key, serializeProjectYaml(p, seedLabel))
  return map
}

/** 续迁：只补写种子里缺失的条目（onDisk 上已有的不动，防覆盖人工改动），最后补 .migrated。
 *  导出供自测直用（生产路径走 ensureMigrated → 这里）。 */
export function resumeMigration(root: string, expected: Map<string, string>, onDiskKeys: Set<string>): void {
  for (const [key, content] of expected) {
    if (onDiskKeys.has(key)) continue
    const dir = join(root, key)
    mkdirSync(dir, { recursive: true })
    const tmp = tmpName(join(dir, 'project.yaml'))
    writeFileSync(tmp, content, 'utf8')
    renameSync(tmp, join(dir, 'project.yaml'))
  }
  try {
    writeFileSync(join(root, '.migrated'), `source: ${legacySeedPath()}\nmigrated_at: ${new Date().toISOString()}\n`, { flag: 'wx' })
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== 'EEXIST') throw err
  }
}

/** per-key 模式装载前的一致性检查：跳过判据只认 .migrated。无标记且根里有内容时，
 *  区分三类现场（修订 v2.1，实现期自测发现——字面「有内容无标记=fail-closed」会把
 *  正常手工注册的注册表全部判死）：
 *  - 纯人工注册表（盘上 key 与种子零交集，或种子不在/不可解析时无任何种子相关项）→ 接受；
 *  - 崩溃残留/丢标记（盘上全是种子条目的精确字节子集，无隔离）→ 续迁补齐 + 补标记；
 *  - 混合现场（部分相关但不可由种子完全复现）→ fail-closed 抛错，人工处置，不静默跳过。 */
function ensureMigrated(root: string): void {
  if (existsSync(join(root, '.migrated'))) return
  const probe = scanRegistry(root)
  const onDisk = probe.projects.length + probe.quarantined.length
  const seed = legacySeedPath()
  if (onDisk === 0) {
    if (!existsSync(seed)) {
      throw new Error(`注册表根目录不存在：${root}，且无迁移源 ${seed}（fail-closed，不静默视为空注册表）`)
    }
    migrateRegistry(root, seed)
    return
  }
  if (!existsSync(seed)) return // 纯人工注册表：种子不在，无从判定也无从迁移，接受现状
  let expected: Map<string, string>
  try {
    const seedLabel = seed
    expected = expectedEntries(parseProjectsYaml(readFileSync(seed, 'utf8'), seedLabel), seedLabel)
  } catch (err) {
    throw new Error(`注册表现场无法判定：${root} 有 ${onDisk} 个项目条目但无 .migrated 标记，` +
      `且迁移源 ${seed} 不可解析（${String(err instanceof Error ? err.message : err)}）。` +
      '处置：修复或移除迁移源后重试。拒绝静默跳过。')
  }
  const seedKeys = new Set(expected.keys())
  const onDiskKeys = new Set([
    ...probe.projects.map(p => p.key),
    ...probe.quarantined.map(q => q.dir.slice(q.dir.lastIndexOf('/') + 1)),
  ])
  const touchesSeed = [...onDiskKeys].some(k => seedKeys.has(k))
  if (!touchesSeed) return // 纯人工注册表（与种子无关），接受现状
  const pureSubset = probe.quarantined.length === 0 && probe.projects.every(p => {
    if (!seedKeys.has(p.key)) return false
    try { return readFileSync(join(root, p.key, 'project.yaml'), 'utf8') === expected.get(p.key) }
    catch { return false }
  })
  if (pureSubset) { resumeMigration(root, expected, onDiskKeys); return }
  throw new Error(`注册表现场无法判定：${root} 有 ${onDisk} 个项目条目、无 .migrated 标记，` +
    `且内容与迁移源 ${seed} 部分相关但不能完全复现（混合现场：可能是崩溃残留叠了人工改动）。` +
    '处置：确认后补写标记、清除该目录重迁，或移除/修复迁移源。拒绝静默跳过。')
}

export interface Registry {
  projects: ProjectEntry[]
  quarantined: QuarantinedEntry[]
}

/** 装载注册表全量（好条目 + 隔离条目）。legacy env 在位时走旧单文件模式。 */
export function loadRegistry(): Registry {
  if (process.env.SANDBAR_PROJECTS_YAML) {
    return { projects: parseProjectsYaml(readFileSync(legacyRegistryPath(), 'utf8'), legacyRegistryPath()), quarantined: [] }
  }
  const root = registryRoot()
  if (!existsSync(root)) {
    const seed = legacySeedPath()
    if (!existsSync(seed)) {
      throw new Error(`注册表根目录不存在：${root}，且无迁移源 ${seed}（fail-closed，不静默视为空注册表）`)
    }
    migrateRegistry(root, seed)
  } else {
    ensureMigrated(root)
  }
  return scanRegistry(root)
}

/** 空注册表统一报错（三分支全显式）：无任何条目 / 全部被隔离（列原因）。 */
function assertNonEmpty(reg: Registry): void {
  if (reg.projects.length > 0) return
  if (reg.quarantined.length > 0) {
    const reasons = reg.quarantined.map(q => `${q.dir}（${q.error}）`).join('；')
    throw new Error(`注册表没有任何可用项目条目：全部 ${reg.quarantined.length} 条被隔离——${reasons}`)
  }
  throw new Error('注册表没有任何项目条目')
}

/** 每请求现读注册表（好条目）；空/全隔离抛错（fail-closed 可见），调用方兜底成 500/400。 */
export function loadProjects(): ProjectEntry[] {
  const reg = loadRegistry()
  assertNonEmpty(reg)
  return reg.projects
}

/** 按 key 查项目。key 形状不合法/真未注册 → undefined（调用方回 400）；
 *  key 对应隔离条目 → 抛错（host 既有 catch 变显式 500/400，非静默）。 */
export function findProject(key: string): ProjectEntry | undefined {
  if (!PROJECT_KEY_RE.test(key)) return undefined
  const reg = loadRegistry()
  assertNonEmpty(reg)
  const q = reg.quarantined.find(e => e.dir.endsWith(`/${key}`) || e.dir === key)
  if (q) {
    throw new Error(`项目 ${key} 注册条目已隔离：${q.dir}：${q.error}`)
  }
  return reg.projects.find(p => p.key === key)
}

/** 主目录 = dirs 首个（知识库/模型路由/会话 cwd 兜底都走它）。 */
export function primaryDir(p: ProjectEntry): string {
  return p.dirs[0]
}

/**
 * suyou-workbench · 侧栏「会话」区记账层纯函数（session-entry t260828-02，
 * 口径调整：项目归属 + 只列 UI 主动打开的会话）。
 *
 * 口径（设计真源 docs/design/右栏会话入口与hero定制设计.md §2/§4/附录）：
 * ctx.sessions.list 是全量枚举（磁盘存量、他途所建都在里面），不带「是否
 * UI 主动打开」信息——所以列表数据源不是它，而是插件自建的账册：仅当用户
 * 通过本插件 UI 主动打开（点切换行）或新建（＋新建按钮）一个会话时登记
 * {id, project, cwd, lastOpenedAt}，MRU 排序；磁盘存量、工单会话、subagent
 * 会话一律不进账册，不做置顶/钉选（MRU 自然收敛）。
 *
 * 完备性：工单台侧栏已顶掉出厂工作区浏览器，UI 上打开项目会话的入口就是
 * 本插件。t260829-06 起 hero 槽位替换落地：hero 紧凑入口复用本层
 * （useSessionEntry），新建/切换登记进同一账册——「hero 首条消息会话不进账」
 * 的过渡期缺口对本插件入口已消除；出厂大输入卡（无接管槽，修订口径共存）
 * 发出的首条消息所建会话仍不进账册，属设计文档 §4 明示的共存残留。
 *
 * t260831-06 口径变更（顶行 tab 三修）：
 *   - 「停原地」走规格 #1 的等价分支：打开路径（handleOpen）不再 touchEntry——
 *     lastOpenedAt 只在登记时写（新建/blank 自愈换绑/↺ 恢复三条显式路径，时间
 *     单调递增，排序结果=登记顺序），点 tab 不再重排，「点谁谁置顶」就此消除。
 *     排序实现保留 lastOpenedAt 降序（smoke/hero.mjs 既有断言兼容，该文件不在
 *     本单写集）。
 *   - OpenedEntry 加可选 title：用户对 tab 的自定义命名（重命名入口落账册），
 *     非空时优先于 displayTitle 显示。
 *
 * 账册存放 = 浏览器 localStorage（sidebar.tsx 负责 IO，本文件纯函数无 IO，
 * smoke/sessions.mjs 直跑，node ≥22.18 原生 type-stripping）。localStorage
 * 生命周期与宿主进程无关，刷新页面与重启 console 都不丢（设计§4：记账存放
 * 需刷新/重启不丢）。ctx.sessions.list 仍被订阅，但只取两个字段：
 * displayTitle（行标签）与 current（活跃高亮）。
 */

/** 账册条目：一次「UI 主动打开/新建」的登记。 */
export interface OpenedEntry {
  id: string
  /** 所属项目 key（projects.yaml 注册表）；会话跟项目走，列表按它过滤。 */
  project: string
  /** 所属项目主目录（登记时的会话 cwd；展示/诊断用，过滤以 project 为准）。 */
  cwd: string
  /** 最近打开时间（ms 时间戳；MRU 排序键——t260831-06 起只在登记路径写，打开不更新）。 */
  lastOpenedAt: number
  /** 用户自定义 tab 名（可选；非空时优先于 displayTitle 显示，t260831-06）。 */
  title?: string
}

/** 侧栏切换行（渲染就绪）。 */
export interface SwitchTarget {
  id: string
  title: string
  cwd: string
  /** 是否当前活跃会话（高亮）。 */
  active: boolean
}

/** 标题来源的最小面（SessionSummary 的子集；结构类型，测试可喂裸对象）。 */
export interface TitleRowLike {
  displayTitle?: string
}

/** 侧栏切换入口上限（设计：不超过 5 个）。 */
export const SWITCH_LIMIT = 5

/**
 * 账册存储上限（跨项目共用一册，超出的最旧条目自然淘汰——MRU 收敛，
 * 防无限增长；展示上限仍是 SWITCH_LIMIT，两者独立）。
 */
export const LEDGER_CAP = 20

/** 全局会话 id 判定：工单会话固定 `ticket-<工单id>` 前缀，不进账册。 */
export function isGlobalSessionId(id: string): boolean {
  return typeof id === 'string' && id !== '' && !id.startsWith('ticket-')
}

/** 行标签：displayTitle 兜底 id（displayTitle 本身已兜底过 id，双保险）。 */
export function labelOf(row: TitleRowLike | undefined, id: string): string {
  const t = row?.displayTitle
  return typeof t === 'string' && t !== '' ? t : id
}

/**
 * 账册反序列化（localStorage → OpenedEntry[]）：坏 JSON、非数组、脏条目
 * （缺 id/project、lastOpenedAt 非有限数）一律容错剔除，全脏则空册——
 * 不抛不崩，宁可列表空也不让侧栏挂掉。同 id 重复条目只留最靠前的一份。
 */
export function parseLedger(raw: string | null | undefined): OpenedEntry[] {
  if (!raw) return []
  let data: unknown
  try { data = JSON.parse(raw) } catch { return [] }
  if (!Array.isArray(data)) return []
  const seen = new Set<string>()
  const out: OpenedEntry[] = []
  for (const item of data) {
    if (typeof item !== 'object' || item === null) continue
    const e = item as Record<string, unknown>
    if (typeof e.id !== 'string' || e.id === '' || seen.has(e.id)) continue
    if (typeof e.project !== 'string' || e.project === '') continue
    seen.add(e.id)
    out.push({
      id: e.id,
      project: e.project,
      cwd: typeof e.cwd === 'string' ? e.cwd : '',
      lastOpenedAt: typeof e.lastOpenedAt === 'number' && Number.isFinite(e.lastOpenedAt) ? e.lastOpenedAt : 0,
      // title 非字符串（数字/对象/null 等畸形输入）→ 剔字段不崩（沿用本函数容错口径）
      ...(typeof e.title === 'string' ? { title: e.title } : {}),
    })
  }
  return out
}

/** 账册序列化（OpenedEntry[] → localStorage）。 */
export function serializeLedger(entries: OpenedEntry[]): string {
  return JSON.stringify(entries ?? [])
}

/**
 * 登记一次打开/新建：同 id upsert（更新 project/cwd/lastOpenedAt，可选带 title）
 * 并插到数组头部（=登记顺序最新），其余条目顺序不变；超出 cap 时淘汰最旧的。
 * ticket- 前缀的工单会话拒绝入账（有自己的常驻入口，不混入）。返回新数组
 * （不改入参）。t260831-06：本函数不再被「点击 tab 打开」路径调用（打开不
 * 重排），只服务新建登记、blank 自愈换绑、↺ 恢复重登三条显式路径。
 */
export function touchEntry(
  entries: OpenedEntry[],
  entry: { id: string; project: string; cwd?: string; lastOpenedAt?: number; title?: string },
  cap: number = LEDGER_CAP,
): OpenedEntry[] {
  if (!isGlobalSessionId(entry?.id) || typeof entry?.project !== 'string' || entry.project === '') {
    return Array.isArray(entries) ? entries.slice() : []
  }
  const next: OpenedEntry = {
    id: entry.id,
    project: entry.project,
    cwd: typeof entry.cwd === 'string' ? entry.cwd : '',
    lastOpenedAt: typeof entry.lastOpenedAt === 'number' && Number.isFinite(entry.lastOpenedAt)
      ? entry.lastOpenedAt : Date.now(),
    // title 仅字符串才采纳（畸形输入容错，同 parseLedger 口径）
    ...(typeof entry.title === 'string' ? { title: entry.title } : {}),
  }
  const rest = (Array.isArray(entries) ? entries : []).filter(e => e && e.id !== next.id)
  const out = [next, ...rest]
  return cap > 0 && out.length > cap ? out.slice(0, cap) : out
}

/**
 * 从账册剔除一个 id（打开失败的残留清理：会话已被磁盘清理时点击 open
 * 失败，顺手剔除——一行容错，非清理 UI）。返回新数组（不改入参）。
 */
export function removeEntry(entries: OpenedEntry[], id: string): OpenedEntry[] {
  return (Array.isArray(entries) ? entries : []).filter(e => e && e.id !== id)
}

/**
 * 重命名一个账册条目（t260831-06 tab 重命名）：同 id 条目更新 title——
 * 入参 trim 后为空串=清除自定义名（恢复默认 displayTitle 显示），非空即采纳；
 * 未知 id 原样返回（不造条目）；返回新数组（不改入参）。纯函数无 IO，落盘
 * 由调用方 persist。
 */
export function renameEntry(entries: OpenedEntry[], id: string, title: string): OpenedEntry[] {
  if (!Array.isArray(entries)) return []
  const t = typeof title === 'string' ? title.trim() : ''
  return entries.map(e => {
    if (!e || e.id !== id) return e
    const next: OpenedEntry = { ...e }
    if (t === '') delete next.title
    else next.title = t
    return next
  })
}

/**
 * 算侧栏切换行：账册 → 按当前项目过滤 → MRU（lastOpenedAt 降序；t260831-06 起
 * 打开路径不再更新 lastOpenedAt——排序结果=登记顺序，点 tab 停在原地）→
 * ≤limit → current 保底（通过过滤却被截断时替换最末一名，沿用 t260825-02 语义
 * ——当前活跃会话掉出列表会让「我在哪」不可感知）→ 标题/高亮装配。
 *
 * - project 为空串 = 未选项目（多项目注册表下新建按钮同步禁用）→ 空列表；
 * - 标题：条目自定义 title 非空优先（tab 重命名，t260831-06），否则从 byId
 *   （ctx.sessions.list 的 byId）取 displayTitle，再缺失兜底 id（账册有、list 无
 *   = 会话已被磁盘清理的残留条目，照常渲染不崩，点击打开失败时由 UI 层
 *   removeEntry 剔除）；
 * - active = id === current（current 来自 ctx.sessions.list）。
 */
export function pickSwitchTargets(
  entries: OpenedEntry[],
  opts: {
    project: string
    current?: string
    byId?: Record<string, TitleRowLike | undefined>
    limit?: number
  },
): SwitchTarget[] {
  const limit = opts?.limit ?? SWITCH_LIMIT
  if (!opts || typeof opts.project !== 'string' || opts.project === '' || limit <= 0) return []
  const byId = opts.byId ?? {}
  const current = opts.current
  const eligible = (Array.isArray(entries) ? entries : [])
    // 工单会话不进列表（t260828-06 防御纵深）：正常口径 touchEntry 已把 ticket-
    // 前缀挡在账册外，这里再挡一层——hero 接管后列表消费方多了一处，防线随之补齐；
    // 合法条目不受影响（工单会话从来不该在账册里）。
    .filter(e => e && typeof e.id === 'string' && e.project === opts.project && isGlobalSessionId(e.id))
    .slice()
  eligible.sort((a, b) => (b.lastOpenedAt ?? 0) - (a.lastOpenedAt ?? 0))
  // current 保底入选：通过过滤却被截断时，替换最末一名。
  if (current !== undefined && eligible.length > limit) {
    const curIdx = eligible.findIndex(e => e.id === current)
    if (curIdx >= limit) {
      eligible[limit - 1] = eligible[curIdx]
    }
  }
  return eligible.slice(0, limit).map(e => ({
    id: e.id,
    title: typeof e.title === 'string' && e.title.trim() !== '' ? e.title : labelOf(byId[e.id], e.id),
    cwd: typeof e.cwd === 'string' ? e.cwd : '',
    active: e.id === current,
  }))
}

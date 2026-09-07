/**
 * sandbar-workbench · 侧栏「会话」区记账层纯函数（session-entry t260828-02，
 * 口径调整：项目归属 + 只列 UI 主动打开的会话）。
 *
 * 口径（设计真源 docs/design/右栏会话入口与hero定制设计.md §2/§4/附录）：
 * ctx.sessions.list 是全量枚举（磁盘存量、他途所建都在里面），不带「是否
 * UI 主动打开」信息——所以列表数据源不是它，而是插件自建的账册：仅当用户
 * 通过本插件 UI 主动打开（点切换行）或新建（＋新建按钮）一个会话时登记
 * {id, project, cwd, lastOpenedAt}，MRU 排序；磁盘存量、工单会话、subagent
 * 会话一律不进账册，不做置顶/钉选（MRU 自然收敛）。
 *
 * 票② R8（t260904-05）：顶部行及其专属纯函数（切换行推导/MRU 上限/重命名）
 * 已随顶部行退役删除（全仓无残留符号，smoke 有「不在场」反转断言看守）；
 * 账册 title 字段与 parseLedger/touchEntry 的 title 采纳保留（blank 换绑
 * 随条目带回）。
 *
 * 第 3 面①（t260904-01，项目内会话区）：账册零迁移成本复用——条目加可选 seq
 * （项目内登记序号，关闭不回收），pickProjectTabs / backfillProjectSeqs /
 * nextProjectSeq 三个纯函数供项目行消费。票② R8 后项目行是唯一渲染消费面。
 *
 * 完备性：工单台侧栏已顶掉出厂工作区浏览器，UI 上打开项目会话的入口就是
 * 本插件。t260829-06 起 hero 槽位替换落地：hero 紧凑入口复用本层
 * （useSessionEntry），新建/切换登记进同一账册——「hero 首条消息会话不进账」
 * 的过渡期缺口对本插件入口已消除；出厂大输入卡（无接管槽，修订口径共存）
 * 发出的首条消息所建会话仍不进账册，属设计文档 §4 明示的共存残留。
 *
 * t260831-06 口径变更（顶行 tab 三修）：
 *   - 打开路径（handleOpen）不再 touchEntry——lastOpenedAt 只在登记时写
 *     （新建/blank 自愈换绑两条显式路径，时间单调递增=登记顺序），点 tab
 *     不重排（↺ 恢复路径已随 R8 顶部行退役）。
 *   - OpenedEntry 加可选 title：用户自定义命名（重命名入口已随 R8 退役；
 *     字段保留，blank 换绑随条目带回）。
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
  /** 所属项目 key（注册表；新建落点记录）。260904 起顶部行不按它过滤；第 3 面①
   *  起项目内会话区按它过滤消费（同一账册两个视图，口径互补不互扰）。 */
  project: string
  /** 所属项目主目录（登记时的会话 cwd；展示/诊断用，过滤以 project 为准）。 */
  cwd: string
  /** 最近打开时间（ms 时间戳；MRU 排序键——t260831-06 起只在登记路径写，打开不更新）。 */
  lastOpenedAt: number
  /** 用户自定义 tab 名（可选；非空时优先于 displayTitle 显示，t260831-06）。 */
  title?: string
  /** 项目内登记序号（第 3 面①，拍板 1「不回收」）：项目会话区 tab 上的数字。
   *  登记时分配；关闭不回收（其余 tab 保留原号、新会话从每项目计数器续号）；
   *  重开/blank 换绑随条目带回原号（稳定身份）。可选字段=存量条目迁移前的
   *  过渡态，由 backfillProjectSeqs 幂等补号；pickProjectTabs 不显示缺号条目。 */
  seq?: number
}

/** 项目内会话 tab（渲染就绪，第 3 面① R2/R6）。 */
export interface ProjectTab {
  id: string
  /** 项目内登记序号（tab 上的数字；关闭不回收，序列可有洞）。 */
  seq: number
  /** 提示用标题（自定义 title → displayTitle → id 三级兜底）。 */
  title: string
  /** 是否右栏当前会话（高亮；全局 current 唯一 → 至多一个 true）。 */
  active: boolean
}

/** 标题来源的最小面（SessionSummary 的子集；结构类型，测试可喂裸对象）。 */
export interface TitleRowLike {
  displayTitle?: string
}

/**
 * 账册存储上限（跨项目共用一册，超出的最旧条目自然淘汰——防无限增长，
 * 账册层全局兜底；项目 tab 数量不设上限，拍板 2）。
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
      // seq 仅有限数采纳（第 3 面①；NaN/Infinity/字符串等畸形输入剔字段不崩）
      ...(typeof e.seq === 'number' && Number.isFinite(e.seq) ? { seq: e.seq } : {}),
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
 * （不改入参）。只服务新建登记、blank 自愈换绑两条显式路径（↺ 恢复已随
 * R8 顶部行退役）。
 */
export function touchEntry(
  entries: OpenedEntry[],
  entry: { id: string; project: string; cwd?: string; lastOpenedAt?: number; title?: string; seq?: number },
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
    // seq 仅有限数采纳（第 3 面①：重开/换绑带原号；畸形输入剔字段走 backfill 补号）
    ...(typeof entry.seq === 'number' && Number.isFinite(entry.seq) ? { seq: entry.seq } : {}),
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

/* ───────────────── 项目内会话区（第 3 面①，R2/R4/R6 + 拍板 1/2）─────────────────
 * 口径真源 notes/epics/session-entry.md：数据源=本账册按 project 过滤；编号=项目内
 * 登记顺序、关闭不回收（seq 存条目 + 每项目计数器续号，见 session-entry.tsx
 * SEQ_COUNTER_KEY）；数量不限（无 limit——LEDGER_CAP=20 仍是账册层全局兜底，
 * 拍板 2 已认）；工单会话纵深防御再挡一层。纯函数无 IO，smoke 直跑。 */

/**
 * 算项目内会话 tab：账册按 project 精确过滤 → 只留有合法 seq（≥1 有限数）的
 * 条目 → seq 升序（=登记顺序）→ 标题/高亮装配。无上限（拍板 2）；缺 seq 条目
 * 不显示（迁移过渡态——消费方挂载时先走 backfillProjectSeqs 补号，防御纵深）。
 * active = id === current（与顶部行同源；current 全局唯一 → 高亮至多一个，
 * current 为工单会话/未入账会话时全不亮，R6）。
 */
export function pickProjectTabs(
  entries: OpenedEntry[],
  opts: {
    project?: unknown
    current?: string
    byId?: Record<string, TitleRowLike | undefined>
  },
): ProjectTab[] {
  const project = typeof opts?.project === 'string' ? opts.project : ''
  if (project === '') return []
  const byId = opts?.byId ?? {}
  const current = opts?.current
  return (Array.isArray(entries) ? entries : [])
    // 工单会话不进 tab（防御纵深：touchEntry 已挡一层，这里再挡一层）
    .filter(e => e && typeof e.id === 'string' && isGlobalSessionId(e.id) && e.project === project)
    .map(e => ({
      id: e.id,
      seq: typeof e.seq === 'number' && Number.isFinite(e.seq) && e.seq >= 1 ? Math.floor(e.seq) : 0,
      title: typeof e.title === 'string' && e.title.trim() !== '' ? e.title : labelOf(byId[e.id], e.id),
      active: e.id === current,
    }))
    // 缺号/坏号条目不显示（backfill 先行的不变式；显示缺号条目=数字无意义）
    .filter(t => t.seq >= 1)
    .sort((a, b) => a.seq - b.seq)
}

/**
 * 存量编号迁移（幂等）：账册里缺 seq 的条目（第 3 面① 之前登记的存量）按
 * 项目内登记顺序（lastOpenedAt 升序——t260831-06 起该键只在登记路径写、单调
 * 递增=登记顺序；并列时按数组位置稳定破平）补号，从「该项目现存最大 seq」之上
 * 续起，保项目内 seq 唯一不变式。无缺号时**原样返回入参引用**（调用方据此免
 * persist——sidebar 挂载 effect 用引用相等判无操作）。返回新数组不改入参。
 *
 * 交错态说明（常态不可达，防御口径）：迁移后新登记条目都带 seq，账册不应再有
 * 缺号条目；若因异常路径（如重开时原号畸形被 touchEntry 剔字段）再现缺号，
 * 本函数从该项目现存最大号之上续——不重号（不变式优先），该条目显示顺序
 * 排在存量之后（lastOpenedAt 最新，语义上即「重新登记」，可接受）。
 */
export function backfillProjectSeqs(entries: OpenedEntry[]): OpenedEntry[] {
  const list = Array.isArray(entries) ? entries : []
  const seqOf = (e: OpenedEntry): number =>
    typeof e?.seq === 'number' && Number.isFinite(e.seq) && e.seq >= 1 ? Math.floor(e.seq) : 0
  // 每项目现存最大 seq（补号从其上续）+ 是否存在缺号
  const maxByProject = new Map<string, number>()
  let hasGap = false
  for (const e of list) {
    if (!e || typeof e.project !== 'string' || e.project === '') continue
    const s = seqOf(e)
    if (s > 0) maxByProject.set(e.project, Math.max(maxByProject.get(e.project) ?? 0, s))
    else hasGap = true
  }
  if (!hasGap) return list
  // 缺号条目按（lastOpenedAt 升序, 原数组位置）排序后逐个续号
  const gaps = list
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => e && seqOf(e) === 0 && typeof e.project === 'string' && e.project !== '')
    .sort((a, b) => (a.e.lastOpenedAt ?? 0) - (b.e.lastOpenedAt ?? 0) || a.i - b.i)
  const assign = new Map<number, number>()
  for (const { e, i } of gaps) {
    const next = (maxByProject.get(e.project) ?? 0) + 1
    maxByProject.set(e.project, next)
    assign.set(i, next)
  }
  return list.map((e, i) => (assign.has(i) ? { ...e, seq: assign.get(i) as number } : e))
}

/**
 * 算某项目的下一个可用编号（登记时调用；号域含「最近关闭」——closed 数据
 * 在 ↺ 恢复随顶部行退役后仍保留，仅作防撞号域，BO-1）：max(计数器值, 账册内该项目现存最大
 * seq, 「最近关闭」内该项目最大 seq) + 1（closed 号域为 t260904-01 验收走查
 * BO-1 修复：计数器丢失时已关的最大号不再重发——重发后再从 ↺ 重开原号条目
 * 会撞号，破坏拍板 1 的「稳定身份」）。计数器丢失/落后时以账册与最近关闭
 * 兜底——只可能跳号，不可能重号（编号语义=稳定身份而非稠密序列，跳号无害）。
 * 畸形容错：计数器非有限数/负数按 0 处理；project 非字符串按「无账册条目」
 * 处理；closed 非数组忽略、脏条目（缺 project/seq 非有限数）跳过。
 */
export function nextProjectSeq(
  entries: OpenedEntry[],
  project: unknown,
  counterMax?: unknown,
  closed?: OpenedEntry[],
): number {
  let max = typeof counterMax === 'number' && Number.isFinite(counterMax) && counterMax > 0
    ? Math.floor(counterMax) : 0
  if (typeof project === 'string' && project !== '') {
    for (const e of Array.isArray(entries) ? entries : []) {
      if (!e || e.project !== project) continue
      if (typeof e.seq === 'number' && Number.isFinite(e.seq) && e.seq > max) max = Math.floor(e.seq)
    }
    // 已关条目的号不回收（拍板 1）：兜底号域一并计入，防计数器丢失后重发已关号
    for (const e of Array.isArray(closed) ? closed : []) {
      if (!e || e.project !== project) continue
      if (typeof e.seq === 'number' && Number.isFinite(e.seq) && e.seq > max) max = Math.floor(e.seq)
    }
  }
  return max + 1
}

/**
 * ticket-time-model.ts —— 「本票时刻只读查看」纯函数层（t260915-17，260904 详情
 * mock 标注 D 落地：文件行=链接，点开以本票时刻的版本只读打开）。
 *
 * 职责（无 DOM / 无 IO，node 裸 import 直测——docs-model.ts 分层先例）：
 *   1. 时刻口径 mode 词表与判定：settle=收口版（该票的提交版本）/ base=开票基点版
 *      （base_ref）/ current=当前版（「跳到当前版」专用，唯一允许读工作树的口径，
 *      语义就是「现在」，不冒充本票时刻）。
 *   2. 仓内相对路径白名单 isSafeTicketFilePath——比 docs 的 isSafeDocRel 宽
 *      （工单文件含 .ts/.mjs/.py/.json 等任意扩展），防穿立场一致：拒绝对、`..`
 *      段、反斜杠、绝对路径、URL 编码残留、空白与空串。
 *   3. 在飞谓词 isInFlightStatus（review C1/N2 钉死口径）：**只认 status 面**
 *      dispatched|rework——stage_state 不作在飞判据（dev_lane update_status 在写入
 *      settled 的瞬间把 stage_state=running 强转 awaiting，正常时序下 settled 票
 *      不会被 running 误伤；反之在飞票的泳道分支必然在场，分支存在性不可作判据）。
 *   4. 失败 reason 人话构表（host 计算核与 UI 失败面板共用同一文案单源；
 *      fail-closed 文案必须点名「为什么拿不到」与「该看哪」，绝不静默回落）。
 *   5. 横幅视图模型 buildTicketTimeBanner：mock D 原话主文案「🕰 本票时刻 · 只读」
 *      + 版本副文案（ref 短哈希 + 来源标签）+「跳到当前版」小链显隐。
 *
 * 归属口径（review C4）：背景引用（refs）的开票闸只对根仓校验——base 口径一律按
 * 根仓票面 base_ref 读，不做 path→repo 归属；改动文件（settle）才走逐仓归属
 * （成员仓路径带 <repo>/ 前缀，与 diff 面定位口径归一）。成员仓路径的 base 口径
 * 常态=fail-closed「成员仓路径未登记开票基点」——诚实降级不是缺陷，不修成回落。
 */

/** 时刻口径词表。 */
export type TicketTimeMode = 'settle' | 'base' | 'current'

export const TICKET_TIME_MODES: readonly TicketTimeMode[] = ['settle', 'base', 'current']

export function isTicketTimeMode(v: unknown): v is TicketTimeMode {
  return v === 'settle' || v === 'base' || v === 'current'
}

/**
 * 仓内相对路径白名单：段字符集=字母数字下划线 + 中文 + 点 + 连字符；`/` 分段；
 * 段不得为 `.` 或 `..`；整串不得为空。显式拒绝：绝对路径（/ 开头）、反斜杠、
 * 空白字符、URL 编码残留（%xx）、空串、非字符串。穿路径进不来（fail-closed）。
 */
const TICKET_FILE_PATH_RE = /^(?:[\w\u4e00-\u9fff.-]+\/)*[\w\u4e00-\u9fff.-]+$/

export function isSafeTicketFilePath(rel: unknown): rel is string {
  if (typeof rel !== 'string' || rel === '') return false
  if (rel.includes('\\') || rel.includes('%')) return false
  if (/\s/.test(rel)) return false
  if (rel.startsWith('/')) return false
  if (!TICKET_FILE_PATH_RE.test(rel)) return false
  return !rel.split('/').some((seg) => seg === '.' || seg === '..')
}

/**
 * 在飞谓词（C1：settle 定位梯子的前置闸）。在飞=status∈{dispatched, rework}——
 * 此态改动尚未收口，收口版不存在；泳道分支此时必然在场（teardown_lane 收口才删），
 * 故分支存在性不能反证「已收口」。非字符串/畸形值不在飞（由调用方按形状另报
 * 「票面 status 畸形」，不冒充在飞语义）。
 */
export function isInFlightStatus(status: unknown): boolean {
  return status === 'dispatched' || status === 'rework'
}

/** 已收口可查态（settle 梯子的合法入口；之外的畸形值由 host 显式报形状错）。 */
export function isSettleCapableStatus(status: unknown): boolean {
  return status === 'settled' || status === 'verified' || status === 'closed'
}

/** 收口提交/基点读取失败的人话构表（host 与 UI 失败面板共用单源）。 */
export type TicketTimeFailKind =
  | 'bad-status'            // 票面 status 缺失/畸形，判不了收口态
  | 'in-flight'             // 票在飞（C1：分支在场也拒）
  | 'main-lane'             // 主树道工单无泳道提交（N1 专门文案，不误导成「泳道已拆」）
  | 'lane-gone'             // 已收口但泳道分支与 main 收口提交都不可得
  | 'path-not-in-version'   // 路径不在该版本（该时刻此文件不存在或未纳入）
  | 'no-base'               // 票面未登记 base_ref（主树道常态）
  | 'member-repo-no-base'   // 成员仓路径的 base 口径（C4③：诚实降级不是 bug）
  | 'invalid-base'          // base_ref 不是可用 ref
  | 'binary'                // 二进制/非 UTF8（C5②：乱码冒充时刻版=温和版撒谎）
  | 'current-missing'       // current 口径：当前工作树无此文件
  | 'repo-error'            // git 读面异常（超时/非仓/缓冲超限）

/** 失败文案单源：每条都答「为什么拿不到本票时刻版」，能指路的顺带指路。 */
export function ticketTimeFailReason(kind: TicketTimeFailKind, detail?: string): string {
  switch (kind) {
    case 'bad-status':
      return `票面 status 缺失或畸形（${detail ?? '未知'}），无法判定本票收口态——本票时刻不可得`
    case 'in-flight':
      return '本票还在飞，改动尚未收口——收口版要等本票结算合并后才有（当前改动可在「变更」页签看 diff）'
    case 'main-lane':
      return '主树道工单无泳道提交，本票时刻的收口版不可得'
    case 'lane-gone':
      return `泳道已拆除，且 main 上找不到本票（${detail ?? ''}）的收口提交——本票时刻不可得`
    case 'path-not-in-version':
      return `路径 ${detail ?? ''} 不在该版本里（该时刻此文件不存在或未纳入）`
    case 'no-base':
      return '本票未登记开票基点（base_ref 为空——主树道工单不登记基点），开票基线版不可得'
    case 'member-repo-no-base':
      return '成员仓路径未登记开票基点（逐仓基点不回写票面），开票基线版不可得'
    case 'invalid-base':
      return `开票基点 ref 无效：${detail ?? ''}`
    case 'binary':
      return '二进制文件，本查看器不渲染'
    case 'current-missing':
      return `路径 ${detail ?? ''} 在当前工作树不存在（可能已删除）`
    case 'repo-error':
      return `本票时刻读取失败：${detail ?? '仓库读面异常'}`
  }
}

/** ref 来源标签（横幅副文案 + 响应 refSource 字段共用）。 */
export type RefSource = 'branch-tip' | 'merge-commit' | 'squash-commit' | 'base-ref'

export function refSourceLabel(s: RefSource): string {
  switch (s) {
    case 'branch-tip': return '泳道分支提交（未合并）'
    case 'merge-commit': return 'merge 收口提交'
    case 'squash-commit': return 'squash 收口提交'
    case 'base-ref': return '开票基点'
  }
}

export interface TicketTimeBannerView {
  /** 固定主文案（mock D 原话，定值）。 */
  text: string
  /** 版本副文案：如「收口版 a1b2c3d4e5f6 · squash 收口提交」。 */
  version: string
  /** 「跳到当前版」小链显隐（settle/base=true；current 无横幅）。 */
  canJumpCurrent: boolean
}

/**
 * 横幅视图模型（mock D：顶部横幅「🕰 本票时刻 · 只读」，带「跳到当前版」小链）。
 * current 口径返回 null（横幅消失=切到当前版的可见信号，验收口径①锁这点）。
 * refShort 畸形（非字符串/空）返回 null——横幅不渲染假版本号，宁可整条不显。
 */
export function buildTicketTimeBanner(
  mode: TicketTimeMode,
  refSource: RefSource,
  refShort: unknown,
): TicketTimeBannerView | null {
  if (mode === 'current') return null
  if (mode !== 'settle' && mode !== 'base') return null
  if (typeof refShort !== 'string' || refShort.trim() === '') return null
  const version = mode === 'settle'
    ? `收口版 ${refShort} · ${refSourceLabel(refSource)}`
    : `开票基线版 ${refShort} · ${refSourceLabel(refSource)}`
  return { text: '🕰 本票时刻 · 只读', version, canJumpCurrent: true }
}

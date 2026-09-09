/**
 * stale-check.ts —— host 陈旧响应分类纯函数（t260902-03 立，t260905-07 KI-052
 * 握手矩阵扩展）。不 import react / 无 DOM，smoke 裸 node 直跑（响应分类逻辑必须
 * 可单测）。
 *
 * 两层判定，演进不另起新文件：
 *
 * 1) classifyBuildInfoResponse —— 服务端应答分类（t260902-03 原口径不变）：
 *    非 2xx、JSON 解析失败、缺 stale 字段、带 error 字段 → {stale:false} 不抛错
 *    （看守自身不得成为新报错源；error=指纹全缺部署异常，不属陈旧提醒范畴）。
 *
 * 2) classifyHandshake —— 三元组（boot/disk/injected）握手判定矩阵（KI-052 根治，
 *    方案 M1-M7＋评审附条件意见 1 修订）：
 *    M1  200 & stale=true（boot≠disk，服务端旧）        → 显「重启」横幅
 *    M2  405/404（端点内存无=看守更旧，KI-052 主现场）   → 显「重启」横幅
 *    M3  200 & 无 error & 缺/类型错 bootFingerprint      → 显「重启」横幅（同构性破坏）
 *    M4  200 & stale=false & injected≠disk（注入在场）   → 显「刷新」横幅
 *        （浏览器旧——含跨重启存活页面：重启后 boot==disk，本支消除动作=刷新，
 *         不再误导宿主去重启 N 次；文案与消除动作一一对应）
 *    M5  200 & stale=false & 其余（injected==disk 或缺失）→ 不显
 *    M6  500，或 200+error 字段（review 附条件1：按既有口径，error→不显+透传；
 *        「重启」对部署异常无效，横幅不做第二报错源）      → 不显，error 透传
 *    M7  502/503/504、网络错（fetch 异常由调用方归入本层）、畸形 JSON → 不显
 *        （部署抖动宁漏勿假警）
 *    优先级即上表行序：stale/error 判定先于 injected 比对（boot≠disk 时 injected
 *    任意归 M1——先「重启」后「刷新」，消除动作顺序正确）。
 *
 * 降级口径（有意降级，注释写明不静默绕过）：
 *   - injected 缺失（L2：bundle 注入点未接通/注入失败）→ M4 自动失效，仅消费
 *     服务端应答（stale/状态码）——矩阵天然兼容降级阶梯，注入缺席不产生误报。
 *   - 畸形 bootFingerprint/diskFingerprint（非 string）按缺失处理：disk 缺失时
 *     injected 无可比对基准，落 M5 不显（不猜测）。
 */

export interface BuildInfoVerdict {
  stale: boolean
  /** 端点带人话 error（指纹全缺=部署形态异常），与「陈旧」区分，供调试观测。 */
  error?: string
}

/** 握手判定结果：banner=null 不显；否则为横幅文案键（restart=重启生效 / reload=刷新生效）。 */
export interface HandshakeVerdict {
  banner: 'restart' | 'reload' | null
  /** 应答带 error 时的透传（M6；供调试观测，不影响横幅判定）。 */
  error?: string
}

/** 分类 build-info 响应（status + 原始文本）。不抛错——任何畸形输入都落 {stale:false}。 */
export function classifyBuildInfoResponse(status: number, bodyText: string): BuildInfoVerdict {
  if (status < 200 || status >= 300) return { stale: false }
  let parsed: unknown
  try {
    parsed = JSON.parse(bodyText)
  } catch {
    return { stale: false }
  }
  if (typeof parsed !== 'object' || parsed === null) return { stale: false }
  const result = (parsed as Record<string, unknown>).result
  if (typeof result !== 'object' || result === null) return { stale: false }
  const r = result as Record<string, unknown>
  if (typeof r.error === 'string') return { stale: false, error: r.error }
  return { stale: r.stale === true }
}

/** 解析 build-info 应答为 {stale, error, bootFingerprint, diskFingerprint} 的内部形态。
 *  任何畸形都归 null 字段（不抛）；status 非 2xx 返回 {statusOk:false}；
 *  JSON 不可解析/形状不对 → parseOk:false（与「可解析但缺指纹键」区分——前者 M7
 *  不显，后者 M3 显横幅，两格语义不同不许合并）。 */
interface HandshakeBody {
  statusOk: boolean
  parseOk: boolean
  stale: boolean | null
  error: string | null
  bootFingerprint: string | null
  diskFingerprint: string | null
}

function parseHandshakeBody(status: number, bodyText: string): HandshakeBody {
  if (status < 200 || status >= 300) {
    return { statusOk: false, parseOk: false, stale: null, error: null, bootFingerprint: null, diskFingerprint: null }
  }
  const empty: HandshakeBody = { statusOk: true, parseOk: false, stale: null, error: null, bootFingerprint: null, diskFingerprint: null }
  let parsed: unknown
  try {
    parsed = JSON.parse(bodyText)
  } catch {
    return empty
  }
  if (typeof parsed !== 'object' || parsed === null) return empty
  const result = (parsed as Record<string, unknown>).result
  if (typeof result !== 'object' || result === null) return empty
  const r = result as Record<string, unknown>
  return {
    statusOk: true,
    parseOk: true,
    stale: typeof r.stale === 'boolean' ? r.stale : null,
    error: typeof r.error === 'string' ? r.error : null,
    bootFingerprint: typeof r.bootFingerprint === 'string' && r.bootFingerprint !== '' ? r.bootFingerprint : null,
    diskFingerprint: typeof r.diskFingerprint === 'string' && r.diskFingerprint !== '' ? r.diskFingerprint : null,
  }
}

/**
 * 三元组握手判定（injected + status + 原始文本）。injected=bundle 下载时刻注入的
 * 盘上指纹（null=缺失：L2 阶梯/注入失败/纯刷新页面外的旧码），任何畸形输入都不抛。
 * 矩阵逐格语义见文件头注 M1-M7；单测真值表（tests/stale-handshake.mjs）逐格对应。
 */
export function classifyHandshake(injected: string | null, status: number, bodyText: string): HandshakeVerdict {
  const b = parseHandshakeBody(status, bodyText)
  // M7：非 2xx 且非「端点缺失」语义（405/404 有专门语义）→ 不可判定不显。
  // M2：405/404=端点不在内存（看守自身更旧或不存在）——KI-052 主现场，强陈旧信号。
  if (!b.statusOk) {
    return { banner: status === 405 || status === 404 ? 'restart' : null }
  }
  // M6（200+error 扩展格，review 附条件1）：指纹全缺/部署异常不显，error 透传。
  if (b.error !== null) return { banner: null, error: b.error }
  // M7（可解析性分支）：应答不可解析/形状不对 → 不可判定不显（畸形≠陈旧）。
  if (!b.parseOk) return { banner: null }
  // M1：服务端明确报陈旧（boot≠disk）→ 重启生效。
  if (b.stale === true) return { banner: 'restart' }
  // M3：可解析应答但缺 boot 指纹（同构性被破坏——看守半新半旧的中间态）→ 重启生效。
  if (b.stale === null || b.bootFingerprint === null) return { banner: 'restart' }
  // M4：服务端一致（boot==disk），但浏览器持有的注入指纹≠当下盘上 disk 指纹
  // → 浏览器旧，刷新生效（重启无效——跨重启存活页面的正确消除动作）。
  // injected 缺失（null）或 disk 缺失（无基准）→ 落 M5 不显（不猜测）。
  if (injected !== null && b.diskFingerprint !== null && injected !== b.diskFingerprint) {
    return { banner: 'reload' }
  }
  // M5：一致态。
  return { banner: null }
}

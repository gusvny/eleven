/**
 * sandbar-workbench —— 工单工作流台的 dsh UI 插件（宿主半 / node）。
 *
 * 职责：在 dsh 自己的 webServer 上挂 /sandbar-workbench/api/wf/*（工单工作流台设计
 * v0.3 §5/§9），供本插件的浏览器半（lib/client.js，设置面板「工单台」分区）同源
 * fetch 使用。独立命名，不寄生 sandbar-admin-ui 壳：
 *
 *   GET  /sandbar-workbench/api/wf/projects       → 项目注册表（260823 多项目化；t260904-15 起走
 *                                                 loadRegistry()：projects + quarantined 隔离条目，
 *                                                 空/全隔离注册表不 500——首接发生在空表时）
 *   GET  /sandbar-workbench/api/wf/projects/detail?key=
 *                                               → 项目详情票计数（票③面D：spawn 安装器
 *                                                 `sandbar project list --json` 单点取 Temporal
 *                                                 计数；CLI 降级 tickets_state 透传由弹层显「—」）
 *   POST /sandbar-workbench/api/wf/projects/add   → 项目接入（票③面D：薄壳 spawn `sandbar project
 *                                                 add --json`；dry_run:true=422 能力应答——CLI 无
 *                                                 add --dry-run 旗（F1），预检=弹层本地形状检查）
 *   POST /sandbar-workbench/api/wf/projects/remove
 *                                               → 项目摘除（票③面D：薄壳 spawn `sandbar project
 *                                                 remove --json`，dry_run/purge/confirm-last 旗一一对应；
 *                                                 在飞闸 fail-closed 文案由 CLI 错误体透传）
 *   GET  /sandbar-workbench/api/wf/tickets?project=<key>
 *                                               → ticket list（按 ProjectKey SA 过滤；project 必传、无默认值；
 *                                                 台面行；enrich=progress 时附进展行）+ workflow list（全局模板表）
 *   GET  /sandbar-workbench/api/wf/tickets?project=<key>&enrich=progress[&ids=a,b]
 *                                               → 进展行 enrichment（t260904-17）：主响应零 show；
 *                                                 enrich 阶段逐票 show 短超时+并发上限+allSettled
 *   GET  /sandbar-workbench/api/wf/tickets/<id>   → ticket show（详情全文）
 *   POST /sandbar-workbench/api/wf/tickets/<id>/accept|advance|dispatch-next|rework|update
 *                                               → 写操作，走 admin.py call ticket（run-id 审计）
 *   GET  /sandbar-workbench/api/wf/workflows      → workflow list（模板链，泳道图用）
 *   GET  /sandbar-workbench/api/wf/docs/tree?scope=docs|notes[&project=<key>]
 *                                               → 「文档」视图目录树（t260905-06；KI-070 起
 *                                                 按项目根解析——?project= 项目锚下读该项目
 *                                                 自己的 docs|notes，缺省/未锚回落引擎仓）：
 *                                                 .md 动态分组（title 自 frontmatter）；白名单
 *                                                 拒收文件进 skipped（可见性）；目录缺席
 *                                                 {empty,reason} 降级；resolved 挂解析来源
 *   GET  /sandbar-workbench/api/wf/docs/doc?scope=docs&path=design/xx.md[&project=<key>]
 *                                               → 「文档」视图按篇正文（原文+frontmatter 元数据；
 *                                                 项目根口径同 tree；白名单/穿路径/大小上限
 *                                                 逐检查精确报错；只读）
 *   GET  /sandbar-workbench/api/wf/book?path=books/hanshu/jizhuan.json&limit=5
 *                                               → 内容预览（审批前过目）：只读 app/public/data/<path>，
 *                                                 返回 meta + 前 limit 章（标题+段落）；path 白名单防穿路径
 *   GET  /sandbar-workbench/api/wf/temporal-health → Temporal 健康（只读，t260821-06）：真实探测
 *                                                 127.0.0.1:7233 端口是否监听（=server 在线）+ worker
 *                                                 pidfile pid 是否存活（=worker 在线），不写死结果
 *   GET  /sandbar-workbench/api/wf/workers        → worker 清单（260824 每工单专属 worker）：
 *                                                 扫 data/worker*.pid 逐个探测存活（共享 sandbar +
 *                                                 专属 sandbar-ticket-<id>），状态条「N workers」数据源
 *   GET  /sandbar-workbench/api/wf/scan-report    → 巡检报告（只读，M6 t260821-m6-scan-expand）：
 *                                                 读 engine/out/scan/ 文件名序最新的
 *                                                 <YYYY-MM-DD>.json（DispatcherScanWorkflow 落盘）；
 *                                                 无报告走 reason 人话降级，不抛错
 *   POST /sandbar-workbench/api/global-session/open {project}
 *                                               → 新建全局会话（session-entry t260825-02，侧栏「会话」区
 *                                                 新建按钮）：仿工单会话开/找，但 id 不带 ticket- 前缀、
 *                                                 不注入工单上下文、always-create（全局会话每次新建一个；
 *                                                 cwd=该项目注册表主目录）
 *   GET  /sandbar-workbench/api/wf/tickets/<id>/agent-logs
 *                                               → 工单 agent 日志（只读，M12 t260822-m12）：
 *                                                 定泳道/隔离目录 .suyou/，列 agent_<stage>_gen<n>.log
 *                                                 （子 agent stdout/stderr 流）+ stage_<stage>_gen<n>.json
 *                                                 （段结算结果），带尾部内容/解析结果；无目录走
 *                                                 reason 人话降级，不抛错
 *   GET  /sandbar-workbench/api/wf/tickets/<id>/agent-live?n=30
 *                                               → agent 实时动态（只读，t260825-03）：泳道
 *                                                 .dsh/sessions/<cwd-slug>/<工单id>-<角色>/
 *                                                 session.jsonl.zstd 整解（zstd -dc，多帧拼接
 *                                                 直接解）取尾部 n 条事件摘要（assistant 文本截断 /
 *                                                 工具调用名+目标路径）；无会话文件/解压失败走
 *                                                 {exists:false,reason} 降级；工单字段 ../ 逃逸 → 400
 *
 * 立项单只读 API（epic-linkage Tier 2，t260825-04；真源=notes/epics/*.md + Temporal
 * 查询，UI 不存状态——立项单关键决策 5；代号存在性=文件存在性强校验——决策 2）：
 *   GET  /sandbar-workbench/api/epics            → 列 notes/epics/*.md：代号（文件名主名）/
 *                                                 标题（首个 # 行）/状态（字段表格「状态」行）/
 *                                                 立项日期；目录不存在/无文件 → 空数组不报错
 *   GET  /sandbar-workbench/api/epics/<code>     → 单份立项单 Markdown 全文；代号形状白名单
 *                                                 （shared.EPIC_CODE_RE 同款）+ 路径防穿双保险，
 *                                                 非法 400 / 不存在 404 人话
 *   GET  /sandbar-workbench/api/epics/<code>/tickets
 *                                               → 该立项全部工单实时状态聚合（复用 ticket list
 *                                                 --epic 通路）：按 status 分桶计数 + 工单行
 *                                                 （id/title/status/stage/stage_state）；Temporal
 *                                                 不可达 → {degraded:true, reason} 降级不 502
 *   POST /sandbar-workbench/api/epics/<code>/suggest-next
 *                                               → 「继续执行」建议 job 启动（t260827-02）：spawn 一次性
 *                                                 headless integration agent 分析立项现状，产出下一步
 *                                                 工单建议（模板/标题/正文）；同 code 进行中 job 复用
 *                                                 不重复起。agent 只产建议，不直接创建工单
 *   GET  /sandbar-workbench/api/epics/<code>/suggest-next/<jobId>
 *                                               → 建议 job 轮询：{state:running|done|failed,
 *                                                 suggestion?|reason?}；宿主重启丢注册表 → 404
 *                                                 （前端重新点击即可）
 *   归档快照 POST /epics/<code>/archive 本工单不做（无调用方，留给归档动作真正发生时的工单）。
 *
 * PR 式审批台（M9，t260821-m9-pr-approval）：
 *   GET  /sandbar-workbench/api/wf/tickets/<id>/diff
 *                                               → 工单变更集（只读）：泳道道=worktree 工作树 vs base_ref
 *                                                 文件级 diff（文档=渲染态 block diff 复用 knowledge
 *                                                 blocks.ts / 代码=unified diff / 数据=前后值对账）；
 *                                                 主树道=write_set+git log，给不出显「无变更记录」。
 *   GET  /sandbar-workbench/api/wf/tickets/<id>/review
 *                                               → 读审批意见（server/reviews/<工单id>.json，无则空 rounds）
 *   POST /sandbar-workbench/api/wf/tickets/<id>/review {base, conclude, blocks[], reviewer?}
 *                                               → 追加一轮审批意见落盘（工单 id 白名单防穿路径、
 *                                                 admin.log 同形 JSONL 审计+run-id；块 key 含内容哈希，
 *                                                 内容变→旧意见客户端标「已过期」，支持多轮迭代）
 *
 * 数据源：写操作=server/tools/ticket.py（读写统一走 runAdminCli spawn
 * admin.py（读列也走，不直读 json）——与模型通道 sandbar-tools 共用同一函数，
 * run-id 审计唯一数据源始终在 python server/admin.log（面板写操作不另开审计通道）。
 * t260910-04 起工单列表主数据改直走引擎 client.py ticket-list（runPocCli）：
 * 引擎行原生带 paused/paused_phase（t260908-01 暂停二态），ticket.py 薄壳投影
 * 曾把这两键丢掉；写操作/模型通道仍走 ticket.py+admin.py 审计口径不变。
 * M11 v2（t260822-m11 模版即代码）+ 260823 多项目化：**工单状态只在 Temporal
 * workflow**（旧 tickets/ JSON 投影目录已删）——ticket.py 薄壳内部全走 client.py
 * ticket-start/ticket-list/ticket-query/ticket，本插件路由按 project 传参即完成分流；
 * v2 行带 engine 标记，前端操作矩阵走 v2 分支
 * （无 dispatch-next/逐项 accept；blocked 的「解除阻塞」=retry-qc → Temporal retry_qc
 * signal，与 sign 同款直发）。
 * 待审批（awaiting-human）的审批/打回走签字（v2 base 的 sign signal，
 * decision=approve/reject），由本插件 spawn engine client.py 直发。
 * book 预览为纯只读文件服务（app/public/data/ 下，白名单 books/ 前缀）。
 *
 * headless profile 没有 webServer 服务：apply 静默待命（internal/service 事件
 * 等不到就什么都不挂），不报错不阻塞。
 *
 * repo 解析顺序：config.repo → SANDBAR_REPO → 按本文件位置推导
 * （<repo>/server/plugins/workbench/node.ts 上三级）。无任何机器绝对路径写死。
 */

import { execFile } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { appendFile, readFile, readdir, stat } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import net from 'node:net'
import { dirname, join, resolve, sep } from 'node:path'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'
import { runAdminCli } from '../../sandbar-tools.ts'
import { findProject, loadProjects, loadRegistry, primaryDir, type ProjectEntry } from '../../project-registry.ts'
// 项目锚解析器（t260907-11 KI-057）：请求层按 ?project= 解析项目根，六处静态锚穿参的
// 单一收口（取舍清单/env 覆盖闸/显式报错口径见该模块头注）。
import { anchorEnv, anchorEpicsDir, resolveProjectAnchor, resolvedMark, type ProjectAnchor } from './src/host/project-anchor.ts'
// 项目生命周期 CLI 薄壳（票③面D：写路径单源=安装器 CLI，读注册表仍走 TS 装载器；
// 票据/体检数据=CLI 独有面，spawn 恰是同源——取舍清单见 src/host/project-admin.ts 头注）。
import { ProjectCliError, runProjectCli } from './src/host/project-admin.ts'
// 「文档」视图宿主半（t260905-06；KI-070 起按项目根解析）：docs/ 定稿库 + notes/ 观察窗只读枚举/读取。
// 降级/白名单/句柄终态口径见该模块头注（R1 取舍清单 2）。
import { listDocs, readDoc } from './src/host/docs.ts'
import { isDocsScope } from './src/shared/docs-model.ts'

function projectRootsFor(projectKey: unknown): string[] {
  // 跨项目工单（t260903-11/-12）：票所属项目注册目录=实时态/日志读取的合法根。
  // 修复：findProject 是单参签名（自读注册表），首版误传 (projects, key) →恒
  // undefined→extraRoots 恒空→守卫照旧拒（t260903-12 实雷二次报障）。
  // 注册表异常→空数组=回落旧行为（仅本仓），不放大故障面。
  if (typeof projectKey !== 'string' || projectKey === '') return []
  try {
    const p = findProject(projectKey)
    return p ? p.dirs.filter((d): d is string => typeof d === 'string') : []
  } catch { return [] }
}

import { computeTicketDiff, type TicketForDiff } from './src/host/changes.ts'
import { ticketShowHttpVerdict } from './src/host/ticket-error.ts'
import { readLatestScanReport } from './src/host/scan-report.ts'
import { listAgentLogs, resolveAgentBaseDir, _sessionKbFast } from './src/host/agent-logs.ts'
import { readAgentLiveTail, resolveSessionFile } from './src/host/agent-live.ts'
import { aggregateTicketUsage, resolveAllSessionFiles, stageWindowsFromTimeline } from './src/host/agent-usage.ts'
import { buildMetricsResponse, defaultDeps } from './src/host/metrics.ts'
import { computeHostFingerprint, type HostFingerprint } from './src/host/build-info.ts'
// 首句派生纯函数（t260905-07）：client 半纯函数层无 react 依赖，node 侧直用同源
// ——列表 enrichment（title_or_first）与详情头部两条通道一个口径。
import { deriveTitleOrFirst } from './src/host/enrich.ts'
import { SESSION_CHARTER_PATH, composeSessionCharter } from './src/host/session-charter.ts'
import { closeEpic, isEvidenceFileName, listEpics, readEpicMarkdown, setEpicStatus } from './src/host/epics.ts'
import {
  dismissPrecache, findRunningJob, pollSuggestJob, precacheExists, readPrecache,
  readPrecacheHint, resolvePrecacheDir, startEpicNextJanitor, startSuggestJob, stateKeyFromRows,
  type EpicNextJob,
} from './src/host/epic-next.ts'
import {
  CONCLUDES, appendReviewRound, loadReview,
  type ReviewBlockEntry, type ReviewConclude, type ReviewRound,
} from '../knowledge/src/shared/review-store.ts'

const execFileP = promisify(execFile)

export const name = 'sandbar-workbench'
// webServer 只存在于 web profile；headless 下本插件待机即可，故不走 inject 硬依赖。
export const inject: string[] = []

/** 本文件固定落在 <repo>/server/plugins/workbench/ 下，上三级即仓库根。 */
const DEFAULT_REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/**
 * host 启动指纹（t260902-03 陈旧看守）：仅首次解析固化——apply 可能被宿主重放/
 * 多次调用，每次刷新会把新磁盘指纹误记为 boot 指纹，stale 永假（一日三咬照样咬）。
 * 不变量：进程内只算一次（Promise 单例），之后 apply 重放不覆盖。导出供 smoke await。
 */
let bootFingerprintP: Promise<HostFingerprint> | undefined
export function resolveBootFingerprint(repo: string): Promise<HostFingerprint> {
  bootFingerprintP ??= computeHostFingerprint(repo)
  return bootFingerprintP
}

/** 插件配置（cordis.patch.yml 里 config: 字段；全部可缺省）。 */
interface SuyouWorkbenchConfig {
  /** 溯游仓库根。缺省按本文件位置推导。 */
  repo?: string
  /** python 解释器，默认 python3。 */
  python?: string
  /** 子进程超时（毫秒），默认 300000。 */
  timeoutMs?: number
}

/** 详情路由前缀（prefix kind 挂在它下面；注册 path 不带尾斜杠——
 * webserver 的 prefix 匹配按 `${prefix}/` 判定，带尾斜杠会拼出双斜杠永不命中）。 */
const TICKETS_PREFIX = '/sandbar-workbench/api/wf/tickets'
/** 立项单路由前缀（epic-linkage Tier 2）：exact 挂列表，prefix 挂 <code>[ /tickets]。 */
const EPICS_PREFIX = '/sandbar-workbench/api/epics'
/** POST 操作白名单（admin.py 引擎的 op 子集 + sign=审批签字走 Temporal signal；
 *  M11 v2 加 retry-qc=blocked 重跑走 Temporal retry_qc signal；
 *  t260908-01 加 pause/resume=段间暂停·恢复走 Temporal pause/resume signal）。
 *  create 不进此表：它没有工单 id，落 exact 路由 /wf/tickets 的 POST 分支
 *  （handleTicketCreate，epic-linkage Tier 3 / t260826-02），与 <id>/<op> 路径正交。
 *  review（审批意见落盘）不进此表——它不经过 admin.py，在路由里按 method 单独分支。 */
const OPS = new Set(['accept', 'advance', 'dispatch-next', 'rework', 'update', 'sign', 'retry-qc', 'pause', 'resume'])

/** 工单 id 白名单：review 落盘文件名由它拼出，必须防穿路径（同 knowledge DOC_PATH_RE 的角色）。
 *  放行 Han 字（真实工单 id 含中文，54 张全量体检零误伤）；/ \ . % 与控制字符全在表外，穿路径无门。 */
const TICKET_ID_RE = /^[A-Za-z0-9\p{Script=Han}][A-Za-z0-9_\-\p{Script=Han}]{2,80}$/u

/**
 * 工单快照 → 首条上下文消息（t260831-08 从 handleTicketSessionOpen 的闭包抽出，
 * 逻辑主体逐字迁移；smoke 直测同口径防实现漂移）。唯一偏离（t260831-08 方案取舍
 * 清单 #5）：pending/acceptance 加 Array.isArray 防线——工单数据来自 Temporal 投影，
 * 字段类型漂移是现实输入，原 `?? []` 写法对对象型 pending 会在 .slice 抛 TypeError。
 */
export function ticketContext(input: any): string {
  const tk = (input && typeof input === 'object') ? input : {}
  const lines: string[] = [
    `【工单上下文】${tk.id}《${tk.title ?? ''}》`,
    `工作流：${tk.workflow ?? '—'} · 角色：${tk.role ?? '—'} · 当前阶段：${tk.stage ?? '—'}（${tk.stage_state ?? '—'}）`,
  ]
  if (tk.blocked_reason) lines.push(`阻塞原因：${tk.blocked_reason}`)
  const pend = Array.isArray(tk.pending) ? tk.pending as any[] : []
  for (const p of pend.slice(0, 5)) lines.push(`待审批：${p?.gate ?? ''} — ${p?.reason ?? ''}`)
  const acc = Array.isArray(tk.acceptance) ? tk.acceptance as any[] : []
  if (acc.length > 0) lines.push(`验收标准：\n${acc.slice(0, 8).map((a, i) => `${i + 1}. ${a}`).join('\n')}`)
  const bodyText = String(tk.body ?? '').trim()
  if (bodyText) lines.push(`工单正文：\n${bodyText.slice(0, 600)}${bodyText.length > 600 ? '…' : ''}`)
  lines.push('——以上是这张工单的快照。接下来的对话都围绕它：先回我一段你对现状的理解和下一步建议。')
  return lines.join('\n')
}

/**
 * 证据候选目录收口（t260910-05 路径新名迁移）：取图/列表两端点共用的唯一候选面，
 * 杜绝两处再错位。读侧全面切新名（`.sandbar/` 点目录、`.lane/<id>` 泳道根）并保留
 * 旧名只读回落（naming-compat：`.suyou/` 粘滞泳道、`.worktrees/` 老泳道根——处理在飞
 * 老泳道的历史数据；写侧真源=引擎 shared.ui_evidence_dir/evidence_base，新泳道只写
 * 新名）。读侧用枚举回落而非照抄引擎 resolve_dot_dir 粘滞判定：读侧纯只读，宿主可能
 * 新旧泳道同仓并存，枚举比状态复判稳且可测。
 *
 * 顺序=新名在前（命中即用），旧名只读回落；env 语义=C1 独占替换：SANDBAR_EVIDENCE_DIR
 * 在场时归档候选=仅 env 一处（env 指临时目录供自测，miss 回落默认目录会击穿自测隔离
 * 读到真仓证据）；泳道/老泳道候选不受 env 影响。
 *
 * 返回 [候选目录, containment 根] 对：旧取图端点的 `resolve(abs,'..','..')` 两级上跳
 * 对更深候选恒真（装饰性断言），改每候选显式 root startsWith 真加固。
 */
export interface EvidenceCandidate { dir: string; containRoot: string }
export function evidenceCandidateDirs(root: string, envBase: string | null, id: string): EvidenceCandidate[] {
  const out: EvidenceCandidate[] = []
  if (envBase) {
    // env 独占替换（自测隔离口径）：归档仅此一处，不与默认目录并读。
    out.push({ dir: resolve(envBase, id), containRoot: resolve(envBase) })
  } else {
    for (const dot of ['.sandbar', '.suyou']) {  // naming-compat: .suyou=旧名只读回落
      out.push({ dir: resolve(root, dot, 'evidence', id), containRoot: resolve(root, dot) })
    }
  }
  for (const laneRoot of ['.lane', '.worktrees']) {   // naming-compat: .worktrees=老泳道根回落
    for (const dot of ['.sandbar', '.suyou']) {       // naming-compat: .suyou=旧名只读回落
      out.push({ dir: resolve(root, laneRoot, id, dot, 'screenshots'), containRoot: resolve(root, laneRoot, id) })
    }
  }
  return out
}

/**
 * 工单截图证据文件列表（t260831-08 建；t260910-05 候选面切新名+回落，收口见
 * evidenceCandidateDirs）：GET /wf/tickets/<id>/evidence 的数据源。取舍结论（票
 * t260831-08，#1b/#1c/#1d）：目录级 containment（resolve 后 startsWith 各自数据根——
 * 词法纵深防御，配合 TICKET_ID_RE 不含 / 和 . 双保险）；枚举结果逐名过 isEvidenceFileName
 * （泳道目录可能被手塞怪名文件，不进列表即不渲染）；目录不存在→该候选空（软降级
 * 不报错，枚举语义没有 404，files=[] 即人话）。同名文件跨候选去重。列表端点行为面
 * 因 .lane 候选扩大=修复本体非回归（t260910-05 C4 注记）：新泳道证据自此可列，
 * 此前只能靠手工复制兜底。
 * symlink 防线不带：截图目录内容来自自家 QA agent 工具产物，非外部输入，与既有取图
 * 端点同洞（不单侧加防线造伪安全）。
 *
 * t260907-11 KI-057 穿参：repo 参数=判界用项目根（默认仓锚传引擎仓、项目锚传项目主
 * 目录，containment 闸随锚走、语义不变）；envBase=SANDBAR_EVIDENCE_DIR 覆盖值——缺省
 * 参数=读 env（旧调用点/默认锚行为不变），项目锚显式传 null（env 属引擎仓域，不透出）。
 */
export async function listEvidenceFiles(
  id: string,
  repo: string,
  envBase: string | null = process.env.SANDBAR_EVIDENCE_DIR ?? null,
): Promise<string[]> {
  if (!TICKET_ID_RE.test(id) || /[./]/.test(id)) return []
  const seen = new Set<string>()
  for (const { dir, containRoot } of evidenceCandidateDirs(repo, envBase, id)) {
    if (!dir.startsWith(containRoot + sep)) continue // containment：越界基目录直接跳过
    let names: string[]
    try {
      names = await readdir(dir)
    } catch {
      continue // 目录不存在（已合并工单/无截图）→ 该候选空
    }
    for (const n of names) {
      if (isEvidenceFileName(n)) seen.add(n)
    }
  }
  return [...seen].sort()
}

/** Temporal 状态探测（t260821-06）：真实探测，不写死结果。 */
const TEMPORAL_HOST = '127.0.0.1'
const TEMPORAL_PORT = 7233
const PORT_PROBE_TIMEOUT_MS = 800

/** TCP 探测端口：有监听者即「server 在线」。 */
function probePort(host: string, port: number, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const sock = net.connect({ host, port })
    let settled = false
    const done = (ok: boolean) => {
      if (settled) return
      settled = true
      sock.destroy()
      resolve(ok)
    }
    sock.setTimeout(timeoutMs)
    sock.once('connect', () => done(true))
    sock.once('error', () => done(false))
    sock.once('timeout', () => done(false))
  })
}

/** 进程存活探测（kill -0）。ESRCH=没了；EPERM=还在只是没权限。 */
function isPidAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (err: any) {
    return err?.code === 'EPERM'
  }
}

/** 读 pidfile（worker.py --daemon 自写），拿不到/脏值返回 null。 */
async function readPid(pidfile: string): Promise<number | null> {
  try {
    const n = Number.parseInt((await readFile(pidfile, 'utf8')).trim(), 10)
    return Number.isInteger(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

/** 读 POST JSON body（64KB 封顶），非法 JSON 抛错。 */
async function readJsonBody(req: IncomingMessage): Promise<any> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    size += (chunk as Buffer).length
    if (size > 64 * 1024) throw new Error('body 超过 64KB')
    chunks.push(chunk as Buffer)
  }
  const text = Buffer.concat(chunks).toString('utf8')
  return text === '' ? {} : JSON.parse(text)
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  res.end(JSON.stringify(body))
}

export function apply(ctx: Context, config?: SuyouWorkbenchConfig): void {
  // repo 语义（KI-057 改判后）：默认仓/回落值——boot 指纹、docs 视图、项目注册表、
  // runProjectCli、runPocCli 等引擎语义面仍锚它；项目工单路由逐请求经 anchorOf 解析
  // 项目主目录，不再直接消费本值。
  const repo = config?.repo ?? process.env.SANDBAR_REPO ?? DEFAULT_REPO
  const logger: { warn?: (...a: unknown[]) => void } | undefined = (ctx as any)?.logger
  // host 陈旧看守（t260902-03）：boot 指纹只在首次 apply 固化（见模块级注释的不变量）。
  void resolveBootFingerprint(repo)
  const cli = { repo, python: config?.python, timeoutMs: config?.timeoutMs }

  /** 逐请求项目锚解析（t260907-11 KI-057）：?project= 缺省回落默认仓；未知 key 400/
   *  隔离与装载异常 502、解析来源与回落原因落 host log（取舍口径见 project-anchor.ts）。 */
  function anchorOf(url: URL): ProjectAnchor {
    const a = resolveProjectAnchor(url.searchParams.get('project'), repo)
    if (!a.ok) logger?.warn?.(`[project-anchor] ?project= 解析失败（${a.status}）：${a.error}`)
    return a
  }
  /** 锚守卫：失败按状态码回 JSON 并返 null，调用方 `const a = ...; if (a === null) return`。 */
  function anchorGuard(res: ServerResponse, a: ProjectAnchor): Extract<ProjectAnchor, { ok: true }> | null {
    if (a.ok) return a
    sendJson(res, a.status, { ok: false, error: a.error })
    return null
  }
  type OkAnchor = Extract<ProjectAnchor, { ok: true }>

  // t260829-07 epic-next 泄漏修复：宿主侧 janitor 定时扫 JOBS 补 poll（前端停 poll
  // 后 running job 的 agent 进程不再无人回收）。unref，不拖宿主退出。
  startEpicNextJanitor()

  /** 调 admin.py call <tool> <args>，成功/结构化失败都原样透传（含 run_id）。 */
  async function callTool(tool: string, args: unknown): Promise<any> {
    return runAdminCli(cli, ['call', tool, JSON.stringify(args ?? {})])
  }

  // ---- enrichment 预算纪律（t260904-17，方案 R5 三钉）----
  // 每票 show 的短超时：show 是单点查询，超时即视同失败降级——不继承 runPocCli
  // 默认 120s 级超时（一次慢 show 拖死整个列表=KI-003/029 查询饿死族加重面）。
  // 注意：超时只放弃等待，底层 spawn 由 execFile 自身 timeout 兜底回收（有界）。
  const SHOW_TIMEOUT_MS = 3_000
  /** enrichment 并发上限：分批跑，不打满 CLI/Temporal 查询面。 */
  const ENRICH_CONCURRENCY = 4

  /** 单票 show + 短超时：成功/结构化失败/超时都 resolve（失败返回 undefined，不 throw）。 */
  function showWithTimeout(id: string): Promise<any> {
    return new Promise((resolveP) => {
      let settled = false
      const finish = (v: any) => { if (!settled) { settled = true; clearTimeout(timer); resolveP(v) } }
      const timer = setTimeout(() => finish(undefined), SHOW_TIMEOUT_MS)
      callTool('ticket', { op: 'show', id }).then((r) => finish(r)).catch(() => finish(undefined))
    })
  }

  /** 有界并发 + allSettled 语义的 map：单项失败/超时不影响其它项与整体 resolve。 */
  async function mapSettled<T>(items: T[], limit: number, fn: (x: T) => Promise<unknown>): Promise<unknown[]> {
    const results: unknown[] = new Array(items.length)
    let next = 0
    async function worker(): Promise<void> {
      while (true) {
        const i = next++
        if (i >= items.length) return
        try { results[i] = await fn(items[i]) } catch { results[i] = undefined }
      }
    }
    await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, worker))
    return results
  }

  /** t260904-17 进展行 enrichment：GET <tickets>?project=<key>&enrich=progress[&ids=a,b]——
   *  逐票 show 取 timeline 末条合法条目挂该行 progress={stage,state,at}（人话派生在
   *  客户端纯函数层，host 不译不猜）。单票慢/失败=该票缺 progress（行卡降级），整体
   *  照常返回；畸形 timeline（末条缺 stage/state）向前找最近合法条，全畸形=不挂。 */
  async function enrichTicketProgress(tickets: any[], idsParam: string | null): Promise<void> {
    const ids = idsParam !== null
      ? idsParam.split(',').map(s => s.trim()).filter(Boolean).slice(0, 32)
      : null
    const idSet = ids !== null ? new Set(ids) : null
    // 无 ids=全量 enrich 兜底：同样封顶 32（O1：极端规模长尾不失控，超限票走降级）
    const targets = tickets.filter((tk: any) =>
      tk?.status !== 'closed' && (idSet === null || idSet.has(tk.id))).slice(0, 32)
    const shows = await mapSettled(targets, ENRICH_CONCURRENCY, (tk: any) => showWithTimeout(tk.id))
    shows.forEach((s, i) => {
      const r = (s as any)?.result ?? null
      // 首句派生（t260905-07，t260903-10 裸编号现场）：口径收口在 deriveTitleOrFirst
      // （src/host/enrich.ts，单测直跑）——title 非空跳过裁剪、show 失败/无 body
      // 字段缺省（行卡回退裸编号，降级自然）。
      if (targets[i] !== undefined && targets[i] !== null) {
        const first = deriveTitleOrFirst(targets[i], r)
        if (first !== undefined) targets[i].title_or_first = first
      }
      const tl = r?.timeline
      if (!Array.isArray(tl)) return
      // 末条合法条目：stage/state 都是非空字符串才算（畸形条目跳过——不挂脏 progress）
      for (let j = tl.length - 1; j >= 0; j--) {
        const e = tl[j]
        if (e !== null && typeof e === 'object'
          && typeof e.stage === 'string' && e.stage !== ''
          && typeof e.state === 'string' && e.state !== '') {
          targets[i].progress = { stage: e.stage, state: e.state, at: e.at }
          break
        }
      }
    })
  }

  /** ticket show 失败的统一分流（KI-025，t260903-06）：判据=body 的 kind 机器字段
   *  （client.py 五出口分级产出 → ticket.py QueryError → tools_registry 并入），
   *  HTTP 裁定收口在 src/host/ticket-error.ts（单测直跑）。kind 缺失/未知一律 500
   *  非 404——「工单不存在」只能由明确 NotFound 语义触发，谎报是本票消灭对象。 */
  function sendTicketShowError(res: ServerResponse, s: unknown, id = ''): void {
    const body = s as { error?: unknown; kind?: unknown } | null
    const kind = typeof body?.kind === 'string' ? body.kind : ''
    const msg = String(body?.error ?? (id ? `工单读取失败：${id}` : '工单读取失败'))
    const v = ticketShowHttpVerdict(kind)
    sendJson(res, v.status, {
      ok: false,
      error: msg,
      kind: kind || 'internal',
      ...(v.retryable ? { retryable: true } : {}),
    })
  }

  /**
   * 调 engine client.py（Temporal TicketWorkflow：sign 审批签字走这里）。
   * KI-057（t260907-11）经评审裁定**保留引擎仓锚、不随项目走**：调用点仅 sign/retry-qc
   * 两个引擎语义操作（审批人工门 / blocked 重跑 signal），client.py 是引擎代码、
   * Temporal 是引擎命名空间，dengzhufpv 的票同样跑在 sandbar 引擎的 Temporal 上；
   * 按项目解析会把今天能用的跨项目签署打断成 502（外部项目无引擎 clone）。若宿主
   * 真实意图是「外部项目各带引擎克隆、独立 Temporal」，那是整套引擎拓扑（worker/
   * namespace/端口）专门票，不随本票做。cwd 同保留引擎仓：两操作只带 id，无文件相对行为。
   *
   * opts（t260910-04）：timeout/maxBuffer 可注入，缺省维持现值（120s / execFile 默认
   * 1MB）——sign/retry-qc 是单票小回执，缺省够用，调用点零变化。ticket-list 这类
   * 批量响应的调用方必须显式传大 maxBuffer（对齐 runAdminCli 的 16MB）与宽 timeout
   * （RUNNING 票逐票 snapshot 查询+3 次重试），见 handleTickets。
   */
  async function runPocCli(
    _cli: { repo: string },
    args: string[],
    opts: { timeoutMs?: number; maxBufferBytes?: number } = {},
  ): Promise<any> {
    const poc = join(repo, 'server', 'engine')
    // 引擎 python 解析回落链（对齐 server/tools/ticket.py _engine_py 同口径）：
    // venv 在场且可执行则用，否则回落 python3——泳道 worktree/测试台容器常无
    // venv（未入库），硬编码 venv 会让列表 502 ENOENT（t260910-04 场景实测）。
    const venvPy = join(poc, '.venv', 'bin', 'python')
    const python = existsSync(venvPy) ? venvPy : 'python3'
    const { stdout } = await execFileP(python, [join(poc, 'client.py'), ...args], {
      cwd: repo,
      timeout: opts.timeoutMs ?? 120_000,
      ...(opts.maxBufferBytes !== undefined ? { maxBuffer: opts.maxBufferBytes } : {}),
    })
    return JSON.parse(stdout)
  }

  /** 台面：ticket list + workflow list 并行（F1 更正：主列表不再逐票 show 取 pending——
   *  审批理由详情抽屉自可见，行卡不放审批理由=mock 口径）。
   *  多项目化（260823）：?project=<key> 必传（projects.yaml 注册表，无默认值）——
   *  工单按 ProjectKey search attribute 过滤（Temporal 侧）；workflow 模板表是全局的，不过滤。 */
  /** 新建工单（epic-linkage Tier 3，t260826-02）：立项单详情页「新建工单」入口的落点——
   *  代号由界面传值（UI 无手输框），本层只透传不重复校验：epic 强校验单点在
   *  client.py validate_epic_code（notes/epics/<代号>.md 存在性），拒收错误经 admin.py
   *  ok:false 原样透传给 UI。审计=admin.py run-id 机制（与面板其他写操作同口径）。
   *  注意：本改动属 host 半，需重启 dsh 才生效。 */
  async function handleTicketCreate(req: IncomingMessage, res: ServerResponse, projectKey: string): Promise<void> {
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const workflow = String(body?.workflow ?? '')
    const title = String(body?.title ?? '').trim()
    if (!workflow) {
      sendJson(res, 400, { ok: false, error: 'create 需要 workflow（模板 id）' })
      return
    }
    if (!title) {
      sendJson(res, 400, { ok: false, error: 'create 需要 title（工单标题）' })
      return
    }
    const epic = String(body?.epic ?? '')
    try {
      const args: Record<string, unknown> = {
        op: 'create',
        project: projectKey,
        workflow,
        title,
        body: String(body?.body ?? ''),
        epic,
      }
      // t260829-07 写集生命周期：弹层写集编辑栏随票透传（数组逐项 String；空数组
      // 不带——「无文件改动」票走客户端显式 allow_empty_write_set，host 不代办）。
      if (Array.isArray(body?.write_set) && body.write_set.length > 0) {
        args.write_set = body.write_set.map((w: unknown) => String(w))
      }
      // t260901-01「无文件改动」显式声明透传：仅客户端显式 true 才带（host 不代办、
      // 不默认）。引擎口（client.py ticket-start）空写集+声明才放行，meta 记 no_file_changes。
      if (body?.allow_empty_write_set === true) {
        args.allow_empty_write_set = true
      }
      const r = await callTool('ticket', args)
      // t260829-06 追加：建票成功即失效该立项的「下一步已备」预跑缓存——新票一出现，
      // 缓存里的建议就是过期的（state_key 失配），挂着只会让列表徽标说谎。
      // best-effort：删失败不影响建票结果。
      if (r?.ok === true && epic) {
        try {
          // KI-057：缓存目录随票所属项目根走（跨项目撞码不互串；key 已过白名单，
          // 解析异常兜底回落默认仓——缓存失效是 best-effort，不该阻断建票响应）。
          const pa = resolveProjectAnchor(projectKey, repo)
          const root = pa.ok ? pa.root : repo
          await dismissPrecache(resolvePrecacheDir(root), epic)
        } catch { /* 缓存删除失败不阻塞建票 */ }
      }
      sendJson(res, 200, r)
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  async function handleTickets(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    const projectKey = String(url.searchParams.get('project') ?? '')
    if (!projectKey) {
      sendJson(res, 400, { ok: false, error: '缺 project 参数（projects.yaml 注册表 key，无默认值）' })
      return
    }
    try {
      // 白名单校验（注册表损坏抛错在这把住）；未知 key/形状非法 findProject 回 undefined 不抛——
      // 必须显式判空，否则白名单形同虚设（t260826-02 顺手修复：原代码只 try/catch 不判空）。
      if (!findProject(projectKey)) {
        sendJson(res, 400, { ok: false, error: `未知项目 key：'${projectKey}'（projects.yaml 注册表无此项）` })
        return
      }
    } catch (err) {
      sendJson(res, 400, { ok: false, error: String(err instanceof Error ? err.message : err) })
      return
    }
    // method 分支（t260826-02）：GET=list（下）、POST=create（上）、其余 405。
    if (req.method === 'POST') {
      await handleTicketCreate(req, res, projectKey)
      return
    }
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '工单列表只支持 GET（列表）/ POST（新建）' })
      return
    }
    try {
      // t260910-04：列表主数据直走引擎 ticket-list（runPocCli）——引擎行原生带
      // paused/paused_phase（t260908-01 段间暂停二态，UI ⏸ 徽标/操作位数据源），
      // 原 ticket.py op=list 投影把这两键丢了（薄壳改不动属 server/tools/ 写集外，
      // 见该通道模型/CLI 消费者的后续专门票）。
      // 参数取舍（runPocCli 先例=sign/retry-qc 单票小回执，缺省 120s/1MB 不够）：
      // ticket-list 是批量响应（全项目行、closed 也在列）→ maxBuffer 16MB（对齐
      // runAdminCli）；RUNNING 票逐票 snapshot 查询+3 次重试 → timeout 300s。
      // 行形状差异表（引擎行 vs 原 ticket.py 出行）：引擎行是**超集**——多
      // paused/paused_phase/exec_status 三键，其余键（workflow/updated/updated_ts/
      // stage_state 缺省 awaiting/handoff·pending 计数/close_ts…）同形，无缺键；
      // close_ts ?? 0 仅为防御性归一（键恒在场）。
      const [t, w] = await Promise.all([
        runPocCli(cli, ['ticket-list', JSON.stringify({ project: projectKey })],
          { timeoutMs: 300_000, maxBufferBytes: 16 * 1024 * 1024 }),
        callTool('workflow', { op: 'list' }),
      ])
      // t260910-04 顺手修（R3）：引擎回执 ok:false 原先被 `?? []` 吃成 200 空列表
      // （引擎挂=台面静默变空）。报错必须精确：显式 502 原文透传。注意 client.py
      // main 全路径 exit 0（含 infra 失败），execFile 不会因此 reject——ok 检查
      // 必须做在回执结构上，靠 throw/catch 兜不住。workflow list 同族补查。
      if (t?.ok === false) {
        sendJson(res, 502, { ok: false, error: `ticket-list 失败: ${t.error ?? JSON.stringify(t)}` })
        return
      }
      if (w?.ok === false) {
        sendJson(res, 502, { ok: false, error: `workflow-list 失败: ${w.error ?? JSON.stringify(w)}` })
        return
      }
      // 行形状归一：close_ts 防御性补 0（键本恒在场，`?? 0` 只兜畸形引擎回执，
      // 不改语义）；其余键逐键透传不清洗（paused/paused_phase 等以引擎为真源）。
      const tickets = (t?.result?.tickets ?? []).map((r: any) => ({ ...r, close_ts: r.close_ts ?? 0 }))
      // workflow list 返回 {workflows:[...]}（M1 引擎结构），兼容裸数组。
      const workflows = w?.result?.workflows ?? (Array.isArray(w?.result) ? w.result : [])
      // t260904-17「主数据先行」（R5/场景 T2）：主响应窗口内零 show——逐票 show 只
      // 发生在显式 enrich=progress 阶段（旧实现 awaiting-human 逐票 show 阻塞
      // sendJson，是 KI-003/029 查询饿死族加重面）。enrich 只挂 progress，不产 pending。
      const url2 = new URL(req.url ?? '/', 'http://x')
      if (url2.searchParams.get('enrich') === 'progress') {
        await enrichTicketProgress(tickets, url2.searchParams.get('ids'))
      }
      // 补充运行中工单的 agent 进度（轻量 stat，不解压）
      const running = tickets.filter((tk: any) => tk.stage_state === 'running' && tk.worktree)
      await Promise.all(running.map(async (tk: any) => {
        try {
          const sessDir = join(repo, tk.worktree, '.dsh', 'sessions')
          const info = await _sessionKbFast(sessDir)
          if (info.kb > 0) {
            tk.session_kb = info.kb
            tk.agent_alive = info.alive
          }
        } catch { /* 静默 */ }
      }))
      sendJson(res, 200, { ok: true, result: { count: tickets.length, tickets }, workflows })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 内容预览（审批前过目）：只读 app/public/data/<path>，path 白名单 books/ 前缀 + 防穿路径。 */
  async function handleBook(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    const p = url.searchParams.get('path') ?? ''
    if (!/^books\/(?:[A-Za-z0-9_\-\u4e00-\u9fff]+\/)?[A-Za-z0-9_\-\u4e00-\u9fff]+\.json$/.test(p)) {
      sendJson(res, 404, { ok: false, error: 'path 不合法（books/<文件>.json 或 books/<册>/<文件>.json）' })
      return
    }
    const root = resolve(repo, 'app', 'public', 'data')
    const abs = resolve(root, p)
    if (abs !== root && !abs.startsWith(root + sep)) {
      sendJson(res, 404, { ok: false, error: 'path 越界（穿路径拒绝）' })
      return
    }
    const limit = Math.max(1, Math.min(20, Number(url.searchParams.get('limit')) || 5))
    try {
      const text = await readFile(abs, 'utf8')
      const data = JSON.parse(text)
      const chapters = (Array.isArray(data.章节) ? data.章节 : []).slice(0, limit).map((c: any) => ({
        id: String(c?.id ?? ''),
        标题: String(c?.标题 ?? ''),
        paras: Array.isArray(c?.正文) ? (c.正文 as unknown[]).map(String) : [],
      }))
      sendJson(res, 200, {
        ok: true,
        result: {
          preview: true,
          meta: {
            主题: String(data.主题 ?? ''),
            类型: String(data.类型 ?? ''),
            期次: String(data.期次 ?? ''),
            total_chapters: (Array.isArray(data.章节) ? data.章节 : []).length,
            size_kb: Math.round(text.length / 1024),
          },
          chapters,
        },
      })
    } catch (err: any) {
      if (err?.code === 'ENOENT') {
        sendJson(res, 404, { ok: false, error: `书文件不存在: ${p}` })
        return
      }
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  /** 「文档」视图（t260905-06；KI-070 修复=t260910-10）：docs/ 定稿库 + notes/ 观察窗，
   *  scope 必传二选一。树按 ?project= 项目根解析（项目锚显式传 root，缺省/未锚回落
   *  引擎仓——取舍清单见方案 gen1 R1：未注册 400/隔离·装载 502/primaryDir 空 502 不回落
   *  全随 anchorOf+anchorGuard 带过来）；装载器 listDocs 语义不变，只换 root 来源。
   *  只读，无写路径。 */
  async function handleDocsTree(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    const scope = url.searchParams.get('scope')
    if (!isDocsScope(scope)) {
      sendJson(res, 400, { ok: false, error: `scope 必传且只能是 docs|notes（收到: ${String(scope)}）` })
      return
    }
    const anchor = anchorGuard(res, anchorOf(url))
    if (anchor === null) return
    try {
      sendJson(res, 200, {
        ok: true,
        result: await listDocs(join(anchor.root, scope), scope),
        resolved: resolvedMark(anchor),
      })
    } catch (err: any) {
      sendJson(res, 500, { ok: false, error: `docs 目录枚举失败: ${String(err?.message ?? err)}` })
    }
  }

  /** 「文档」视图按篇正文（t260905-06；KI-070 修复=t260910-10）：scope+path 必传；
   *  篇按 ?project= 项目根解析（同 handleDocsTree 锚口径，缺省回落引擎仓）。
   *  path 白名单/穿路径/大小上限每步失败的 reason 点名该检查（精确报错纪律，
   *  R1 取舍清单 2）。 */
  async function handleDocsDoc(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    const scope = url.searchParams.get('scope')
    const rel = url.searchParams.get('path') ?? ''
    if (!isDocsScope(scope)) {
      sendJson(res, 400, { ok: false, error: `scope 必传且只能是 docs|notes（收到: ${String(scope)}）` })
      return
    }
    if (rel === '') {
      sendJson(res, 400, { ok: false, error: 'path 必传（scope 下相对路径，.md 结尾）' })
      return
    }
    const anchor = anchorGuard(res, anchorOf(url))
    if (anchor === null) return
    try {
      const r = await readDoc(join(anchor.root, scope), rel)
      // 降级走 200 + {empty,reason}（人话可见，同 book/scan-report 风格——路径问题不是服务器错）
      sendJson(res, 200, { ok: true, result: r, resolved: resolvedMark(anchor) })
    } catch (err: any) {
      sendJson(res, 500, { ok: false, error: `docs 篇章读取失败: ${String(err?.message ?? err)}` })
    }
  }

  /** 模板列表（泳道图/筛选用，台面接口已附带，独立路由供单独刷新）。 */
  async function handleWorkflows(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const w = await callTool('workflow', { op: 'list' })
      const workflows = w?.result?.workflows ?? (Array.isArray(w?.result) ? w.result : [])
      sendJson(res, 200, { ok: true, result: workflows })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** Temporal 健康（只读）：server=7233 端口监听，worker=pidfile pid 存活，真实探测。
   *  worker pidfile 缺省 <repo>/server/engine/data/worker.pid（worker.py --daemon 自写，
   *  与 sandbar-temporal-tools supervisor 的 pidfile 同一真相源）。 */
  async function handleTemporalHealth(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    const workerPidfile = join(repo, 'server', 'engine', 'data', 'worker.pid')
    const serverOnline = await probePort(TEMPORAL_HOST, TEMPORAL_PORT, PORT_PROBE_TIMEOUT_MS)
    const pid = await readPid(workerPidfile)
    const workerOnline = pid !== null && isPidAlive(pid)
    sendJson(res, 200, {
      ok: true,
      result: {
        ts: Math.floor(Date.now() / 1000),
        server: {
          online: serverOnline,
          host: TEMPORAL_HOST,
          port: TEMPORAL_PORT,
          detail: serverOnline
            ? `${TEMPORAL_HOST}:${TEMPORAL_PORT} 端口监听中`
            : `${TEMPORAL_HOST}:${TEMPORAL_PORT} 未监听（server 离线）`,
        },
        worker: {
          online: workerOnline,
          pid,
          pidfile: workerPidfile,
          detail: workerOnline
            ? `pid ${pid} 存活（${workerPidfile}）`
            : (pid !== null
              ? `pid ${pid} 已退出（pidfile ${workerPidfile}）`
              : `无 pidfile（${workerPidfile}）`),
        },
        restart_hint: {
          server: 'cd server/engine && ./run_server.sh（或重启控制台，supervisor 会自动拉起）',
          worker: 'cd server/engine && .venv/bin/python worker.py --daemon（或重启控制台，supervisor 会自动拉起）',
        },
      },
    })
  }

  /** Worker 清单（260824 每工单专属 worker）：扫 data/worker*.pid 逐个探测存活。
   *  worker.pid=共享队列 suyou-poc；worker-<工单id>.pid=专属队列 suyou-ticket-<id>。
   *  工单台状态条「N workers」点开即是本接口的清单。 */
  async function handleWorkers(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    const dataDir = join(repo, 'server', 'engine', 'data')
    const workers: unknown[] = []
    try {
      const files = await readdir(dataDir)
      for (const f of files.sort()) {
        const m = /^worker(?:-(.+))?\.pid$/.exec(f)
        if (!m) continue
        const tid = m[1] ?? ''
        const pid = await readPid(join(dataDir, f))
        const online = pid !== null && isPidAlive(pid)
        let logMtime: number | null = null
        try {
          logMtime = Math.floor((await stat(join(dataDir, `worker${tid ? `-${tid}` : ''}.log`))).mtimeMs / 1000)
        } catch { /* 无日志文件（前台 worker 直打 stdout） */ }
        workers.push({
          ticket: tid || null,
          queue: tid ? `suyou-ticket-${tid}` : 'suyou-poc',
          pid,
          online,
          log_mtime: logMtime,
        })
      }
    } catch { /* data 目录不存在 → 空清单 */ }
    sendJson(res, 200, {
      ok: true,
      result: {
        count: workers.length,
        count_alive: (workers as { online: boolean }[]).filter(w => w.online).length,
        workers,
      },
    })
  }

  /* ------------------------------------------------ M9 PR 式审批台：diff + review */

  /**
   * 变更集（只读）：worktree/base_ref/write_set 读工单 JSON 字段，计算在 src/host/changes.ts。
   * KI-057（t260907-11）：判界仓根按锚走——?project= 显式 > 票面 t.project（权威，:1527
   * 先例）> 缺省回落默认仓；防穿越闸在 changes.ts 内按传入根判界（语义不变）。
   * 响应带 resolved 来源标记（报错精确：键解析失败 400/502 点名项目键，不冒充穿越）。
   */
  async function handleTicketDiff(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendTicketShowError(res, s, id)
        return
      }
      const t = s.result as TicketForDiff
      const url = new URL(req.url ?? '/', 'http://x')
      const queryKey = url.searchParams.get('project')
      // 键序：query 显式 > 票面 t.project（字符串才认，畸形类型视同缺省）> 默认仓。
      const a = resolveProjectAnchor(
        queryKey !== null && queryKey !== '' ? queryKey : (typeof t.project === 'string' ? t.project : ''),
        repo)
      const anchor = anchorGuard(res, a)
      if (anchor === null) return
      const result = await computeTicketDiff(anchor.root, {
        id, worktree: t.worktree, base_ref: t.base_ref, write_set: t.write_set, project: t.project,
        // t260911-01 2a：多仓逐仓明细随 meta 全量透传（client.py ticket show 链路已核）；
        // 畸形形状由 changes.ts sanitizeRepoWorktrees 消毒（视同缺省走单仓，不 500）。
        repo_worktrees: t.repo_worktrees,
      })
      sendJson(res, 200, { ok: true, result, resolved: resolvedMark(anchor) })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * 读审批意见：reviews/<工单id>.json（复用 knowledge review-store 的读改写与文件形制）。
   * KI-057：落盘锚 reviewsAnchor=<项目根>/server 直下 reviews/ 按 ?project= 解析（缺省=默认仓，行为不变）。
   */
  async function handleTicketReviewGet(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    const anchor = anchorGuard(res, anchorOf(new URL(req.url ?? '/', 'http://x')))
    if (anchor === null) return
    try {
      const reviewsAnchor = join(anchor.root, 'server', 'dsh')
      sendJson(res, 200, { ok: true, result: await loadReview(reviewsAnchor, id), resolved: resolvedMark(anchor) })
    } catch (err: any) {
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  /** 追加一轮审批意见（制式照 knowledge /review/save：白名单防穿+admin.log 同形审计+run-id）。 */
  async function handleTicketReviewSave(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    const runId = randomUUID().replace(/-/g, '').slice(0, 12)
    if (!TICKET_ID_RE.test(id)) {
      await audit(runId, 'review.save', { ticket: id }, false, '工单 id 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: '工单 id 不合法' })
      return
    }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      await audit(runId, 'review.save', { ticket: id }, false, '请求体非法 JSON')
      sendJson(res, 400, { ok: false, run_id: runId, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const base = typeof body?.base === 'string' ? body.base : ''
    if (!/^[A-Za-z0-9._~^/-]*$/.test(base)) {
      await audit(runId, 'review.save', { ticket: id }, false, 'base 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: 'base 不合法' })
      return
    }
    const conclude = body?.conclude as ReviewConclude
    if (!CONCLUDES.includes(conclude)) {
      await audit(runId, 'review.save', { ticket: id }, false, 'conclude 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: `conclude 必须是 ${CONCLUDES.join(' | ')}` })
      return
    }
    if (!Array.isArray(body?.blocks)) {
      await audit(runId, 'review.save', { ticket: id }, false, 'blocks 缺/非数组')
      sendJson(res, 400, { ok: false, run_id: runId, error: 'blocks 必须是数组' })
      return
    }
    const blocks: ReviewBlockEntry[] = []
    for (const b of body.blocks as any[]) {
      if (typeof b?.block_key !== 'string' || b.block_key === '') {
        await audit(runId, 'review.save', { ticket: id }, false, 'block 缺 block_key')
        sendJson(res, 400, { ok: false, run_id: runId, error: '每个 block 必须带 block_key' })
        return
      }
      const decision = b.decision === 'approve' || b.decision === 'reject' ? b.decision : undefined
      blocks.push({
        block_key: b.block_key.slice(0, 300),
        summary: typeof b.summary === 'string' ? b.summary.slice(0, 120) : '',
        type: typeof b.type === 'string' ? b.type : '',
        status: typeof b.status === 'string' ? b.status : '',
        decision,
        comment: typeof b.comment === 'string' && b.comment !== '' ? b.comment.slice(0, 2000) : undefined,
      })
    }
    const reviewer = typeof body?.reviewer === 'string' && body.reviewer.trim() !== ''
      ? body.reviewer.trim().slice(0, 40) : 'user'
    const round: ReviewRound = { base, ts: Math.floor(Date.now() / 1000), reviewer, conclude, blocks }
    // KI-057：落盘锚按 ?project= 解析（校验失败=run-id 审计留痕后显式报错，不静默回落）。
    const anchor = anchorGuard(res, anchorOf(new URL(req.url ?? '/', 'http://x')))
    if (anchor === null) {
      await audit(runId, 'review.save', { ticket: id }, false, '项目锚解析失败')
      return
    }
    try {
      const saved = await appendReviewRound(join(anchor.root, 'server', 'dsh'), id, round)
      const summary = `${id} 第 ${saved.rounds.length} 轮 conclude=${conclude} 块 ${blocks.length}`
      await audit(runId, 'review.save', { ticket: id, base, conclude, blocks: blocks.length }, true, summary)
      ctx.logger.info('sandbar-workbench: review.save %s（run-id %s）', summary, runId)
      sendJson(res, 200, { ok: true, run_id: runId, result: { ticket: id, rounds: saved.rounds.length, round } })
    } catch (err: any) {
      await audit(runId, 'review.save', { ticket: id }, false, String(err?.message ?? err))
      sendJson(res, 500, { ok: false, run_id: runId, error: String(err?.message ?? err) })
    }
  }

  /**
   * admin.log 同款审计（同 knowledge 插件的取舍：为一条文件写入不 spawn python，
   * 直接按同一 JSONL schema 追加 server/admin.log，审计单一真源保持一致）。
   */
  async function audit(runId: string, name: string, args: unknown, ok: boolean, summary: string): Promise<void> {
    const rec = JSON.stringify({
      run_id: runId, ts: Math.floor(Date.now() / 1000), actor: 'sandbar-workbench',
      name, args, ok, summary: summary.length > 800 ? summary.slice(0, 800) + '…' : summary,
    })
    try {
      await appendFile(join(repo, 'server', 'admin.log'), rec + '\n', 'utf8')
    } catch (err: any) {
      ctx.logger.warn('sandbar-workbench: admin.log 审计写入失败（不影响主流程）：%s', String(err?.message ?? err))
    }
  }

  /**
   * 工单截图证据只读端点（t260829-02 建；t260910-05 候选面切新名+回落）：GET /wf/tickets/<id>/evidence/<file>。
   * 候选序=evidenceCandidateDirs 单一收口：①归档新名 <root>/.sandbar/evidence/<id>（泳道
   * 拆树后 report 引图不死链）→ 旧名 .suyou/evidence 回落（naming-compat）；②泳道
   * <root>/.lane/<id>/.sandbar/screenshots（新）→ .suyou 回落；③老泳道 .worktrees/<id>
   * 两代点目录回落。防穿三层：TICKET_ID_RE 白名单 + 文件名白名单（^[A-Za-z0-9._-]+$ 且
   * .png 结尾）+ 每候选显式 containment 根断言（旧「resolve(abs,'..','..')」两级上跳对
   * 深候选恒真，t260910-05 改真加固）。归档基目录 SANDBAR_EVIDENCE_DIR env 独占替换
   * （python 侧 _archive_shots 同名 env 互指，自测指向临时目录；在场则归档仅 env 一处，
   * 泳道候选不受影响）。
   * KI-057：候选根随 ?project= 项目主目录走（env 仅默认仓锚透出，取舍见 project-anchor.ts）。
   */
  async function handleTicketEvidence(req: IncomingMessage, res: ServerResponse, id: string, file: string): Promise<void> {
    if (!TICKET_ID_RE.test(id) || /[./]/.test(id)) {
      sendJson(res, 400, { ok: false, error: `工单 id 不合法：'${id.slice(0, 40)}'` })
      return
    }
    if (!isEvidenceFileName(file)) {
      sendJson(res, 400, { ok: false, error: `证据文件名不合法：'${file.slice(0, 60)}'（要求 ^[A-Za-z0-9._-]+$ 且 .png 结尾）` })
      return
    }
    const anchor = anchorGuard(res, anchorOf(new URL(req.url ?? '/', 'http://x')))
    if (anchor === null) return
    const root = anchor.root
    // 项目锚显式传 null（env 仅默认仓锚生效，红线口径）；默认锚走 anchorEnv（env 独占）。
    const envBase = anchorEnv(anchor, 'SANDBAR_EVIDENCE_DIR')
    const candidates = evidenceCandidateDirs(root, envBase, id)
    for (const { dir, containRoot } of candidates) {
      const abs = resolve(dir, file)
      if (!abs.startsWith(containRoot + sep)) continue // 落点越界（.. 穿越等），直接跳过
      try {
        const png = await readFile(abs)
        res.writeHead(200, { 'content-type': 'image/png', 'cache-control': 'no-store' })
        res.end(png)
        return
      } catch (err: any) {
        if (err?.code === 'ENOENT') continue // 下一候选
        sendJson(res, 500, { ok: false, error: `证据读取失败：${String(err?.message ?? err)}` })
        return
      }
    }
    sendJson(res, 404, { ok: false, error: `证据不存在：${file}（归档处与新旧泳道 screenshots 均无）` })
  }

  /**
   * 工单截图证据列表端点（t260831-08）：GET /wf/tickets/<id>/evidence（无 file 段）。
   * 数据源=listEvidenceFiles（归档+泳道两候选枚举，防穿/降级口径见其注释）。
   * 空列表=200 files:[]（枚举语义无 404；「证据不存在」的人话由取图端点承担）。
   */
  async function handleTicketEvidenceList(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id) || /[./]/.test(id)) {
      sendJson(res, 400, { ok: false, error: `工单 id 不合法：'${id.slice(0, 40)}'` })
      return
    }
    const anchor = anchorGuard(res, anchorOf(new URL(req.url ?? '/', 'http://x')))
    if (anchor === null) return
    try {
      // 项目锚显式传 envBase=null（env 仅默认仓锚生效，红线口径）；默认锚走缺省读 env。
      const envBase = anchor.source === 'default' ? undefined : null
      sendJson(res, 200, { ok: true, result: { files: await listEvidenceFiles(id, anchor.root, envBase) } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: `证据列表读取失败：${String(err instanceof Error ? err.message : err)}` })
    }
  }

  /** 详情 + 操作：prefix 路由，<id> 或 <id>/<op>。 */
  async function handleTicketRoute(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    let rest: string
    try {
      rest = decodeURIComponent(url.pathname.slice(TICKETS_PREFIX.length)).replace(/^\/+/, '')
    } catch {
      sendJson(res, 400, { ok: false, error: '路径含非法百分号编码' })
      return
    }
    const parts = rest.split('/').filter(Boolean)
    if (parts.length === 1) {
      if (req.method !== 'GET') {
        sendJson(res, 405, { ok: false, error: '详情只支持 GET' })
        return
      }
      try {
        const r = await callTool('ticket', { op: 'show', id: parts[0] })
        if (r?.ok !== true) {
          // KI-025 分级分流：详情不再 200 透传 ok:false——按 kind 定 HTTP
          // （404/410/503+retryable/500），UI 据此「真不存在报错 / 瞬时保留快照静默重试」。
          sendTicketShowError(res, r, parts[0])
          return
        }
        // 补充 agent 进度（轻量 stat）
        const tk = r.result
        if (tk && tk.stage_state === 'running' && tk.worktree) {
          try {
            const info = await _sessionKbFast(join(repo, tk.worktree, '.dsh', 'sessions'))
            if (info.kb > 0) { tk.session_kb = info.kb; tk.agent_alive = info.alive }
          } catch { /* 静默 */ }
        }
        sendJson(res, 200, r)
      } catch (err) {
        sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
      }
      return
    }
    if (parts.length === 3 && parts[1] === 'evidence') {
      if (req.method !== 'GET') {
        sendJson(res, 405, { ok: false, error: 'evidence 只支持 GET（只读图片）' })
        return
      }
      await handleTicketEvidence(req, res, parts[0], parts[2])
      return
    }
    if (parts.length === 2) {
      const [id, op] = parts
      // t260831-08：evidence 列表只读 GET（详情抽屉「截图证据」区数据源；
      // 带文件段的取图在同前缀 3 段路由，见上方 handleTicketEvidence）。
      if (op === 'evidence' && req.method === 'GET') {
        await handleTicketEvidenceList(req, res, id)
        return
      }
      // M9：diff / review 是只读 GET；review 的 POST 是审批意见落盘（不走 admin.py）。
      if (op === 'diff' && req.method === 'GET') {
        await handleTicketDiff(req, res, id)
        return
      }
      // M12：agent-logs 只读 GET（工单 agent 日志，见 handleAgentLogs）。
      if (op === 'agent-logs' && req.method === 'GET') {
        await handleAgentLogs(res, id)
        return
      }
      // t260825-03：agent-live 只读 GET（泳道会话事件流尾部，「实时动态」面板数据源）。
      if (op === 'agent-live' && req.method === 'GET') {
        await handleAgentLive(req, res, id)
        return
      }
      // t260828-07：agent-usage 只读 GET（token 消耗聚合，同一解析通路的第二个端点）。
      if (op === 'agent-usage' && req.method === 'GET') {
        await handleAgentUsage(res, id)
        return
      }
      if (op === 'review') {
        if (req.method === 'GET') {
          await handleTicketReviewGet(req, res, id)
          return
        }
        if (req.method === 'POST') {
          await handleTicketReviewSave(req, res, id)
          return
        }
        sendJson(res, 405, { ok: false, error: 'review 只支持 GET（读）/ POST（落盘一轮）' })
        return
      }
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '操作只支持 POST' })
        return
      }
      if (!OPS.has(op)) {
        sendJson(res, 404, { ok: false, error: `未知操作 ${op}（可用：${[...OPS].join('/')}）` })
        return
      }
      let body: any
      try {
        body = await readJsonBody(req)
      } catch (err) {
        sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
        return
      }
      try {
        // sign = 审批签字（awaiting-human 人工审批段）：走 Temporal TicketWorkflow 的签字
        // （decision=approve 放行推进 / reject 打回），不经 admin.py（引擎对 human 门只认 sign）。
        if (op === 'sign') {
          const decision = body.decision === 'reject' ? 'reject' : 'approve'
          const note = String(body.note ?? '')
          const who = String(body.who ?? 'op-local')
          const pocArgs = {
            op: 'sign',
            ticket_id: id,
            input: { who, gate: '', decision, note },
          }
          const r = await runPocCli(cli, ['ticket', JSON.stringify(pocArgs)])
          sendJson(res, 200, r)
          return
        }
        // M11 v2：retry-qc = blocked 工单请求重跑本段（Temporal retry_qc signal，新旧类同名）。
        if (op === 'retry-qc') {
          const who = String(body.who ?? 'op-local')
          const r = await runPocCli(cli, ['signal', JSON.stringify({
            workflow_id: id, signal: 'retry_qc', input: who,
          })])
          sendJson(res, 200, r)
          return
        }
        // t260908-01：pause/resume = 段间暂停·恢复（Temporal pause/resume signal，
        // 与 sign/retry-qc 同款绕 ticket.py 直调 engine client.py——不造旁路）。
        // 幂等反馈可辨在 workflow 侧（重复 pause/空态 resume/畸形 payload 落 refused，
        // snapshot 可观测）；通道失败（非零退出/120s 超时/非 JSON）由下方 try/catch
        // 转 502 结构化，前端走既有 apiPost 错误通路。
        if (op === 'pause' || op === 'resume') {
          const who = String(body.who ?? 'op-local')
          const note = String(body.note ?? '')
          const r = await runPocCli(cli, ['ticket', JSON.stringify({
            op, ticket_id: id, who, note,
          })])
          sendJson(res, 200, r)
          return
        }
        // 面板通道写操作直接执行（总管操作本身即意图）；审计由 admin.py run-id 机制承担。
        const args: Record<string, unknown> = { op, id }
        if (op === 'accept') {
          for (const k of ['item', 'done', 'by', 'evidence', 'agent']) {
            if (body[k] !== undefined) args[k] = body[k]
          }
        } else if (op === 'advance') {
          if (body.note !== undefined) args.note = body.note
        } else if (op === 'dispatch-next') {
          if (body.mark_running !== undefined) args.mark_running = body.mark_running
        } else if (op === 'rework') {
          if (!body.note) {
            sendJson(res, 400, { ok: false, error: 'rework 需要 note（返工原因）' })
            return
          }
          args.note = body.note
          if (body.to_stage !== undefined) args.to_stage = body.to_stage
        } else if (op === 'update') {
          for (const k of ['status', 'stage_state', 'note', 'pending_add']) {
            if (body[k] !== undefined) args[k] = body[k]
          }
        }
        const r = await callTool('ticket', args)
        sendJson(res, 200, r)
      } catch (err) {
        sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
      }
      return
    }
    sendJson(res, 404, { ok: false, error: '路径不合法：/sandbar-workbench/api/wf/tickets/<id>[/op | /evidence/<file>]' })
  }

  /** 巡检报告（M6，只读）：最新一份 out/scan/<YYYY-MM-DD>.json；无报告走 reason 降级。 */
  async function handleScanReport(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const scanDir = join(repo, 'server', 'engine', 'out', 'scan')
      sendJson(res, 200, { ok: true, result: await readLatestScanReport(scanDir) })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * host 陈旧看守读侧（t260902-03，只读）：GET /sandbar-workbench/api/build-info。
   * 现算磁盘指纹与启动指纹比对，stale=true 即「磁盘 host 半已更新、console 进程
   * 还在跑旧码」，客户端据此渲染全局「重启 console 生效」横幅。指纹全缺（部署
   * 形态异常）→ stale:false + error 人话，客户端见 error 有意降级不显横幅
   * （不属于陈旧提醒范畴，不静默绕过——响应里带 error 字段显性化）。
   */
  async function handleBuildInfo(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'build-info 只支持 GET（只读看守）' })
      return
    }
    try {
      const disk = await computeHostFingerprint(repo)
      if (disk.error !== undefined) {
        sendJson(res, 200, {
          ok: true,
          result: { stale: false, error: disk.error, missing: disk.missing },
        })
        return
      }
      const boot = bootFingerprintP === undefined ? undefined : await bootFingerprintP
      sendJson(res, 200, {
        ok: true,
        result: {
          stale: boot?.hash !== undefined && disk.hash !== boot.hash,
          bootFingerprint: boot?.hash,
          diskFingerprint: disk.hash,
          missing: disk.missing,
        },
      })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * 会话开局 charter 读侧（t260904-07，只读）：GET /sandbar-workbench/api/session-charter?project=<key>。
   * 每次请求现读 <repo>/server/session_charter.md（改文件即生效，只影响
   * 之后新建的会话）。渲染纯函数在 src/host/session-charter.ts（smoke 直测）：
   * 通用模板占位符现填（engine_root=repo，本仓根）+ 命中 ## project:<key>
   * 分段原文追加（段内占位符统一渲染）。项目名/主目录从注册表现查
   * （findProject），查不到/注册表异常 → name=key、dir=''，端点仍 200——
   * 注册表异常不拖垮注入链。文件缺失/读失败/空/渲染结果空 → 回落插件内置
   * 兜底模板（composeSessionCharter 内收口），恒 200 不 5xx：charter 只是
   * 新建会话的开局注入源，端点不该挡会话创建。project query 缺失或空串=
   * 400 形状错误（与路由 404 形状同族，不崩）。
   */
  async function handleSessionCharter(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'session-charter 只支持 GET（只读）' })
      return
    }
    const url = new URL(req.url ?? '/', 'http://x')
    const project = (url.searchParams.get('project') ?? '').trim()
    if (project === '') {
      sendJson(res, 400, { ok: false, error: 'session-charter 缺 project query：' + SESSION_CHARTER_PATH + '?project=<key>' })
      return
    }
    let projectName = project
    let projectDir = ''
    try {
      const p = findProject(project)
      if (p) {
        projectName = p.name
        projectDir = primaryDir(p) || ''
      }
    } catch { /* 注册表异常（如条目隔离）→ 兜底 name=key、dir=''，链路不断 */ }
    let raw = ''
    try {
      raw = await readFile(join(repo, 'server', 'session_charter.md'), 'utf8')
    } catch (err) {
      ctx.logger.warn('sandbar-workbench: session_charter.md 读取失败，回落内置兜底模板：%s', String(err instanceof Error ? err.message : err))
    }
    const charter = composeSessionCharter(raw, project, {
      projectKey: project,
      projectName,
      primaryDir: projectDir,
      engineRoot: repo,
    })
    // kind 字段（t260905-04）：端点响应声明注入物类型=charter（机制在引擎打标
    // 的引擎半；文本首行标记由客户端 injectSessionCharter 拼装，标记常量同源
    // 在 src/host/session-charter.ts CHARTER_MARKER）。
    sendJson(res, 200, { ok: true, project, charter, kind: 'charter', source: raw.trim() !== '' ? 'file' : 'fallback' })
  }

  /**
   * metrics 读侧聚合（t260901-20，只读，M1a）：GET /sandbar-workbench/api/wf/metrics。
   * 聚合唯一实现在 src/host/metrics.ts（与 metrics-cli.mjs CLI 前门同函数同缓存，
   * 契约块 2「同实现同缓存」）；本 handler 只做 query 透传（同名重复参数由
   * parseMetricsQuery 防穿）与 sendJson 回包，4xx {error,reason} / 200 响应形状
   * 单点在 metrics.ts。零逻辑前门——改动聚合口径请改 metrics.ts，勿在此堆逻辑。
   */
  async function handleMetrics(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'metrics 只支持 GET（只读聚合）' })
      return
    }
    const url = new URL(req.url ?? '/', 'http://x')
    try {
      const r = await buildMetricsResponse(url.searchParams, defaultDeps(repo))
      // 回包即契约块 2 冻结响应本体（不再包 {ok,result} 外壳）：CLI 前门 stdout
      // 是同一份 body，双前门字节级一致才成立（M3 基线比较面）。
      sendJson(res, r.status, r.body)
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }


  /* ---------------------------------- 立项单只读 API（epic-linkage Tier 2） */

  /**
   * 立项单列表：列 notes/epics/*.md（目录不存在/无文件 → 空数组不报错）。
   * KI-057：epics 目录与预跑缓存目录随 ?project= 项目根走（env 闸见 project-anchor.ts）。
   */
  async function handleEpics(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '立项单列表只支持 GET' })
      return
    }
    const anchor = anchorGuard(res, anchorOf(new URL(req.url ?? '/', 'http://x')))
    if (anchor === null) return
    try {
      const epics = await listEpics(anchorEpicsDir(anchor))
      // t260829-02：轻量带上「下一步已备」缓存命中标记（只 stat pre.json 存在性，
      // 不逐个算 state_key；准态由详情响应 nextHint 承担），前端列表行直接消费。
      const cacheDir = resolvePrecacheDir(anchor.root)
      const withHint = await Promise.all(epics.map(async (e) => ({
        ...e,
        nextHintCached: await precacheExists(cacheDir, e.code),
      })))
      sendJson(res, 200, { ok: true, result: { count: withHint.length, epics: withHint }, resolved: resolvedMark(anchor) })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 立项单工单聚合（只读）：复用 ticket list --epic 通路（handleTickets 同款 callTool）。
   *  前置与详情路由同口径：形状 400 / 不存在 404（拦住后 ticket.py 侧强校验不会再以
   *  引擎错误冒出）；其后 callTool 抛错或回 ok:false 一律降级 {degraded:true, reason}
   *  （reason 透传底层 error 原文，不吞成空泛「不可用」），不 502。 */
  async function handleEpicTickets(res: ServerResponse, code: string, anchor: OkAnchor): Promise<void> {
    const chk = await readEpicMarkdown(anchorEpicsDir(anchor), code)
    if (!chk.ok) {
      sendJson(res, chk.status, { ok: false, error: chk.error })
      return
    }
    let r: any
    try {
      r = await callTool('ticket', { op: 'list', epic: code })
    } catch (err) {
      const detail = String(err instanceof Error ? err.message : err)
      sendJson(res, 200, { ok: true, result: { code, degraded: true, reason: `工单状态查询降级：admin.py 调用失败——${detail}` } })
      return
    }
    if (r?.ok !== true) {
      const detail = String(r?.error ?? '返回缺 error 字段')
      sendJson(res, 200, { ok: true, result: { code, degraded: true, reason: `工单状态查询降级：ticket list 失败——${detail}` } })
      return
    }
    const rows = ((r.result?.tickets ?? []) as any[]).map((t) => ({
      id: String(t?.id ?? ''),
      title: String(t?.title ?? ''),
      status: String(t?.status ?? ''),
      stage: String(t?.stage ?? ''),
      stage_state: String(t?.stage_state ?? ''),
    }))
    const buckets: Record<string, number> = {}
    for (const row of rows) buckets[row.status || 'unknown'] = (buckets[row.status || 'unknown'] ?? 0) + 1
    sendJson(res, 200, { ok: true, result: { code, count: rows.length, buckets, tickets: rows } })
  }

  /** 「继续执行」建议 job 启动（t260827-02，host 半，需重启 dsh 生效）：
   *  code 校验复用 readEpicMarkdown 口径（形状 400/不存在 404）；同 code 有进行中
   *  job 直接复用（不重复 spawn agent）；模板清单（验证建议合法性的白名单基准）
   *  拿不到 → 502 可重试（不放行无校验的建议）；工单状态汇总失败降级为说明文字
   *  内联进 prompt（不阻塞建议链路）。 */
  async function handleSuggestNextStart(res: ServerResponse, code: string, anchor: OkAnchor): Promise<void> {
    const chk = await readEpicMarkdown(anchorEpicsDir(anchor), code)
    if (!chk.ok) {
      sendJson(res, chk.status, { ok: false, error: chk.error })
      return
    }
    const existing = findRunningJob(code)
    if (existing) {
      sendJson(res, 200, { ok: true, result: { job_id: existing.jobId, state: existing.state, reused: true } })
      return
    }
    let workflows: { id: string; name: string }[]
    try {
      const w = await callTool('workflow', { op: 'list' })
      if (w?.ok !== true) {
        sendJson(res, 502, { ok: false, error: `模板清单查询失败：${String(w?.error ?? '返回缺 error 字段')}（可重试）` })
        return
      }
      workflows = ((w.result?.workflows ?? []) as any[])
        .map((x) => ({ id: String(x?.id ?? ''), name: String(x?.name ?? '') }))
        .filter((x) => x.id !== '')
    } catch (err) {
      sendJson(res, 502, { ok: false, error: `模板清单查询失败：${String(err instanceof Error ? err.message : err)}（可重试）` })
      return
    }
    let ticketsSummary: string
    let ticketRows: { id: string; closed: boolean }[] = []
    try {
      const t = await callTool('ticket', { op: 'list', epic: code })
      if (t?.ok === true) {
        const rows = ((t.result?.tickets ?? []) as any[]).map((x) => ({
          id: String(x?.id ?? ''), title: String(x?.title ?? ''), status: String(x?.status ?? ''),
          stage: String(x?.stage ?? ''), stage_state: String(x?.stage_state ?? ''),
        }))
        ticketRows = rows.map((r) => ({ id: r.id, closed: r.status === 'closed' }))
        ticketsSummary = rows.length === 0 ? '（本立项暂无关联工单）' : JSON.stringify(rows, null, 1)
      } else {
        ticketsSummary = `（工单状态查询失败：${String(t?.error ?? '未知错误')}，请基于立项单全文判断）`
      }
    } catch (err) {
      ticketsSummary = `（工单状态查询失败：${String(err instanceof Error ? err.message : err)}，请基于立项单全文判断）`
    }
    // 预跑缓存命中（t260828-08）→ 秒回，不再 spawn agent 冷启动（1~5 分钟 → 毫秒级）。
    // state_key 口径：点击时本票已 closed（ticketRows 里就是 closed），与 python 预跑侧
    // 「当前票强制 closed」口径对齐（shared.py epic_state_key / stateKeyFromRows 互指）。
    // 坏缓存 readPrecache 一律当未命中 → 落回下方原冷起路径。
    if (ticketRows.length > 0) {
      const cached = await readPrecache(
        resolvePrecacheDir(anchor.root), code,
        stateKeyFromRows(ticketRows, ''), workflows.map((w) => w.id))
      if (cached) {
        sendJson(res, 200, { ok: true, result: { state: 'done', suggestion: cached, cached: true } })
        return
      }
    }
    try {
      const job: EpicNextJob = await startSuggestJob({
        // KI-057：repo=引擎仓锚（roles/model-routes=引擎侧声明，保留）；root=项目根
        // （job 目录/预跑缓存随项目走，epic-next.ts 消费）。
        repo, root: anchor.root, code, epicTitle: chk.title, epicMarkdown: chk.markdown, ticketsSummary, workflows,
      })
      sendJson(res, 200, { ok: true, result: { job_id: job.jobId, state: job.state, reused: false } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: `建议任务启动失败：${String(err instanceof Error ? err.message : err)}` })
    }
  }

  /** 建议 job 轮询：done 带 suggestion / failed 带人话 reason（200 透传，前端黄条降级）。 */
  async function handleSuggestNextPoll(res: ServerResponse, code: string, jobId: string): Promise<void> {
    if (!/^[a-z0-9-]{6,80}$/.test(jobId)) {
      sendJson(res, 400, { ok: false, error: `job id 形状不合法：'${jobId}'` })
      return
    }
    const job = await pollSuggestJob(jobId)
    if (!job || job.code !== code) {
      sendJson(res, 404, { ok: false, error: '无此建议任务（宿主可能已重启，回到立项单重新点击「继续执行」即可）' })
      return
    }
    const result: Record<string, unknown> = { job_id: job.jobId, state: job.state }
    if (job.state === 'done') result.suggestion = job.suggestion
    if (job.state === 'failed') result.reason = job.reason ?? '未知原因'
    sendJson(res, 200, { ok: true, result })
  }

  /** 立项详情的「下一步建议」准态（t260829-02）：工单集合现算 state_key（本票已
   *  closed 口径，currentTicketId 传 '' 与 suggest-next 缓存命中路径同款）+
   *  readPrecacheHint 全量校验。任一查询失败 → null（详情不被建议链路拖垮）。 */
  async function epicNextHintFor(code: string, anchor: OkAnchor): Promise<unknown> {
    try {
      const [w, t] = await Promise.all([
        callTool('workflow', { op: 'list' }),
        callTool('ticket', { op: 'list', epic: code }),
      ])
      if (w?.ok !== true || t?.ok !== true) return null
      const workflowIds = ((w.result?.workflows ?? []) as any[])
        .map((x) => String(x?.id ?? '')).filter((x) => x !== '')
      const rows = ((t.result?.tickets ?? []) as any[]).map((x) => ({
        id: String(x?.id ?? ''), closed: String(x?.status ?? '') === 'closed',
      }))
      return await readPrecacheHint(
        resolvePrecacheDir(anchor.root), code, stateKeyFromRows(rows, ''), workflowIds)
    } catch {
      return null
    }
  }

  /** 立项单详情/工单聚合/继续执行建议：prefix 路由，<code> 或 <code>/tickets
   *  （只读 GET）或 <code>/suggest-next[/<jobId>]（t260827-02：POST 启动 + GET 轮询）。 */
  async function handleEpicRoute(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    let rest: string
    try {
      rest = decodeURIComponent(url.pathname.slice(EPICS_PREFIX.length)).replace(/^\/+/, '')
    } catch {
      sendJson(res, 400, { ok: false, error: '路径含非法百分号编码' })
      return
    }
    const parts = rest.split('/').filter(Boolean)
    // KI-057：项目锚在分支前解析（?project= 缺省回落默认仓；未知/隔离显式 400/502）。
    const anchor = anchorGuard(res, anchorOf(url))
    if (anchor === null) return
    // suggest-next 两支（t260827-02）须在下面的 GET-only 405 之前分支。
    if (parts.length === 2 && parts[1] === 'suggest-next') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: 'suggest-next 启动只支持 POST' })
        return
      }
      await handleSuggestNextStart(res, parts[0], anchor)
      return
    }
    if (parts.length === 3 && parts[1] === 'suggest-next') {
      if (req.method !== 'GET') {
        sendJson(res, 405, { ok: false, error: 'suggest-next 轮询只支持 GET' })
        return
      }
      await handleSuggestNextPoll(res, parts[0], parts[2])
      return
    }
    // 结项动作（t260828-08）：POST /epics/<code>/close——立项目标达成后人审确认，
    // 外科改写 notes/epics/<code>.md 状态表行为「已完结」（写前备份 /tmp）。须在
    // 下面的 GET-only 405 之前分支。
    if (parts.length === 2 && parts[1] === 'close') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '结项动作只支持 POST（人审确认语义）' })
        return
      }
      const r = await closeEpic(anchorEpicsDir(anchor), parts[0])
      if (!r.ok) {
        sendJson(res, r.status, { ok: false, error: r.error })
        return
      }
      sendJson(res, 200, { ok: true, result: { code: r.code, status: r.status } })
      return
    }
    // 状态编辑动作（t260831-05）：POST /epics/<code>/status {status, note?}——枚举白名单
    // 校验 + 外科改写状态行 + 可选更新备注列 + 写前 /tmp 备份（setEpicStatus 与 close
    // 单点共用骨架）。须在下面的 GET-only 405 之前分支。note 语义：缺省/null=不动备注，
    // ''=清空，非空=写入（形状校验在 setEpicStatus/validateEpicNote 单口径）。
    if (parts.length === 2 && parts[1] === 'status') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '状态编辑只支持 POST（写动作语义）' })
        return
      }
      let body: any
      try {
        body = await readJsonBody(req)
      } catch {
        sendJson(res, 400, { ok: false, error: '请求体必须是合法 JSON（readJsonBody 64KB 封顶）' })
        return
      }
      if (body === null || typeof body !== 'object' || typeof body.status !== 'string') {
        sendJson(res, 400, { ok: false, error: '请求体必须是 {"status": "<四值枚举>", "note"?: <单行字符串>}，status 必填字符串' })
        return
      }
      const r = await setEpicStatus(anchorEpicsDir(anchor), parts[0], body.status, body.note)
      if (!r.ok) {
        sendJson(res, r.status, { ok: false, error: r.error })
        return
      }
      sendJson(res, 200, { ok: true, result: { code: r.code, status: r.status, note: r.note } })
      return
    }
    // [忽略] 动作（t260829-02）：POST /epics/<code>/next-hint/dismiss——删预跑缓存
    // pre.json（幂等；删除前备份 /tmp）。与 suggest-next/close/status 同理须在下方
    // GET-only 405 之前分支（t260907-11 顺手修复：分支原被卡在 405 闸之后，POST
    // dismiss 恒 405，前端 [忽略建议] 按钮全灭；tests/epics-api.mjs 已备修复后断言）。
    if (parts.length === 3 && parts[1] === 'next-hint' && parts[2] === 'dismiss') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '忽略建议只支持 POST（写动作语义）' })
        return
      }
      const chk = await readEpicMarkdown(anchorEpicsDir(anchor), parts[0])
      if (!chk.ok) {
        sendJson(res, chk.status, { ok: false, error: chk.error })
        return
      }
      const dr = await dismissPrecache(resolvePrecacheDir(anchor.root), parts[0])
      if (!dr.ok) {
        sendJson(res, dr.status, { ok: false, error: dr.error })
        return
      }
      sendJson(res, 200, { ok: true, result: { code: dr.code, dismissed: true } })
      return
    }
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '立项单路由只支持 GET（只读）' })
      return
    }
    if (parts.length === 1) {
      const r = await readEpicMarkdown(anchorEpicsDir(anchor), parts[0])
      if (!r.ok) {
        sendJson(res, r.status, { ok: false, error: r.error })
        return
      }
      // t260829-02：详情准态「下一步建议」——state_key 现算 + readPrecacheHint 全量
      // 校验（命中才带 nextHint；工单/模板清单查询失败一律静默 null，不拖垮详情）。
      const nextHint = await epicNextHintFor(parts[0], anchor)
      sendJson(res, 200, {
        ok: true,
        result: {
          code: r.code,
          path: `notes/epics/${r.code}.md`,
          title: r.title,
          status: r.status,
          note: r.note,
          created: r.created,
          markdown: r.markdown,
          nextHint,
        },
      })
      return
    }
    if (parts.length === 2 && parts[1] === 'tickets') {
      await handleEpicTickets(res, parts[0], anchor)
      return
    }
    sendJson(res, 404, { ok: false, error: '路径不合法：/sandbar-workbench/api/epics/<代号>[/tickets | /suggest-next[/<jobId>] | /next-hint/dismiss | /close | /status]' })
  }

  /** 工单 agent 日志（M12，只读）：show 工单 → 定 .suyou 目录 → 列 agent_*.log / stage_*.json。
   *  无目录/无文件走 reason 人话降级（不抛错）；id 白名单在进 show 前拦（防穿）。 */
  async function handleAgentLogs(res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendTicketShowError(res, s, id)
        return
      }
      const t = s.result ?? {}
      const { base, reason } = resolveAgentBaseDir(repo, id, t, projectRootsFor(t.project))
      const result = await listAgentLogs(base)
      if (reason !== undefined && result.reason === undefined) result.reason = reason
      sendJson(res, 200, { ok: true, result })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** agent 实时动态（t260825-03，只读）：show 工单 → 定泳道会话文件 → 整解取尾 n 条事件摘要。
   *  降级契约仿 agent-logs：无会话/解压失败 → 200 {exists:false,reason} 不抛错；
   *  防穿比 agent-logs 更严（验收硬性要求）：id 非法或工单字段（worktree/workspace）越界 → 400。 */
  async function handleAgentLive(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    const url = new URL(req.url ?? '/', 'http://x')
    const n = Math.max(1, Math.min(200, Number.parseInt(url.searchParams.get('n') ?? '', 10) || 30))
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendTicketShowError(res, s, id)
        return
      }
      const t = s.result ?? {}
      const ref = await resolveSessionFile(repo, id, t, projectRootsFor(t.project))
      if (ref.refused === true) {
        sendJson(res, 400, { ok: false, error: ref.reason ?? '工单字段越界（拒绝读取）' })
        return
      }
      if (ref.path === undefined) {
        sendJson(res, 200, {
          ok: true,
          result: { exists: false, events: [], truncated: false, ws_root: ref.wsRoot ?? '', reason: ref.reason ?? '会话文件未定位' },
        })
        return
      }
      const result = await readAgentLiveTail(ref.path, n)
      sendJson(res, 200, { ok: true, result: { ...result, ws_root: ref.wsRoot ?? '' } })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** token 消耗聚合（t260828-07，只读）：show 工单 → 定全部会话文件（多角色加总）→
   *  按 timeline running 条目切阶段时间窗 → 整解聚合。与 agent-live 同一解析通路
   *  （decompressSession 复用）。降级契约同 handleAgentLive：无会话/无 usage →
   *  200 {exists:false,reason}；id 非法/字段越界 → 4xx 防穿。 */
  async function handleAgentUsage(res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendTicketShowError(res, s, id)
        return
      }
      const t = s.result ?? {}
      const ref = await resolveAllSessionFiles(repo, id, t, projectRootsFor(t.project))
      if (ref.refused === true) {
        sendJson(res, 400, { ok: false, error: ref.reason ?? '工单字段越界（拒绝读取）' })
        return
      }
      if ((ref.paths ?? []).length === 0) {
        sendJson(res, 200, {
          ok: true,
          result: {
            exists: false, files: 0, total: { input: 0, output: 0, cacheRead: 0 },
            byStage: {}, models: [], ws_root: ref.wsRoot ?? '', reason: ref.reason ?? '会话文件未定位',
          },
        })
        return
      }
      const windows = stageWindowsFromTimeline(t.timeline)
      const result = await aggregateTicketUsage(ref.paths, windows)
      sendJson(res, 200, { ok: true, result: { ...result, ws_root: ref.wsRoot ?? '' } })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 工单↔session 绑定：点工单→验存在→找/建 session，新建时附工单快照（client 作首条消息注入）。
   *  t260903-07 起客户端无调用方（openTicketSessionFlow 已删），联动入口下线仅客户端面——
   *  本路由按 ③ 口径保留（既有 ticket-* 会话数据留存、回滚面完整），勿标废弃。 */
  async function handleTicketSessionOpen(req: IncomingMessage, res: ServerResponse): Promise<void> {
    let body: any
    try { body = await readJsonBody(req) } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const ticketId = body?.ticket_id
    if (!ticketId || !TICKET_ID_RE.test(ticketId)) {
      sendJson(res, 400, { ok: false, error: 'ticket_id 不合法' })
      return
    }
    // 多项目化（260823）：project 必传（projects.yaml 注册表 key，无默认值）——
    // 会话工作区按该项目的注册目录判定。
    const projectKey = typeof body?.project === 'string' ? body.project : ''
    let proj: ProjectEntry | undefined
    try {
      proj = projectKey ? findProject(projectKey) : undefined
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
      return
    }
    if (!proj) {
      sendJson(res, 400, { ok: false, error: projectKey ? `未知项目：${projectKey}（projects.yaml 未注册）` : '缺 project 字段（projects.yaml 注册表 key，无默认值）' })
      return
    }
    const primary = primaryDir(proj)
    // 存在性校验 + 快照素材：bogus id 不许建空 session（原路只验格式， bogus 也会建出孤儿会话）
    // KI-025：show 失败按 kind 分流——只有 not_found 才许「工单不存在」；瞬时/终态/
    // 未知走 503/410/500（传输层抛错同属瞬时面）。否则阶段切换窗开建会话会谎报不存在。
    let tk: any
    try {
      const r = await callTool('ticket', { op: 'show', id: ticketId })
      if (r?.ok !== true) {
        sendTicketShowError(res, r, ticketId)
        return
      }
      tk = r.result
    } catch (err) {
      sendJson(res, 503, {
        ok: false,
        error: `工单查询失败（瞬时），请稍后重试：${String(err instanceof Error ? err.message : err)}`,
        retryable: true,
      })
      return
    }
    if (!tk || tk.id !== ticketId) {
      sendJson(res, 404, { ok: false, error: `工单不存在：${ticketId}` })
      return
    }
    const sessionId = `ticket-${ticketId}`
    const sessions = ctx.get('sessions')
    if (!sessions) {
      sendJson(res, 500, { ok: false, error: 'sessions 服务不可用（headless 无此路由）' })
      return
    }
    // 工单快照→首条上下文消息：契约抽成模块级纯函数 ticketContext（t260831-08，
    // smoke 直测同口径；本处语义不变）
    // 检查 live store
    if (sessions.get(sessionId)) {
      sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: false } })
      return
    }
    // 工作区随工单走（用户拍板 260823）：泳道工单 cwd=泳道目录，主树工单 cwd=项目主目录。
    // 优先级同 workspaceInfoOf：workspace{type,path} > 旧 worktree 字段 > 主目录；
    // 相对路径对项目主目录解，绝对路径须落在该项目注册目录之一。
    const wsPath = (tk.workspace && typeof tk.workspace.path === 'string' && tk.workspace.path) || tk.worktree || ''
    let cwd = primary
    if (wsPath) {
      const abs = resolve(primary, wsPath)
      const inProject = proj.dirs.some(d => abs === d || abs.startsWith(d.replace(/\/+$/, '') + sep))
      if (inProject && existsSync(abs)) cwd = abs
      else ctx.logger.warn('sandbar-workbench: 工单 %s 的工作区 %s 不在项目 %s 注册目录内或不存在，会话落主目录', ticketId, wsPath, proj.key)
    }
    try {
      sessions.create(sessionId, { meta: { cwd } })
      sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: true, cwd, context: ticketContext(tk) } })
    } catch (err: any) {
      const msg = String(err?.message ?? err)
      // 可能在持久层存在（上次进程创建的）：给 client open 自己加载
      if (msg.includes('already') || msg.includes('exist') || msg.includes('duplicate')) {
        sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: false } })
      } else {
        sendJson(res, 500, { ok: false, error: msg })
      }
    }
  }

  /**
   * 新建全局会话（session-entry t260825-02 建端点、t260828-02 口径调整，侧栏
   * 「会话」区新建按钮）。
   * 仿 handleTicketSessionOpen 的开/找形制，但语义边界三条：
   *   ① id 不带 ticket- 前缀（chat-<yyyymmdd-hhmmss>-<rand4>，可读有序防撞）；
   *   ② 不注入工单上下文（自由聊天，无首条快照消息）；
   *   ③ always-create 不 find（全局会话每次新建一个——连点会在服务端累积空会话
   *     尸体，但 t260828-02 起客户端列表数据源=插件记账层（只登记 UI 主动打开/
   *     新建的会话），存量不进列表，设计文档 §4 已授权此取舍，本期不做清理 UI）。
   * cwd 取该项目注册表主目录（「落在当前项目主目录」）。
   */
  async function handleGlobalSessionOpen(req: IncomingMessage, res: ServerResponse): Promise<void> {
    let body: any
    try { body = await readJsonBody(req) } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    // project 必传（projects.yaml 注册表 key，无默认值）——cwd 取该项目主目录。
    const projectKey = typeof body?.project === 'string' ? body.project : ''
    let proj: ProjectEntry | undefined
    try {
      proj = projectKey ? findProject(projectKey) : undefined
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
      return
    }
    if (!proj) {
      sendJson(res, 400, { ok: false, error: projectKey ? `未知项目：${projectKey}（projects.yaml 未注册）` : '缺 project 字段（projects.yaml 注册表 key，无默认值）' })
      return
    }
    const sessions = ctx.get('sessions')
    if (!sessions) {
      sendJson(res, 500, { ok: false, error: 'sessions 服务不可用（headless 无此路由）' })
      return
    }
    const cwd = primaryDir(proj)
    const d = new Date()
    const pad = (n: number): string => String(n).padStart(2, '0')
    const ts = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
    const sessionId = `chat-${ts}-${randomUUID().replace(/-/g, '').slice(0, 4)}`
    try {
      sessions.create(sessionId, { meta: { cwd } })
      ctx.logger.info('sandbar-workbench: 新建全局会话 %s（项目 %s，cwd %s）', sessionId, proj.key, cwd)
      sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: true, cwd } })
    } catch (err: any) {
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  /**
   * 项目注册表：侧栏分组数据源（260823 多项目化）+ 隔离条目（票③面D，验收 11）。
   * t260904-15：loadProjects() → loadRegistry()——空/全隔离注册表不再 throw→500
   * （首个项目接入恰恰发生在空注册表时；隔离条目以红色行呈现，无组头无设置入口），
   * 响应体补 quarantined[{key,dir,error}]（error 含 <dir>/project.yaml 定位，TS 装载器同源）。
   */
  async function handleProjects(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const reg = loadRegistry()
      const projects = reg.projects.map((p: ProjectEntry) => ({
        key: p.key,
        name: p.name,
        dirs: p.dirs,
        primary: primaryDir(p),
      }))
      const quarantined = reg.quarantined.map(q => ({
        key: q.key ?? q.dir.slice(q.dir.lastIndexOf('/') + 1),
        dir: q.dir,
        error: q.error,
      }))
      sendJson(res, 200, { ok: true, result: { projects, quarantined } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * 项目详情（票③面D，设置弹层数据面）：GET detail?key= —— spawn 安装器
   * `sandbar project list --json` 单点取票计数（tickets{open,closed,archived}）。
   * 口径（票③面D 决策 8）：「读不 spawn CLI」指注册表读面
   * （上方 handleProjects 走 TS 装载器防两份漂移）；票计数属 Temporal 查询=CLI
   * 独有数据，spawn 恰是同源而非第二份。Temporal 不可达时 CLI 自己降级
   * （tickets_state/tickets_note），本路由原样透传由弹层显「—」提示（不红）。
   */
  async function handleProjectDetail(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') { sendJson(res, 405, { ok: false, error: '只读路由，仅 GET' }); return }
    const key = new URL(req.url ?? '/', 'http://x').searchParams.get('key') ?? ''
    if (!/^[a-z0-9][a-z0-9-]*$/.test(key)) {
      sendJson(res, 400, { ok: false, error: `项目 key 形状不合法：${JSON.stringify(key.slice(0, 40))}` })
      return
    }
    try {
      const out = await runProjectCli({ repo, python: config?.python, entryPath: projectCliEntry() }, ['project', 'list', '--json'])
      const row = Array.isArray(out?.projects) ? out.projects.find((p: any) => p?.key === key) : undefined
      if (row === undefined) {
        sendJson(res, 404, { ok: false, error: `项目不存在于注册表：${key}` })
        return
      }
      sendJson(res, 200, {
        ok: true,
        result: {
          key: row.key, name: row.name, dirs: row.dirs,
          tickets: row.tickets, tickets_state: row.tickets_state, tickets_note: row.tickets_note,
        },
      })
    } catch (err) {
      if (err instanceof ProjectCliError) {
        sendJson(res, err.status >= 500 ? 502 : err.status, { ok: false, error: err.message, body: err.body })
        return
      }
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * 项目接入（票③面D，接入弹层写路径）：POST add {key,name,dir} —— 薄壳转
   * `sandbar project add --json`，含 dry_run 档（预检，不落盘）。校验/闸逻辑零实现
   * （CLI 单源）；CLI 拒收（非零退出含 stdout JSON 错误体）→ 409 原体透传，弹层就地显示。
   */
  async function handleProjectAdd(req: IncomingMessage, res: ServerResponse): Promise<void> {
    // dry_run 口径：CLI `project add` 无 --dry-run 旗（--help 实证；补旗=跨写集改动，
    // 路由收到 dry_run:true 时不 spawn、422 显式应答不支持（零现场变更保证）；
    // 深度校验（存在性/交叉/重复/legacy）在确认时由 CLI 执行并就地显示。
    await projectWriteRoute(req, res, 'add', (body, dryRun) => {
      if (dryRun) return null
      return ['project', 'add', '--key', String(body?.key ?? ''), '--name', String(body?.name ?? ''), '--dir', String(body?.dir ?? ''), '--json']
    })
  }

  /**
   * 项目摘除（票③面D，摘除弹层四步流写路径）：POST remove {key,purge_data,
   * purge_credentials,confirm_last,dry_run} —— 薄壳转 `sandbar project remove
   * --json`，旗标与 CLI 一一对应（在飞闸/purge 前置闸全在 CLI 侧，fail-closed
   * 文案由 CLI 错误体原样透传）。二次确认（purge 输入 key）是弹层职责，路由不重复。
   */
  async function handleProjectRemove(req: IncomingMessage, res: ServerResponse): Promise<void> {
    await projectWriteRoute(req, res, 'remove', (body, dryRun) => {
      // key 是 --key 必选旗，非位置参数（CLI --help 实证）。
      const args = ['project', 'remove', '--key', String(body?.key ?? ''), '--json']
      if (dryRun) args.push('--dry-run')
      if (body?.purge_data) args.push('--purge-data')
      if (body?.purge_credentials) args.push('--purge-credentials')
      if (body?.confirm_last) args.push('--confirm-last')
      return args
    })
  }

  /** 写路由共用壳：POST-only + body 校验 + dry-run 旗 + CLI 调用与错误分流。 */
  async function projectWriteRoute(
    req: IncomingMessage, res: ServerResponse, action: 'add' | 'remove',
    buildArgs: (body: any, dryRun: boolean) => string[] | null,
  ): Promise<void> {
    if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: '写路由，仅 POST' }); return }
    let body: any
    try { body = await readJsonBody(req) } catch {
      sendJson(res, 400, { ok: false, error: '请求体必须是合法 JSON（readJsonBody 64KB 封顶）' })
      return
    }
    const dryRun = body?.dry_run === true
    const argv = buildArgs(body, dryRun)
    if (argv === null) {
      // add dry-run 能力应答（F1：CLI 无此旗，预检降档为弹层本地形状检查）。
      sendJson(res, 422, { ok: false, error: 'CLI 暂不支持 add 预检（project add 无 --dry-run 旗，补旗为跨写集裁定项）；预检=弹层本地形状检查，深度校验在确认时由 CLI 执行', action, dry_run: true })
      return
    }
    try {
      const out = await runProjectCli({ repo, python: config?.python, entryPath: projectCliEntry() }, argv)
      sendJson(res, 200, { ok: out?.ok !== false, result: out })
    } catch (err) {
      if (err instanceof ProjectCliError) {
        // 状态语义（project-admin.ts 分流）：拒收（JSON 体或 exit 1 人话）→ 409
        // 原文/原体透传（弹层就地显示的数据源）；argv 拼装错（exit 2）→ 502；
        // 输出不可解析/超时/取消 → 502/504/499 精确文案（不裸抛堆栈、不谎报无结果）。
        const status = err.status === 504 || err.status === 499 ? (err.status === 499 ? 499 : 504) : err.status >= 500 ? 502 : 409
        sendJson(res, status, { ok: false, error: err.message, body: err.body, action, dry_run: dryRun })
        return
      }
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** project CLI 入口（测试缝：repo 根 sandbar；UT 经 config.python='node' + 假脚本注入）。 */
  function projectCliEntry(): string {
    return join(repo, 'sandbar')
  }

  /** 工作区列表（项目切换器数据源）。 */
  async function handleWorkspaceList(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    const wr = ctx.get('workspaceRegistry')
    if (!wr) {
      sendJson(res, 500, { ok: false, error: 'workspaceRegistry 不可用' })
      return
    }
    try {
      const list = wr.list()
      // repo 一并下发：工单台侧栏按它把「相对 worktree / 无 worktree」的工单归属到本仓库项目组。
      sendJson(res, 200, { ok: true, result: { repo, list: list.map((w: any) => {
        const ids = w.sessionIds
        return {
          id: w.id,
          title: w.title,
          path: w.path,
          sessionCount: typeof ids?.length === 'number' ? ids.length : 0,
        }
      }) } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 把路由挂到 webServer（同一 effect，卸载随插件生命周期）。 */
  const attach = (ws: any): void => {
    ctx.effect(() => {
      const disposers = [
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/tickets', handler: handleTickets }),
        ws.register({ kind: 'prefix', path: TICKETS_PREFIX, handler: handleTicketRoute }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/workflows', handler: handleWorkflows }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/book', handler: handleBook }),
        // 「文档」视图两路由（t260905-06；KI-070 起按 ?project= 项目根解析）：目录树 + 按篇正文。
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/docs/tree', handler: handleDocsTree }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/docs/doc', handler: handleDocsDoc }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/temporal-health', handler: handleTemporalHealth }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/workers', handler: handleWorkers }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/scan-report', handler: handleScanReport }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/build-info', handler: handleBuildInfo }),
        // 会话开局 charter 读侧（t260904-07）：路径同源常量（src/host/session-charter.ts
        // SESSION_CHARTER_PATH），客户端 fetch URL 与此处注册逐字同源，防 KI-042 漂移。
        ws.register({ kind: 'exact', path: SESSION_CHARTER_PATH, handler: handleSessionCharter }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/metrics', handler: handleMetrics }),
        ws.register({ kind: 'exact', path: EPICS_PREFIX, handler: handleEpics }),
        ws.register({ kind: 'prefix', path: EPICS_PREFIX, handler: handleEpicRoute }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/workspaces', handler: handleWorkspaceList }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects', handler: handleProjects }),
        // 票③面D：项目生命周期三路由（detail 票计数读面 / add·remove 写面，薄壳 spawn 安装器 CLI）。
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects/detail', handler: handleProjectDetail }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects/add', handler: handleProjectAdd }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects/remove', handler: handleProjectRemove }),
        // t260903-07 起客户端无调用方（openTicketSessionFlow 已删），联动入口下线仅客户端面——
        // 路由按 ③ 口径保留（数据留存/回滚面），见 handleTicketSessionOpen 头注。
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/ticket-session/open', handler: handleTicketSessionOpen }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/global-session/open', handler: handleGlobalSessionOpen }),
      ]
      return () => { for (const dispose of disposers) dispose() }
    }, 'sandbar-workbench: wf api routes')
    ctx.logger.info('sandbar-workbench: 工单工作流台 API 已挂载 /sandbar-workbench/api/wf/*（repo=%s）', repo)
  }

  // webServer 可能先已提供（直接取），也可能后到（等 internal/service 事件）；
  // headless 永远等不到——待机即正确行为。
  const existing = ctx.get('webServer')
  if (existing !== undefined) {
    attach(existing)
    return
  }
  const dispose = ctx.on('internal/service', (serviceName: string, value: any) => {
    if (serviceName !== 'webServer') return
    dispose()
    attach(value)
  })
}

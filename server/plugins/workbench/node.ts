/**
 * sandbar-workbench —— 工单工作流台的 dsh UI 插件（宿主半 / node）。
 *
 * 职责：在 dsh 自己的 webServer 上挂 /sandbar-workbench/api/wf/*（Ticket Workflow Console Design
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
 *   GET  /sandbar-workbench/api/wf/tickets/<id>/file?path=&mode=settle|base|current
 *                                               → 「本票时刻」只读文件（t260915-17，mock 260904
 *                                                 标注 D）：settle=收口版（该票的提交版本）/base=
 *                                                 开票基点版（票面 base_ref）/current=当前版（「跳到
 *                                                 当前版」小链专用）。fail-closed 人话降级走 200，绝不
 *                                                 回落工作树冒充本票时刻；只读刚性=非 GET 一律 405
 *   GET  /sandbar-workbench/api/wf/inspection/tickets
 *                                               → 巡检板面（t260915-08）：引擎 ticket-list
 *                                                 {kind:"inspection"} 薄壳；无 project 维度
 *                                                 （巡检票无 ProjectKey SA，引擎级面）
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
 *   GET  /sandbar-workbench/api/wf/worker-staleness → worker 陈旧度对比（只读，t261008-29 KI-227）：
 *                                                 运行中 worker 指纹 vs 当前 HEAD + 当前活动注册集；
 *                                                 stale=警告（observe-only，绝不阻断/重启 worker）
 *                                                 （t261008-18 已撤 temporal-health/workers/
 *                                                 scan-report 三路由：main 侧删除语义保留，
 *                                                 本路由不依赖其探针助手，自带 execFile 直探）
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
 *                                                 会话文件（session.jsonl.zstd / session.v3.jsonl.zstd 双名）整解（zstd -dc，多帧拼接
 *                                                 直接解）取尾部 n 条事件摘要（assistant 文本截断 /
 *                                                 工具调用名+目标路径）；无会话文件/解压失败走
 *                                                 {exists:false,reason} 降级；工单字段 ../ 逃逸 → 400
 *
 * 立项单只读 API（epic-linkage Tier 2，t260825-04；t261019-12 起真源=docs/epics/*.md
 * 英文 front-matter 档（code/retired/summary/started），retired 布尔是唯一状态——
 * design=docs/design/epic-registry-v1.md；状态真源仍=Temporal 查询，UI 不存状态）：
 *   GET  /sandbar-workbench/api/epics            → 列 docs/epics/*.md：{code, retired, summary,
 *                                                 started, defect?}；目录不存在 → 具名 500（硬切换，
 *                                                 绝不返回空表冒充「无立项」）；单档 front-matter
 *                                                 缺失/畸形 → 该行 retired:true + defect（fail-closed）
 *   GET  /sandbar-workbench/api/epics/<code>     → 单份立项 front-matter 元信息（不回 Markdown 全文
 *                                                 ——summary 是唯一上台面的档内文字）；形状 400 /
 *                                                 不存在 404 人话（shared.validate_epic_code 同风格）
 *   GET  /sandbar-workbench/api/epics/<code>/tickets
 *                                               → 该立项全部工单实时状态聚合（复用 ticket list
 *                                                 --epic 通路）：按 status 分桶计数 + 工单行
 *                                                 （id/title/status/stage/stage_state）；Temporal
 *                                                 不可达 → {degraded:true, reason} 降级不 502
 *   （t261019-12 退役注记：POST /epics/<code>/close 与 /status 两支状态改写路由随
 *     「retired 布尔是唯一状态」整链删除——retiring = 在 git 里改 docs/epics/<code>.md
 *     的 retired 行，不再有机器改写入口；原 suggest-next 两支随 suggest_next 退役（t260910-14）。）
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
import { appendFile, readFile, readdir } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { dirname, join, resolve, sep } from 'node:path'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { resolveRepo } from '../repo-anchor.mjs'  // t261008-33: shared anchor chain + escape guard
import type { Context } from '@deepseek-ai/cordis'
import { runAdminCli } from '../../sandbar-tools.ts'
import { findProject, loadProjects, loadRegistry, primaryDir, type ProjectEntry } from '../../project-registry.ts'
// 项目锚解析器（t260907-11 KI-057）：请求层按 ?project= 解析项目根，六处静态锚穿参的
// 单一收口（取舍清单/env 覆盖闸/显式报错口径见该模块头注）。
import { anchorEnv, resolveProjectAnchor, resolvedMark, type ProjectAnchor } from './src/host/project-anchor.ts'
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
import { readTicketTimeFile } from './src/host/ticket-time-file.ts'
import { isTicketTimeMode } from './src/shared/ticket-time-model.ts'
import { ticketShowErrorReply } from './src/host/ticket-error.ts'
import { readInspectionArchive, readPeriodReport } from './src/host/inspection-archive.ts'
// t261021-14: the inspection ledger directory is resolved ONCE through the
// engine's own resolver (shared.INSPECTION_DIR via a bounded subprocess) — the
// previous join(root, 'out', 'inspection') literal here had drifted from the
// writer's declared location.
import { resolveInspectionDir } from './src/host/inspection-dir.ts'
// t260926-05：巡检落账报告只读端点（report_path → 可读摘要；fail-closed 200+reason 同 /file 风格）。
import { readInspectionReportFile } from './src/host/inspection-report.ts'
// Per-project session ledger file (sessions.json, UI-5 t261005-06): the single
// logic point of the GET/POST routes lives in src/host/session-ledger-file.ts
// (atomic write / merge / refusal all live there; this file is a zero-logic front).
import {
  SessionLedgerError,
  readExecutorSessionIds,
  readLedgerFile,
  saveSessionEntry,
  validateSessionEntry,
} from './src/host/session-ledger-file.ts'
import { mergeExecutorSessions } from './src/shared/session-handles.ts'
import { listAgentLogs, resolveAgentBaseDirs, _sessionKbFast } from './src/host/agent-logs.ts'
import { readAgentLiveTail, resolveSessionFile } from './src/host/agent-live.ts'
import { aggregateTicketUsage, resolveAllSessionFiles, stageWindowsFromTimeline } from './src/host/agent-usage.ts'
import { buildMetricsResponse, defaultDeps } from './src/host/metrics.ts'
import { computeHostFingerprint, type HostFingerprint } from './src/host/build-info.ts'
// 首句派生纯函数（t260905-07）：client 半纯函数层无 react 依赖，node 侧直用同源
// ——列表 enrichment（title_or_first）与详情头部两条通道一个口径。
import { deriveTitleOrFirst } from './src/host/enrich.ts'
import { SESSION_CHARTER_PATH, composeSessionCharter } from './src/host/session-charter.ts'
import { isEvidenceFileName } from './src/host/epics.ts'
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
 *  t260908-01 加 pause/resume=段间暂停·恢复走 Temporal pause/resume signal；
 *  t260912-03 加 authorize=人授权签发（唯一入口＝sign 信号面，走 ticket.py 审计面，
 *  不新开旁路））。
 *  create 不进此表：它没有工单 id，落 exact 路由 /wf/tickets 的 POST 分支
 *  （handleTicketCreate，epic-linkage Tier 3 / t260826-02），与 <id>/<op> 路径正交。
 *  review（审批意见落盘）不进此表——它不经过 admin.py，在路由里按 method 单独分支。
 *  t261009-54 加 dismiss/restore=人工摘除失败票 / 撤回摘除：走 ticket.py 既有
 *  op=dismiss|restore（t261009-31 CLI 审计面：who 记名、reason 必填非空绝不默认、
 *  拒收 agent 角色名），不造旁路、不直写 journal。此前缺口：client 已 POST 此二
 *  路径而本表没有 ⇒ 恒 404「未知操作」，左列按钮点了没反应。 */
const OPS = new Set(['accept', 'advance', 'dispatch-next', 'rework', 'update', 'sign', 'authorize', 'retry-qc', 'pause', 'resume', 'dismiss', 'restore'])

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

/* t261008-18: the Temporal port probe / pid-alive / pidfile helpers went with the
   /wf/temporal-health and /wf/workers routes (the machine-status strip was their
   only consumer). */

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
  // t261008-33: shared anchor chain (config.repo -> SANDBAR_REPO -> DEFAULT_REPO) + escape
  // guard (SANDBAR_ANCHOR_MISMATCH before any write) — see repo-anchor.mjs.
  const repo = resolveRepo(config?.repo, DEFAULT_REPO)
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
   *  HTTP 裁定与 body 装配收口在 src/host/ticket-error.ts（单测直跑）。kind 缺失/
   *  未知一律 500 非 404——「工单不存在」只能由明确 NotFound 语义触发，谎报是本票
   *  消灭对象。t260919-02：可选 face（终态失败面）——只加键不改级（terminal 仍
   *  410 仍「刷新无效」）；face 仅 plain dict 且 terminal 才附带（直读失败/超时/
   *  畸形 → 无 face 键，UI 按纯错误提示降级，绝不渲染半残假面）。 */
  function sendTicketShowError(res: ServerResponse, s: unknown, id = '', face?: unknown): void {
    const reply = ticketShowErrorReply(s as { error?: unknown; kind?: unknown } | null, id, face)
    sendJson(res, reply.status, reply.body)
  }

  // t260919-02 终态失败面直读桥：tools_registry/ticket.py 的 QueryError 只带 kind
  // 不带 face（server/tools/ 写集外），terminal 回执要对 UI 附失败面就直读引擎
  // ticket-query（client.py 终态分支 face 键的正源）。超时纪律（review④）：显著
  // 小于 UI 详情加载体验阈值——详情请求已在 tools_registry 通道等过一轮，这里再等
  // 就把 410 兜底拖成二次卡顿；5s 读不到=照旧 410 无 face（诚实降级，不重试）。
  const TERMINAL_FACE_TIMEOUT_MS = 5_000

  /** 直读引擎终态回执的 face；失败/超时/畸形回执 → undefined（调用方不附带）。 */
  async function fetchTerminalFace(id: string): Promise<unknown> {
    try {
      const r = await runPocCli(cli, ['ticket-query', JSON.stringify({ ticket_id: id })],
        { timeoutMs: TERMINAL_FACE_TIMEOUT_MS })
      return (r !== null && typeof r === 'object' && !Array.isArray(r)) ? (r as any).face : undefined
    } catch {
      return undefined
    }
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

  // ---------------------------------------------------------------------------
  // t261011-19: the left column's LineOn pill data source. The engine derives
  // the line face (spawn src/host/line-face-adapter.py once per project; its
  // receipt is one single-line JSON); this route only ASSEMBLES: engine faces
  // land on matching rows verbatim, and a dev-lane opt-in row with no landing
  // row gets the membership word 'on_line' (lane_version + develop_line are
  // themselves engine row keys — no state is derived here, only presence).
  // Failure discipline: a non-zero exit, empty stdout, or non-JSON stdout all
  // become ONE named `line_face_error` string; rows pass through un-enriched
  // and the list never 502s because of the enrichment (explicit degradation,
  // never silent).
  // Spawn fan-out discipline (KI-018 polling family): `GET /wf/tickets` is
  // what the console polls every 10 s per project, so the adapter spawn sits
  // behind a 15 s TTL cache with a single-flight in-flight promise map —
  // concurrent polls share one spawn instead of one each; a failed receipt is
  // NOT cached past its own TTL. The timeout bounds the hang; the
  // single-flight map bounds the fan-out.
  const LINE_FACE_TTL_MS = 15_000
  type LineFaceRead = {
    frozen: boolean | null
    faces: Map<string, { face: string; overdue: boolean }>
    error: string
  }
  const lineFaceCache = new Map<string, { at: number; promise: Promise<LineFaceRead> }>()

  async function readLineFace(repoDir: string, projectKey: string): Promise<LineFaceRead> {
    const key = `${repoDir}::${projectKey}`
    const hit = lineFaceCache.get(key)
    if (hit && Date.now() - hit.at < LINE_FACE_TTL_MS) return hit.promise
    const entry = {
      at: Date.now(),
      promise: (async (): Promise<LineFaceRead> => {
        const poc = join(repoDir, 'server', 'engine')
        const venvPy = join(poc, '.venv', 'bin', 'python')
        const python = existsSync(venvPy) ? venvPy : 'python3'
        const adapter = join(repoDir, 'server', 'plugins', 'workbench', 'src', 'host', 'line-face-adapter.py')
        try {
          const { stdout } = await execFileP(python, [adapter, projectKey], {
            cwd: repoDir, timeout: 20_000, maxBuffer: 4 * 1024 * 1024,
          })
          const doc = JSON.parse(stdout)
          if (doc?.ok !== true) {
            return { frozen: null, faces: new Map(), error: `line-face adapter: ${String(doc?.reason ?? 'refused')}` }
          }
          const faces = new Map<string, { face: string; overdue: boolean }>()
          for (const f of (Array.isArray(doc.faces) ? doc.faces : [])) {
            if (f && typeof f.ticket === 'string' && typeof f.face === 'string') {
              faces.set(f.ticket, { face: f.face, overdue: f.overdue === true })
            }
          }
          return { frozen: doc.frozen === true, faces, error: '' }
        } catch (err) {
          // Crash path (traceback on stderr / signal / timeout): one named
          // error, rows pass through un-enriched, nothing stays cached good.
          lineFaceCache.delete(key)
          return { frozen: null, faces: new Map(), error: String(err instanceof Error ? err.message : err) }
        }
      })(),
    }
    lineFaceCache.set(key, entry)
    return entry.promise
  }

  /** Attach per-row line_face keys + the project-level frozen flag (t261011-19).
   *  Degradation contract (arbitration round 1, code-fault fix): when the
   *  adapter read carried a named error, rows pass through UN-enriched — the
   *  `on_line` membership branch is taken ONLY on a clean read. A stuck
   *  adapter must never present a legitimate-looking line state; the error
   *  string already names the cause, and the pill's absence is the honest
   *  "unreadable" face. */
  function applyLineFace(tickets: any[], face: LineFaceRead): { frozen: boolean | null; error: string } {
    for (const tk of tickets) {
      const hit = face.error === '' ? face.faces.get(String(tk.id)) : undefined
      if (hit) {
        tk.line_face = hit.face
        tk.line_face_overdue = hit.overdue
      } else if (face.error === '' && tk.lane_version === 'develop-buffer-v1' && tk.develop_line) {
        // On-line, not landed (the design's baseline row): membership only,
        // from two engine row keys — never a derived state.
        tk.line_face = 'on_line'
        tk.line_face_overdue = false
      }
    }
    return { frozen: face.frozen, error: face.error }
  }

  /** 台面：ticket list + workflow list 并行（F1 更正：主列表不再逐票 show 取 pending——
   *  审批理由详情抽屉自可见，行卡不放审批理由=mock 口径）。
   *  多项目化（260823）：?project=<key> 必传（projects.yaml 注册表，无默认值）——
   *  工单按 ProjectKey search attribute 过滤（Temporal 侧）；workflow 模板表是全局的，不过滤。 */
  /** 新建工单（epic-linkage Tier 3，t260826-02）：立项单详情页「新建工单」入口的落点——
   *  代号由界面传值（UI 无手输框），本层只透传不重复校验：epic 强校验单点在
   *  client.py validate_epic_code（docs/epics/<代号>.md 存在性+retired 布尔），拒收错误经 admin.py
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
      // t261011-19: the LineOn pill enrichment — best-effort, named on failure,
      // never a 502 (see readLineFace/applyLineFace above).
      const lf = applyLineFace(tickets, await readLineFace(repo, projectKey))
      sendJson(res, 200, {
        ok: true,
        result: {
          count: tickets.length, tickets,
          line_frozen: lf.frozen, line_face_error: lf.error,
        },
        workflows })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 巡检板面（t260915-08）：GET /wf/inspection/tickets —— 引擎 ticket-list
   *  {kind:"inspection"} 的薄壳（巡检票无 ProjectKey SA，项目板过滤天然不含它们；
   *  本端点有意**不收 project 参数**——巡检是引擎级面，行合流进每个项目板由客户端做）。
   *  引擎侧白名单（inspection.yaml 在册且 enabled 实例）+ 闭合行窗口过滤都在引擎，
   *  本壳零清洗逐键透传（与 handleTickets 同纪律）；ok:false → 502 原文透传（不吞成
   *  空列表——t260910-04 R3 同款教训）。 */
  async function handleInspectionTickets(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '巡检板面只支持 GET' })
      return
    }
    try {
      const t = await runPocCli(cli, ['ticket-list', JSON.stringify({ kind: 'inspection' })],
        { timeoutMs: 300_000, maxBufferBytes: 16 * 1024 * 1024 })
      if (t?.ok === false) {
        sendJson(res, 502, { ok: false, error: `ticket-list(inspection) 失败: ${t.error ?? JSON.stringify(t)}` })
        return
      }
      const tickets = (t?.result?.tickets ?? []).map((r: any) => ({ ...r, close_ts: r.close_ts ?? 0 }))
      sendJson(res, 200, {
        ok: true,
        result: {
          count: tickets.length,
          tickets,
          inspection_filter: t?.result?.inspection_filter ?? null,
        },
      })
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

  /* ------------------------------------------------ M9 PR 式审批台：diff + review */

  /** KI-227（t261008-29）worker 陈旧度对比面（只读 observe-only）：比对运行中
   *  worker 的指纹文件与当前 HEAD + 当前活动注册集，stale=警告，绝不阻断、绝不
   *  重启/停止 worker、绝不写泳道。引擎侧单源=worker_staleness.py（--tree 全量
   *  组装同源路径），本路由只 spawn（绝对路径锚 repo——review 条件②：路径跨进程
   *  边界必须绝对，console cwd 不保真）+ 15s 进程内缓存（--tree 全引擎导入秒级，
   *  防止控制台轮询反复打 git）。 */
  const STALENESS_CACHE_MS = 15_000
  let stalenessCache: { at: number; payload: any } | null = null
  async function handleWorkerStaleness(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (stalenessCache && Date.now() - stalenessCache.at < STALENESS_CACHE_MS) {
      sendJson(res, 200, stalenessCache.payload)
      return
    }
    const poc = join(repo, 'server', 'engine')
    const venvPy = join(poc, '.venv', 'bin', 'python')
    const python = existsSync(venvPy) ? venvPy : 'python3'
    try {
      const { stdout } = await execFileP(python, [join(poc, 'worker_staleness.py'), '--tree'], {
        // cwd 锚引擎目录（worker_staleness.py 自锚 _ENGINE_DIR，双保险）；有界回收
        // 由 execFile timeout 兜底（同 runPocCli 纪律）。
        cwd: poc,
        timeout: 30_000,
        maxBuffer: 4 * 1024 * 1024,
      })
      const parsed = JSON.parse(stdout)
      const payload = { ok: true, result: parsed }
      stalenessCache = { at: Date.now(), payload }
      sendJson(res, 200, payload)
    } catch (err) {
      // 失败=named 502（不缓存，下一轮重试）；可见面自身故障绝不能被误读成 worker 绿。
      sendJson(res, 502, { ok: false, error: `worker-staleness face failed: ${String(err instanceof Error ? err.message : err)}` })
    }
  }


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
   * 「本票时刻」只读文件（t260915-17）：GET /wf/tickets/<id>/file?path=<仓内相对路径>&mode=settle|base|current[&project=]。
   * settle=收口版（该票的提交版本：main 收口提交或残留泳道分支 tip）；base=开票基点版
   * （票面 base_ref，C4：不做 path→repo 归属）；current=当前版（「跳到当前版」小链专用，
   * 唯一读工作树的口径，读主树布局不依赖泳道树）。fail-closed：票在飞/泳道拆且无收口
   * 提交/路径不在该版本/二进制 → 200 + {result:{ok:false,reason}} 人话（路径与时刻问题
   * 不是服务器错，docs doc 端点同风格），绝不回落工作树版本冒充「本票时刻」。
   * 只读刚性：本分支非 GET 已在路由处 405；读取计算在 src/host/ticket-time-file.ts
   * （git 子命令白名单源码锁）。project 锚解析同 handleTicketDiff（query 显式 > 票面
   * t.project > 默认仓）。
   */
  async function handleTicketTimeFile(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id) || /[./]/.test(id)) {
      sendJson(res, 400, { ok: false, error: `工单 id 不合法：'${id.slice(0, 40)}'` })
      return
    }
    const url = new URL(req.url ?? '/', 'http://x')
    const p = url.searchParams.get('path')
    const mode = url.searchParams.get('mode')
    if (p === null || p === '') {
      sendJson(res, 400, { ok: false, error: 'path 必传（仓内相对路径）' })
      return
    }
    if (!isTicketTimeMode(mode)) {
      sendJson(res, 400, { ok: false, error: `mode 必传且只能是 settle|base|current（收到: ${String(mode)}）` })
      return
    }
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendTicketShowError(res, s, id)
        return
      }
      const t = (s.result ?? {}) as Record<string, unknown>
      const queryKey = url.searchParams.get('project')
      const a = resolveProjectAnchor(
        queryKey !== null && queryKey !== '' ? queryKey : (typeof t.project === 'string' ? t.project : ''),
        repo)
      const anchor = anchorGuard(res, a)
      if (anchor === null) return
      const result = await readTicketTimeFile(anchor.root, {
        id,
        status: t.status,
        lane: t.lane,
        branch: t.branch,
        baseRef: t.base_ref,
        repoWorktrees: t.repo_worktrees,
      }, mode, p)
      sendJson(res, 200, { ok: true, result, resolved: resolvedMark(anchor) })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: `本票时刻读取失败：${String(err instanceof Error ? err.message : err)}` })
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
          // t260919-02：终态回执补直读引擎把 face 带进 410 body（只加键不改级：
          // 仍 410 仍「刷新无效」；直读失败/超时/畸形 → 照旧 410 无 face，UI 降级
          // 纯错误提示不渲染失败面板）。仅详情 GET 桥接，写操作通道零变化。
          if ((r as any)?.kind === 'terminal') {
            const face = await fetchTerminalFace(parts[0])
            sendTicketShowError(res, r, parts[0], face)
          } else {
            sendTicketShowError(res, r, parts[0])
          }
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
      // t260915-17：「本票时刻」只读文件（mock 260904 标注 D——文件行=链接，点开以
      // 该票收口版/开票基点版只读打开）。只读刚性：该通道任何写方法一律 405（file
      // 没有写语义；与 POST 操作面 OPS 白名单互斥）。
      if (op === 'file') {
        if (req.method !== 'GET') {
          sendJson(res, 405, { ok: false, error: '本票时刻文件读取是只读通道，仅支持 GET' })
          return
        }
        await handleTicketTimeFile(req, res, id)
        return
      }
      // t260926-05：巡检落账报告只读端点（report_path 指针 → 缩进式可读摘要）。
      // 只读刚性：非 GET 一律 405；路径问题走 fail-closed 200+reason（不 5xx 不抛）。
      if (op === 'inspection-report') {
        if (req.method !== 'GET') {
          sendJson(res, 405, { ok: false, error: '巡检报告摘要是只读通道，仅支持 GET' })
          return
        }
        if (!TICKET_ID_RE.test(id)) {
          sendJson(res, 400, { ok: false, error: `工单 id 不合法：'${id.slice(0, 40)}'` })
          return
        }
        const url = new URL(req.url ?? '/', 'http://x')
        const result = await readInspectionReportFile(repo, url.searchParams.get('path'))
        sendJson(res, 200, { ok: true, result })
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
      // t260928-24（宿主实报：巡检票详情里 approve/reject 点了没反应）：引擎直调 op
      // （sign / authorize / pause / resume 走 client.py 的 ticket 面）必须**声明调用方
      // 项目身份**——260927 起引擎对 undeclared 写 op 一律拒收（cross_project_refused），
      // 而本面此前一个身份字段都不带 ⇒ 签字信号根本没进门（票面 gate_error 留痕的
      // 「跨项目闸：…调用未声明身份…拒收」就是这个；UI 侧只表现为点了没反应）。
      // 身份来源=请求 ?project=（与读面同一个逐请求项目锚：多项目控制台按当前视图
      // 声明自己）；视图无 key 时不猜、保持原样（引擎照旧按未声明处理）。
      const callAnchor = anchorGuard(res, anchorOf(url))
      if (callAnchor === null) return
      const callerProject = String(callAnchor.key ?? '')
      const withCaller = <T extends Record<string, unknown>>(payload: T): T =>
        callerProject === '' ? payload : ({ ...payload, caller_project: callerProject } as T)
      try {
        // sign = 审批签字（awaiting-human 人工审批段）：走 Temporal TicketWorkflow 的签字
        // （decision=approve 放行推进 / reject 打回），不经 admin.py（引擎对 human 门只认 sign）。
        // t260915-08：gate 改透传 body.gate ?? ''——dev-lane 调用方不传（引擎按当前门
        // 兜底，零变化）；巡检详情面带 gate=inspection-close（值=引擎 ticket-query
        // meta.gate_id 单点下发），workflow intake validate_close_signature 按它放行
        // （gate 不匹配拒收）。与 inspection_trigger.py sign 同义同门，零旁路。
        if (op === 'sign') {
          const decision = body.decision === 'reject' ? 'reject' : 'approve'
          const note = String(body.note ?? '')
          const who = String(body.who ?? 'op-local')
          const gate = String(body.gate ?? '')
          const pocArgs = withCaller({
            op: 'sign',
            ticket_id: id,
            input: { who, gate, decision, note },
          })
          const r = await runPocCli(cli, ['ticket', JSON.stringify(pocArgs)])
          sendJson(res, 200, r)
          return
        }
        // t260912-03：authorize = 人授权签发（受保护路径 / 仲裁上限的放行钥匙）。
        // 唯一入口＝sign 信号面——经 ticket.py op=authorize 转发（与 sign 同审计面，
        // 不造旁路）；who/kind/scope/reason/expires 全由调用方注入（agent 不得自签，
        // workflow intake 机械拒收 agent 角色名）。expires 收 ISO8601 或 epoch 秒。
        if (op === 'authorize') {
          const pocArgs = withCaller({
            op: 'authorize',
            ticket_id: id,
            input: {
              who: String(body.who ?? 'op-local'),
              kind: String(body.kind ?? ''),
              scope: body.scope ?? [],
              reason: String(body.reason ?? ''),
              expires: body.expires ?? '',
            },
          })
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
          const r = await runPocCli(cli, ['ticket', JSON.stringify(withCaller({
            op, ticket_id: id, who, note,
          }))])
          sendJson(res, 200, r)
          return
        }
        // t261009-54：dismiss/restore = 人工摘除失败票 / 撤回摘除。与 pause/resume
        // 同形但**刻意不同通道**：走 ticket.py op=dismiss|restore（callTool 审计面，
        // run-id 入账），不发 Temporal signal——摘除只记 audit journal、不发信号、
        // 不动状态机（ticket_dismiss.py 自己的契约；别「顺手修」成 signal）。
        // 借 pause/resume 分支形态的故障模式取舍（review 意见①）：畸形 payload 与
        // 幂等态（重复 dismiss / 未摘先 restore）**不在路由层处理**——who 空、reason
        // 空、agent 角色名、未知票、重复处置全部是引擎的具名拒收（t261009-31），
        // 原样透传给面板显示，路由绝不默认、绝不改写成成功。身份来自请求体
        // （who→by），路由不注入任何侧常量——journal 行的 who 是审计锚。
        if (op === 'dismiss' || op === 'restore') {
          const args: Record<string, unknown> = withCaller({
            op, id, by: String(body.who ?? ''), reason: String(body.reason ?? ''),
          })
          const r = await callTool('ticket', args)
          sendJson(res, 200, r)
          return
        }
        // 面板通道写操作直接执行（总管操作本身即意图）；审计由 admin.py run-id 机制承担。
        // t260928-24 同批：ticket.py 写 op 的跨项目闸同样要身份（admin.py→tools_registry→
        // ticket.py 一路不带身份 ⇒ accept/advance/rework/update 一律被拒）——同一个
        // ?project= 逐请求锚透传，调用点两条通道口径一致。
        const args: Record<string, unknown> = withCaller({ op, id })
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

  /**
   * Inspection period archive read side (t261006-15, plan D1, read-only):
   *   GET /sandbar-workbench/api/wf/inspection-archive?project=<key>[&period=YYYYMMDD&instance=<id>]
   * Serves the period list (explicit newest-first + missing/merge semantics; computation
   * core = src/host/inspection-archive.ts); with period+instance it serves that single
   * report. The project root goes through anchorOf (same contract as docs/tree: unknown
   * key 400 / isolated-or-broken entry 502, never a silent fallback to the default
   * repo). The ledger directory is NOT derived here: it comes from
   * resolveInspectionDir (t261021-14) — the engine's own declared location
   * (shared.INSPECTION_DIR), so the read face cannot drift from the writer
   * again. The ledger is ONE global per-engine directory: per-project
   * separation stays filename-whitelist-only inside the archive reader
   * (unchanged); `project` still gates the anchor only. An absent archive
   * directory = 200 + ok:false + human reason (no inspection has run — not a
   * server error, the same degraded style as scan-report); a resolver failure
   * = 200 + ok:false + the named error (explicit degradation, never a
   * fallback literal).
   */
  async function handleInspectionArchive(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'inspection-archive is a read face: GET only' })
      return
    }
    const url = new URL(req.url || '/', 'http://localhost')
    const a = anchorGuard(res, anchorOf(url))
    if (a === null) return
    try {
      const r = await resolveInspectionDir(repo)
      if (!r.ok) {
        sendJson(res, 200, { ok: false, error: r.error })
        return
      }
      const dir = r.dir
      const period = url.searchParams.get('period')
      const instance = url.searchParams.get('instance')
      if (period !== null || instance !== null) {
        if (period === null || instance === null) {
          sendJson(res, 400, { ok: false, error: 'period and instance must be given together (single report fetch)' })
          return
        }
        sendJson(res, 200, { ok: true, result: await readPeriodReport(dir, instance, period) })
        return
      }
      sendJson(res, 200, { ok: true, result: await readInspectionArchive(dir) })
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
    // kind field (t260905-04): the response declares the injection kind=charter
    // (the engine-side half of the tagging; the text is composed client-side by
    // injectSessionCharter via composeCharterInjection, marker constant shared
    // from src/host/session-charter.ts CHARTER_MARKER).
    // projectName field (t261008-01): the registry-looked-up project name; the
    // client uses it for the human-readable title line 1 of the injection (the
    // platform session title takes the first line). Lookup miss already
    // degrades to name=key inside this handler.
    sendJson(res, 200, { ok: true, project, charter, projectName, kind: 'charter', source: raw.trim() !== '' ? 'file' : 'fallback' })
  }

  /* ------------------------------ 项目并发顺序（CL-3, t261006-18） */

  /** 并发路由前缀（读脸）与写子路由（重排）。常量与客户端 fetch 逐字同源（session-charter KI-042 先例）。 */
  const CONCURRENCY_PATH = '/sandbar-workbench/api/wf/concurrency'
  const CONCURRENCY_REORDER_PATH = '/sandbar-workbench/api/wf/concurrency/reorder'

  /**
   * GET  ${CONCURRENCY_PATH}?project=<key> → ticket.py {"op":"concurrency","project"}
   *   （engine concurrency.read_state 的薄壳投影：limit/holders/queue 位次。面板只读账，
   *   不自己算队列——规则 8）。
   * POST ${CONCURRENCY_REORDER_PATH} {project, order:[ids]} → 同一 op 附 order 键，
   *   引擎侧 reorder() 写人工顺序后回读同脸。host 不持有任何本地顺序状态。
   *
   * 写脸已接（t261009-03）：ticket.py 的 op=concurrency 认 order 键（引擎
   * concurrency.reorder 唯一实现：置换校验/锁内写/具名拒收），POST 的新序经
   * read_state 同脸回读，比对自然通过。比对不一致分支保留为异常防线（引擎说
   * ok 却回执序与请求序不同）——具名 409 拒收、文案中性不臆断成因，绝不静默
   * 成功假装已重排；引擎自己的置换拒收走 ok:false → 502 透传原文。
   *
   * 故障面（runAdminCli 链既有纪律全沿用，不另造）：CLI 结构化失败 {ok:false,error}
   * → 具名 502 透传（声明缺席/畸形的规则 9 具名拒收原样上抛）；spawn 超时/非零退出/
   * 空 stdout → runAdminCli 抛错 → 502；子进程回收由 execFile timeout 兜底（有界）。
   */
  async function handleConcurrency(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    if (req.method === 'GET') {
      const project = (url.searchParams.get('project') ?? '').trim()
      if (project === '') {
        sendJson(res, 400, { ok: false, error: 'missing project query: ' + CONCURRENCY_PATH + '?project=<key>' })
        return
      }
      try {
        const r = await callTool('ticket', { op: 'concurrency', project })
        if (r?.ok !== true) {
          sendJson(res, 502, { ok: false, error: String(r?.error ?? 'concurrency read face failed'), kind: r?.kind })
          return
        }
        sendJson(res, 200, { ok: true, result: r.result })
      } catch (err) {
        sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
      }
      return
    }
    if (req.method === 'POST') {
      if (url.pathname !== CONCURRENCY_REORDER_PATH) {
        sendJson(res, 404, { ok: false, error: '路径不合法：' + CONCURRENCY_REORDER_PATH })
        return
      }
      let body: any
      try {
        body = await readJsonBody(req)
      } catch (err) {
        sendJson(res, 400, { ok: false, error: String(err instanceof Error ? err.message : err) })
        return
      }
      const project = String(body?.project ?? '').trim()
      const order = Array.isArray(body?.order) ? body.order.map((t: unknown) => String(t)) : null
      if (project === '' || order === null) {
        sendJson(res, 400, { ok: false, error: 'reorder 需要 {project, order:[ticket ids]}' })
        return
      }
      try {
        const r = await callTool('ticket', { op: 'concurrency', project, order })
        if (r?.ok !== true) {
          sendJson(res, 502, { ok: false, error: String(r?.error ?? 'concurrency reorder failed'), kind: r?.kind })
          return
        }
        const q = (r.result as any)?.queue
        const got = Array.isArray(q) ? q.map((e: any) => String(e?.ticket ?? e)) : null
        if (got === null || JSON.stringify(got) !== JSON.stringify(order)) {
          sendJson(res, 409, {
            ok: false,
            // Neutral named text (review t261009-03 conditional 1): this branch
            // only fires when the engine said ok:true but the returned queue
            // differs from the requested order — an anomaly whose cause is not
            // known here, so the text must not assert one. Never fake success.
            error: 'concurrency reorder not applied: the engine\'s returned queue '
              + 'differs from the requested order — refusing to fake success',
            queue: got ?? undefined,
          })
          return
        }
        sendJson(res, 200, { ok: true, result: r.result })
      } catch (err) {
        sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
      }
      return
    }
    sendJson(res, 405, { ok: false, error: 'concurrency 只支持 GET（读脸）/ POST reorder（写顺序）' })
  }

  /* ------------------------------ 项目会话账册（sessions.json，UI-5 t261005-06） */

  /** project query whitelist check (same discipline as findProject: an unknown key / registry fault -> 400). */
  function sessionsProjectOf(req: IncomingMessage): { project: string } | { error: [number, string] } {
    const url = new URL(req.url ?? '/', 'http://x')
    const project = (url.searchParams.get('project') ?? '').trim()
    if (project === '') return { error: [400, 'missing project query: /sandbar-workbench/api/wf/sessions?project=<key>'] }
    try {
      if (!findProject(project)) return { error: [400, `unknown project key: '${project}' (not in the projects registry)`] }
    } catch (err) {
      return { error: [400, String(err instanceof Error ? err.message : err)] }
    }
    return { project }
  }

  /**
   * GET /sandbar-workbench/api/wf/sessions?project=<key>: read sessions.json
   * (a missing/bad file -> an empty ledger, never a crash) + project the
   * executor sessions declared in executor-grants.json (handle='executor',
   * derived display, never persisted - the grants file stays the single source
   * of who-is-executor). The reply carries file (absolute path, the acceptance
   * read-back anchor) and mtime (plan R5 freshness contract).
   */
  async function handleSessionsGet(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const p = sessionsProjectOf(req)
    if ('error' in p) {
      sendJson(res, p.error[0], { ok: false, error: p.error[1] })
      return
    }
    try {
      const read = readLedgerFile(p.project)
      const entries = mergeLedgerFileWithExecutors(read.entries, readExecutorSessionIds(p.project))
      sendJson(res, 200, { ok: true, project: p.project, file: read.file, mtime: read.mtime, entries })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * POST /sandbar-workbench/api/wf/sessions?project=<key>: register/update
   * one session (id-union merge + atomic write). KI-193 stance (declared,
   * never silent): a plugin write endpoint inherits the KI-193 exposure; the
   * surface is caller-self-reported - a write carrying the executor identity
   * is refused by declaration (403); this is declared behavior, not auth (the
   * injection test guards it). The recorded writer is echoed as received and
   * the reply names by_self_reported=true - never a silent "source = host"
   * attribution.
   */
  async function handleSessionsPost(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const p = sessionsProjectOf(req)
    if ('error' in p) {
      sendJson(res, p.error[0], { ok: false, error: p.error[1] })
      return
    }
    let body: unknown
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `request body is not valid JSON: ${String(err instanceof Error ? err.message : err)}` })
      return
    }
    // Shape validation (including the executor-surface declared refusal) is single-pointed in validateSessionEntry.
    const [entry, entryErr] = validateSessionEntry((body as { entry?: unknown } | null)?.entry ?? body)
    if (entryErr !== null) {
      const refused = (body as { surface?: unknown } | null)?.surface === 'executor-session'
      sendJson(res, refused ? 403 : 400, { ok: false, error: entryErr })
      return
    }
    try {
      const result = saveSessionEntry(p.project, entry)
      sendJson(res, 200, {
        ok: true,
        project: p.project,
        file: result.file,
        handle: result.handle,
        entries: result.entries,
        by_self_reported: true,
      })
    } catch (err) {
      if (err instanceof SessionLedgerError) {
        sendJson(res, err.status, { ok: false, error: err.message })
        return
      }
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  async function handleSessionsRoute(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method === 'GET') return handleSessionsGet(req, res)
    if (req.method === 'POST') return handleSessionsPost(req, res)
    sendJson(res, 405, { ok: false, error: 'sessions route supports GET (read) and POST (register) only' })
  }

  /** Executor projection (a route-side thin shell over the shared pure function; executors first). */
  function mergeLedgerFileWithExecutors(entries: ReturnType<typeof readLedgerFile>['entries'], executorIds: string[]) {
    return mergeExecutorSessions(entries, executorIds)
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


  /* ---------------------------------- 立项单只读 API（epic-linkage Tier 2；t261019-12 docs/epics 面孔） */

  // ---- front-matter 读取（自含于本文件：epics.ts 的表格刮取/状态改写面已随
  // 「retired 布尔是唯一状态」退役；正则口径与 shared.parse_epic_front_matter 互指，
  // 改一边必须同步另一边）。

  /** 立项代号形状白名单：镜像 shared.py EPIC_CODE_RE（互指，勿单边漂移）。本文件自含
   *  定义——旧的 src/host/epics.ts 再出口随状态改写面退役，不再 import（t261019-12）。 */
  const EPIC_CODE_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

  /** 立项档目录：env SANDBAR_EPICS_DIR 优先（shared._epics_dir 同款先例），缺省 <项目根>/docs/epics。
   *  t261019-12 硬切换：不再回落 notes/epics（双真源=本票要杀的漂移）。 */
  function epicDocsDir(anchor: ProjectAnchor): string {
    const env = anchorEnv(anchor, 'SANDBAR_EPICS_DIR')
    return env ?? join(anchor.root, 'docs', 'epics')
  }

  /** 解析一份 front-matter 块（--- ... --- 之间的 key: value 行）。块缺失/不闭合/行畸形
   *  → throw（调用方决定降级口径；enforcement 面按 fail-closed 处置）。 */
  function parseEpicFrontMatter(markdown: string): Record<string, string> {
    if (!markdown.startsWith('---')) throw new Error("no front-matter block (file must start with '---')")
    const lines = markdown.split('\n')
    let end = -1
    for (let i = 1; i < lines.length; i++) {
      if (lines[i].trim() === '---') { end = i; break }
    }
    if (end === -1) throw new Error("unterminated front-matter block (no closing '---')")
    const fields: Record<string, string> = {}
    for (let i = 1; i < end; i++) {
      const line = lines[i].trim()
      if (line === '') continue
      const idx = line.indexOf(':')
      if (idx <= 0) throw new Error(`malformed front-matter line (no 'key: value'): ${JSON.stringify(line)}`)
      fields[line.slice(0, idx).trim().toLowerCase()] = line.slice(idx + 1).trim()
    }
    return fields
  }

  interface EpicDocMeta {
    code: string
    retired: boolean
    summary: string
    started: string
    /** front-matter 缺失/畸形时的具名缺陷（fail-closed：defect 行一律按 retired 呈现）。 */
    defect?: string
  }

  /** 单档元信息：retired 严格取字面 'false'/'true'，其余（缺 key/其他值/解析失败）一律
   *  retired:true + defect（与 shared.validate_epic_code 的 fail-closed 同一口径）。 */
  function epicDocMeta(code: string, markdown: string): EpicDocMeta {
    let fields: Record<string, string>
    try {
      fields = parseEpicFrontMatter(markdown)
    } catch (err) {
      return { code, retired: true, summary: '', started: '', defect: String(err instanceof Error ? err.message : err) }
    }
    const retired = fields.retired ?? ''
    const defect = retired !== 'false' && retired !== 'true'
      ? `front-matter 'retired' must be exactly 'false' or 'true' (found: ${retired === '' ? '(missing)' : JSON.stringify(retired)})`
      : undefined
    return {
      code,
      retired: retired !== 'false',
      summary: fields.summary ?? '',
      started: fields.started ?? '',
      defect,
    }
  }

  /** 列 docs/epics/*.md（只读）。目录不存在 → throw 具名错误（硬切换：绝不空表冒充「无立项」）；
   *  单档读失败跳过不拖垮整列（与旧 listEpics 同款容错），但该档缺席在 enforcement 面
   *  （shared.validate_epic_code）仍 fail-closed。 */
  async function listEpicDocs(dir: string): Promise<EpicDocMeta[]> {
    let names: string[]
    try {
      names = await readdir(dir)
    } catch {
      throw new Error(`epic registry directory not found: ${dir} (docs/epics — the store moved from notes/epics in t261019-12; hard cut, no fallback)`)
    }
    const out: EpicDocMeta[] = []
    for (const name of names.sort()) {
      if (!name.endsWith('.md')) continue
      const code = name.slice(0, -'.md'.length)
      if (!EPIC_CODE_RE.test(code)) continue
      try {
        out.push(epicDocMeta(code, await readFile(join(dir, name), 'utf8')))
      } catch { /* 单文件读失败跳过 */ }
    }
    return out
  }

  /** 读单份立项 front-matter 元信息。形状/路径防穿/不存在 404（人话附现有代号清单，
   *  shared.validate_epic_code 同风格）。 */
  async function readEpicDoc(dir: string, code: string):
    Promise<{ ok: true; meta: EpicDocMeta; path: string } | { ok: false; status: number; error: string }> {
    if (!EPIC_CODE_RE.test(code)) {
      return {
        ok: false, status: 400,
        error: `epic code shape is illegal: '${code}' (required ^[a-z0-9][a-z0-9-]{0,40}$, lowercase letters/digits/hyphens)`,
      }
    }
    const root = resolve(dir)
    const abs = resolve(root, code + '.md')
    if (abs !== root && !abs.startsWith(root + sep)) {
      return { ok: false, status: 400, error: `path escapes the epic registry (refused): '${code}'` }
    }
    let markdown: string
    try {
      markdown = await readFile(abs, 'utf8')
    } catch (err: any) {
      if (err?.code === 'ENOENT') {
        let existing: string[] = []
        try {
          existing = (await readdir(root))
            .filter((f) => f.endsWith('.md') && EPIC_CODE_RE.test(f.slice(0, -'.md'.length)))
            .map((f) => f.slice(0, -'.md'.length))
            .sort()
        } catch { /* 目录不可读则不给清单 */ }
        return {
          ok: false, status: 404,
          error: `epic code not found: '${code}' (docs/epics/ has no such file). Existing codes: ${existing.join(', ') || '(directory empty or missing)'}`,
        }
      }
      return { ok: false, status: 500, error: `epic document read failed: ${String(err?.message ?? err)}` }
    }
    return { ok: true, meta: epicDocMeta(code, markdown), path: `docs/epics/${code}.md` }
  }

  /**
   * 立项单列表：列 docs/epics/*.md（t261019-12 front-matter 面孔）。目录不存在 → 具名 500
   * （硬切换；KI-057：epics 目录随 ?project= 项目根走）。
   */
  async function handleEpics(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'epic list supports GET only' })
      return
    }
    const anchor = anchorGuard(res, anchorOf(new URL(req.url ?? '/', 'http://x')))
    if (anchor === null) return
    try {
      const epics = await listEpicDocs(epicDocsDir(anchor))
      sendJson(res, 200, { ok: true, result: { count: epics.length, epics }, resolved: resolvedMark(anchor) })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 立项单工单聚合（只读）：复用 ticket list --epic 通路（handleTickets 同款 callTool）。
   *  前置与详情路由同口径：形状 400 / 不存在 404（拦住后 ticket.py 侧强校验不会再以
   *  引擎错误冒出）；retired 立项照常可查（读历史，不是开新票）；其后 callTool 抛错或
   *  回 ok:false 一律降级 {degraded:true, reason}（reason 透传底层 error 原文），不 502。 */
  async function handleEpicTickets(res: ServerResponse, code: string, anchor: OkAnchor): Promise<void> {
    const chk = await readEpicDoc(epicDocsDir(anchor), code)
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

  /** 立项单详情/工单聚合：prefix 路由，<code> 或 <code>/tickets（只读 GET）。
   *  （t261019-12 退役注记：POST <code>/close 与 <code>/status 两支状态改写路由随
   *   「retired 布尔是唯一状态」删除——retiring = 在 git 里改 docs/epics/<code>.md；
   *   原「下一步建议」hint 两支随 suggest_next 退役（t260910-14）。） */
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
    // 状态改写路由已删（t261019-12）：close/status 一律 410 具名指路（不是静默 404——
    // 旧调用方要能一眼看出「这入口是随 retired 布尔退役的，改法=编辑 docs/epics 档」）。
    if (parts.length === 2 && (parts[1] === 'close' || parts[1] === 'status')) {
      sendJson(res, 410, {
        ok: false,
        error: `POST /epics/<code>/${parts[1]} was removed in t261019-12: 'retired' is the only epic state now — retire an epic by editing docs/epics/${parts[0]}.md in git`,
      })
      return
    }
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'epic routes support GET only (read-only)' })
      return
    }
    if (parts.length === 1) {
      const r = await readEpicDoc(epicDocsDir(anchor), parts[0])
      if (!r.ok) {
        sendJson(res, r.status, { ok: false, error: r.error })
        return
      }
      sendJson(res, 200, {
        ok: true,
        result: {
          code: r.meta.code,
          path: r.path,
          retired: r.meta.retired,
          summary: r.meta.summary,
          started: r.meta.started,
          ...(r.meta.defect !== undefined ? { defect: r.meta.defect } : {}),
        },
      })
      return
    }
    if (parts.length === 2 && parts[1] === 'tickets') {
      await handleEpicTickets(res, parts[0], anchor)
      return
    }
    sendJson(res, 404, { ok: false, error: '路径不合法：/sandbar-workbench/api/epics/<code>[/tickets]' })
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
      const { dirs, reason } = resolveAgentBaseDirs(repo, id, t, projectRootsFor(t.project))
      const result = await listAgentLogs(dirs) // t261008-23：候选序探测，result.base=实际探测目录
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
          result: {
            exists: false, events: [], truncated: false, ws_root: ref.wsRoot ?? '',
            reason: ref.reason ?? '会话文件未定位',
            // t260917-05 S3：发现集空但目录有未入统计的会话样文件 → 清单透传（UI 可辨）
            ...(ref.suspectFiles?.length ? { suspect_files: ref.suspectFiles } : {}),
          },
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
            // t260917-05 S3：发现集空但目录有未入统计的会话样文件 → 清单透传（UI 可辨）
            ...(ref.suspectFiles?.length ? { suspectFiles: ref.suspectFiles } : {}),
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
        // 巡检板面（t260915-08）：引擎 ticket-list{kind:inspection} 薄壳，无 project 维度。
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/inspection/tickets', handler: handleInspectionTickets }),
        ws.register({ kind: 'prefix', path: TICKETS_PREFIX, handler: handleTicketRoute }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/workflows', handler: handleWorkflows }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/book', handler: handleBook }),
        // 「文档」视图两路由（t260905-06；KI-070 起按 ?project= 项目根解析）：目录树 + 按篇正文。
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/docs/tree', handler: handleDocsTree }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/docs/doc', handler: handleDocsDoc }),
        // KI-227（t261008-29）：worker 陈旧度对比面（只读，observe-only）。
        // （t261008-18 已撤 temporal-health/workers/scan-report 三路由——main 侧删除
        // 语义保留，本路由不依赖其探针助手。）
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/worker-staleness', handler: handleWorkerStaleness }),
        // Inspection period archive read side (t261006-15): period list + single
        // period+instance report (read-only, project root via anchorOf).
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/inspection-archive', handler: handleInspectionArchive }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/build-info', handler: handleBuildInfo }),
        // 会话开局 charter 读侧（t260904-07）：路径同源常量（src/host/session-charter.ts
        // SESSION_CHARTER_PATH），客户端 fetch URL 与此处注册逐字同源，防 KI-042 漂移。
        ws.register({ kind: 'exact', path: SESSION_CHARTER_PATH, handler: handleSessionCharter }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/metrics', handler: handleMetrics }),
        ws.register({ kind: 'exact', path: EPICS_PREFIX, handler: handleEpics }),
        ws.register({ kind: 'prefix', path: EPICS_PREFIX, handler: handleEpicRoute }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/workspaces', handler: handleWorkspaceList }),
        // Per-project session ledger (sessions.json, UI-5 t261005-06): GET read
        // (executor projection included) + POST register (id-union merge + atomic
        // write; KI-193 stance in the handleSessionsPost doc).
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/sessions', handler: handleSessionsRoute }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects', handler: handleProjects }),
        // 票③面D：项目生命周期三路由（detail 票计数读面 / add·remove 写面，薄壳 spawn 安装器 CLI）。
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects/detail', handler: handleProjectDetail }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects/add', handler: handleProjectAdd }),
        ws.register({ kind: 'exact', path: '/sandbar-workbench/api/wf/projects/remove', handler: handleProjectRemove }),
        // CL-3（t261006-18）：并发读脸 GET + 重排写子路由 POST（exact 在前缀 TICKETS 之外独立挂）。
        ws.register({ kind: 'exact', path: CONCURRENCY_PATH, handler: handleConcurrency }),
        ws.register({ kind: 'exact', path: CONCURRENCY_REORDER_PATH, handler: handleConcurrency }),
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

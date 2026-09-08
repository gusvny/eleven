/**
 * epic-next.ts —— 立项单「继续执行」按钮的宿主半（t260827-02，epic-linkage 延伸）。
 *
 * 链路：POST /api/epics/<code>/suggest-next 启动一个异步建议 job —— spawn 一次性
 * headless integration agent（dsh --profile sandbar-headless --patch roles/integration.yml），
 * agent 只读分析并把建议写进 <jobDir>/result.json；前端轮询
 * GET /api/epics/<code>/suggest-next/<jobId> 拿结果，预填进既有「新建工单」弹层，
 * 人类确认后才走 POST /wf/tickets 真正创建——agent 永远不直接开工单。
 *
 * 与 python 侧真源互指（改一边必须同步另一边）：
 *   - spawn 口径复刻 server/engine/agent_activities.py：DSH_HOME=jobDir/.dsh
 *     + 拷 sandbar-headless profile / .credentials.yaml / settings.yaml；模型路由读
 *     model-routes.yaml 钉 agent-default-model（一次性 patch + settings 用户层双写，
 *     260826 事故教训：只发 patch 会被 settings 用户层盖掉）；SANDBAR_AGENT_CMD env
 *     覆盖（shlex 白空切分）；SANDBAR_EPIC_NEXT_STUB=1|ok/invalid_json/never_write
 *     自测桩（仿 SANDBAR_AGENT_STUB）。
 *   - 进程生命周期同样复刻 agent_activities.py 的 finally-terminate 口径（那边是
 *     「轮询到结果文件即 terminate」，见该文件 agent activity 的 finally 块）：本模块
 *     所有终态（done/校验失败/非法 JSON/超时）统一 reapAgentProc 回收 agent 进程——
 *     260828 实测本模块复刻时丢了这半，done/校验失败路径各泄露一个 dsh 进程。
 *   - 结果文件判读分两类（260828 事故修复）：读不到=还没写出（继续等）；读到但
 *     parse 不过=文件已产出但不是合法 JSON（LLM 典型非法转义 \- 等）→ fail-fast：
 *     进程已退出或文件连续两轮轮询未变即置 failed，reason 明说「不是合法 JSON」并附
 *     parse 错误摘要，不再干等超时、不再误说「未产出」。
 *   - model-routes.yaml 只读消费：格式自带「YAML 最小子集」约束（key: value 标量 +
 *     2 空格缩进映射、裸 token），本文件 parseMiniYaml 按此解析，不引 YAML 依赖。
 *
 * 防幻觉闸：建议的 workflow 必须在启动时抓取的模板清单内、title 非空，否则 job 置
 * failed 不透给 UI（validateSuggestion 单点）。并发：同一 code 同时只允许一个
 * running job（重复点击复用进行中的 job，不重复起 agent）。job 目录每 code 保留
 * 最近 5 份（含 prompt.md/result.json/agent.log/.dsh 会话，可审计）。
 *
 * 降级契约：agent 崩/超时/输出不合规 → job state=failed + 人话 reason，路由层 200
 * 透传，前端黄条降级并照常打开空白新建工单弹层——建议链路永不阻塞手动新建。
 */

import { spawn, type ChildProcess } from 'node:child_process'
import * as nodeCrypto from 'node:crypto'
import { closeSync, existsSync, openSync } from 'node:fs'
import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join, resolve, sep } from 'node:path'
import { EPIC_CODE_RE } from './epics.ts'

// node-shims.d.ts 的 'node:crypto' 最小面只声明了 randomUUID（本文件写集外，不扩它）——
// createHash 走命名空间 + 显式 any 面（运行时 node ≥18 一直有）。
const { randomUUID, createHash } = nodeCrypto as unknown as {
  randomUUID: () => string
  createHash: (alg: string) => { update(s: string): { digest(enc: 'hex'): string } }
}

/* ---------------------------------------------------------------- 常量 */

/** job 总时限默认值：超过即杀进程置 failed（integration 实跑一般 1~5 分钟，10 分钟封顶）。 */
export const JOB_TIMEOUT_MS = 10 * 60_000
/** job 总时限（env SANDBAR_EPIC_NEXT_TIMEOUT_MS 可覆盖，自测用；非正数回退默认值）。 */
export function jobTimeoutMs(): number {
  const v = Number(process.env.SANDBAR_EPIC_NEXT_TIMEOUT_MS)
  return Number.isFinite(v) && v > 0 ? v : JOB_TIMEOUT_MS
}
/** 时限人话（<60s 写秒，避免「等待超过 0 分钟」）。 */
function formatTimeout(ms: number): string {
  return ms >= 60_000 ? `${Math.floor(ms / 60_000)} 分钟` : `${Math.round(ms / 1000)} 秒`
}
/** 每个立项代号保留的 job 目录份数（防膨胀；新 job 启动时清理更旧的）。 */
export const KEEP_PER_CODE = 5

/** integration 建议形状（result.json 的 ok 形态；client epics-model.ts EpicNextSuggestion 互指）。
 *  字段全部可选以容纳 done 形态（{status:'done',summary}，t260828-08）；消费侧一律
 *  String(x ?? '') 容错读。 */
export interface EpicNextSuggestion {
  workflow?: string
  title?: string
  body?: string
  rationale?: string
  /** t260829-07 写集生命周期：建议的预计改动文件清单（仓库内相对路径）。
   *  缺失/全非法 → 置空数组（validateSuggestion 单点保证），不阻塞建议主价值，
   *  人可在新建工单弹层补。消费侧 epics-model.ts 同名字段互指。 */
  write_set?: string[]
  /** 三态口径扩展（python 侧 shared.py build_suggest_next_prompt 契约互指）：
   *  'ok'=建议下一单（缺省视为 ok，兼容旧缓存/旧 job 结果）；'done'=立项可完结。 */
  status?: 'ok' | 'done'
  /** status='done' 时的人话说明（立项目标已达成，给「确认结项」卡片展示）。 */
  summary?: string
}

/* ---------------------------------------------------------------- 预跑缓存（t260828-08） */

/** 预跑缓存目录：<repo>/.suyou/epic-next/<code>/pre.json（python 侧 shared.py
 *  epic_next_precache_path 互指；与 <jobId> 形状的 job 目录共存——cleanupOldJobs 的
 *  形状正则不匹配 <code>/ 目录，不会被清理）。 */
export function resolvePrecacheDir(repo: string): string {
  return join(repo, '.suyou', 'epic-next')
}

/**
 * state_key 现算（python 侧 shared.py epic_state_key 口径互指，改一边必须同步另一边）：
 * sorted "<id>:closed|open" 行 "\n" 拼接后 sha1 hex。currentTicketId 指定的工单强制按
 * closed 计入——预跑发生在 merge 落账前（本票尚 open），host 点击时本票已 closed，
 * 两侧口径对齐否则缓存永不命中（t260828-08 review 第 2 条）。
 */
export function stateKeyFromRows(
  rows: { id: string; closed: boolean }[], currentTicketId: string,
): string {
  const lines = rows
    .filter((r) => r.id !== '')
    .map((r) => `${r.id}:${r.closed || r.id === currentTicketId ? 'closed' : 'open'}`)
    .sort()
  return createHash('sha1').update(lines.join('\n')).digest('hex')
}

/**
 * 读预跑缓存（坏缓存一律当未命中返回 null，不透给 UI）：
 * pre.json 可解析 + epic 与 code 一致 + state_key 与现算一致 + suggestion 校验过
 * （ok 形态：workflow 在模板白名单内且 title 非空；done 形态：summary 非空）。
 */
export async function readPrecache(
  dir: string, code: string, currentStateKey: string, workflowIds: string[],
): Promise<EpicNextSuggestion | null> {
  if (!EPIC_CODE_RE.test(code)) return null
  let raw: any
  try {
    raw = JSON.parse(await readFile(join(dir, code, 'pre.json'), 'utf8'))
  } catch {
    return null
  }
  if (raw === null || typeof raw !== 'object') return null
  if (String(raw.epic ?? '') !== code) return null
  if (String(raw.state_key ?? '') !== currentStateKey || currentStateKey === '') return null
  const s = raw.suggestion
  if (s === null || typeof s !== 'object') return null
  const st = String(s.status ?? 'ok')
  if (st === 'done') {
    const summary = String(s.summary ?? '').trim()
    return summary === '' ? null : { status: 'done', summary }
  }
  if (st !== 'ok') return null
  const workflow = String(s.workflow ?? '').trim()
  const title = String(s.title ?? '').trim()
  if (workflow === '' || !workflowIds.includes(workflow) || title === '') return null
  return {
    status: 'ok', workflow, title,
    body: String(s.body ?? ''), rationale: String(s.rationale ?? ''),
  }
}

export type EpicNextState = 'running' | 'done' | 'failed'

/* ---------------------------------------------------------------- 下一步建议可见性（t260829-02） */

/** 轻量缓存命中探测（立项列表徽标「下一步已备」用）：只 stat pre.json 存在性，
 *  不解析不验 state_key——列表 N 个代号逐个算 state_key 太重，准态由详情响应的
 *  nextHint 承担（node.ts handleEpicRoute）。坏缓存也报 true：详情卡 readPrecache
 *  会当未命中，徽标与卡片短暂不一致是接受的性能取舍（create_plan 方案口径）。 */
export async function precacheExists(dir: string, code: string): Promise<boolean> {
  if (!EPIC_CODE_RE.test(code)) return false
  try {
    return !(await stat(join(dir, code, 'pre.json'))).isDirectory()
  } catch {
    return false
  }
}

/** 详情态「下一步建议」投影（readPrecache 结果的展示子集；前端 epics.tsx 消费）。
 *  全部 string 化（宿主侧收口容错，前端不再逐字段 String()）。 */
export interface EpicNextHint {
  status: 'ok' | 'done'
  workflow: string
  title: string
  body: string
  rationale: string
  summary: string
}

/** 读缓存并投影成 hint（复用 readPrecache 的全部校验：state_key 对齐 + 模板白名单
 *  + 坏缓存一律 null，不新增第二套判定，防漂移）。 */
export async function readPrecacheHint(
  dir: string, code: string, currentStateKey: string, workflowIds: string[],
): Promise<EpicNextHint | null> {
  const s = await readPrecache(dir, code, currentStateKey, workflowIds)
  if (!s) return null
  return {
    // status 在 readPrecache 返回类型里可选（缺省视作 ok），投影收口成必填二值
    status: s.status === 'done' ? 'done' : 'ok',
    workflow: String(s.workflow ?? ''),
    title: String(s.title ?? ''),
    body: String(s.body ?? ''),
    rationale: String(s.rationale ?? ''),
    summary: String(s.summary ?? ''),
  }
}

export type EpicHintDismissResult =
  | { ok: true; code: string }
  | { ok: false; status: number; error: string }

/** [忽略] 动作（t260829-02）：删 .suyou/epic-next/<code>/pre.json。防穿同
 *  readEpicMarkdown 双保险（EPIC_CODE_RE 白名单 + resolve 落点断言）；删除前备份
 *  /tmp/epic-next-backup/（closeEpic 同款先例，误删可手工找回）；文件不存在也回
 *  ok（幂等——重复点击 [忽略] 不报错）。 */
export async function dismissPrecache(dir: string, code: string): Promise<EpicHintDismissResult> {
  if (!EPIC_CODE_RE.test(code)) {
    return {
      ok: false, status: 400,
      error: `立项代号形状不合法：'${code}'（要求 ^[a-z0-9][a-z0-9-]{0,40}$）`,
    }
  }
  const root = resolve(dir)
  const abs = resolve(root, code, 'pre.json')
  if (!abs.startsWith(root + sep)) {
    return { ok: false, status: 400, error: `路径越界（拒绝删除）：'${code}'` }
  }
  let content: string
  try {
    content = await readFile(abs, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') return { ok: true, code } // 幂等：本来就没有
    return { ok: false, status: 500, error: `预跑缓存读取失败：${String(err?.message ?? err)}` }
  }
  const backupDir = '/tmp/epic-next-backup'
  await mkdir(backupDir, { recursive: true })
  await writeFile(join(backupDir, `${code}-${Date.now()}.json`), content, 'utf8')
  await rm(abs)
  return { ok: true, code }
}

export interface EpicNextJob {
  jobId: string
  code: string
  state: EpicNextState
  startedAt: number
  /** job 目录（<epicNextRoot>/<jobId>），prompt.md/result.json/agent.log 都在这。 */
  dir: string
  /** agent 交付锚点（绝对路径，已内联进 prompt）。 */
  resultPath: string
  /** 启动时抓取的模板 id 清单（validateSuggestion 白名单基准）。 */
  workflowIds: string[]
  suggestion?: EpicNextSuggestion
  reason?: string
  proc?: ChildProcess
  /** 结果文件指纹（invalid-JSON fail-fast 用：连续两轮轮询 mtime+size 未变即判定已写定）。 */
  lastResultMtimeMs?: number
  lastResultSize?: number
}

/** 内存 job 注册表：dsh webServer 长驻进程内有效；重启即丢（前端 404 后重新点击即可，不存盘）。 */
const JOBS = new Map<string, EpicNextJob>()

/** job 根目录：env SANDBAR_EPIC_NEXT_DIR 优先（自测指向临时目录），缺省 <repo>/.suyou/epic-next（gitignored）。 */
export function resolveEpicNextDir(repo: string): string {
  return process.env.SANDBAR_EPIC_NEXT_DIR ?? join(repo, '.suyou', 'epic-next')
}

/* ---------------------------------------------------------------- 纯函数（smoke 直测） */

/**
 * model-routes.yaml 迷你解析器（只支持该文件自我约束的最小子集：顶层/嵌套映射 +
 * `key: value` 裸 token 标量 + 2 空格缩进；注释整行或行尾 # 起）。列表/引号/多行
 * 标量不在表内——该文件头注明说「任何 30 行 stdlib 解析器也能读」，本函数即此口径。
 */
export function parseMiniYaml(text: string): Record<string, any> {
  const root: Record<string, any> = {}
  const stack: { indent: number; obj: Record<string, any> }[] = [{ indent: -1, obj: root }]
  for (const rawLine of text.split('\n')) {
    const line = rawLine.replace(/#.*$/, '')
    if (line.trim() === '') continue
    const indent = line.length - line.trimStart().length
    const m = /^([A-Za-z0-9_-]+):(?:\s+(\S+))?\s*$/.exec(line.trim())
    if (!m) continue // 不在最小子集内的行跳过，不抛错
    const [, key, value] = m
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop()
    const parent = stack[stack.length - 1].obj
    if (value === undefined) {
      const child: Record<string, any> = {}
      parent[key] = child
      stack.push({ indent, obj: child })
    } else {
      parent[key] = value
    }
  }
  return root
}

/**
 * 角色级模型路由（复刻 shared.py model_route_for 的 role → default 两级；
 * 本模块只服务 integration 一个角色，无分工 kind 维度）。查不到返回 null
 * （不钉路由，agent 用 profile 默认模型——不硬失败）。
 */
export function modelRouteFromYaml(text: string, role: string): { provider: string; model: string } | null {
  const table = parseMiniYaml(text)
  const cands = [(table.roles ?? {})[role], table.default]
  for (const cand of cands) {
    if (cand && typeof cand.provider === 'string' && typeof cand.model === 'string') {
      return { provider: cand.provider, model: cand.model }
    }
  }
  return null
}

export interface SuggestPromptInput {
  code: string
  epicTitle: string
  epicMarkdown: string
  /** 关联工单实时汇总（JSON 文本或人话降级说明）。 */
  ticketsSummary: string
  workflows: { id: string; name: string }[]
  /** 结果文件绝对路径（内联进 prompt，agent 的唯一写点）。 */
  resultPath: string
}

/** 派活指令组装（纯函数，零 IO）：全部上下文内联，agent 不依赖读仓库也能完成任务。 */
export function buildSuggestPrompt(input: SuggestPromptInput): string {
  const wfLines = input.workflows.map(w => `- ${w.id}：${w.name}`).join('\n')
  return `【任务】你是溯游（suyou）项目的 integration 角色。请基于下面的立项单全文与关联工单现状，决定这个立项下一步最应该开的一张工单。

【硬性要求】
1. 这是只读分析任务：除最后的结果文件外，不创建、不修改任何文件，不做任何 git 写操作。
2. 建议的工单模板必须来自下方「可用工单模板」清单，原样填 id，不得发明。
3. 结论写入结果文件：${input.resultPath}
   UTF-8 JSON，形状：
   {"status":"ok","workflow":"<模板id>","title":"<工单标题，一句话说清做什么>","body":"<工单正文：背景、要做什么、验收要点>","rationale":"<给人类看的一句话理由>","write_set":["<预计改动文件，仓库内相对路径，一条一个>"]}
   write_set 是给这张工单的写集护栏预填（人在弹层可增删），按你预计的实现改动列全；
   判断不准时宁多勿漏，绝对路径与仓库外路径无效。
   如果你判断本立项已无事可做（目标全达成），写 {"status":"failed","reason":"<原因>"}。
4. 写完结果文件即结束，不要等待人类输入，不要开任何工单。

【所属立项】${input.code}（新工单的代号由界面带入，正文无需声明绑定方式）

【立项单全文】
${input.epicMarkdown}

【关联工单实时状态】
${input.ticketsSummary}

【可用工单模板】
${wfLines === '' ? '（清单为空）' : wfLines}
`
}

/**
 * 写集条目合法性（纯函数，t260829-07；smoke 直测，client epics-model.ts 同构互指）：
 * 仓库内相对路径——非字符串/空串/绝对路径/含 '..'/反斜杠/Windows 盘符一律非法。
 */
export function validWriteSetEntry(p: unknown): boolean {
  if (typeof p !== 'string') return false
  const s = p.trim()
  if (s === '' || s.startsWith('/') || s.startsWith('\\') || s.includes('\\')) return false
  if (s.length >= 2 && s[1] === ':' && /[a-zA-Z]/.test(s[0])) return false
  return !s.split('/').includes('..')
}

/** 建议写集清洗（纯函数）：逐条校验，非法丢弃（拒条不拒次），保序去重。 */
export function sanitizeWriteSet(raw: unknown): string[] {
  const out: string[] = []
  for (const p of (Array.isArray(raw) ? raw : [])) {
    if (!validWriteSetEntry(p)) continue
    const s = String(p).trim()
    if (!out.includes(s)) out.push(s)
  }
  return out
}

/**
 * 建议合法性校验（防幻觉闸，单点）：status=ok、workflow 在模板清单内、title 非空
 * 才放行；agent 自报 failed 时透传它的 reason。body/rationale 可空（给 ''）。
 * write_set（t260829-07）：缺失/全非法 → 置空数组不阻塞（建议主价值在工单本身）。
 */
export function validateSuggestion(raw: any, workflowIds: string[]):
  { ok: true; suggestion: EpicNextSuggestion } | { ok: false; error: string } {
  if (raw === null || typeof raw !== 'object') {
    return { ok: false, error: '结果文件不是合法 JSON 对象' }
  }
  if (String(raw.status ?? '') !== 'ok') {
    const why = String(raw.reason ?? raw.summary ?? '未说明原因')
    return { ok: false, error: `integration 判定无法给出建议：${why}` }
  }
  const workflow = String(raw.workflow ?? '').trim()
  if (!workflowIds.includes(workflow)) {
    return { ok: false, error: `建议的模板 '${workflow}' 不在可用清单内（拒收，防幻觉模板 id）` }
  }
  const title = String(raw.title ?? '').trim()
  if (title === '') {
    return { ok: false, error: '建议缺工单标题（拒收）' }
  }
  return {
    ok: true,
    suggestion: {
      workflow,
      title,
      body: String(raw.body ?? ''),
      rationale: String(raw.rationale ?? ''),
      write_set: sanitizeWriteSet(raw.write_set),
    },
  }
}

/* ---------------------------------------------------------------- job 编排 */

/** 同 code 是否有进行中的 job（重复点击复用，不重复起 agent 烧钱）。 */
export function findRunningJob(code: string): EpicNextJob | null {
  for (const j of JOBS.values()) {
    if (j.code === code && j.state === 'running') return j
  }
  return null
}

/** SANDBAR_AGENT_CMD 切分（迷你 shlex：白空分词，单/双引号成对剥除——payload 等带空格参数靠引号保真）。 */
function splitCmd(s: string): string[] {
  const out: string[] = []
  let cur = ''
  let quote = ''
  for (const ch of s) {
    if (quote !== '') {
      if (ch === quote) quote = ''
      else cur += ch
    } else if (ch === '"' || ch === "'") {
      quote = ch
    } else if (/\s/.test(ch)) {
      if (cur !== '') { out.push(cur); cur = '' }
    } else {
      cur += ch
    }
  }
  if (cur !== '') out.push(cur)
  return out
}

async function copyIfExists(src: string, dst: string): Promise<void> {
  try {
    await stat(src)
  } catch {
    return
  }
  await cp(src, dst, { recursive: true })
}

/**
 * 把路由钉进 jobDir/.dsh/settings.yaml 的 agent-default-model 用户层
 * （复刻 agent_activities._pin_default_model：settings 用户层 > cordis patch 层，
 * 只发一次性 patch 会被 GUI 默认段盖掉——260826 事故根因）。
 */
async function pinDefaultModel(dshHome: string, route: { provider: string; model: string }): Promise<void> {
  const p = join(dshHome, 'settings.yaml')
  let text: string
  try {
    text = await readFile(p, 'utf8')
  } catch {
    return
  }
  const out: string[] = []
  let skipping = false
  for (const ln of text.split('\n')) {
    if (ln.startsWith('agent-default-model:')) {
      skipping = true
      continue
    }
    if (skipping && ln !== '' && !/^[ \t#]/.test(ln)) skipping = false
    if (!skipping) out.push(ln)
  }
  out.push('agent-default-model:', `  provider: ${route.provider}`, `  model: ${route.model}`, '')
  await writeFile(p, out.join('\n'), 'utf8')
}

/** spawn 一次性 headless integration agent（口径复刻 agent_activities.py，见文件头注）。 */
async function spawnAgent(repo: string, job: EpicNextJob, prompt: string): Promise<void> {
  const dshHome = join(job.dir, '.dsh')
  await mkdir(dshHome, { recursive: true })
  const userDsh = process.env.DSH_HOME ?? join(homedir(), '.dsh')
  await copyIfExists(join(userDsh, '.credentials.yaml'), join(dshHome, '.credentials.yaml'))
  await copyIfExists(join(userDsh, 'settings.yaml'), join(dshHome, 'settings.yaml'))
  await copyIfExists(join(userDsh, 'profiles', 'suyou-headless'), join(dshHome, 'profiles', 'suyou-headless'))

  const cmd = splitCmd(process.env.SANDBAR_AGENT_CMD || 'dsh --profile suyou-headless')
  const args = cmd.slice(1)
  const rolePatch = join(repo, 'server', 'roles', 'integration.yml')
  if (existsSync(rolePatch)) args.push('--patch', rolePatch)
  // 运行时模型路由（真源=model-routes.yaml；缺失/解析失败不硬失败，用 profile 默认）
  try {
    const table = await readFile(join(repo, 'server', 'model-routes.yaml'), 'utf8')
    const route = modelRouteFromYaml(table, 'integration')
    if (route) {
      const patchPath = join(job.dir, 'model_patch.yml')
      await writeFile(patchPath,
        `# 本文件由 epic-next 建议任务每次 spawn 时生成（运行时模型路由，真源=model-routes.yaml）。
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: ${route.provider}
    model: ${route.model}
`, 'utf8')
      args.push('--patch', patchPath)
      await pinDefaultModel(dshHome, route)
    }
  } catch { /* 路由不可用则跳过，不硬失败 */ }

  args.push(prompt)
  const logFd = openSync(join(job.dir, 'agent.log'), 'a')
  const proc = spawn(cmd[0], args, {
    cwd: job.dir,
    env: { ...process.env, DSH_HOME: dshHome },
    detached: true, // t260829-07：进程组首——reapAgentProc kill(-pid) 连 agent 自 spawn 的子进程整组回收
    stdio: ['ignore', logFd, logFd],
  })
  // error 事件（如 ENOENT 命令不存在）必须挂监听，否则未捕获异常打崩宿主；
  // 具体失败由 poll 侧按「进程退出但无合规结果」判定成人话 reason。
  proc.on('error', () => {})
  // logFd 是本 job 私有 fd：进程退出即关，不留 fd 泄漏（t260829-07）
  proc.on('close', () => { try { closeSync(logFd) } catch { /* 已关 */ } })
  job.proc = proc
}

/**
 * janitor（t260829-07 泄漏修复 b 案）：poll 由前端驱动——前端停 poll 后 running
 * job 无人问津，agent 进程即使已死/超时也无人 reap（实测 4 个僵尸的最可疑路径）。
 * 宿主侧定时扫 JOBS：仍 running 的 job 一律补跑 pollSuggestJob（其内部已覆盖
 * 进程已退出 / 超时 / 结果文件已写出三类终态并统一 reap）。unref 不拖宿主退出。
 */
export function startEpicNextJanitor(): void {
  if ((JOBS as any).__janitorStarted) return
  ;(JOBS as any).__janitorStarted = true
  const t = setInterval(() => {
    for (const [id, job] of JOBS) {
      if (job.state !== 'running') continue
      pollSuggestJob(id).catch(() => { /* 单 job 失败不拖垮扫台 */ })
    }
  }, 30_000)
  t.unref()
}

/** 读 agent.log 尾部（失败 reason 的诊断附件；读不到给空串）。 */
async function logTail(dir: string): Promise<string> {
  try {
    const text = await readFile(join(dir, 'agent.log'), 'utf8')
    const tail = text.slice(-600).trim()
    return tail === '' ? '' : `；agent.log 尾部：${tail}`
  } catch {
    return ''
  }
}

/** 每 code 只留最近 KEEP_PER_CODE 份 job 目录（按名字里的 base36 时间戳排序，新的在后）。
 *  jobId 形为 `<code>-<base36时间戳>-<6位hex>`；匹配走完整形状锚定，避免 code 互为前缀
 *  时误清（如 demo-epic 的清理把 demo-epic-2 的目录算进来）。 */
async function cleanupOldJobs(root: string, code: string): Promise<void> {
  const shape = new RegExp(`^${code}-[0-9a-z]+-[0-9a-f]{6}$`)
  let names: string[]
  try {
    names = (await readdir(root, { withFileTypes: true }))
      .filter(e => e.isDirectory() && shape.test(e.name))
      .map(e => e.name)
      .sort()
  } catch {
    return
  }
  const excess = names.length - KEEP_PER_CODE
  for (let i = 0; i < excess; i++) {
    await rm(join(root, names[i]), { recursive: true, force: true }).catch(() => {})
  }
}

export interface StartSuggestInput {
  /** 引擎仓锚（保留，KI-057 t260907-11 评审裁定）：spawnAgent 的 roles/model-routes 读取——
   *  引擎侧声明属引擎语义，不随项目走。 */
  repo: string
  /** 项目主目录锚（t260907-11 KI-057）：job 目录根 resolveEpicNextDir 用它——作业簿记
   *  是项目泳道产物，epic 代号跨项目无唯一约束，锚引擎仓会撞码串项目。缺省回 repo。 */
  root?: string
  code: string
  epicTitle: string
  epicMarkdown: string
  ticketsSummary: string
  workflows: { id: string; name: string }[]
}

/**
 * 启动建议 job（调用方已做过 code 校验与 findRunningJob 复用判断；这里再兜底一次复用）。
 * SANDBAR_EPIC_NEXT_STUB 自测桩变体（不真起 agent）：
 *   1|ok          → 直接写一份合规 result.json（模板取清单第一个；清单为空写 failed）；
 *   invalid_json  → 写一份非法 JSON（复刻 LLM 典型非法转义 \- 现场），走 fail-fast 降级路径；
 *   never_write   → 不写文件，陪 SANDBAR_EPIC_NEXT_TIMEOUT_MS 覆盖走超时降级路径。
 * stub 模式统一挂一个哑长驻进程到 job.proc（unref，不拖宿主退出）：与真实路径在进程
 * 生命周期上等价，终态回收行为可被 smoke 断言。轮询路径与真实路径完全一致。
 */
export async function startSuggestJob(input: StartSuggestInput): Promise<EpicNextJob> {
  const existing = findRunningJob(input.code)
  if (existing) return existing
  // KI-057 env 闸：项目锚直拼 <root>/.suyou/epic-next（SANDBAR_EPIC_NEXT_DIR 属引擎仓
  // 域，不透出）；缺省（无 root）走原 resolveEpicNextDir（env 优先，行为不变）。
  const root = input.root !== undefined ? join(input.root, '.suyou', 'epic-next') : resolveEpicNextDir(input.repo)
  const jobId = `${input.code}-${Date.now().toString(36)}-${randomUUID().slice(0, 6)}`
  const dir = join(root, jobId)
  await mkdir(dir, { recursive: true })
  const resultPath = join(dir, 'result.json')
  const prompt = buildSuggestPrompt({
    code: input.code,
    epicTitle: input.epicTitle,
    epicMarkdown: input.epicMarkdown,
    ticketsSummary: input.ticketsSummary,
    workflows: input.workflows,
    resultPath,
  })
  await writeFile(join(dir, 'prompt.md'), prompt, 'utf8')
  const job: EpicNextJob = {
    jobId,
    code: input.code,
    state: 'running',
    startedAt: Date.now(),
    dir,
    resultPath,
    workflowIds: input.workflows.map(w => w.id),
  }
  JOBS.set(jobId, job)
  const stubMode = process.env.SANDBAR_EPIC_NEXT_STUB
  if (stubMode) {
    if (stubMode === 'invalid_json') {
      // 复刻 260828 事故现场：内容形状合规但混了 LLM 非法转义 \-（JSON 只认 \" \\ \n 等少数）。
      const first = input.workflows[0]
      await writeFile(resultPath,
        `{"status":"ok","workflow":"${first?.id ?? 'dev-lane'}","title":"[stub] 非法 JSON\\-破折号","body":"b","rationale":"r"}\n`, 'utf8')
    } else if (stubMode !== 'never_write') {
      const first = input.workflows[0]
      const stub = first
        ? { status: 'ok', workflow: first.id, title: `[stub] ${input.code} 下一步建议`, body: '[stub] 建议正文', rationale: '[stub] 自测桩，未调用真实模型' }
        : { status: 'failed', reason: '[stub] 无可用工单模板' }
      await writeFile(resultPath, JSON.stringify(stub, null, 1) + '\n', 'utf8')
    }
    // 哑长驻进程：与真实 agent「干完活不自退」行为对齐（stock headless 已知行为），
    // 让 stub 路径的终态进程回收可被断言；unref 保证不拖宿主/测试进程退出。
    const proc = spawn(process.execPath, ['-e', 'setTimeout(()=>{}, 900000)'], { stdio: 'ignore' })
    proc.on('error', () => {})
    proc.unref()
    job.proc = proc
  } else {
    await spawnAgent(input.repo, job, prompt)
  }
  await cleanupOldJobs(root, input.code).catch(() => {})
  return job
}

/**
 * 终态回收 agent 进程（对齐 agent_activities.py 的 finally-terminate 语义，见文件头注）。
 * stock headless 干完活不自退是已知行为；t260829-07 实测 SIGTERM 仍可能杀不死
 * （headless 忽略/处理慢）——TERM 后 3s 宽限仍存活则 SIGKILL 兜底。detached spawn
 * （进程组首）优先 kill(-pid) 整组回收，防 agent 自己 spawn 的子进程残留。
 * kill 失败（已死/权限）不阻塞终态翻转。
 */
function reapAgentProc(job: EpicNextJob): void {
  const p = job.proc
  if (!p || p.exitCode !== null || p.signalCode !== null) return  // 已终态，无需回收
  const term = () => {
    try { p.pid !== undefined && p.detached ? process.kill(-p.pid, 'SIGTERM') : p.kill('SIGTERM') } catch { /* 已死 */ }
  }
  const kill = () => {
    try { p.pid !== undefined && p.detached ? process.kill(-p.pid, 'SIGKILL') : p.kill('SIGKILL') } catch { /* 已死 */ }
  }
  term()
  const t = setTimeout(kill, 3000)
  t.unref() // 宿主退出不等宽限
}

/**
 * 轮询 job。结果文件判读分两类（260828 事故修复）：
 *   - 读不到 = 还没写出/正在写 → 继续判进程存活与超时；
 *   - 读到但 JSON.parse 不过 = 文件已产出但不是合法 JSON → fail-fast：进程已退出
 *     （文件不会再改写）或文件连续两轮轮询 mtime+size 未变（已写定）即置 failed，
 *     reason 明说「结果文件不是合法 JSON」附 parse 摘要，不再干等超时、不再误说「未产出」。
 * parse 过则 validateSuggestion 过 → done / 不过 → failed；进程已退出但无合规结果 →
 * failed（附 agent.log 尾部）；超 jobTimeoutMs() → 杀进程 failed。
 * 所有终态统一 reapAgentProc 回收 agent 进程。未知 jobId 返回 null（宿主重启丢注册表
 * 属预期，前端重新点击即可）。
 */
export async function pollSuggestJob(jobId: string): Promise<EpicNextJob | null> {
  const job = JOBS.get(jobId)
  if (!job || job.state !== 'running') return job ?? null

  let text: string | null = null
  try {
    text = await readFile(job.resultPath, 'utf8')
  } catch { /* 文件不存在/读不到——按「还没写出」处理，落入下方进程/超时判断 */ }

  if (text !== null) {
    let raw: any
    try {
      raw = JSON.parse(text)
    } catch (err) {
      // 文件在但 parse 不过（LLM 典型非法转义 \- 等）。fail-fast 判定：
      const procGone = !job.proc || job.proc.exitCode !== null || job.proc.signalCode !== null
      const st = await stat(job.resultPath).catch(() => null)
      const stable = st !== null && job.lastResultMtimeMs === st.mtimeMs && job.lastResultSize === st.size
      if (procGone || stable) {
        const why = err instanceof Error ? err.message.slice(0, 160) : String(err)
        reapAgentProc(job)
        job.state = 'failed'
        job.reason = `结果文件已产出但不是合法 JSON：${why}`
          + `（${procGone ? 'agent 进程已退出，文件不会再改写' : '文件连续两轮轮询未变化，判定已写定'}）`
          + await logTail(job.dir)
        return job
      }
      // 可能仍在写——记录本轮文件指纹，下一轮仍未变即 fail-fast；本轮落入进程/超时判断。
      if (st) {
        job.lastResultMtimeMs = st.mtimeMs
        job.lastResultSize = st.size
      }
      return pollProcOrTimeout(job)
    }
    const v = validateSuggestion(raw, job.workflowIds)
    reapAgentProc(job)
    if (v.ok) {
      job.state = 'done'
      job.suggestion = v.suggestion
    } else {
      job.state = 'failed'
      job.reason = v.error
    }
    return job
  }
  return pollProcOrTimeout(job)
}

/** 结果文件未写出时的存活/超时判断（pollSuggestJob 的下半，两个调用点共用）。 */
async function pollProcOrTimeout(job: EpicNextJob): Promise<EpicNextJob> {
  if (!job.proc) {
    job.state = 'failed'
    job.reason = 'agent 进程未启动且未产出结果（内部错误）'
    return job
  }
  const rc = job.proc.exitCode
  if (rc !== null) {
    job.state = 'failed'
    job.reason = `integration agent 已退出（rc=${rc}）但未写出合规结果文件` + await logTail(job.dir)
    return job
  }
  const timeoutMs = jobTimeoutMs()
  if (Date.now() - job.startedAt > timeoutMs) {
    reapAgentProc(job)
    job.state = 'failed'
    job.reason = `等待超过 ${formatTimeout(timeoutMs)} 未产出结果，已终止` + await logTail(job.dir)
    return job
  }
  return job
}

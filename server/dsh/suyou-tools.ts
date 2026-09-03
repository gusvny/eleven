/**
 * suyou-tools —— 溯游 admin 工具面的 dsh 插件（路线 C：混合薄壳）。
 *
 * 机制（对照 docs/ops/admin-dsh-应用方案.md §3-C / §4）：
 *   ① 启动时 spawn `python3 <repo>/server/admin.py tools`，拿到工具注册表的
 *     DeepSeek function-calling schema dump，逐字映射注册成 dsh 裸 JSON Schema
 *     工具（schema 每次启动现取现注册，python 侧永远是单一真源，无双写漂移）；
 *   ② 每次工具调用 = spawn `python3 <repo>/server/admin.py call <name> <argsJSON>`，
 *     stdout 的 {ok, result|error, run_id} 原样成为工具返回——run-id 审计单一真源
 *     仍在 python server/admin.log，run_id 随返回值进 dsh 会话日志，双层互查；
 *   ③ `tools/pre-execute` 门禁：命中 needsApproval 名单（默认 params_set）的调用
 *     返回 {kind:'ask'}，走 dsh approval seam 弹人工审批（§12.2-③ 两阶段提交 v1；
 *     headless 无审批应答者时 fail-closed 自动拒绝——无人值守不许批，这恰好是对的）。
 *
 * 只用 dsh 稳定面：apply(ctx) + ctx.tools.register + tools/pre-execute；
 * 不碰 preview 不稳定面（不启用 dsh-tool-cordis 动态插件）。
 *
 * repo 解析顺序：config.repo → SUYOU_REPO 环境变量 → 按本文件位置推导
 * （<repo>/server/dsh/suyou-tools.ts 上两级）。无任何机器绝对路径写死。
 */

import { execFile } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'

const execFileP = promisify(execFile)

export const name = 'suyou-tools'
export const inject = ['tools']

/** 本文件固定落在 <repo>/server/dsh/ 下，上两级即仓库根。 */
const DEFAULT_REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

/** 调用 admin.py 的共享参数（repo 必给；python/timeoutMs 有默认）。 */
export interface AdminCliOptions {
  repo: string
  python?: string
  timeoutMs?: number
}

/**
 * 共享出口：spawn `python3 <repo>/server/admin.py <args>`，stdout 解析为 JSON 返回。
 * admin.py call 在工具失败时 exit 1 但 stdout 仍是结构化 JSON——捞回来走正常路径。
 * suyou-tools（模型可见工具面）与 suyou-admin-ui（浏览器面板 API）共用此函数，
 * run-id 审计单一真源始终在 python server/admin.log。
 */
export async function runAdminCli(opts: AdminCliOptions, args: string[], signal?: AbortSignal): Promise<any> {
  const python = opts.python ?? 'python3'
  const adminPy = join(opts.repo, 'server', 'admin.py')
  try {
    const { stdout } = await execFileP(python, [adminPy, ...args], {
      cwd: opts.repo,
      maxBuffer: 16 * 1024 * 1024,
      timeout: opts.timeoutMs ?? 300_000,
      ...(signal ? { signal } : {}),
    })
    return JSON.parse(stdout)
  } catch (err: any) {
    if (err?.stdout) {
      try {
        return JSON.parse(err.stdout)
      } catch { /* 落下面统一报错 */ }
    }
    const detail = (err?.stderr ?? err?.message ?? String(err)).slice(0, 500)
    throw new Error(`suyou admin cli: 调用 ${python} ${adminPy} 失败: ${detail}`)
  }
}

/** 插件配置（cordis.patch.yml 里 config: 字段；全部可缺省）。 */
interface SuyouToolsConfig {
  /** 溯游仓库根（含 server/admin.py 的那级）。缺省按本文件位置推导。 */
  repo?: string
  /** python 解释器，默认 python3。 */
  python?: string
  /** 调用工具子进程的超时（毫秒），默认 300000（qc_run all 级够用）。 */
  timeoutMs?: number
  /** 走人工审批的工具名单，默认 ['params_set']。 */
  needsApproval?: string[]
}

/** `admin.py tools` 输出里单个工具的 DeepSeek function-calling 形态。 */
interface PyToolEntry {
  type: 'function'
  function: {
    name: string
    description: string
    parameters: Record<string, unknown>
  }
}

export async function apply(ctx: Context, config?: SuyouToolsConfig) {
  const repo = config?.repo ?? process.env.SUYOU_REPO ?? DEFAULT_REPO
  const python = config?.python ?? 'python3'
  const timeoutMs = config?.timeoutMs ?? 300_000
  const needsApproval = new Set(config?.needsApproval ?? ['params_set'])

  /** 唯一出口：共享的 runAdminCli。将来要切 HTTP 后端（路线 B 能力）只改这里。 */
  const cliOpts: AdminCliOptions = { repo, python, timeoutMs }
  async function py(args: string[], signal?: AbortSignal): Promise<any> {
    return runAdminCli(cliOpts, args, signal)
  }

  // ① 启动时现取工具表。取不到 = 配置错误，响亮报错但不拖垮整个 dsh 启动。
  let tools: PyToolEntry[]
  try {
    tools = await py(['tools'])
    if (!Array.isArray(tools)) throw new Error('admin.py tools 输出不是数组')
  } catch (err) {
    ctx.logger.error(
      'suyou-tools: 启动取工具表失败，未注册任何 suyou 工具（repo=%s）：%s',
      repo, String(err))
    return
  }

  // ② 逐字映射成 dsh 裸 JSON Schema 工具（输入校验沿用 python 侧 tools_registry 口径）。
  for (const t of tools) {
    const fn = t.function
    if (!fn?.name) continue
    ctx.tools.register({
      name: fn.name,
      description: `${fn.description ?? ''}（结果含 run_id，审计见 server/admin.log）`,
      parameters: fn.parameters ?? { type: 'object', properties: {} },
      timeoutMs,
      output: {
        // 注解空 schema = 任意 JSON 根：python 返回 {ok, result|error, run_id} 原样透传。
        schema: {},
        render: (_args: unknown, value: unknown) => [{
          type: 'text' as const,
          text: typeof value === 'string' ? value : JSON.stringify(value, null, 1),
        }],
      },
      async execute(args: unknown, exec: { signal: AbortSignal }) {
        const res = await py(['call', fn.name, JSON.stringify(args ?? {})], exec.signal)
        // ok=false → 抛异常走 isError 结果路径（run_id 进错误消息，双层可互查）。
        if (!res?.ok) {
          throw new Error(`${res?.error ?? '未知错误'}（run_id ${res?.run_id ?? 'n/a'}，审计见 server/admin.log）`)
        }
        return res
      },
    } as any)
  }
  ctx.logger.info('suyou-tools: 已注册 %d 个溯游 admin 工具（repo=%s，审批名单=%s）',
    tools.length, repo, [...needsApproval].join(',') || '空')

  // ③ 两阶段提交 v1：破坏性工具转人工审批（approval seam；无应答者 fail-closed 拒绝）。
  if (needsApproval.size > 0) {
    ctx.on('tools/pre-execute', async (exec: any, next: any) => {
      if (needsApproval.has(exec.name)) {
        return {
          kind: 'ask',
          reason: `溯游 admin 写操作 ${exec.name}，需人工确认（决定会写入会话日志；工具调用审计见 server/admin.log）`,
        }
      }
      return next()
    })
  }
}

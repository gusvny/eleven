/**
 * project-admin.ts —— workbench host × 安装器 project CLI 的薄 spawn 壳
 * （project-lifecycle 票③面D，写路径薄壳单源纪律：UI 不实现任何校验/闸逻辑，
 * add/remove/list 全部落安装器 CLI `sandbar project … --json`，行为与命令行同源）。
 *
 * 借鉴先例与故障模式取舍（方案 R1-① 定稿，实现照单落）：
 *   借 runAdminCli（server/sandbar-tools.ts）的**模式**，不借函数——它硬编码
 *   spawn `python3 <repo>/server/admin.py`，而 project 命令族真实入口=仓根
 *   `sandbar` 薄壳（installer.cli.main；admin.py 内零 project 接线，实核）。
 *   逐项取舍：
 *   - repo 锚定：**带**。repo 由 node.ts `config?.repo ?? SANDBAR_REPO ?? DEFAULT_REPO`
 *     同源解析传入（node.ts:319），spawn cwd=repo、entry=<repo>/sandbar——防异仓
 *     执行错注册表（KI-032/033 错仓=脑裂）。
 *   - 超时：**不带原值**。runAdminCli 默认 300s（UI 照抄=宿主转圈五分钟）；本壳
 *     默认 30s（remove 的在飞闸是本地 Temporal 查询，足够），可经 opts 覆盖。
 *     超时文案点名「CLI 执行超时（Ns）」，不谎报「无结果」。
 *   - 四终态回收（spawn 资源生命周期逐项答）：正常=收满 stdout 解析返回；报错=
 *     非零退出先捞 stdout JSON 体（projects.py FailClosed 口径）再退化 Error；
 *     超时=kill('SIGTERM') 后 await exit 事件才返回，不留僵尸；取消=AbortSignal
 *     触发同超时回收路径（signal.reason 进 Error）。全部路径都 await 子进程退出。
 *   - stdout 畸形/非 JSON/maxBuffer 溢出：**不带 runAdminCli 的裸抛**——本壳转
 *     ProjectCliError{status:502}，message 含截断原文，路由侧不裸抛堆栈。
 *   - run-id 审计：不带（admin.log 面与 installer CLI 无关，无此面）。
 *
 * entryPath 仅测试缝：默认 join(repo,'sandbar')，UT 用假脚本注入覆盖（不触真仓）。
 */

import { spawn } from 'node:child_process'
import { join } from 'node:path'

export interface ProjectCliOptions {
  /** 引擎仓根（真源解析在 node.ts，本壳不重复解析）。 */
  repo: string
  /** python 解释器，默认 python3。 */
  python?: string
  /** 超时毫秒，默认 30_000（UI 级短超时，取舍见头注）。 */
  timeoutMs?: number
  /** CLI 入口路径（测试缝；生产恒 <repo>/sandbar）。 */
  entryPath?: string
}

/** CLI 调用失败的类型化错误：status=建议 HTTP 状态（409 拒收 / 502 输出不可解析 / 504 超时）。 */
export class ProjectCliError extends Error {
  status: number
  /** CLI 原始输出体（可解析时为对象；供路由透传给弹层就地显示）。 */
  body?: unknown

  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.name = 'ProjectCliError'
    this.status = status
    this.body = body
  }
}

/** stdout 采集上限（runAdminCli 同款 16MB；溢出按畸形输出转 502）。 */
const MAX_STDOUT = 16 * 1024 * 1024

/**
 * 跑 `python3 <repo>/sandbar <args…>`，stdout 解析为 JSON 返回。
 * 四终态（正常/报错/超时/取消）全部 kill+await exit，见头注取舍清单。
 */
export function runProjectCli(opts: ProjectCliOptions, args: string[], signal?: AbortSignal): Promise<any> {
  const python = opts.python ?? 'python3'
  const entry = opts.entryPath ?? join(opts.repo, 'sandbar')
  const timeoutMs = opts.timeoutMs ?? 30_000
  return new Promise((resolve, reject) => {
    const child = spawn(python, [entry, ...args], { cwd: opts.repo })
    let stdout = ''
    let stderr = ''
    let settled = false
    let timedOut = false
    let bytes = 0
    const finish = (fn: () => void): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      fn()
    }
    const killAndSettle = (why: string, status: number): void => {
      // 终态回收：先杀再等 exit 事件（exit 处理器里 finish）——kill 发出≠已回收。
      if (!timedOut) timedOut = status === 504
      try { child.kill('SIGTERM') } catch { /* 已退出：exit 事件会带我们走 */ }
      pendingWhy = why
      pendingStatus = status
    }
    let pendingWhy = ''
    let pendingStatus = 0
    const timer = setTimeout(() => killAndSettle(`CLI 执行超时（${Math.round(timeoutMs / 1000)}s）：sandbar ${args.join(' ')}`, 504), timeoutMs)
    const onAbort = (): void => killAndSettle(`请求已取消：sandbar ${args.join(' ')}`, 499)
    signal?.addEventListener('abort', onAbort, { once: true })
    child.stdout.on('data', (c: Buffer) => {
      bytes += c.length
      if (bytes > MAX_STDOUT) {
        killAndSettle('CLI stdout 超出 16MB 上限（输出不可解析）', 502)
        child.stdout.destroy()
        return
      }
      stdout += c.toString('utf8')
    })
    child.stderr.on('data', (c: Buffer) => { stderr += c.toString('utf8') })
    child.on('error', (err) => {
      finish(() => reject(new ProjectCliError(502, `project CLI 无法启动：${String(err?.message ?? err)}`)))
    })
    child.on('exit', () => {
      finish(() => {
        if (pendingWhy) {
          reject(new ProjectCliError(pendingStatus, pendingWhy))
          return
        }
        // 报错路径（按 CLI exit 码分流，不解析语义仍薄壳）：
        //   JSON 体在（FailClosed 机器口径）→ 409 原体透传；
        //   exit 1 且无人话 JSON → 409+原文转述（用户输入拒收≠上游故障；票① add 拒收
        //     现状输出 [红] 人话——契约缺口已跨票上报）；
        //   exit 2 → 502「参数错误」（argparse 用法错=路由 argv 拼装与 CLI 契约不符，
        //     那是路由自己的 bug，不谎报给用户）；
        //   其余非零 → 502 原文截断。
        const parsed = (() => { try { return JSON.parse(stdout) } catch { return undefined } })()
        if (child.exitCode !== 0) {
          if (parsed !== undefined) {
            reject(new ProjectCliError(409, typeof parsed?.error === 'string' ? parsed.error : `project CLI 失败（exit ${child.exitCode}）`, parsed))
          } else if (child.exitCode === 1) {
            reject(new ProjectCliError(409, `CLI 拒收：${(stdout || stderr).trim().slice(0, 500)}`))
          } else if (child.exitCode === 2) {
            reject(new ProjectCliError(502, `project CLI 参数错误（exit 2，路由 argv 拼装与 CLI 契约不符）：${(stderr || stdout).trim().slice(0, 500)}`))
          } else {
            reject(new ProjectCliError(502, `project CLI 失败（exit ${child.exitCode}）且输出不可解析：${(stderr || stdout).slice(0, 500)}`))
          }
          return
        }
        if (parsed === undefined) {
          reject(new ProjectCliError(502, `CLI 输出不可解析（非 JSON）：${stdout.slice(0, 500)}`))
          return
        }
        resolve(parsed)
      })
    })
  })
}

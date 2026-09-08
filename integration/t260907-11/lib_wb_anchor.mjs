/**
 * lib_wb_anchor.mjs —— t260907-11 场景共享夹具与驱动（KI-057 工单台 host 项目感知化）。
 *
 * 夹具=临时注册表（SANDBAR_PROJECTS_DIR per-key 目录模式，.migrated 标记跳过种子迁移）
 * ＋两个伪造项目仓 repoA(=sandbar fixture)/repoB(=fpv fixture)，同代号立项单 demo-x
 * 各放一份（撞码面）。驱动=smoke/changes.mjs 先例：apply(ctx,{repo})+mock webServer
 * 收路由+mock req/res 直调 handler——零端口零 Temporal 零 3099/7233 接触。
 *
 * 注册表 env 每次调用现读（project-registry.ts registryRoot），进程内改 env 即刻生效；
 * withEnv 负责保存/恢复，场景退出必还原。
 *
 * 三态退出码（t260904-12 契约，「闸内无 SKIP」）：全过 exit 0；有 FAIL exit 1；
 * 环境缺失（git 等）打印 ENV_FAIL 点名后 exit 2。实现段落地前红属预期（TDD 信号），
 * arbitrate/merge 期必须绿。
 */
import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../../server/plugins/workbench/node.ts'

export const EPIC_CODE = 'demo-x'
export const EPICS_PREFIX = '/sandbar-workbench/api/epics'
export const TICKETS_PREFIX = '/sandbar-workbench/api/wf/tickets'

export const EPIC_MD_A = `# 立项单：sandbar 侧演示立项\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | \\\`demo-x\\\` |\n| 状态 | 已立项（执行中） |\n`
export const EPIC_MD_B = `# 立项单：fpv 侧演示立项\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | \\\`demo-x\\\` |\n| 状态 | 已立项（执行中） |\n`
export const EPIC_MD_ENV = `# 立项单：env 覆盖侧演示立项\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | \\\`demo-x\\\` |\n| 状态 | 已立项（执行中） |\n`

/** 断言登记：FAIL 进 failures，退出码按三态收敛。 */
export function makeJudge(label) {
  const failures = []
  return {
    failures,
    ok(cond, msg) {
      if (cond) console.log(`  ok ${label}: ${msg}`)
      else { failures.push(`${label}: ${msg}`); console.log(`  FAIL ${label}: ${msg}`) }
    },
    finish(envFailReason) {
      if (envFailReason) {
        console.log(`ENV_FAIL: ${envFailReason}`)
        process.exit(2)
      }
      if (failures.length > 0) {
        console.log(`\nFAIL ${label}：${failures.length} 条断言未过（实现段落地前红属预期=TDD 信号；arbitrate/merge 期必须绿）`)
        process.exit(1)
      }
      console.log(`\nPASS ${label}`)
      process.exit(0)
    },
  }
}

/** per-key 注册表条目（契约① schema v1 固定形状）。 */
function projectYaml(key, name, dir) {
  return `schema: v1\nproject:\n  - key: ${key}\n    name: ${name}\n    dirs:\n      - ${dir}\n`
}

/** 伪造注册表：sandbar→repoA、fpv→repoB、badproj=坏条目（schema 缺失→隔离面）。 */
async function writeRegistry(root, repoA, repoB) {
  const regDir = join(root, 'projects')
  for (const [key, dir, body] of [
    ['sandbar', repoA, projectYaml('sandbar', 'sandbar fixture', repoA)],
    ['fpv', repoB, projectYaml('fpv', 'dengzhufpv fixture', repoB)],
    // schema 缺失=畸形→该条目隔离（fail-closed），隔离文案透传注册表 error
    ['badproj', join(regDir, 'badproj'), 'project:\n  - key: badproj\n    name: 坏条目\n    dirs:\n      - /nonexistent\n'],
  ]) {
    const d = join(regDir, key)
    await mkdir(d, { recursive: true })
    await writeFile(join(d, 'project.yaml'), body, 'utf8')
  }
  // .migrated 标记：跳过 legacy 种子迁移，注册表只有本夹具三条
  await writeFile(join(regDir, '.migrated'), 'fixture\n', 'utf8')
  return regDir
}

/**
 * 建夹具：repoA/repoB 各有 notes/epics/<demo-x>.md（同代号不同标题=撞码面）。
 * 返回 {root, repoA, repoB, regDir, cleanup, withEnv, drive}。
 */
export async function makeFixture() {
  const root = await mkdtemp(join(tmpdir(), 'wb-anchor-fixture-'))
  const repoA = join(root, 'repoA')
  const repoB = join(root, 'repoB')
  for (const repo of [repoA, repoB]) {
    await mkdir(join(repo, 'notes', 'epics'), { recursive: true })
    await mkdir(join(repo, 'server', 'dsh'), { recursive: true })
  }
  await writeFile(join(repoA, 'notes', 'epics', `${EPIC_CODE}.md`), EPIC_MD_A, 'utf8')
  await writeFile(join(repoB, 'notes', 'epics', `${EPIC_CODE}.md`), EPIC_MD_B, 'utf8')
  const regDir = await writeRegistry(root, repoA, repoB)

  // 项目键解析必须读本夹具注册表：registryRoot() 每次现读 SANDBAR_PROJECTS_DIR，
  // 不设=读到真用户注册表（sandbar 解析出真仓根、badproj 不存在→400），夹具失真。
  // 保存旧值，cleanup 还原（进程内设 env 即刻生效，无需重启）。
  const savedRegistryDir = process.env.SANDBAR_PROJECTS_DIR
  process.env.SANDBAR_PROJECTS_DIR = regDir

  const savedEnv = {}
  /**
   * withEnv(overrides, fn)：进程内设 env 跑 fn，finally 逐键恢复。
   * 值=null 表示删除该键。
   */
  async function withEnv(overrides, fn) {
    for (const [k, v] of Object.entries(overrides)) {
      savedEnv[k] = savedEnv[k] ?? { had: k in process.env, val: process.env[k] }
      if (v === null) delete process.env[k]
      else process.env[k] = v
    }
    try { return await fn() } finally {
      for (const [k, s] of Object.entries(savedEnv)) {
        if (s.had) process.env[k] = s.val
        else delete process.env[k]
      }
    }
  }

  /** apply+mock 驱动（smoke/changes.mjs B 段同款手法）。 */
  function drive(repo) {
    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const routeFor = (prefix, url) => {
      // 列表端点是 exact 路由（EPICS_PREFIX 裸路径），详情族才是 prefix——按
      // 「请求路径剥 query 后与前缀逐字节相等→exact」选择（TDD 期驱动只认 prefix，
      // 对列表调用会误中 handleEpicRoute 吃 404，此处修正路由选择）。
      const path = (url ?? '').split('?')[0]
      if (path === prefix) {
        const e = routes.find((x) => x.kind === 'exact' && x.path === prefix)
        if (e) return e
      }
      const r = routes.find((x) => x.kind === 'prefix' && x.path === prefix)
      if (!r) throw new Error(`路由未挂：${prefix}`)
      return r
    }
    const mockRes = () => ({
      status: 0, body: null, raw: null, headers: null,
      writeHead(s, h) { this.status = s; this.headers = h },
      end(b) {
        if (b === undefined || b === null) { this.body = null; return }
        if (typeof b === 'string' && b.startsWith('{')) { try { this.body = JSON.parse(b); return } catch { /* 落 raw */ } }
        this.raw = b
      },
    })
    const mockReq = (url, method = 'GET', json) => ({
      url, method,
      async *[Symbol.asyncIterator]() { if (json !== undefined) yield Buffer.from(JSON.stringify(json)) },
    })
    return async (prefix, url, method = 'GET', json) => {
      const r = routeFor(prefix, url)
      const res = mockRes()
      await r.handler(mockReq(url, method, json), res)
      return res
    }
  }

  return {
    root, repoA, repoB, regDir, withEnv, drive,
    async cleanup() {
      if (savedRegistryDir === undefined) delete process.env.SANDBAR_PROJECTS_DIR
      else process.env.SANDBAR_PROJECTS_DIR = savedRegistryDir
      await rm(root, { recursive: true, force: true })
    },
  }
}

/** git 在场性（diff 面依赖）：缺席=ENV_FAIL。 */
export function requireGit() {
  try { execFileSync('git', ['--version'], { stdio: 'ignore' }); return null } catch {
    return 'git 不可用（diff 判界面需要真 git 仓 fixture）'
  }
}

/** repoB 建真 git 仓＋带改动的 worktree，返回 {base, absWt}。 */
export function makeGitWorktree(repoB) {
  // 调用方有传数组形（git(['init','-q'])）也有传变参形——flat() 统一摊平，
  // 否则数组被 coerce 成单个 'init,-q' 参数，git 报「不是 git 命令」。
  const git = (...args) => execFileSync('git', ['-C', repoB, ...args.flat()], { stdio: 'pipe' })
  git(['init', '-q'])
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '--allow-empty', '-q', '-m', 'base'])
  const base = git(['rev-parse', 'HEAD']).toString().trim()
  git(['worktree', 'add', '-q', '.worktrees/wt', '-b', 'lane/wb-anchor'])
  const absWt = join(repoB, '.worktrees', 'wt')
  execFileSync('sh', ['-c', `printf 'export const changed = 1\\n' > '${absWt}/src-changed.ts'; printf 'fresh\\n' > '${absWt}/fresh-untracked.ts'`])
  return { base, absWt }
}

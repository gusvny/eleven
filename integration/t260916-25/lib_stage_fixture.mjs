// lib_stage_fixture.mjs — t260916-25 stage 控制台场景共享夹具（非 sc_ 共享代码，不入场景清单）。
//
// 职责：为 sc_stage_console_* 场景提供——
//   1. dsh 启动面测试桩（假 dsh-root：bin/dsh 壳 + catch-all 桩控制台，模式可注入）；
//   2. 夹具 src-home（凭据/settings/旧代会话的最小真实形态）；
//   3. stage_console.sh 步进器（超时兜底击杀，绝不挂死套件）；
//   4. 端口探针 / 残留进程清点 / pidfile 探测（行为级断言的观测面）。
//
// 红线（夹具自身纪律）：绝不绑定/请求 3099/3199/7233/8233/17233/18233——桩内硬拒；
// 对真 home（~/.dsh）零接触——一切夹具落 os.tmpdir() 隔离目录，由场景 finally 清场。
// 被测件（server/tools/stage_console.sh、integration/lib_stage_ui_surface.mjs）是
// 本票 developer 交付物，本库只从公开 CLI/FS 面驱动，不读其内部。
import { spawn, execFileSync } from 'node:child_process'
import { createServer, connect } from 'node:net'
import {
  mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync,
  rmSync, chmodSync, existsSync,
} from 'node:fs'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'

export const SCRIPT_PATH = 'server/tools/stage_console.sh'
export const ASSERT_LIB_PATH = 'integration/lib_stage_ui_surface.mjs'

// 全项目既定端口面（docs/testing-guide.md）：生产 3099/7233/8233、共享测试台 3199/17233/18233。
// 夹具高位取口 3511-3549 与之保持距离；桩内另有一道硬拒。
export const FORBIDDEN_PORTS = [3099, 3199, 7233, 8233, 17233, 18233]

// ---------------------------------------------------------------- 端口探针

/** 从 3511 起挑一个本机空闲高位口；耗尽返回 0（场景记 env_fail——环境面）。 */
export async function pickFreePort() {
  for (let p = 3511; p <= 3549; p++) {
    if (FORBIDDEN_PORTS.includes(p)) continue
    // eslint-disable-next-line no-await-in-loop
    const free = await new Promise((done) => {
      const s = createServer()
      s.once('error', () => done(false))
      s.listen(p, '127.0.0.1', () => s.close(() => done(true)))
    })
    if (free) return p
  }
  return 0
}

/** 端口是否有监听者（400ms 探测窗）。 */
export function listening(port) {
  return new Promise((done) => {
    const s = connect({ port, host: '127.0.0.1' })
    const settle = (v) => { s.destroy(); done(v) }
    s.once('connect', () => settle(true))
    s.once('error', () => settle(false))
    setTimeout(() => settle(false), 400)
  })
}

/** 等端口进入指定状态（up=true 等在听 / up=false 等释放），到帽返回最新状态。 */
export async function waitPort(port, up, capMs = 5000) {
  const t0 = Date.now()
  for (;;) {
    // eslint-disable-next-line no-await-in-loop
    if ((await listening(port)) === up) return true
    if (Date.now() - t0 > capMs) return (await listening(port)) === up
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 150))
  }
}

// ---------------------------------------------------------------- 夹具目录

/** 在系统临时区建本场景隔离工作区（夹具纪律：绝不落仓库、绝不落真 home）。 */
export function makeWorkspace(label) {
  return mkdtempSync(join(tmpdir(), `t260916-25-${label}-`))
}

export function rmRf(p) {
  try { rmSync(p, { recursive: true, force: true } ) } catch { /* 清场失败由残留断言兜底点名 */ }
}

/** 夹具 src-home：凭据/settings/匿名 id/若干旧代（v0 形态）会话目录。 */
export function writeSrcHome(home, { creds, settings, sessionNames = [], sessionBody = 'v0 legacy transcript line\n' }) {
  mkdirSync(home, { recursive: true })
  writeFileSync(join(home, '.credentials.yaml'), creds)
  writeFileSync(join(home, 'settings.yaml'), settings)
  writeFileSync(join(home, '.anonymous-user-id'), 'anon-fixture-id')
  for (const name of sessionNames) {
    const d = join(home, 'sessions', name)
    mkdirSync(d, { recursive: true })
    writeFileSync(join(d, 'session.jsonl'), sessionBody)
  }
}

// ---------------------------------------------------------------- dsh 启动面测试桩

// catch-all 桩控制台：/ →首页 HTML（script src + 五插件名都在页面里）；
// /assets/app-bundle.js →含五插件名的 JS；/sandbar-workbench/api/* →JSON
// （badapi 模式恒 500）；其余路径一律 200 JSON 宽松面——桩不预判自检库的探测面，
// 消费方探任何接缝都拿确定性应答（对断言名集的 R1 校准免疫：桩供超集）。
const STUB_SERVER_JS = [
  '// t260916-25 夹具：catch-all 桩控制台（非产品代码）。',
  "const http = require('node:http')",
  'const port = Number(process.argv[2])',
  "const mode = process.argv[3] || 'normal'",
  "const NAMES = ['sandbar-admin-ui','sandbar-knowledge','sandbar-providers','sandbar-temporal-tools','sandbar-workbench'].join(' ')",
  'const html = \'<!doctype html><html><head><script src="/assets/app-bundle.js"></script></head><body data-plugins="\' + NAMES + \'">stage stub console</body></html>\'',
  "const bundle = '/* stage stub bundle (t260916-25 fixture) */\\n' + NAMES + '\\n'",
  'http.createServer(function (req, res) {',
  "  const url = (req.url || '/').split('?')[0]",
  "  if (mode === 'badapi' && url.indexOf('/sandbar-workbench/api/') === 0) {",
  "    res.writeHead(500, {'content-type': 'application/json'})",
  "    res.end(JSON.stringify({ error: 'stub badapi injection' }))",
    '    return',
    '  }',
    "  if (url === '/') { res.writeHead(200, {'content-type': 'text/html; charset=utf-8'}); res.end(html); return }",
    "  if (url === '/assets/app-bundle.js') { res.writeHead(200, {'content-type': 'application/javascript'}); res.end(bundle); return }",
    "  res.writeHead(200, {'content-type': 'application/json'})",
    '  res.end(JSON.stringify({ ok: true, stub: true, url: url }))',
    '}).listen(port, \'127.0.0.1\')',
  '',
].join('\n')

// 假 dsh-root 的 bin/dsh 壳（sh）：模仿真 dsh 控制台启动面——
//   normal = 打两行带 token URL（票面实测形态）再 exec 桩台；
//   nolog  = 只起台不打 URL 行（start 的 URL 提取缺失注入）；
//   hang   = 挂起永不监听（start 超时路注入）；
//   badapi = 正常起台但 workbench API 恒 500（自检红路注入）。
// 非 serve 形态（真实 dsh 的 --version/-h 等即退语义，被测脚本 resolve_dsh_root 会以
//   `bin/dsh --version` 探测入口）：打印版本行立即退出，绝不起台——否则脚本对探测
//   调用的输出捕获永不返回，prepare/start 整链挂死（本夹具 gen0 轮实踩）。
// 红线端口硬拒：绝不绑定 3099/3199/7233/8233/17233/18233（防 prepare sed 失守时误绑真口）。
const STUB_DSH_SH = [
  '#!/bin/sh',
  '# t260916-25 场景夹具：dsh 启动面测试桩（非产品代码）。',
  'set -u',
  'STUB_PORT="__STUB_PORT__"',
  'STUB_SERVER="__STUB_SERVER__"',
  'STUB_MODE="__STUB_MODE__"',
  'case " 3099 3199 7233 8233 17233 18233 " in',
  '  *" $STUB_PORT "*) echo "stub: 拒绝绑定红线端口 $STUB_PORT" >&2; exit 3;;',
  'esac',
  '[ -n "$STUB_PORT" ] || { echo "stub: 缺 STUB_PORT" >&2; exit 4; }',
  'case " $* " in',
  '  *" --profile "*) ;;  # 文档化启动形态（票面实测：dsh --profile sandbar-stage）→ 继续起台',
  '  *) echo "0.0.0-stage-stub"; exit 0 ;;  # --version/-h 等探测/即退形态：忠实即退，不起台',
  'esac',
  'case "$STUB_MODE" in',
  '  hang) echo "stub: hang 模式（永不监听）"; exec sleep 300 ;;',
  '  nolog) exec node "$STUB_SERVER" "$STUB_PORT" nolog ;;',
  '  *)',
  '    echo "dsh web: http://127.0.0.1:$STUB_PORT/?token=stubtoken0123456789abcdef"',
  '    echo "dsh web: opening the default browser; pass --no-open to disable"',
  '    exec node "$STUB_SERVER" "$STUB_PORT" "$STUB_MODE"',
  '    ;;',
  'esac',
  '',
].join('\n')

/** 建假 dsh-root：bin/dsh 壳 + node_modules 目录（prepare 软链目标）。返回 root 路径。
 * node_modules 必须非空且含 scoped 包——被测脚本 resolve_dsh_root 对空/缺依赖树
 * 诚实 RED（「安装不完整？」），桩必须建模真实 dsh 安装的最小形态。 */
export function makeStubRoot(ws, { port, mode = 'normal' }) {
  const root = join(ws, 'dshroot')
  mkdirSync(join(root, 'bin'), { recursive: true })
  const nm = join(root, 'node_modules')
  mkdirSync(join(nm, '@deepseek-ai', 'dsh'), { recursive: true })
  writeFileSync(join(nm, '@deepseek-ai', 'dsh', 'package.json'),
    JSON.stringify({ name: '@deepseek-ai/dsh', version: '0.0.0-stage-stub' }))
  writeFileSync(join(nm, '@deepseek-ai', 'dsh', 'index.js'), 'module.exports = {}\n')
  for (const pkg of ['fixture-pkg-one', 'fixture-pkg-two']) {
    mkdirSync(join(nm, pkg), { recursive: true })
    writeFileSync(join(nm, pkg, 'package.json'), JSON.stringify({ name: pkg, version: '0.0.0' }))
  }
  const serverPath = join(ws, 'stub_server.js')
  writeFileSync(serverPath, STUB_SERVER_JS)
  const dsh = STUB_DSH_SH
    .split('__STUB_PORT__').join(String(port))
    .split('__STUB_SERVER__').join(serverPath)
    .split('__STUB_MODE__').join(mode)
  const dshPath = join(root, 'bin', 'dsh')
  writeFileSync(dshPath, dsh)
  chmodSync(dshPath, 0o755)
  return root
}

// ---------------------------------------------------------------- 步进器

/**
 * 以 repo 根为 cwd 步进 server/tools/stage_console.sh（sh 调起，不要求可执行位）。
 * 超时兜底 SIGKILL，绝不挂死套件；返回 {code,stdout,stderr,killed}。
 */
export function runStep(args, opts = {}) {
  const timeoutMs = opts.timeoutMs || 90000
  const env = { ...process.env, ...(opts.env || {}) }
  return new Promise((done) => {
    const child = spawn('sh', [SCRIPT_PATH, ...args], { cwd: process.cwd(), env })
    let stdout = ''
    let stderr = ''
    let settled = false
    const timer = setTimeout(() => {
      if (!settled) { try { child.kill('SIGKILL') } catch { /* 已退 */ } }
    }, timeoutMs)
    child.stdout.on('data', (d) => { stdout += d })
    child.stderr.on('data', (d) => { stderr += d })
    child.on('error', (e) => {
      if (settled) return
      settled = true; clearTimeout(timer)
      done({ code: -1, stdout, stderr: `${stderr}\n${String(e)}`, killed: true })
    })
    child.on('close', (code, signal) => {
      if (settled) return
      settled = true; clearTimeout(timer)
      done({ code: code === null ? -1 : code, stdout, stderr, killed: signal === 'SIGKILL' })
    })
  })
}

// ---------------------------------------------------------------- 行为级观测面

/** 进程表可观测性前检：ps 被环境拒绝时残留/误杀断言无法进行——场景必须 ENV_FAIL，不空转假绿。 */
export function psAvailable() {
  try { execFileSync('ps', ['-axo', 'pid='], { encoding: 'utf8' }); return true } catch { return false }
}

/** 全进程表清点 cmdline 含 substr 的进程（排除自身）；残留断言用，绝不真杀。
 * ps 不可观测返回 null——上游用 psAvailable() 前检门住，此处兜底不谎报空集。
 * 格式参数必须单参数逗号连写（`pid=,command=`）：macOS BSD ps 把空格分写的
 * 第二个词当独立参数报 `illegal argument`（t260916-25 gen16 套件实锤——
 * psAvailable 单参门过了、本函数双参炸成 null，撞上场景 `.length` 直接崩）。
 * 断言用例对 null 仍需 env_fail 兜底：ps 中途失效=不可判定，不是通过也不是 0。 */
export function pidsMatching(substr) {
  let buf = null
  try { buf = execFileSync('ps', ['-axo', 'pid=,command='], { encoding: 'utf8' }) } catch { return null }
  const out = []
  for (const line of buf.split('\n')) {
    const m = line.match(/^\s*(\d+)\s+(.*)$/)
    if (!m) continue
    const pid = Number(m[1])
    if (pid === process.pid) continue
    if (m[2].includes(substr)) out.push({ pid, cmd: m[2] })
  }
  return out
}

export function pidAlive(pid) {
  try { process.kill(pid, 0); return true } catch { return false }
}

/** 结束夹具自己起的进程（先 TERM 后 KILL）；只用于清场，不作断言手段。 */
export async function killPid(pid) {
  try { process.kill(pid, 'SIGTERM') } catch { return }
  await new Promise((r) => setTimeout(r, 400))
  if (pidAlive(pid)) { try { process.kill(pid, 'SIGKILL') } catch { /* 已退 */ } }
}

/**
 * 在 stage home 下找 pidfile（契约面：stop 以 pidfile 记账）。
 * 判据=深度≤3 内内容为纯整数的文件且该 pid 存活；找不到返回 null——
 * 场景据此点名「安全用例不可注入」，不猜位置不造误红。
 */
export function findPidFile(home) {
  const found = []
  const walk = (dir, depth) => {
    if (depth > 3) return
    let entries = []
    try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      const p = join(dir, e.name)
      if (e.isDirectory()) walk(p, depth + 1)
      else {
        let c = ''
        try { c = readFileSync(p, 'utf8') } catch { continue } // 二进制跳过
        if (/^\d+\s*$/.test(c)) found.push({ path: p, pid: Number(c.trim()) })
      }
    }
  }
  walk(home, 0)
  return found.find((f) => pidAlive(f.pid)) || null
}

/** 五插件软链名（票面「node_modules 五条软链」的可见契约面）。 */
export const PLUGIN_LINK_NAMES = [
  'sandbar-admin-ui', 'sandbar-knowledge', 'sandbar-providers',
  'sandbar-temporal-tools', 'sandbar-workbench',
]

export { existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync, join, resolve }

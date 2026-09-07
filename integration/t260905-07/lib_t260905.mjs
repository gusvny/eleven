/**
 * lib_t260905 —— t260905-07 场景族共享夹具（详情面板真点台 + staleness 注入台）。
 *
 * 复用纪律：通用夹具（登记表/桩票/隔离台/浏览器/三态结果器）直接 re-export
 * t260904-17 场景族 lib（已入主树的共享资产，环境变量参数化、零本票耦合）——
 * 共享 helpers 允许复用（用例设计纪律），不复制不漂移。
 * 本票新增面只有两件：
 *   - loadBannerTexts()：横幅文案锚常量（banner-text.ts）的源码侧加载——
 *     KI-051 锚纪律：场景断言 import 常量而非裸字面量；模块缺席返回 null
 *     （调用方 FAIL 点名「锚常量未落地」，不以字面量回退蒙混该断言）。
 *   - makeFixtureConsole()：staleness 注入台——fixture 真拷贝 server/dsh
 *     （capture-stale-banner.mjs 先例：boot 指纹算 fixture 文件），支持同端口
 *     restart（跨重启存活页面序列的唯一实现方式）。
 * 红线：临时端口 + 临时 DSH_HOME（退出即删）+ 零 3099/7233 接触 + 不 seed 真数据。
 */

import { spawn } from 'node:child_process'
import {
  closeSync, copyFileSync, existsSync, mkdtempSync, openSync, readFileSync, rmSync, writeFileSync,
} from 'node:fs'
import { cp, mkdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT = join(HERE, '..', '..')

export {
  tmpRoot, freePort, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults, mainRoot,
} from '../t260904-17/lib_fix17.mjs';
import { freePort, mainRoot } from '../t260904-17/lib_fix17.mjs';

/* ------------------------------------------------------- 横幅文案锚常量 */

/** 字面量仅作常量模块缺席时的机制分支回退（该缺席本身会被 sb/anchor-constants 判 FAIL）。 */
export const FALLBACK_TEXTS = Object.freeze({
  STALE_BANNER_TEXT: '有更新，重启控制台生效',
  STALE_RELOAD_TEXT: '有更新，刷新页面生效',
})

/** 源码侧加载横幅文案常量；模块缺席/不可解析 → null（调用方点名 FAIL，不静默回退）。 */
export async function loadBannerTexts() {
  try {
    const mod = await import(pathToFileURL(join(
      REPO_ROOT, 'server', 'dsh', 'workbench', 'src', 'client', 'banner-text.ts',
    )).href)
    return { ...FALLBACK_TEXTS, ...mod }
  } catch {
    return null
  }
}

/* ------------------------------------------------- staleness 注入台（fixture） */

async function waitReady(port, timeoutMs, logPath) {
  const t0 = Date.now()
  for (;;) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(2000) })
      if (res.ok) return
    } catch { /* 未就绪，续等 */ }
    if (Date.now() - t0 > timeoutMs) {
      let tail = ''
      try { tail = readFileSync(logPath, 'utf8').slice(-2000) } catch {}
      throw new Error(`注入台 ${Math.round(timeoutMs / 1000)}s 内未就绪（127.0.0.1:${port}）。日志尾部：\n${tail || '（无日志）'}`)
    }
    await new Promise((r) => setTimeout(r, 500))
  }
}

/**
 * fixture 注入台：拷贝 server/dsh → 临时 repo（跳过 node_modules）→ buildTempProfile
 * 把 sandbar-workbench 指向 fixture 拷贝（boot/盘指纹都算 fixture 文件，真拷贝=控制台
 * 行为全真，只有「落账」这一步由脚本触发）→ start/restart（同端口）/teardown。
 * 同端口 restart 是「跨重启存活页面」序列（M4）的唯一实现方式：页面不重载，
 * 注入值保持下载时刻盘态，与重启后的 boot 形成 gen2 判定矩阵 M4 格。
 */
export async function makeFixtureConsole() {
  const tmpHome = mkdtempSync(join(tmpdir(), 't260905-stale-'))
  const fixtureRepo = join(tmpHome, 'repo')
  await mkdir(fixtureRepo, { recursive: true })
  await cp(join(REPO_ROOT, 'server', 'dsh'), join(fixtureRepo, 'server', 'dsh'), {
    recursive: true,
    filter: (src) => !src.includes('node_modules'),
  })
  const fixtureWb = join(fixtureRepo, 'server', 'dsh', 'workbench')

  // capture-lane 必须与被测代码同树解析（t260907-05 仲裁归因）：物化器以插件名声明
  // fixture profile（patch id/node_modules 链），被测 bundle 以同一插件名注册模块——
  // 跨树错窗（主树旧版物化器写旧名 × 泳道新 bundle 注册新名）= dsh 加载器
  // 「loaded without registering …」客户端半挂载失败，横幅不出（M5「不在场」腿
  // 被环境错配捂成假绿，KI-051/046 同族）。泳道 profile/node_modules 五链在位后
  // （t260907-05 步5），本树 capture-lane 即可物化全量 temp profile——不再依赖主树。
  const captureLane = await import(pathToFileURL(join(
    REPO_ROOT, 'server', 'dsh', 'ui-check', 'capture-lane.mjs',
  )).href)
  await captureLane.buildTempProfile(tmpHome, fixtureWb)

  const userDsh = [process.env.DSH_HOME, join(process.env.HOME || '', '.dsh')]
    .filter(Boolean).find((d) => existsSync(join(d, '.credentials.yaml')))
  if (userDsh) copyFileSync(join(userDsh, '.credentials.yaml'), join(tmpHome, '.credentials.yaml'))
  const presetSrc = process.env.SANDBAR_CAPTURE_PRESET_SOURCE
    || join(process.env.HOME || '', '.dsh', '.agent-presets', 'suyou-integration')  // naming-compat
  const presetReject = captureLane.presetMaterializeRejectReason(presetSrc)
  if (presetReject) {
    const e = new Error(`preset 物化拒绝：${presetReject}（env SANDBAR_CAPTURE_PRESET_SOURCE 可指 preset 源）`)
    e.envFail = true
    throw e
  }
  await captureLane.materializePresets(tmpHome, presetSrc)

  const port = await freePort()
  if (port === 3099 || port === 7233) throw new Error('freePort 撞红线端口（概率≈0，命中即拒跑）')
  const logPath = join(tmpHome, 'console.log')
  const portPatch = join(tmpHome, 'port_patch.yml')
  writeFileSync(portPatch, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`)
  let logFd = null
  let proc = null

  async function start() {
    logFd = openSync(logPath, 'a')
    proc = spawn('dsh', ['--profile', 'suyou', '--patch', portPatch,
      '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        DSH_HOME: tmpHome,
        SANDBAR_TARGET_HOST: process.env.SANDBAR_T07_TARGET_HOST || '127.0.0.1:17233',
      },
      detached: true,
      stdio: ['ignore', logFd, logFd],
    })
    await waitReady(port, 90_000, logPath)
  }

  async function stopProc() {
    if (proc && proc.pid && proc.exitCode === null && proc.signalCode === null) {
      try { process.kill(-proc.pid, 'SIGTERM') } catch { try { proc.kill('SIGKILL') } catch { /* 已退 */ } }
      await new Promise((res) => {
        const t0 = Date.now()
        const t = setInterval(() => {
          if (proc.exitCode !== null || proc.signalCode !== null || Date.now() - t0 > 8000) {
            clearInterval(t); res()
          }
        }, 100)
      })
    }
    if (logFd !== null) { try { closeSync(logFd) } catch { /* 已关 */ } logFd = null }
  }

  async function teardown() {
    await stopProc()
    try { rmSync(tmpHome, { recursive: true, force: true }) } catch { /* 尽力删 */ }
  }

  return {
    tmpHome, fixtureRepo, fixtureWb, port, logPath,
    base: `http://127.0.0.1:${port}`,
    start,
    restart: async () => { await stopProc(); await start() },
    teardown,
  }
}

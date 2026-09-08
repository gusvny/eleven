#!/usr/bin/env node
// bench_console.mjs —— 隔离台 console boot 骨架薄壳（t260904-02，review C6）。
// 【t260904-19 退役注记】自搭进程舞台退役后，本壳只剩「boot 骨架自检」价值：
// 闸内/场景一律走 integration/stage_docker.py（docker 台单点入口）；本壳不再被
// 任何场景消费，保留仅供 boot 机制自检（buildTempProfile 仍服务 --boot-local
// 人工通路）。勿在闸内引用。
//
// 复用真源 server/ui-check/capture-lane.mjs（buildTempProfile /
// materializePresets / presetMaterializeRejectReason），不复制逻辑（双份必漂移）。
// 本壳提供 --selfcheck：临时 DSH_HOME + 凭据拷贝（若源在）+ pickFreePort×2 不等 +
// preset 物化（桩源）+ buildTempProfile + teardown 幂等二连。
//
// 与 suyou t260903-06 骨架的差异（落文明示）：骨架里 preset 不合=exit2 拒跑——
// 那是「场景门」语义；本 selfcheck 是**自检**，buildTempProfile 腿在泳道内缺
// profile/node_modules 时显式 [ENV_FAIL]（t260904-12 三态：缺环境=exit 2，
// 绝不 exit 0 假绿）并继续跑其余腿（原因必须打印，不静默），
// 合并回主树后（node_modules 在位）自检腿自然全量。
//
// 用法：node integration/bench_console.mjs --selfcheck
import { mkdtempSync, mkdirSync, existsSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = join(HERE, '..')
const CAPTURE_LANE = join(REPO_ROOT, 'server', 'ui-check', 'capture-lane.mjs')

const hardFails = []
let envFails = 0
const check = (ok, msg) => {
  console.log((ok ? 'ok    ' : 'FAIL  ') + msg)
  if (!ok) hardFails.push(msg)
}
const envFail = (msg) => { envFails++; console.log('[ENV_FAIL] ' + msg) }

function pickFreePort() {
  return new Promise((res, rej) => {
    const srv = createServer()
    srv.listen(0, '127.0.0.1', () => {
      const p = srv.address().port
      srv.close(() => res(p))
    })
    srv.on('error', rej)
  })
}

async function selfcheck() {
  const { buildTempProfile, materializePresets, presetMaterializeRejectReason } =
    await import(pathToFileURL(CAPTURE_LANE).href)

  const tmpHome = mkdtempSync(join(tmpdir(), 'sandbar-bench-selfcheck-'))
  let tornDown = false
  const teardown = () => {
    if (tornDown) return
    tornDown = true
    rmSync(tmpHome, { recursive: true, force: true })
  }
  process.on('exit', teardown)
  for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, () => { teardown(); process.exit(130) })
  }

  // ① 凭据只拷 .credentials.yaml（不拷 settings.yaml——3099 钉死防线，骨架原教训）
  const userDsh = process.env.DSH_HOME || join(process.env.HOME || '', '.dsh')
  const credSrc = join(userDsh, '.credentials.yaml')
  if (existsSync(credSrc)) {
    const dst = join(tmpHome, '.credentials.yaml')
    writeFileSync(dst, readFileSync(credSrc))
    check(existsSync(dst) && !existsSync(join(tmpHome, 'settings.yaml')),
      '凭据只拷 .credentials.yaml（settings.yaml 不在场——3099 钉死防线）')
  } else {
    envFail(`凭据源不在场（${credSrc}）——拷贝腿环境缺件（本机无 dsh 凭据不影响骨架自检）`)
  }

  // ② port-0 内核分配 ×2：端口有效且互不等
  const p1 = await pickFreePort()
  const p2 = await pickFreePort()
  check(Number.isInteger(p1) && p1 > 0 && Number.isInteger(p2) && p2 > 0 && p1 !== p2,
    `port-0 内核分配：p1=${p1} p2=${p2}（互不等）`)

  // ③ preset 物化（桩源：临时目录造最小 preset 实体）
  const presetSrc = join(tmpHome, 'preset-stub')
  mkdirSync(presetSrc, { recursive: true })
  writeFileSync(join(presetSrc, 'preset.yml'), '# stub\n')
  writeFileSync(join(presetSrc, 'agent.cordis.yml'), '# stub\n')
  check(presetMaterializeRejectReason(presetSrc) === null, 'preset 源校验（桩实体完整=可物化）')
  check(presetMaterializeRejectReason(join(tmpHome, 'nope')) !== null,
    'preset 源校验（缺源=拒因非空，安全侧失败）')
  const dstPreset = await materializePresets(tmpHome, presetSrc)
  check(existsSync(join(dstPreset, 'preset.yml')), 'preset 物化落地实体')

  // ④ buildTempProfile：泳道缺 profile/node_modules 时显式 ENV_FAIL（主树合并后自然全量）
  const laneWb = join(REPO_ROOT, 'server', 'plugins', 'workbench')
  const profileNm = join(REPO_ROOT, 'server', 'profile', 'node_modules')
  if (existsSync(profileNm)) {
    try {
      const profDir = await buildTempProfile(tmpHome, laneWb)
      check(existsSync(join(profDir, 'cordis.yml')), `buildTempProfile 全量（${profDir}）`)
    } catch (err) {
      check(false, `buildTempProfile 失败：${err?.message ?? err}`)
    }
  } else {
    envFail(`buildTempProfile 腿：泳道 profile/node_modules 不在场（${profileNm}）——` +
      `骨架逻辑在真源 capture-lane.mjs 未动，主树合并后本腿自然全量`)
  }

  // ⑤ teardown 幂等二连
  teardown()
  teardown()
  check(!existsSync(tmpHome), 'teardown 幂等二连：临时家已清且二次调用零异常')

  if (hardFails.length) {
    console.log(`SELFCHECK FAIL：${hardFails.length} 项未过（首因：${hardFails[0]}）`)
    process.exit(1)
  }
  if (envFails > 0) {
    console.log(`SELFCHECK ENV_FAIL：${envFails} 腿环境缺件未验成（已显式说明，非静默）——t260904-12 三态记环境红`)
    process.exit(2)
  }
  console.log('SELFCHECK PASS（console boot 骨架全腿验成）')
}

const mode = process.argv[2] || ''
if (mode === '--selfcheck') {
  await selfcheck()
} else {
  console.error('用法：node integration/bench_console.mjs --selfcheck')
  process.exit(2)
}

#!/usr/bin/env node
// bench_console.mjs — thin self-check shell for the isolated console boot path (ticket t260904-02).
// [Retired note t260904-19] Since the self-managed process stage was retired,
// this shell only has self-check value. Gates and scenarios all go through
// integration/stage_docker.py now; nothing consumes this shell, and it stays
// only so the boot mechanism can self-check (buildTempProfile still serves the
// manual --boot-local path). Do not reference it from inside the gate.
//
// It reuses the real source server/ui-check/capture-lane.mjs (buildTempProfile
// / materializePresets / presetMaterializeRejectReason) instead of copying
// logic — two copies always drift.
// --selfcheck runs: temp DSH_HOME + credential copy (if the source exists) +
// pickFreePort x2 distinct + preset materialization (stub source) +
// buildTempProfile + teardown idempotency twice.
//
// Difference from the t260903-06 skeleton (stated plainly): the skeleton
// refused to run (exit 2) when presets were missing — that was a "scenario
// gate" semantic. This selfcheck is a *self check*: when profile/node_modules
// is missing inside a lane, the buildTempProfile leg reports an explicit
// [ENV_FAIL] (three-state contract of t260904-12: missing environment =
// exit 2, never a fake green with exit 0) and the other legs keep running
// (the reason must be printed, never swallowed). After merging back to the
// main tree (node_modules present) the self-check legs run in full.
//
// Usage: node integration/bench_console.mjs --selfcheck
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

  // 1. Copy only .credentials.yaml (never settings.yaml — the hard 3099 guard, original lesson)
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

  // 2. Kernel port-0 allocation x2: both valid and distinct
  const p1 = await pickFreePort()
  const p2 = await pickFreePort()
  check(Number.isInteger(p1) && p1 > 0 && Number.isInteger(p2) && p2 > 0 && p1 !== p2,
    `port-0 内核分配：p1=${p1} p2=${p2}（互不等）`)

  // 3. Preset materialization (stub source: minimal preset entity in a temp dir)
  const presetSrc = join(tmpHome, 'preset-stub')
  mkdirSync(presetSrc, { recursive: true })
  writeFileSync(join(presetSrc, 'preset.yml'), '# stub\n')
  writeFileSync(join(presetSrc, 'agent.cordis.yml'), '# stub\n')
  check(presetMaterializeRejectReason(presetSrc) === null, 'preset 源校验（桩实体完整=可物化）')
  check(presetMaterializeRejectReason(join(tmpHome, 'nope')) !== null,
    'preset 源校验（缺源=拒因非空，安全侧失败）')
  const dstPreset = await materializePresets(tmpHome, presetSrc)
  check(existsSync(join(dstPreset, 'preset.yml')), 'preset 物化落地实体')

  // 4. buildTempProfile: explicit ENV_FAIL when the lane lacks profile/node_modules (full after merging to main)
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

  // 5. Teardown idempotent twice
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

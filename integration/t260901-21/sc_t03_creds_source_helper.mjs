#!/usr/bin/env node
/**
 * t260901-21 t03 —— creds-source.mjs（ui-check 凭据源解析）镜像用例。
 *
 * 与 t01（Python 侧真源）同口径：per-key 优先 / legacy 两级回落 / null / 畸形输入
 * （env 空串、相对路径、穿越 key、目录冒充文件）。全 tmp + env 桩，零网络。
 * 跑法：node integration/t260901-21/t03_creds_source_helper.mjs
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const helper = await import(pathToFileURL(
  path.resolve(path.dirname(new URL(import.meta.url).pathname),
    '../../server/ui-check/creds-source.mjs')).href)

let fails = 0
function check(name, cond, detail = '') {
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond || !detail ? '' : ' | ' + detail))
  if (!cond) fails++
}

const saved = {}
function setEnv(k, v) { saved[k] = process.env[k]; if (v === undefined) delete process.env[k]; else process.env[k] = v }
function restoreEnv() { for (const k of Object.keys(saved)) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; delete saved[k] } }

// tmp 场景
const tmp = mkdtempSync(path.join(tmpdir(), 't260901-21-t03-'))
const root = path.join(tmp, 'projects')
const dsh = path.join(tmp, 'dsh')
const home = path.join(tmp, 'home')
mkdirSync(root, { recursive: true }); mkdirSync(dsh, { recursive: true })
mkdirSync(path.join(home, '.dsh'), { recursive: true })

function perkey(key, content = 'version: 1\nrefs:\n  K: v\n') {
  const d = path.join(root, key)
  mkdirSync(d, { recursive: true })
  const p = path.join(d, 'credentials.yaml')
  writeFileSync(p, content)
  return p
}
function legacyDsh(content = 'version: 1\nrefs:\n  L: v\n') {
  const p = path.join(dsh, '.credentials.yaml')
  writeFileSync(p, content)
  return p
}
function legacyHome() {
  const p = path.join(home, '.dsh', '.credentials.yaml')
  writeFileSync(p, 'home-legacy\n')
  return p
}

try {
  setEnv('SANDBAR_PROJECTS_DIR', root)
  setEnv('DSH_HOME', dsh)
  setEnv('HOME', home)

  // 1. per-key 优先
  const pk = perkey('suyou'); legacyDsh()
  check('per-key 优先', helper.resolveCredentialsSource('suyou') === pk)
  check('perkeyIsHit 命中', helper.perkeyIsHit('suyou', helper.resolveCredentialsSource('suyou')))

  // 2. legacy 回落 DSH_HOME（per-key 移除 = 未迁移现场）
  rmSync(pk)
  check('回落 DSH_HOME', helper.resolveCredentialsSource('suyou') === legacyDsh())
  check('回落非 per-key 命中', !helper.perkeyIsHit('suyou', helper.resolveCredentialsSource('suyou')))

  // 3. 回落 $HOME/.dsh
  const lgHome = legacyHome()
  setEnv('DSH_HOME', undefined)
  check('回落 HOME/.dsh', helper.resolveCredentialsSource('suyou') === lgHome)
  setEnv('DSH_HOME', dsh)

  // 4. 两处皆无 → null
  const t4 = mkdtempSync(path.join(tmpdir(), 't260901-21-t03b-'))
  setEnv('SANDBAR_PROJECTS_DIR', path.join(t4, 'p'))
  setEnv('DSH_HOME', path.join(t4, 'd'))
  setEnv('HOME', path.join(t4, 'h'))
  mkdirSync(path.join(t4, 'd'), { recursive: true })
  check('两处皆无=null', helper.resolveCredentialsSource('suyou') === null)
  restoreEnv()
  setEnv('SANDBAR_PROJECTS_DIR', root); setEnv('DSH_HOME', dsh); setEnv('HOME', home)

  // 5. 空/非法 key → 跳过 per-key 走 legacy（=M1-2 前行为）
  const lg = legacyDsh()
  for (const bad of ['', '../etc', 'a/b', 'UPPER', 'suyou/../../x', 'x'.repeat(50)]) {
    check(`非法 key 拒绝：${bad || '空'}`, helper.resolveCredentialsSource(bad) === lg)
  }

  // 6. 目录冒充文件 → 回落
  mkdirSync(path.join(root, 'dirkey', 'credentials.yaml'), { recursive: true })
  check('目录冒充文件→回落', helper.resolveCredentialsSource('dirkey') === lg)

  // 7. env 空串/相对路径视为未设置
  setEnv('SANDBAR_PROJECTS_DIR', '')
  check('env 空串视为未设置', helper.resolveCredentialsSource('suyou') === lg)
  setEnv('SANDBAR_PROJECTS_DIR', 'relative/path')
  check('env 相对路径视为未设置', helper.resolveCredentialsSource('suyou') === lg)
  setEnv('SANDBAR_PROJECTS_DIR', root)

  // 8. DSH_HOME 空串剔除
  setEnv('DSH_HOME', '')
  const lgHome2 = legacyHome()
  check('DSH_HOME 空串剔除→HOME', helper.resolveCredentialsSource('suyou') === lgHome2)
} finally {
  restoreEnv()
}

console.log()
if (fails) { console.log(`FAILED: ${fails}`); process.exit(1) }
console.log('t03 all green')

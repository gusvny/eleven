#!/usr/bin/env node
/**
 * i03 —— 控制台截图台链路接线 + JS helper 行为冒烟（t260901-21）。
 *
 * 用户场景：UI 检查台（capture-lane 截图 / dbg-chat 调试）把用户凭据拷进临时隔离台
 * DSH_HOME——凭据出仓后，两台都应优先取项目目录 ~/.sandbar/projects/suyou/
 * credentials.yaml，没迁才回落 legacy 全局；若有人改回旧取源（绕开 creds-source.mjs），
 * 台子会静默用错真源，本测试守卫接线不回退。
 *
 * 三部分：
 *   A. helper 行为冒烟（fixture tmp root + env 桩）：per-key 优先 / legacy 回落 /
 *      null / 穿越 key / env 空串 / 目录冒充；
 *   B. 接线守卫：capture-lane.mjs 与 dbg-chat.mjs 都经 creds-source.mjs 取源且
 *      per-key 首选具名项目 key（capture-lane=t261005-16 起绑台内 capture-bench；dbg-chat=固定 suyou）、legacy 回落有提示日志；
 *   C. import 健全：两脚本 + helper 可被 node 解析（--check 等价的 ESM 语法校验走
 *      node:module strip？此处用动态 import helper 实跑代替；脚本本体 import 用
 *      源级断言）。
 *
 * 跑法：node integration/t260901-21/i03_ui_check_wiring.mjs（cwd=泳道根）
 * 全 tmp/env 桩，不读真 ~/.sandbar，零网络，不碰 3099。
 */

import { readFileSync } from 'node:fs'
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repo = join(here, '..', '..')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log('  ok ' + label) }
  else { fail++; console.log('  FAIL ' + label) }
}

// ---- A. helper 行为冒烟 ----
const tmp = mkdtempSync(join(tmpdir(), 't260901-21-i03-'))
const root = join(tmp, 'projects')
const dsh = join(tmp, 'dsh')
const home = join(tmp, 'home')
for (const d of [root, dsh, home]) mkdirSync(d, { recursive: true })
const saved = {}
for (const k of ['SANDBAR_PROJECTS_DIR', 'DSH_HOME', 'HOME']) {
  saved[k] = process.env[k]
  process.env[k] = { SANDBAR_PROJECTS_DIR: root, DSH_HOME: dsh, HOME: home }[k]
}
const credText = 'version: 1\nrefs: {}\n'

function perkey(key, kind = 'file') {
  mkdirSync(join(root, key), { recursive: true })
  const f = join(root, key, 'credentials.yaml')
  if (kind === 'file') writeFileSync(f, credText)
  else mkdirSync(f)
  return f
}
function legacy() {
  const f = join(dsh, '.credentials.yaml')
  writeFileSync(f, credText)
  return f
}

const mod = await import(join(repo, 'server', 'ui-check', 'creds-source.mjs'))

// per-key 优先（两级 legacy 同时在场）
const pk = perkey('suyou'); const lg = legacy()
const homeLegacy = join(home, '.dsh'); mkdirSync(homeLegacy, { recursive: true })
writeFileSync(join(homeLegacy, '.credentials.yaml'), credText)
ok(mod.resolveCredentialsSource('suyou') === pk, 'A1 per-key 命中优先（两级 legacy 在场）')

// per-key 缺失 → DSH_HOME legacy
ok(mod.resolveCredentialsSource('other') === lg, 'A2 无 per-key 条目回落 DSH_HOME legacy')

// 两级皆无 → null（用无 per-key 条目的 key；suyou 的 per-key 文件在场会优先命中）
const saveDsh = process.env.DSH_HOME
delete process.env.DSH_HOME
ok(mod.resolveCredentialsSource('other') === join(homeLegacy, '.credentials.yaml'),
   'A3 DSH_HOME 未设回落 HOME/.dsh legacy')
process.env.DSH_HOME = saveDsh
{
  // 注意：不删 HOME——删了 homedir() 会落回真用户家目录（真机 ~/.dsh 常有真凭据，
  // 「两处皆无」就测不出来）；改为指空目录桩。
  const s1 = process.env.DSH_HOME; const s2 = process.env.HOME
  const emptyDsh = mkdtempSync(join(tmpdir(), 't260901-21-i03-empty-dsh-'))
  const emptyHome = mkdtempSync(join(tmpdir(), 't260901-21-i03-empty-home-'))
  process.env.DSH_HOME = emptyDsh; process.env.HOME = emptyHome
  ok(mod.resolveCredentialsSource('other') === null, 'A4 两处皆无 = null（不拷）')
  if (s1 !== undefined) process.env.DSH_HOME = s1
  if (s2 !== undefined) process.env.HOME = s2
}

// 空 project_key = 跳过 per-key 走 legacy（现行为不变）
ok(mod.resolveCredentialsSource('') === lg, 'A5 空 project_key 走 legacy')

// 穿越 / 斜杠 / 大写 key 拒 per-key
ok(mod.resolveCredentialsSource('../escape') === lg, 'A6 穿越 key 拒 per-key')
ok(mod.resolveCredentialsSource('a/b') === lg, 'A7 斜杠 key 拒 per-key')
ok(mod.resolveCredentialsSource('Suyou') === lg, 'A8 大写 key 拒 per-key')

// 目录冒充文件不算命中
{
  const d = perkey('dirkey', 'dir')
  ok(mod.resolveCredentialsSource('dirkey') === lg, 'A9 目录冒充 credentials.yaml 回落（' + d + ' 不算）')
}

// env 空串视为未设置
{
  const s = process.env.SANDBAR_PROJECTS_DIR
  process.env.SANDBAR_PROJECTS_DIR = ''
  ok(mod.resolveCredentialsSource('suyou') === lg, 'A10 SANDBAR_PROJECTS_DIR 空串视为未设置')
  if (s !== undefined) process.env.SANDBAR_PROJECTS_DIR = s
}

// 白名单同款导出在位（与 project-registry.ts 同款口径的锚点）
ok(mod.PROJECT_KEY_RE instanceof RegExp && !mod.PROJECT_KEY_RE.test('Suyou') && mod.PROJECT_KEY_RE.test('a-b-1'),
   'A11 PROJECT_KEY_RE 导出且口径正确')

// ---- B. 接线守卫 ----
// B2 契约更新（t261005-16）：capture-lane 的 per-key 首查改绑台内项目
// BENCH_PROJECT_KEY（capture-bench，经常量引用非裸串）——不再绑定历史 suyou 项目；
// dbg-chat.mjs 的固定服务对象不变仍为 suyou。两台都保留 perkeyIsHit 迁移提示。
const lane = readFileSync(join(repo, 'server', 'ui-check', 'capture-lane.mjs'), 'utf8')
const dbg = readFileSync(join(repo, 'server', 'ui-check', 'dbg-chat.mjs'), 'utf8')
for (const [name, src, keySrc] of [
  ['capture-lane.mjs', lane, 'resolveCredentialsSource(BENCH_PROJECT_KEY)'],
  ['dbg-chat.mjs', dbg, 'resolveCredentialsSource("suyou")'],
]) {
  ok(src.includes("from './creds-source.mjs'") || src.includes('from "./creds-source.mjs"'),
     'B1 ' + name + ' 经 creds-source.mjs 取源（未绕开真源逻辑）')
  ok(src.includes(keySrc),
     'B2 ' + name + ' per-key 首选绑定具名项目 key（capture-lane=台内 capture-bench / dbg-chat=固定 suyou）')
  ok(src.includes('perkeyIsHit('),
     'B3 ' + name + ' legacy 回落带迁移提示判定（perkeyIsHit）')
}

// ---- C. 还原 env ----
for (const k of Object.keys(saved)) {
  if (saved[k] === undefined) delete process.env[k]
  else process.env[k] = saved[k]
}

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`)
process.exit(fail ? 1 : 0)

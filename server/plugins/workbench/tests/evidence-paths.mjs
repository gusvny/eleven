#!/usr/bin/env node
/**
 * evidence-paths.mjs —— 证据读路径新名迁移 L1 白盒自测（t260910-05）。
 *
 * 直跑：node tests/evidence-paths.mjs（node ≥22.18 原生 type-stripping）。
 *
 * 层次归属（review_plan R1③ 定口径）：本文件=L1 细粒度白盒——containment 逐层、
 * 畸形输入逐类、env 独占语义；**不作契约网**。契约网=integration/baselines/
 * sc_ticket_evidence_images.mjs（闸上黑盒三态）。
 *
 * 覆盖（对照方案验收口径）：
 *   A. 新名主腿：.lane/<id>/.sandbar/screenshots 可读可列，怪名/非 png 滤除。
 *   B. 旧名回落腿：仅 .lane/<id>/.suyou/screenshots 时仍命中（naming-compat）。
 *   C. 新旧并存去重：同名文件两代点目录并存只计一次；异名并集。
 *   D. 归档两代并存：.sandbar/evidence 与 .suyou/evidence 并存去重。
 *   E. env 独占替换（C1）：SANDBAR_EVIDENCE_DIR 在场=归档仅 env 一处，不枚举默认目录。
 *   F. 老泳道根回落：.worktrees/<id> 两代点目录。
 *   G. containment 形状：候选面结构（env 无/有）、containRoot 与 dir 的包含关系。
 *   H. 畸形输入：穿路径 id / 含点 id / 含斜杠 id → 空列表不抛。
 *   I. 缺目录软降级：全候选不存在 → []（枚举语义无 404）。
 */

import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { listEvidenceFiles, evidenceCandidateDirs } from './../node.ts'

let passed = 0, failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function makeRoot() {
  return mkdtempSync(join(tmpdir(), 'evidence-paths-'))
}
function seed(...segs) {
  const file = join(...segs)
  mkdirSync(join(file, '..'), { recursive: true })
  writeFileSync(file, Buffer.from('89504e470d0a1a0a', 'hex')) // PNG 魔数头即可（列表端点只滤名不验字节）
}

// A. 新名泳道主腿
{
  const root = makeRoot()
  const id = 't26091005a'
  seed(root, '.lane', id, '.sandbar', 'screenshots', 'a.png')
  seed(root, '.lane', id, '.sandbar', 'screenshots', 'notes.txt')      // 非 png 滤除
  seed(root, '.lane', id, '.sandbar', 'screenshots', 'weird name.png') // 怪名滤除
  ok(JSON.stringify(await listEvidenceFiles(id, root, null)) === '["a.png"]',
    'A 新名泳道 .sandbar/screenshots 可读可列（怪名/非 png 滤除）')
  rmSync(root, { recursive: true, force: true })
}

// B. 旧名泳道回落（仅旧名在场）
{
  const root = makeRoot()
  const id = 't26091005b'
  seed(root, '.lane', id, '.suyou', 'screenshots', 'b.png')
  ok(JSON.stringify(await listEvidenceFiles(id, root, null)) === '["b.png"]',
    'B 仅旧名 .suyou/screenshots 回落命中（naming-compat）')
  rmSync(root, { recursive: true, force: true })
}

// C. 新旧并存去重
{
  const root = makeRoot()
  const id = 't26091005c'
  seed(root, '.lane', id, '.sandbar', 'screenshots', 'd.png')
  seed(root, '.lane', id, '.suyou', 'screenshots', 'd.png')  // 同名两代并存
  seed(root, '.lane', id, '.suyou', 'screenshots', 'e.png')  // 仅旧名的异名
  ok(JSON.stringify(await listEvidenceFiles(id, root, null)) === '["d.png","e.png"]',
    'C 新旧并存同名去重只计一次，异名并集')
  rmSync(root, { recursive: true, force: true })
}

// D. 归档两代并存
{
  const root = makeRoot()
  const id = 't26091005d'
  seed(root, '.sandbar', 'evidence', id, 'e1.png')
  seed(root, '.suyou', 'evidence', id, 'e1.png')
  seed(root, '.suyou', 'evidence', id, 'e2.png')
  ok(JSON.stringify(await listEvidenceFiles(id, root, null)) === '["e1.png","e2.png"]',
    'D 归档 .sandbar/evidence 新名命中，与 .suyou/evidence 并存去重')
  rmSync(root, { recursive: true, force: true })
}

// E. env 独占替换（C1）：env 在场不枚举默认目录
{
  const root = makeRoot()
  const envBase = mkdtempSync(join(tmpdir(), 'evidence-env-'))
  const id = 't26091005e'
  seed(envBase, id, 'f.png')
  seed(root, '.sandbar', 'evidence', id, 'a.png')  // 真仓默认目录也有证据
  seed(root, '.suyou', 'evidence', id, 'old.png')
  ok(JSON.stringify(await listEvidenceFiles(id, root, envBase)) === '["f.png"]',
    'E1 env 在场=归档仅 env 一处（独占替换，不读真仓默认目录）')
  ok(JSON.stringify(await listEvidenceFiles(id, root, null)) === '["a.png","old.png"]',
    'E2 env 缺省=两代归档目录并读（新名在前去重）')
  rmSync(root, { recursive: true, force: true })
  rmSync(envBase, { recursive: true, force: true })
}

// F. 老泳道根 .worktrees 两代点目录
{
  const root = makeRoot()
  const id = 't26091005f'
  seed(root, '.worktrees', id, '.sandbar', 'screenshots', 'g.png')
  ok(JSON.stringify(await listEvidenceFiles(id, root, null)) === '["g.png"]',
    'F1 老泳道根新名 .worktrees/<id>/.sandbar/screenshots 命中')
  rmSync(root, { recursive: true, force: true })
  const root2 = makeRoot()
  seed(root2, '.worktrees', id, '.suyou', 'screenshots', 'h.png')
  ok(JSON.stringify(await listEvidenceFiles(id, root2, null)) === '["h.png"]',
    'F2 老泳道根旧名 .worktrees/<id>/.suyou/screenshots 回落命中')
  rmSync(root2, { recursive: true, force: true })
}

// G. containment 候选面形状
{
  const root = makeRoot()
  const id = 't26091005g'
  const cDefault = evidenceCandidateDirs(root, null, id)
  ok(cDefault.length === 6, `G1 env 缺省候选面=6（归档2+泳道4），实得 ${cDefault.length}`)
  ok(cDefault[0].dir === join(root, '.sandbar', 'evidence', id)
    && cDefault[0].containRoot === join(root, '.sandbar'),
    'G2 首候选=归档新名，containRoot=点目录根（词法纵深基准）')
  ok(cDefault.every(c => c.dir.startsWith(c.containRoot + (process.platform === 'win32' ? '\\' : '/'))),
    'G3 每候选 dir 均落在自己 containRoot 内（startsWith + sep）')
  const cEnv = evidenceCandidateDirs(root, '/tmp/env-only', id)
  ok(cEnv.length === 5 && cEnv[0].dir === join('/tmp/env-only', id)
    && !cEnv.some(c => c.dir.startsWith(join(root, '.sandbar')) || c.dir.startsWith(join(root, '.suyou'))),
    'G4 env 在场候选面=5（归档仅 env 一处+泳道4），默认归档目录不进候选')
  ok(cEnv.slice(1).every(c => c.dir.startsWith(root)),
    'G5 env 只换归档腿，泳道/老泳道腿仍随项目根（不受 env 影响）')
  rmSync(root, { recursive: true, force: true })
}

// H. 畸形输入（穿路径/含点/含斜杠/超长）→ 空列表不抛
{
  const root = makeRoot()
  for (const [label, id] of [
    ['dotdot-parent', '../etc'],
    ['dotdot-inside', '..'],
    ['slash', 'a/b'],
    ['dot', 'x.y'],
    ['oversize', 't'.repeat(200)],
  ]) {
    let r = null
    try { r = await listEvidenceFiles(id, root, null) } catch (e) { r = `THREW:${e.message}` }
    ok(Array.isArray(r) && r.length === 0, `H 畸形 id（${label}）→ [] 不抛`)
  }
  rmSync(root, { recursive: true, force: true })
}

// I. 缺目录软降级
{
  const root = makeRoot()
  ok(JSON.stringify(await listEvidenceFiles('t26091005i', root, null)) === '[]',
    'I 全候选目录不存在 → []（枚举语义无 404）')
  rmSync(root, { recursive: true, force: true })
}

console.log(`EVIDENCE-PATHS pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)

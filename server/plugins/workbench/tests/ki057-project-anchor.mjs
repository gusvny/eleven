#!/usr/bin/env node
/**
 * ki057-project-anchor.mjs —— 工单台 host 项目锚解析器＋穿参纯函数层自测
 * （t260907-11 KI-057，S1/S2 面；方案=stage_create_plan_gen2）。
 *
 * 直跑：node tests/ki057-project-anchor.mjs（node ≥22.18 原生 type-stripping）。
 * 覆盖（对照方案 S1/S2 验收口径，硬性畸形输入用例齐备）：
 *   A. resolveProjectAnchor 纯逻辑（find 注入桩）：缺省回落 / 合法 key→primaryDir /
 *      未知 key→400 / 隔离条目 throw→502 / 注册表装载异常→502 / primaryDir 空串→502 /
 *      畸形 key 类型（数字/对象）→视同缺省。
 *   B. 真注册表 fixture（SANDBAR_PROJECTS_DIR temp）：sandbar/fpv 双条目解析＋坏条目隔离回落。
 *   C. env 覆盖闸红线：SANDBAR_EPICS_DIR / SANDBAR_EVIDENCE_DIR / SANDBAR_EPIC_NEXT_DIR
 *      仅默认仓锚生效，项目锚恒 root 拼接（防串味）。
 *   D. computeTicketDiff 按项目根判界（防穿越闸语义不弱化）：项目根内泳道放行
 *      （KI-057 实报修复点）/ ../ 穿越仍拒 / 根外绝对路径仍拒 / 同 worktree 在引擎
 *      仓锚下仍拒（判界基准随锚走，闸本身一行未改）。
 *   E. listEvidenceFiles 项目根＋env 闸：双候选枚举随项目根、穿越 id 拒、
 *      默认锚吃 env、项目锚无视 env。
 */

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { resolveProjectAnchor, anchorEpicsDir, anchorEvidenceBase, anchorEpicNextDir, resolvedMark } from './../src/host/project-anchor.ts'
import { computeTicketDiff } from './../src/host/changes.ts'
import { listEvidenceFiles } from './../node.ts'

let passed = 0, failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const FALLBACK = '/engine/repo'
const FIND_OK = (k) => (k === 'fpv' ? { key: 'fpv', name: 'fpv', dirs: ['/fpv/primary', '/fpv/alt'] } : k === 'empty' ? { key: 'empty', name: '', dirs: [] } : undefined)
const FIND_THROW = () => { throw new Error('项目 bad 注册条目已隔离：/reg/bad：坏 yaml') }

section('A resolveProjectAnchor 纯逻辑（注入桩）')
{
  const d = resolveProjectAnchor('', FALLBACK, FIND_OK)
  ok(d.ok && d.source === 'default' && d.root === FALLBACK && d.key === null, '空 key → 默认仓回落')
  const d2 = resolveProjectAnchor('   ', FALLBACK, FIND_OK)
  ok(d2.ok && d2.source === 'default', '空白 key → 默认仓回落')
  const d3 = resolveProjectAnchor(42, FALLBACK, FIND_OK)
  ok(d3.ok && d3.source === 'default', '数字 key（畸形）→ 视同缺省')
  const d4 = resolveProjectAnchor({ a: 1 }, FALLBACK, FIND_OK)
  ok(d4.ok && d4.source === 'default', '对象 key（畸形）→ 视同缺省')
  const p = resolveProjectAnchor('fpv', FALLBACK, FIND_OK)
  ok(p.ok && p.source === 'project' && p.root === '/fpv/primary' && p.key === 'fpv', '合法 key → primaryDir（dirs[0]）')
  const u = resolveProjectAnchor('nosuch', FALLBACK, FIND_OK)
  ok(!u.ok && u.status === 400 && (u.error ?? '').includes('未知项目 key'), '未知 key → 显式 400（不静默回落）')
  const q = resolveProjectAnchor('bad', FALLBACK, FIND_THROW)
  ok(!q.ok && q.status === 502 && (q.error ?? '').includes('已隔离'), '隔离条目 throw → 502 透传原文')
  const e = resolveProjectAnchor('empty', FALLBACK, FIND_OK)
  ok(!e.ok && e.status === 502 && (e.error ?? '').includes('主目录'), 'primaryDir 空串 → 502 拒回落')
  ok(typeof resolvedMark(p).root === 'string' && resolvedMark(d).source === 'default', 'resolvedMark 形状（source/key/root）')
}

section('B 真注册表 fixture（SANDBAR_PROJECTS_DIR temp）')
const B_ROOT = '/tmp-wb-fpv-repo'
{
  const reg = mkdtempSync(join(tmpdir(), 'wb-anchor-reg-'))
  process.env.SANDBAR_PROJECTS_DIR = reg
  delete process.env.SANDBAR_PROJECTS_YAML
  const entry = (key, dir) =>
    `# 注释\nschema: v1\n\nproject:\n  - key: ${key}\n    name: ${key}名\n    dirs:\n      - ${dir}\n`
  mkdirSync(join(reg, 'sandbar'), { recursive: true })
  writeFileSync(join(reg, 'sandbar', 'project.yaml'), entry('sandbar', B_ROOT), 'utf8')
  mkdirSync(join(reg, 'fpv'), { recursive: true })
  writeFileSync(join(reg, 'fpv', 'project.yaml'), entry('fpv', '/tmp-wb-fpv-primary'), 'utf8')
  mkdirSync(join(reg, 'broken'), { recursive: true })
  writeFileSync(join(reg, 'broken', 'project.yaml'), 'dirs:\n  - 相对路径不是绝对\n', 'utf8')

  const a = resolveProjectAnchor('sandbar', FALLBACK)
  ok(a.ok && a.source === 'project' && a.root === B_ROOT, '真注册表：sandbar key → fixture 主目录')
  const b = resolveProjectAnchor('fpv', FALLBACK)
  ok(b.ok && b.root === '/tmp-wb-fpv-primary', '真注册表：fpv key → 其主目录')
  const c = resolveProjectAnchor('broken', FALLBACK)
  ok(!c.ok && c.status === 502, '真注册表：坏条目（隔离）→ 502')
  const e = resolveProjectAnchor('zzz', FALLBACK)
  ok(!e.ok && e.status === 400, '真注册表：未知 key → 400')
  delete process.env.SANDBAR_PROJECTS_DIR
}

section('C env 覆盖闸（红线：旧 env 链保留，仅默认仓锚生效）')
{
  process.env.SANDBAR_EPICS_DIR = '/env/epics'
  process.env.SANDBAR_EVIDENCE_DIR = '/env/evidence'
  process.env.SANDBAR_EPIC_NEXT_DIR = '/env/epic-next'
  const def = resolveProjectAnchor('', FALLBACK, FIND_OK)
  ok(anchorEpicsDir(def) === '/env/epics', '默认锚：SANDBAR_EPICS_DIR 生效（旧链保留）')
  ok(anchorEvidenceBase(def) === '/env/evidence', '默认锚：SANDBAR_EVIDENCE_DIR 生效')
  ok(anchorEpicNextDir(def) === '/env/epic-next', '默认锚：SANDBAR_EPIC_NEXT_DIR 生效')
  const proj = resolveProjectAnchor('fpv', FALLBACK, FIND_OK)
  ok(anchorEpicsDir(proj) === '/fpv/primary/notes/epics', '项目锚：epics 目录随项目根，env 不透出')
  ok(anchorEvidenceBase(proj) === '/fpv/primary/.suyou/evidence', '项目锚：证据基目录随项目根')
  ok(anchorEpicNextDir(proj) === '/fpv/primary/.suyou/epic-next', '项目锚：作业根随项目根')
  delete process.env.SANDBAR_EPICS_DIR
  delete process.env.SANDBAR_EVIDENCE_DIR
  delete process.env.SANDBAR_EPIC_NEXT_DIR
  ok(anchorEvidenceBase(def) === join(FALLBACK, '.suyou', 'evidence'), '默认锚：env 缺省回 <repo>/.suyou/evidence（行为不变）')
}

/* ------------------------------------------------ D/E：fixture 仓＋证据目录 */

function git(args, cwd) {
  return execFileSync('git', ['-C', cwd, ...args], { stdio: ['ignore', 'pipe', 'pipe'] }).toString()
}

const tmp = mkdtempSync(join(tmpdir(), 'wb-anchor-'))
const engineRepo = join(tmp, 'engine')     // 引擎仓（sandbar 默认仓视角）
const fpvRepo = join(tmp, 'fpv')           // fpv 项目主目录（KI-057 实报视角）
for (const repo of [engineRepo, fpvRepo]) {
  mkdirSync(join(repo, 'docs'), { recursive: true })
  writeFileSync(join(repo, 'docs/a.md'), '# 基线\n\n正文。\n', 'utf8')
  git(['init', '-q', '-b', 'main'], repo)
  git(['add', '.'], repo)
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'base'], repo)
}
git(['worktree', 'add', '.worktrees/wt', '-b', 'lane/t-fpv-1'], fpvRepo)
writeFileSync(join(fpvRepo, '.worktrees/wt/docs/a.md'), '# 基线\n\n改过的正文。\n', 'utf8')

section('D computeTicketDiff 按项目根判界（闸一行未改，基准随锚走）')
{
  const base = git(['rev-parse', 'HEAD'], fpvRepo).trim()
  // KI-057 实报修复点：fpv 泳道在 fpv 仓根内——引擎仓锚下判「越出仓库根」，项目锚下放行。
  // 票面 worktree 是绝对路径（引擎仓外的 fpv 泳道）——resolve 到引擎锚外 → 闸拒（实报形态）。
  const rEngineAnchor = await computeTicketDiff(engineRepo, { id: 't-fpv-1', worktree: join(fpvRepo, '.worktrees/wt'), base_ref: base })
  ok(rEngineAnchor.source === 'none' && (rEngineAnchor.emptyReason ?? '').includes('越出仓库根'), '引擎仓锚（旧行为）：fpv 泳道被闸拒——复现实报')
  const rFpv = await computeTicketDiff(fpvRepo, { id: 't-fpv-1', worktree: '.worktrees/wt', base_ref: base })
  ok(rFpv.source === 'worktree' && rFpv.changed === true, '项目根锚：fpv 泳道 diff 放行（实报修复）')
  ok(rFpv.files.some(f => f.path === 'docs/a.md'), '变更集含改文件')
  // 闸语义不弱化三态：../ 穿越仍拒
  const rDotDot = await computeTicketDiff(fpvRepo, { id: 't-x1', worktree: '../outside', base_ref: base })
  ok(rDotDot.source === 'none' && (rDotDot.emptyReason ?? '').includes('越出仓库根'), '../ 穿越仍拒（闸未弱化）')
  const rAbs = await computeTicketDiff(fpvRepo, { id: 't-x2', worktree: engineRepo, base_ref: base })
  ok(rAbs.source === 'none' && (rAbs.emptyReason ?? '').includes('越出仓库根'), '根外绝对路径仍拒（闸未弱化）')
}

section('E listEvidenceFiles 项目根＋env 闸')
{
  const id = 't-fpv-2'
  mkdirSync(join(fpvRepo, '.suyou', 'evidence', id), { recursive: true })
  writeFileSync(join(fpvRepo, '.suyou', 'evidence', id, 'archived.png'), 'png', 'utf8')
  mkdirSync(join(fpvRepo, '.worktrees', id, '.suyou', 'screenshots'), { recursive: true })
  writeFileSync(join(fpvRepo, '.worktrees', id, '.suyou', 'screenshots', 'live.png'), 'png', 'utf8')
  process.env.SANDBAR_EVIDENCE_DIR = '/env-evidence-does-not-exist'
  const rProj = await listEvidenceFiles(id, fpvRepo, null)
  ok(rProj.includes('archived.png') && rProj.includes('live.png'), '项目锚：归档+泳道双候选随项目根')
  const rDef = await listEvidenceFiles(id, FALLBACK)
  ok(rDef.length === 0, '默认锚：吃 env（指向不存在目录 → 空列表，旧行为）')
  delete process.env.SANDBAR_EVIDENCE_DIR
  const rBad = await listEvidenceFiles('../evil', fpvRepo, null)
  ok(Array.isArray(rBad) && rBad.length === 0, '穿越 id → 空列表（防穿不弱化）')
}

console.log(`\nKI057_PROJECT_ANCHOR pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)

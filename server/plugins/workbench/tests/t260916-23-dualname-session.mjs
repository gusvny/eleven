/**
 * t260916-23-dualname-session.mjs —— 会话文件双名兼容 workbench 面 UT（epic dsh-upgrade T1）。
 *
 * 覆盖：
 *  A. session-discovery 常量形状与发现/pick 五态（仅旧 / 仅新 / 双名 mtime 双方向 + 平局 /
 *     皆无 / 畸形：同名目录、stat 失败候选）；
 *  B. resolveAllSessionFiles：双名并存目录只返回一份（mtime 最新，不双计）、仅旧照旧、
 *     零会话文案双名并列表述、防穿不变；
 *  C. resolveSessionFile：同目录两代取最新、exact 角色优先不变、同 mtime 平局旧名优先、
 *     零会话文案双名；
 *  D. _sessionKbFast：仅新名目录可探活（工单列表徽标不因换名静默恒 0——t260825-03 同族坑）。
 *
 * Run: node server/plugins/workbench/tests/t260916-23-dualname-session.mjs  (cwd = repo root)
 */
import { mkdir, mkdtemp, rm, utimes, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { projectDirKey, resolveSessionFile } from '../src/host/agent-live.ts'
import { resolveAllSessionFiles } from '../src/host/agent-usage.ts'
import { _sessionKbFast } from '../src/host/agent-logs.ts'
import {
  SESSION_FILE_NAMES, existingSessionFilesIn, pickNewestSessionFile,
} from '../src/host/session-discovery.ts'

let PASS = 0, FAIL = 0
function ok(cond, label, detail = '') {
  if (cond) { PASS++; console.log('  ok  ' + label) }
  else { FAIL++; console.log('  FAIL ' + label + (detail ? ' | ' + String(detail).slice(0, 300) : '')) }
}
function section(t) { console.log(`\n== ${t}`) }

const OLD = SESSION_FILE_NAMES[0]
const NEW = SESSION_FILE_NAMES[1]

const tmp = await mkdtemp(join(tmpdir(), 'wb-dualname-'))
try {
  /* ---------------------------------------------- A. helper 五态 */
  section('A session-discovery 常量与发现/pick 五态')
  ok(OLD === 'session.jsonl.zstd' && NEW === 'session.v3.jsonl.zstd', '常量形状：旧代在前、新代在后')

  {
    const dir = join(tmp, 'd1')
    await mkdir(dir)
    await writeFile(join(dir, OLD), 'x')
    ok((await existingSessionFilesIn(dir)).length === 1, '仅旧名：发现一份')
    ok(await pickNewestSessionFile(await existingSessionFilesIn(dir)) === join(dir, OLD), '仅旧名：pick=旧名（现状基线）')
  }
  {
    const dir = join(tmp, 'd2')
    await mkdir(dir)
    await writeFile(join(dir, NEW), 'x')
    ok(await pickNewestSessionFile(await existingSessionFilesIn(dir)) === join(dir, NEW), '仅新名：pick=新名')
  }
  {
    const dir = join(tmp, 'd3')
    await mkdir(dir)
    await writeFile(join(dir, OLD), 'old')
    await writeFile(join(dir, NEW), 'new')
    await utimes(join(dir, OLD), 1000, 1000)
    await utimes(join(dir, NEW), 2000, 2000)
    ok(await pickNewestSessionFile(await existingSessionFilesIn(dir)) === join(dir, NEW), '双名：新 mtime 新 → 新名')
    await utimes(join(dir, OLD), 3000, 3000)
    ok(await pickNewestSessionFile(await existingSessionFilesIn(dir)) === join(dir, OLD), '双名：旧 mtime 新 → 旧名（语义=取最新，不偏袒新代）')
    await utimes(join(dir, OLD), 2000, 2000)
    ok(await pickNewestSessionFile(await existingSessionFilesIn(dir)) === join(dir, OLD), '双名：mtime 平局 → 旧名优先')
  }
  {
    const dir = join(tmp, 'd4')
    await mkdir(dir)
    const found = await existingSessionFilesIn(dir)
    ok(found.length === 0 && (await pickNewestSessionFile(found)) === null, '皆无：空集 + null')
  }
  {
    const dir = join(tmp, 'd5')
    await mkdir(join(dir, NEW), { recursive: true })
    ok((await existingSessionFilesIn(dir)).length === 0, '畸形：session.v3.jsonl.zstd 是目录 → 不入发现集')
    ok(await pickNewestSessionFile([join(tmp, 'nope', OLD), join(tmp, 'd1', OLD)]) === join(tmp, 'd1', OLD), '畸形：stat 失败候选跳过')
  }

  /* ---------------------------------------------- B. resolveAllSessionFiles */
  section('B resolveAllSessionFiles：双名并存单份 + 文案 + 防穿')
  const repo = join(tmp, 'repo')
  const wt = join(repo, '.worktrees', 'wt')
  const slug = projectDirKey(wt)
  const sessDir = join(wt, '.dsh', 'sessions', slug)
  await mkdir(join(sessDir, 't-d-developer'), { recursive: true })
  await writeFile(join(sessDir, 't-d-developer', OLD), 'old')
  await writeFile(join(sessDir, 't-d-developer', NEW), 'new')
  await utimes(join(sessDir, 't-d-developer', OLD), 1000, 1000)
  await utimes(join(sessDir, 't-d-developer', NEW), 2000, 2000)
  await mkdir(join(sessDir, 't-d-integration'), { recursive: true })
  await writeFile(join(sessDir, 't-d-integration', OLD), 'old2')
  await utimes(join(sessDir, 't-d-integration', OLD), 500, 500)

  const rAll = await resolveAllSessionFiles(repo, 't-d', { worktree: '.worktrees/wt' })
  ok(rAll.refused === undefined && rAll.paths.length === 2,
    `双名并存目录只取一份 + 仅旧目录一份（实得 ${rAll.paths.length}）`, JSON.stringify(rAll.paths))
  ok(rAll.paths.some(p => p.endsWith(NEW)), 'developer 目录取新代')
  ok(!rAll.paths.some(p => p === join(sessDir, 't-d-developer', OLD)), 'developer 目录旧代不双计')

  const rNone = await resolveAllSessionFiles(repo, 't-absent', { worktree: '.worktrees/wt' })
  ok(rNone.paths.length === 0 && (rNone.reason ?? '').includes(OLD) && (rNone.reason ?? '').includes(NEW),
    '零会话文案双名并列表述', rNone.reason)
  const rEsc = await resolveAllSessionFiles(repo, 't-d', { worktree: '..' })
  ok(rEsc.refused === true && (rEsc.reason ?? '').includes('越界'), '防穿不变：.. 越界 refused')

  /* ---------------------------------------------- C. resolveSessionFile */
  section('C resolveSessionFile：最新/角色/平局/文案')
  const r1 = await resolveSessionFile(repo, 't-d', { worktree: '.worktrees/wt' })
  ok(r1.path !== undefined && r1.path.endsWith(NEW), '无 role：两代候选取 mtime 最新（新代）', r1.path)
  const r2 = await resolveSessionFile(repo, 't-d', { worktree: '.worktrees/wt', role: 'integration' })
  ok(r2.path !== undefined && r2.path.includes('t-d-integration') && r2.path.endsWith(OLD),
    'exact 角色优先不变（旧代文件照常命中）', r2.path)
  await utimes(join(sessDir, 't-d-developer', OLD), 2000, 2000)  // 与新代拉平
  const r3 = await resolveSessionFile(repo, 't-d', { worktree: '.worktrees/wt' })
  ok(r3.path !== undefined && r3.path.endsWith(OLD), '同 mtime 平局 → 旧名优先（与 py 侧口径一致）', r3.path)
  const r4 = await resolveSessionFile(repo, 't-nope', { worktree: '.worktrees/wt' })
  ok(r4.path === undefined && (r4.reason ?? '').includes(NEW), '零会话文案双名', r4.reason)

  /* ---------------------------------------------- D. _sessionKbFast 仅新名 */
  section('D _sessionKbFast：仅新名目录可探活')
  const wt2 = join(tmp, 'wt2')
  const slug2 = projectDirKey(wt2)
  const sess2 = join(wt2, '.dsh', 'sessions', slug2, 't-e-developer')
  await mkdir(sess2, { recursive: true })
  const fresh = Date.now() / 1000 - 10
  await writeFile(join(sess2, NEW), 'z'.repeat(4096))
  await utimes(join(sess2, NEW), fresh, fresh)
  const kb = await _sessionKbFast(join(wt2, '.dsh', 'sessions'))
  ok(kb.kb === 4 && kb.path.endsWith(NEW), '仅新名目录：KB 徽标可探（换名不静默恒 0）', JSON.stringify(kb))
  ok(kb.alive === true, '新名会话新鲜 mtime → alive')

  console.log(`\nSUMMARY pass=${PASS} fail=${FAIL}`)
  process.exitCode = FAIL === 0 ? 0 : 1
} catch (err) {
  console.error('FATAL', err)
  process.exitCode = 1
} finally {
  await rm(tmp, { recursive: true, force: true })
}

#!/usr/bin/env node
/**
 * sc_t260911_01_multirepo_diff_faces.mjs —— t260911-01 场景①（dengzhufpv 260910 缺陷 2a/2b 回归面）：
 * 多仓票 diff 面逐仓可见 + 过程物过滤点名 + 单仓退化零回归 + 畸形明细不炸。
 *
 * intent（用户可感知面 / 验收 a–d 落点）：
 *   人审打开一张多仓工单的变更 tab——
 *   a. 主体改动在成员仓的票：成员仓文件出现在改动清单（repos[] 逐仓汇总 + 顶层兼容层带
 *      <repo>/ 前缀），且可展开看内容（code 条目带 unified 文本）、各仓 base 对照各自正确；
 *      成员仓大改动（>60 文件）按仓封顶但不把根仓/他仓挤出清单（顶层=各仓封顶后拼接，
 *      不再全局截断，2a 修复不得被 60 条全局 cap 在旗舰场景复活）。
 *   c/d. 泳道内引擎过程物（.sandbar/ .dsh/ out/ __pycache__/ node_modules/ .venv/，含嵌套
 *      a/b/__pycache__/x 与成员仓内形态）不进改动清单，且被剔除路径**点名可见**
 *      （excludedPaths 到具体路径，不只聚合计数——验收 d「或点名」腿；「不落盘」腿=engine
 *      侧根修另票挂账，见场景②）。
 *   b. 单仓票零回归：repo_worktrees 缺省/空 → 今日单仓路径原样（无 repos、路径无前缀、
 *      过滤仍生效）——多仓字段不改变单仓票的呈现。
 *   异常输入三态（M1）：repo_worktrees 畸形（非列表/条目缺字段/repo 含 ..）→ 整体视同
 *      单仓、不炸不部分采纳；成员仓树未物化 → 该仓 emptyReason 点名仓不静默、他仓照常。
 *
 * 分层（灰盒，防 intent 重复）：与 developer L1（tests/t260911_01_*.mjs 真值表/封顶常量）
 * 分层——本条锁「多仓泳道夹具上的人审可见性」组合行为；与 t260907-11（项目锚判界/跨项目
 * 取数）不同面；单仓 diff 形状回归归既有 diff 族场景（t01/i02/i03）+ 本条 b 腿只锁
 * 「多仓字段在场时的退化不改变单仓行为」这一新缝，不重复彼处。
 *
 * 舞台：临时目录 git 夹具（假多仓项目：根仓+泳道 worktree+成员仓 worktree，零真实项目
 * 依赖、零 Temporal、零端口）；git 缺席=ENV_FAIL exit 2。被测缝=workbench host 公开契约
 * computeTicketDiff（node ≥22.18 原生 type-stripping 直驱，t260907-11 同款先例）；
 * ticket show→host 透传一跳（node.ts）的静态守卫在场景②。
 */
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { computeTicketDiff } from '../../server/plugins/workbench/src/host/changes.ts'

const LABEL = 'sc_t260911_01_multirepo_diff_faces'
const failures = []
let passed = 0
function ok(cond, msg) {
  if (cond) { passed++; console.log(`  ok ${msg}`) }
  else { failures.push(msg); console.log(`  FAIL ${msg}`) }
}

// 环境前置：git 在场（diff 判界面需要）；其余零外部依赖
try { execFileSync('git', ['--version']) } catch (e) {
  console.log(`ENV_FAIL: git 不可用（${e.message.split('\n')[0]}）——多仓 diff 判界面需要 git`)
  process.exit(2)
}

function git(args, cwd) {
  return execFileSync('git', args, { cwd, encoding: 'utf8' }).trim()
}
function gitInit(repoDir) {
  execFileSync('git', ['-c', 'init.defaultBranch=main', 'init'], { cwd: repoDir })
  git(['config', 'user.email', 'integ@test'], repoDir)
  git(['config', 'user.name', 'integ'], repoDir)
  git(['config', 'commit.gpgsign', 'false'], repoDir)
}
function commitAll(repoDir, msg) {
  git(['add', '-A'], repoDir)
  git(['commit', '-m', msg], repoDir)
  return git(['rev-parse', 'HEAD'], repoDir)
}
const w = (p, s) => { mkdirSync(join(p, '..'), { recursive: true }); writeFileSync(p, s, 'utf8') }

/**
 * 造一个多仓夹具项目：
 *   proj/                     根仓（.gitignore 声明 member/ member-src/ .lane/——KI-066 实案形态：
 *                             成员仓被根仓 .gitignore 忽略，根仓 diff 不得看见成员仓文件）
 *   proj/.lane/t<N>/          泳道容器=根仓 worktree（worktree 道被测对象）
 *   proj/member-src/          成员仓本体（独立 git 仓）
 *   proj/.lane/t<N>/<repo>/   成员仓 worktree（物化形态）
 */
function makeProject(tmp, tag, { rootChanges, artifacts, memberChanges, memberArtifacts }) {
  const proj = join(tmp, `proj-${tag}`)
  mkdirSync(proj, { recursive: true })
  gitInit(proj)
  writeFileSync(join(proj, '.gitignore'), '.lane/\nmember-src/\nmember/\n', 'utf8')
  writeFileSync(join(proj, 'root-base.py'), 'print("base")\n', 'utf8')
  const baseR = commitAll(proj, 'root base')

  const lane = join(proj, '.lane', tag)
  git(['worktree', 'add', lane, '-b', `lane/${tag}`, baseR], proj)

  for (const [rel, s] of rootChanges ?? []) w(join(lane, rel), s)
  for (const rel of artifacts ?? []) w(join(lane, rel), 'artifact\n')

  const mSrc = join(proj, 'member-src')
  mkdirSync(mSrc, { recursive: true })
  gitInit(mSrc)
  writeFileSync(join(mSrc, 'm-base.py'), 'def base():\n    pass\n', 'utf8')
  const baseM = commitAll(mSrc, 'member base')

  const mTree = join(lane, 'member')
  git(['worktree', 'add', mTree, '-b', `lane/${tag}-member`, baseM], mSrc)
  for (const [rel, s] of memberChanges ?? []) w(join(mTree, rel), s)
  for (const rel of memberArtifacts ?? []) w(join(mTree, rel), 'artifact\n')

  return { proj, lane, baseR, baseM, mTree }
}

const TMP = mkdtempSync(join(tmpdir(), 't260911-01-'))
try {
  // ── 夹具 t1：根仓小改动 + 成员仓改动 + 两仓过程物（含嵌套与成员仓内形态） ──
  const t1 = makeProject(TMP, 't1', {
    rootChanges: [['root-new.ts', 'export const n = 1\n']],
    artifacts: ['.sandbar/agent_t1.log', '.dsh/state.json', 'a/b/__pycache__/x.pyc', 'out/x.pyc', 'node_modules/m/index.js', '.venv/pyvenv.cfg'],
    memberChanges: [['m-base.py', 'def base():\n    return 1  # changed\n'], ['m-feature.py', 'def feature():\n    return 42\n']],
    memberArtifacts: ['.sandbar/settle.log', 'pkg/__pycache__/y.pyc'],
  })
  const rwsT1 = [
    { repo: '', name: 'proj', branch: 'lane/t1', base_ref: t1.baseR },
    { repo: 'member', name: 'member', branch: 'lane/t1-member', base_ref: t1.baseM },
  ]

  // ── 腿A 多仓逐仓可见（验收 a：成员仓文件在清单、可展开、base 各自对照） ──
  {
    const r = await computeTicketDiff(t1.proj, { id: 't1', worktree: t1.lane, base_ref: t1.baseR, repo_worktrees: rwsT1 })
    ok(Array.isArray(r.repos) && r.repos.length === 2, `A1 逐仓汇总 repos[] 两仓（实得 ${r.repos?.length}）`)
    const mem = r.repos.find((x) => x.repo === 'member')
    ok(!!mem, 'A2 成员仓条目在场')
    ok(mem?.files.some((f) => f.path === 'm-feature.py'), 'A3 成员仓新增文件在成员仓清单（m-feature.py）')
    ok(mem?.files.some((f) => f.path === 'm-base.py'), 'A4 成员仓修改文件在成员仓清单（m-base.py）')
    ok(mem?.files.find((f) => f.path === 'm-feature.py')?.unified?.length > 0, 'A5 成员仓条目可展开看内容（unified 非空）')
    ok(mem?.base === t1.baseM, 'A6 成员仓 base 对照=成员仓基线（各自 base，不串根仓）')
    const root = r.repos.find((x) => x.repo === '')
    ok(root?.files.some((f) => f.path === 'root-new.ts'), 'A7 根仓条目含根仓改动（root-new.ts）')
    ok(!root?.files.some((f) => f.path.startsWith('member/')), 'A8 根仓清单不被成员仓文件污染（.gitignore 形态）')
    ok(r.files.some((f) => f.path === 'member/m-feature.py'), 'A9 顶层兼容层成员仓路径带 <repo>/ 前缀（定位口径归一）')
    ok(r.files.some((f) => f.path === 'root-new.ts'), 'A10 顶层兼容层根仓路径不带前缀')
    ok(r.changed === true, 'A11 多仓票 changed=true（人审面不再空转——2a 缺陷的反面）')
  }

  // ── 腿B 过程物过滤 + 点名（验收 c + d「点名」腿，含嵌套/成员仓内形态） ──
  {
    const r = await computeTicketDiff(t1.proj, { id: 't1', worktree: t1.lane, base_ref: t1.baseR, repo_worktrees: rwsT1 })
    const bad = ['\\.sandbar/', '\\.dsh/', 'out/', '__pycache__', 'node_modules/', '\\.venv/'].map((p) => new RegExp(p))
    ok(!r.files.some((f) => bad.some((re) => re.test(f.path))), 'B1 顶层清单零过程物（6 类目录全不出现）')
    for (const s of r.repos ?? []) {
      ok(!s.files.some((f) => bad.some((re) => re.test(f.path))), `B2 仓 ${s.repo || '（根）'} 清单零过程物`)
    }
    ok((r.repos.find((x) => x.repo === '')?.excludedCount ?? 0) >= 6, 'B3 根仓排除计数≥6（点名计数留痕）')
    ok((r.repos.find((x) => x.repo === 'member')?.excludedCount ?? 0) >= 2, 'B4 成员仓排除计数≥2（成员仓内过程物同样滤）')
    const names = r.excludedPaths ?? []
    ok(names.includes('a/b/__pycache__/x.pyc'), 'B5 嵌套过程物点名到具体路径（a/b/__pycache__/x.pyc——JS 真源覆盖嵌套）')
    ok(names.includes('member/pkg/__pycache__/y.pyc'), 'B6 成员仓过程物点名带 <repo>/ 前缀')
    ok(names.includes('out/x.pyc') && names.includes('.sandbar/agent_t1.log'), 'B7 out/ 与 .sandbar/ 点名（2b 白名单目录）')
    ok(names.length <= 20, 'B8 点名列表有上限封顶（≤20，防大噪声刷屏）')
  }

  // ── 腿C 单仓退化零回归（验收 b 的新缝：多仓字段缺省不改变单仓行为） ──
  {
    const r = await computeTicketDiff(t1.proj, { id: 't1', worktree: t1.lane, base_ref: t1.baseR })
    ok(r.repos === undefined, 'C1 无 repo_worktrees → 无 repos（单仓呈现路径原样）')
    ok(r.source === 'worktree' && r.files.some((f) => f.path === 'root-new.ts'), 'C2 单仓 diff 内容不变')
    ok(!r.files.some((f) => f.path.includes('/')), 'C3 单仓路径无 <repo>/ 前缀')
    ok((r.excludedPaths ?? []).includes('out/x.pyc'), 'C4 单仓过程物过滤仍生效且点名')
    const rEmpty = await computeTicketDiff(t1.proj, { id: 't1', worktree: t1.lane, base_ref: t1.baseR, repo_worktrees: [] })
    ok(rEmpty.repos === undefined && rEmpty.files.some((f) => f.path === 'root-new.ts'), 'C5 空列表同退化（不误入多仓道）')
  }

  // ── 腿D 畸形 repo_worktrees（M1：整体视同单仓，不炸不部分采纳） ──
  {
    const shapes = [
      ['非列表', 'not-a-list'],
      ['条目缺 branch', [{ repo: 'member', name: 'member' }]],
      ['repo 含 ..', [{ repo: '../escape', name: 'x', branch: 'y' }]],
      ['repo 绝对路径', [{ repo: '/etc', name: 'x', branch: 'y' }]],
    ]
    for (const [label, shape] of shapes) {
      let r = null
      let threw = ''
      try { r = await computeTicketDiff(t1.proj, { id: 't1', worktree: t1.lane, base_ref: t1.baseR, repo_worktrees: shape }) }
      catch (e) { threw = String(e) }
      ok(threw === '' && r?.repos === undefined && r?.files.some((f) => f.path === 'root-new.ts'),
        `D ${label} → 视同单仓不炸（实得 ${threw ? 'throw:' + threw.slice(0, 60) : 'repos=' + JSON.stringify(r?.repos)?.slice(0, 40)}）`)
    }
  }

  // ── 腿E 成员仓未物化（点名不静默，他仓照常） ──
  {
    const rws = [...rwsT1, { repo: 'ghost', name: 'ghost', branch: 'lane/ghost', base_ref: t1.baseM }]
    const r = await computeTicketDiff(t1.proj, { id: 't1', worktree: t1.lane, base_ref: t1.baseR, repo_worktrees: rws })
    const g = r.repos.find((x) => x.repo === 'ghost')
    ok(!!g && (g.emptyReason ?? '').includes('ghost') && (g.emptyReason ?? '').includes('未物化'),
      `E1 缺席成员仓 emptyReason 点名仓（实得 ${g?.emptyReason}）`)
    ok((r.repos.find((x) => x.repo === 'member')?.files.length ?? 0) > 0, 'E2 他仓不受牵连照常出清单')
    ok(r.files.some((f) => f.path === 'member/m-feature.py'), 'E3 顶层清单不受缺席仓影响')
  }

  // ── 腿F 成员仓 >60 文件：按仓封顶、不全局互挤（R3 回归：2a 不得被全局 cap 复活） ──
  {
    const many = Array.from({ length: 70 }, (_, i) => [`gen/f${String(i).padStart(3, '0')}.py`, `def f${i}():\n    pass\n`])
    const t2 = makeProject(TMP, 't2', {
      rootChanges: [['root-new.ts', 'export const n = 1\n']],
      memberChanges: many,
    })
    const rws2 = [
      { repo: '', name: 'proj', branch: 'lane/t2', base_ref: t2.baseR },
      { repo: 'member', name: 'member', branch: 'lane/t2-member', base_ref: t2.baseM },
    ]
    const r = await computeTicketDiff(t2.proj, { id: 't2', worktree: t2.lane, base_ref: t2.baseR, repo_worktrees: rws2 })
    const mem = r.repos.find((x) => x.repo === 'member')
    const root = r.repos.find((x) => x.repo === '')
    ok(mem?.files.length === 60 && mem?.filesTruncated === true, `F1 成员仓按仓封顶 60+截断标记（实得 ${mem?.files.length}/${mem?.filesTruncated}）`)
    ok((root?.files.length ?? 0) >= 1, 'F2 大成员仓不把根仓挤出清单（无全局 cap 互挤——R3）')
    ok(r.files.length === (root?.files.length ?? 0) + 60, `F3 顶层=各仓封顶后拼接不叠加全局 cap（实得 ${r.files.length}）`)
    ok(r.filesTruncated === true, 'F4 顶层截断标记=任一仓截断即置位')
  }
} finally {
  rmSync(TMP, { recursive: true, force: true })
}

if (failures.length > 0) {
  console.log(`\nFAIL ${LABEL}：${failures.length} 条断言未过`)
  process.exit(1)
}
console.log(`\nPASS ${LABEL}（${passed} 条断言）`)
process.exit(0)

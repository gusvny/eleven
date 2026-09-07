/**
 * sc_wb_anchor_cross_project_faces.mjs —— t260907-11 场景①（KI-057）：
 * 跨项目三面取数对照＋撞码不互串＋审批写落项目根＋防穿越闸随项目根判界。
 *
 * intent（用户可感知面）：宿主在工单台选 dengzhufpv 视图时——①epics tab 看到的是
 * fpv 仓的立项单（不是 sandbar 的，同代号也不串）；②审批意见 POST 落 fpv 仓
 * server/dsh/reviews/，sandbar 视图读不到；③变更 diff 按 fpv 项目根判界后泳道可见，
 * 而同一 worktree 路径换 sandbar 锚仍被防穿越闸拒（闸语义不弱化，判界基准随项目走，
 * 红线）。与 developer L1（computeTicketDiff 真值表、resolver 单测）分层：本条锁
 * 「路由按项目键取数」的组装行为与跨面互不串；与 smoke/changes.mjs（单仓单项目）
 * 不同面（彼无第二项目可对照）。
 *
 * 舞台：进程内 apply+mock req/res（零端口），SANDBAR_PROJECTS_DIR 临时注册表；
 * git 缺席=ENV_FAIL exit 2；Temporal 不需要。实现落地前红属预期（TDD 信号）。
 */
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { computeTicketDiff } from '../../server/dsh/workbench/src/host/changes.ts'
import { makeFixture, makeJudge, requireGit, makeGitWorktree, EPIC_CODE, EPICS_PREFIX, TICKETS_PREFIX } from './lib_wb_anchor.mjs'

const j = makeJudge('sc_wb_anchor_cross_project_faces')

// 环境前置：git 在场性（diff 判界面需要）
{
  const missing = requireGit()
  if (missing) {
    console.log(`ENV_FAIL: ${missing}`)
    process.exit(2)
  }
}

const fx = await makeFixture()
let gitBits = null
try {
  gitBits = makeGitWorktree(fx.repoB)

  // ── 腿A epics 取数：同代号撞码，两项目各见各库 ──
  {
    const rFpv = await fx.drive(fx.repoA)(EPICS_PREFIX, `${EPICS_PREFIX}?project=fpv`)
    j.ok(rFpv.status === 200 && rFpv.body?.ok === true, `epics 列表 ?project=fpv → 200（实得 ${rFpv.status}）`)
    const tFpv = rFpv.body?.result?.epics?.find((e) => e.code === EPIC_CODE)
    j.ok(tFpv?.title === 'fpv 侧演示立项', `fpv 视图看到 fpv 仓立项单（实得 ${JSON.stringify(tFpv?.title)}）`)
    const rA = await fx.drive(fx.repoA)(EPICS_PREFIX, `${EPICS_PREFIX}?project=sandbar`)
    const tA = rA.body?.result?.epics?.find((e) => e.code === EPIC_CODE)
    j.ok(tA?.title === 'sandbar 侧演示立项', `sandbar 视图看到 sandbar 仓立项单（实得 ${JSON.stringify(tA?.title)}）`)
    const rD = await fx.drive(fx.repoA)(EPICS_PREFIX, `${EPICS_PREFIX}/${EPIC_CODE}?project=fpv`)
    j.ok(typeof rD.body?.result?.markdown === 'string' && rD.body.result.markdown.includes('fpv 侧演示立项'),
      'fpv 视图详情读 fpv 仓全文')
  }

  // ── 腿B precache 项目化：nextHintCached 与 dismiss 均按项目根，撞码不互串 ──
  {
    const preB = join(fx.repoB, '.suyou', 'epic-next', EPIC_CODE)
    const preA = join(fx.repoA, '.suyou', 'epic-next', EPIC_CODE)
    await mkdir(preB, { recursive: true })
    await mkdir(preA, { recursive: true })
    await writeFile(join(preB, 'pre.json'), '{"state_key":"fixture"}', 'utf8')
    await writeFile(join(preA, 'pre.json'), '{"state_key":"fixture"}', 'utf8')
    const rFpv = await fx.drive(fx.repoA)(EPICS_PREFIX, `${EPICS_PREFIX}?project=fpv`)
    const eFpv = rFpv.body?.result?.epics?.find((e) => e.code === EPIC_CODE)
    j.ok(eFpv?.nextHintCached === true, 'fpv 视图 demo-x nextHintCached=true（缓存锚在 fpv 根）')
    const rA = await fx.drive(fx.repoA)(EPICS_PREFIX, `${EPICS_PREFIX}?project=sandbar`)
    const eA = rA.body?.result?.epics?.find((e) => e.code === EPIC_CODE)
    j.ok(eA?.nextHintCached === true, 'sandbar 视图 demo-x nextHintCached=true（各自根各有缓存）')
    // dismiss fpv：只删 fpv 根的缓存，sandbar 根的不动
    const rDis = await fx.drive(fx.repoA)(EPICS_PREFIX, `${EPICS_PREFIX}/${EPIC_CODE}/next-hint/dismiss?project=fpv`, 'POST')
    j.ok(rDis.status === 200 && rDis.body?.ok === true, `dismiss ?project=fpv → 200（实得 ${rDis.status}）`)
    j.ok(!existsSync(join(preB, 'pre.json')), 'fpv 根 pre.json 已删')
    j.ok(existsSync(join(preA, 'pre.json')), 'sandbar 根 pre.json 不受牵连（撞码不互串）')
    await rm(preA, { recursive: true, force: true })
    await rm(preB, { recursive: true, force: true })
  }

  // ── 腿C 审批面：写落 fpv 仓 reviews/，sandbar 视图读不到 ──
  {
    const call = fx.drive(fx.repoA)
    const rPost = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/t-fpv-1/review?project=fpv`, 'POST', {
      base: 'fixture', conclude: 'changes-requested', reviewer: 'integ',
      blocks: [{ block_key: 'code:src.ts:00000000', summary: 'fpv 审批意见', type: 'code', status: 'modified', decision: 'reject', comment: '落项目仓' }],
    })
    j.ok(rPost.status === 200 && rPost.body?.ok === true, `POST 审批 ?project=fpv → 200（实得 ${rPost.status}）`)
    const savedRaw = await readFile(join(fx.repoB, 'server', 'dsh', 'reviews', 't-fpv-1.json'), 'utf8')
    const saved = JSON.parse(savedRaw)
    j.ok(saved.rounds?.length === 1 && saved.rounds[0].blocks[0].comment === '落项目仓',
      '审批意见落 fpv 仓 server/dsh/reviews/<id>.json 逐字一致')
    const rGetA = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/t-fpv-1/review?project=sandbar`)
    j.ok(rGetA.status === 200 && rGetA.body?.result?.rounds?.length === 0,
      'sandbar 视图读同一工单 id 审批 → 空（不串项目）')
    const rGetB = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/t-fpv-1/review?project=fpv`)
    j.ok(rGetB.body?.result?.rounds?.length === 1, 'fpv 视图 GET 回读一轮')
  }

  // ── 腿D diff 判界：闸语义不变、基准随项目根走（红线面） ──
  {
    const { base, absWt } = gitBits
    const dFpv = await computeTicketDiff(fx.repoB, { id: 't-fpv-1', worktree: absWt, base_ref: base })
    j.ok(dFpv.changed === true && dFpv.files.some((f) => f.path === 'src-changed.ts'),
      'fpv 项目根内泳道 diff 可见（宿主实报的变更 tab 空＝本断言的反面）')
    const dCross = await computeTicketDiff(fx.repoA, { id: 't-fpv-1', worktree: absWt, base_ref: base })
    j.ok(dCross.changed === false && (dCross.emptyReason ?? '').includes('越出'),
      '同一 worktree 换 sandbar 锚判界 → 仍拒（闸不弱化，只是基准随项目走）')
    const dEsc = await computeTicketDiff(fx.repoB, { id: 't-fpv-1', worktree: join(fx.repoB, '..', 'escape'), base_ref: base })
    j.ok(dEsc.changed === false && (dEsc.emptyReason ?? '').includes('越出'),
      'fpv 根外路径（../ 语义同级目录）仍拒')
  }
} finally {
  await fx.cleanup()
}
j.finish()

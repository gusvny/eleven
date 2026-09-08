/**
 * sc_wb_anchor_evidence_family.mjs —— t260907-11 场景③（KI-057）：
 * 证据目录锚项目化——证据列表/取图按项目根取数，SANDBAR_EVIDENCE_DIR 仅回落默认仓生效。
 *
 * intent（用户可感知面）：宿主在 fpv 视图打开工单详情的「截图证据」区——列表列出
 * fpv 仓 .suyou/evidence 与 .worktrees 泳道两候选的截图，取图端点按 ?project= 从
 * fpv 仓读字节；sandbar 视图同 id 看不到（不串项目）；旧 env 覆盖链保留但只在
 * 无参回落时生效（红线「env 链保留」×方案收窄声明）。与 smoke 既有证据防穿
 * （文件名白名单/TICKET_ID_RE containment）不同面：本条只锁项目化取数与 env 收窄，
 * 防穿语义归既有覆盖不重复。
 *
 * 舞台：进程内 apply+mock req/res（零端口零 Temporal）；实现落地前红属预期。
 */
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { makeFixture, makeJudge, TICKETS_PREFIX } from './lib_wb_anchor.mjs'

const j = makeJudge('sc_wb_anchor_evidence_family')
const fx = await makeFixture()
const TID = 't-fpv-1'
try {
  // 夹具：fpv 根两候选（归档 + 泳道 screenshots）＋env 覆盖目录
  const evB = join(fx.repoB, '.suyou', 'evidence', TID)
  const wtB = join(fx.repoB, '.worktrees', TID, '.suyou', 'screenshots')
  await mkdir(evB, { recursive: true })
  await mkdir(wtB, { recursive: true })
  await writeFile(join(evB, 'shot-a.png'), 'png-bytes-a', 'utf8')
  await writeFile(join(evB, 'shot-b.png'), 'png-bytes-b', 'utf8')
  await writeFile(join(wtB, 'shot-c.png'), 'png-bytes-c', 'utf8')
  const call = fx.drive(fx.repoA)

  // ── 腿A 证据列表项目化：fpv 视图见 fpv 根两候选；sandbar 视图同 id 为空 ──
  {
    const rFpv = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/${TID}/evidence?project=fpv`)
    const files = rFpv.body?.result?.files ?? []
    j.ok(rFpv.status === 200 && ['shot-a.png', 'shot-b.png', 'shot-c.png'].every((f) => files.includes(f)),
      `fpv 视图证据列表=归档+泳道三件（实得 ${JSON.stringify(files)}）`)
    const rA = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/${TID}/evidence?project=sandbar`)
    const filesA = rA.body?.result?.files ?? ['非数组']
    j.ok(Array.isArray(filesA) && filesA.length === 0, `sandbar 视图同 id 证据为空不串项目（实得 ${JSON.stringify(filesA)}）`)
  }

  // ── 腿B 取图项目化：按 ?project= 从 fpv 根读字节 ──
  {
    const rImg = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/${TID}/evidence/shot-a.png?project=fpv`)
    j.ok(rImg.status === 200 && String(rImg.raw) === 'png-bytes-a', `取图 ?project=fpv → 200 字节一致（实得 ${rImg.status}）`)
    const rMiss = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/${TID}/evidence/shot-a.png?project=sandbar`)
    j.ok(rMiss.status === 404, `sandbar 视图取图 → 404 不串项目（实得 ${rMiss.status}）`)
  }

  // ── 腿C env 收窄：SANDBAR_EVIDENCE_DIR 仅无参回落生效，per-project 不被串 ──
  await fx.withEnv({ SANDBAR_EVIDENCE_DIR: null }, async () => {
    const envEv = join(fx.root, 'env-evidence')
    await mkdir(join(envEv, TID), { recursive: true })
    await writeFile(join(envEv, TID, 'env-shot.png'), 'png-bytes-env', 'utf8')
    await fx.withEnv({ SANDBAR_EVIDENCE_DIR: envEv }, async () => {
      const rNo = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/${TID}/evidence`)
      j.ok((rNo.body?.result?.files ?? []).includes('env-shot.png'), '无参回落：SANDBAR_EVIDENCE_DIR 覆盖生效（旧 env 链保留）')
      const rFpv = await call(TICKETS_PREFIX, `${TICKETS_PREFIX}/${TID}/evidence?project=fpv`)
      const files = rFpv.body?.result?.files ?? []
      j.ok(files.includes('shot-a.png') && !files.includes('env-shot.png'), 'per-project 证据不被 env 串味')
    })
  })
} finally {
  await fx.cleanup()
}
j.finish()

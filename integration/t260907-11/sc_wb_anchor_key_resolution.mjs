/**
 * sc_wb_anchor_key_resolution.mjs —— t260907-11 场景②（KI-057）：
 * 项目键解析契约面——无参回落、sandbar key 等价、未知 key 显式 400 点名、
 * 隔离条目 502 透传、env 覆盖链收窄（仅回落默认仓生效）。
 *
 * intent（用户可感知面＋工单红线）：①「sandbar 自身票零回归」的fixture化——
 * 无参请求走默认仓回落链；?project=<sandbar key> 走注册表路径且解析根与回落链
 * 逐字节一致（生产 UI 恒带 ?project=，此断言钉住注册表条目不漂移）；②报错精确——
 * 未知 key 的 error 点名项目键，不把键解析失败伪装成「越出仓库根」；③隔离条目
 * 显式 502 透传注册表文案（不回落默认仓=不违隔离语义）；④env 红线——
 * SANDBAR_EPICS_DIR 仅在回落默认仓时生效，per-project 读取不被 env 串味。
 * 与 developer L1（resolver 四边角单测）分层：本条锁路由组装后的响应契约
 * （状态码/error 文案/resolved 来源标记）；票面 t.project 与 query 的优先级需
 * 引擎 ticket show，归 S5 实票验收，本条不重复。
 *
 * 舞台：进程内 apply+mock req/res（零端口零 Temporal）；实现落地前红属预期。
 */
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { makeFixture, makeJudge, EPIC_CODE, EPICS_PREFIX } from './lib_wb_anchor.mjs'

const j = makeJudge('sc_wb_anchor_key_resolution')
const fx = await makeFixture()
try {
  const call = fx.drive(fx.repoA)

  // ── 腿A 无参回落：默认仓链，resolved.source='default' ──
  let noParamRoot = null
  {
    const r = await call(EPICS_PREFIX, EPICS_PREFIX)
    j.ok(r.status === 200 && r.body?.ok === true, `无参 epics 列表 → 200（实得 ${r.status}）`)
    const t = r.body?.result?.epics?.find((e) => e.code === EPIC_CODE)
    j.ok(t?.title === 'sandbar 侧演示立项', '无参回落读默认仓（repoA）立项单')
    noParamRoot = r.body?.resolved?.root
    j.ok(r.body?.resolved?.source === 'default', `响应带 resolved.source='default' 来源标记（方案承诺；实得 ${JSON.stringify(r.body?.resolved?.source)}）`)
    j.ok(noParamRoot === fx.repoA, `resolved.root=默认仓根（实得 ${JSON.stringify(noParamRoot)}）`)
  }

  // ── 腿B sandbar key 等价：注册表路径 root 与回落链逐字节一致（零回归闸） ──
  {
    const r = await call(EPICS_PREFIX, `${EPICS_PREFIX}?project=sandbar`)
    j.ok(r.status === 200, `?project=sandbar → 200（实得 ${r.status}）`)
    j.ok(r.body?.resolved?.source === 'project', 'resolved.source=\'project\'（注册表路径）')
    j.ok(r.body?.resolved?.root === noParamRoot, `注册表解析根与无参回落根逐字节一致（实得 ${JSON.stringify(r.body?.resolved?.root)} vs ${JSON.stringify(noParamRoot)}）`)
  }

  // ── 腿C 未知 key：显式 400 且 error 点名项目键（报错精确，非「越出仓库根」） ──
  {
    const r = await call(EPICS_PREFIX, `${EPICS_PREFIX}?project=nope`)
    j.ok(r.status === 400, `未知 key → 400（实得 ${r.status}）`)
    j.ok(typeof r.body?.error === 'string' && r.body.error.includes('nope'), 'error 点名未知项目键')
    j.ok(!(r.body?.error ?? '').includes('越出'), 'error 不伪装成穿越语义')
  }

  // ── 腿D 隔离条目：显式 502 透传注册表文案（不回落默认仓=不违隔离语义） ──
  {
    const r = await call(EPICS_PREFIX, `${EPICS_PREFIX}?project=badproj`)
    j.ok(r.status === 502, `隔离条目 → 502（实得 ${r.status}）`)
    j.ok(typeof r.body?.error === 'string' && r.body.error.includes('badproj'), 'error 透传注册表隔离文案（点名条目）')
  }

  // ── 腿E env 收窄：SANDBAR_EPICS_DIR 仅回落默认仓生效，不串 per-project ──
  await fx.withEnv({ SANDBAR_EPICS_DIR: null }, async () => {
    const envEpics = join(fx.root, 'env-epics')
    await mkdir(envEpics, { recursive: true })
    await writeFile(join(envEpics, `${EPIC_CODE}.md`), '# 立项单：env 覆盖侧演示立项\n', 'utf8')
    await fx.withEnv({ SANDBAR_EPICS_DIR: envEpics }, async () => {
      const rNo = await call(EPICS_PREFIX, EPICS_PREFIX)
      const tNo = rNo.body?.result?.epics?.find((e) => e.code === EPIC_CODE)
      j.ok(tNo?.title === 'env 覆盖侧演示立项', '无参回落：SANDBAR_EPICS_DIR 覆盖生效（旧 env 链保留）')
      const rFpv = await call(EPICS_PREFIX, `${EPICS_PREFIX}?project=fpv`)
      const tFpv = rFpv.body?.result?.epics?.find((e) => e.code === EPIC_CODE)
      j.ok(tFpv?.title === 'fpv 侧演示立项', `per-project 不被 env 串味（实得 ${JSON.stringify(tFpv?.title)}）`)
    })
  })
} finally {
  await fx.cleanup()
}
j.finish()

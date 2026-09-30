/**
 * executor-grants.test.mjs —— 执行器授权声明读写面 UT（t260930-14）。
 *
 * 覆盖（工单验收杆的面板半边）：
 *  - 声明写面：保存=写时回读校验+原子 rename；缺 by 拒收；坏声明不落盘且原文件
 *    逐字节不动（畸形输入族）；
 *  - 元权限反锁：caller_surface=executor-session 一律拒收（改/扩/缩都拒）；
 *  - 声明读面三态：absent（真缺席，不冒充空授予）/ malformed / ok；
 *  - 溯源面：逐 op 可答「哪个声明哪条键定的」（grants.<op> / night_tier /
 *    not-declared / no-usable-declaration）；
 *  - 审计：每次授予变更追加一行（who/from/to）。
 * 零真实 ~/.sandbar（SANDBAR_PROJECTS_DIR 指临时目录）、零 3099。
 */
import { assert, done, freshDir, cleanup, fakeClock } from './lib.mjs'
import {
  GRANT_OPS, EXECUTOR_SURFACE, declarationPath, auditPath,
  readDeclaration, saveGrantsDecl, provenanceKeys, validateDeclaration, toGrantOp,
} from '../src/host/executor-grants.ts'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const wd = freshDir(), pan = freshDir()
const env = { HOME: '/nonexistent-home', SANDBAR_WATCHDOG_DIR: wd, SANDBAR_PANEL_DIR: pan, SANDBAR_PROJECTS_DIR: wd }
const clock = fakeClock()
let n = 0
try {
  // ---- 写面：happy path + 审计 ----
  {
    const r = saveGrantsDecl('sandbar', { grants: { sign: true, rerun: true } }, 'host', env, clock.now())
    assert(r.saved === true, `save happy: saved (${++n})`)
    const back = JSON.parse(readFileSync(declarationPath('sandbar', env), 'utf8'))
    assert(back.version === 1 && back.grants.sign === true && back.updated_by === 'host', `save happy: file shape (${++n})`)
    const rows = readFileSync(auditPath('sandbar', env), 'utf8').trim().split('\n').map((l) => JSON.parse(l))
    assert(rows.length === 1 && rows[0].action === 'grant-change' && rows[0].who === 'host'
        && rows[0].to.sign === true, `save happy: audit row (${++n})`)
  }

  // ---- 写面：缺 by / 坏声明 / 原文件逐字节不动 ----
  {
    const before = readFileSync(declarationPath('sandbar', env), 'utf8')
    const r1 = saveGrantsDecl('sandbar', { grants: { sign: true } }, '', env, clock.now())
    assert(r1.saved === false && r1.reason.includes('by'), `save: missing by refused (${++n})`)
    const r2 = saveGrantsDecl('sandbar', { grants: { fly: true } }, 'host', env, clock.now())
    assert(r2.saved === false && r2.reason.includes('fly'), `save: unknown op refused (${++n})`)
    const r3 = saveGrantsDecl('sandbar', 'nope', 'host', env, clock.now())
    assert(r3.saved === false, `save: non-object refused (${++n})`)
    const r4 = saveGrantsDecl('sandbar', { grants: {}, night_tier: { enabled: 'yes', until: 5 } }, 'host', env, clock.now())
    assert(r4.saved === false && r4.reason.includes('night_tier'), `save: bad night_tier refused (${++n})`)
    assert(readFileSync(declarationPath('sandbar', env), 'utf8') === before, `save: original byte-identical (${++n})`)
    assert(!existsSync(declarationPath('sandbar', env) + '.tmp'), `save: no tmp residue (${++n})`)
  }

  // ---- 元权限反锁（acceptance rod：executor-identified widening refused） ----
  {
    const widen = saveGrantsDecl('sandbar', { grants: { cleanup: true, 'open-ticket': true } }, 'executor', env, clock.now(), EXECUTOR_SURFACE)
    assert(widen.saved === false && widen.reason.includes('反锁'), `reverse lock: widening refused (${++n})`)
    const shrink = saveGrantsDecl('sandbar', { grants: {} }, 'executor', env, clock.now(), EXECUTOR_SURFACE)
    assert(shrink.saved === false, `reverse lock: even shrinking refused (${++n})`)
    const rows = existsSync(auditPath('sandbar', env))
      ? readFileSync(auditPath('sandbar', env), 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []
    assert(!rows.some((r) => r.who === 'executor'), `reverse lock: no audit row for refused (${++n})`)
  }

  // ---- 读面三态 + 溯源 ----
  {
    const absent = readDeclaration('fresh-project', env)
    assert(absent.ok === false && absent.kind === 'absent' && absent.declared === false,
        `read: absent is absent (${++n})`)
    const prov0 = provenanceKeys(absent, clock.now())
    assert(Object.values(prov0).every((v) => v.includes('no-usable-declaration')),
        `provenance: absent → no-usable-declaration (${++n})`)

    mkdirSync(join(wd, 'broken'), { recursive: true })
    writeFileSync(declarationPath('broken', env), '{bad json', 'utf8')
    const bad = readDeclaration('broken', env)
    assert(bad.ok === false && bad.kind === 'malformed' && bad.declared === true,
        `read: malformed named (${++n})`)

    const okR = readDeclaration('sandbar', env)
    assert(okR.ok === true && okR.declaration.grants.sign === true, `read: ok (${++n})`)
    const prov = provenanceKeys(okR, clock.now())
    assert(prov.sign.includes('grants.sign'), `provenance: granted op names key (${++n})`)
    assert(prov.cleanup.includes('not-declared'), `provenance: ungranted op names default-refuse (${++n})`)
    const night = { version: 1, grants: {}, night_tier: { enabled: true, until: clock.now() + 1000 } }
    saveGrantsDecl('night', night, 'host', env, clock.now())
    const provN = provenanceKeys(readDeclaration('night', env), clock.now())
    assert(provN.sign.includes('night_tier.until'), `provenance: night tier names key (${++n})`)
    const provExpired = provenanceKeys(readDeclaration('night', env), clock.now() + 2000)
    assert(provExpired.sign.includes('not-declared'), `provenance: expired night → not-declared (${++n})`)
  }

  // ---- 校验器镜像（与引擎 validate_declaration 同规则） ----
  {
    const [, e1] = validateDeclaration({ version: 2, grants: {} })
    assert(e1 && e1.includes('version'), `validate: version drift refused (${++n})`)
    const [, e2] = validateDeclaration({ version: 1, grants: { sign: 'yes' } })
    assert(e2 && e2.includes('boolean'), `validate: non-bool refused (${++n})`)
    assert(toGrantOp('reject') === 'send-back' && toGrantOp('sign') === 'sign', `alias: reject↔send-back (${++n})`)
    assert(GRANT_OPS.length === 6 && GRANT_OPS.includes('send-back') && GRANT_OPS.includes('open-ticket'),
        `ops: fixed six (${++n})`)
  }
} finally {
  cleanup([wd, pan])
}
done(n)

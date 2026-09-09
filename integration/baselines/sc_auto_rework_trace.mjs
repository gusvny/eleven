/**
 * Baseline: auto-rework trace contract (t260901-04).
 *
 * Intent:
 *   Lock the USER-VISIBLE contract of the t260901-04 fix: when the engine sends a
 *   ticket back automatically (acceptance fail / arbitrate code-fault /
 *   integration_review mechanical or reading reject / merge fail), the ticket
 *   timeline gains exactly one state='rework' record carrying time / target step /
 *   reason / who — the only shape the workbench rework banner (D2Reworks) renders.
 *   Before this fix the internal auto-rework branches bypassed the trace entirely,
 *   so users saw no reason at all (t260901-02 incident).
 *
 * Pure half (always runs, no environment needed):
 *   A. Real-code behavioral matrix: extract PHASE_MAIN_CHAIN / PHASE_MAIN_ROLES /
 *      _auto_rework / _mark / _log / _touch / _now_* verbatim from dev_lane.py
 *      (temporalio can't be imported here) and EXECUTE them against a fake lane:
 *      - five auto-rework scenarios each produce exactly one banner-shaped record
 *        (state/stage/reason/note+who/time) + the meta five-piece;
 *      - malformed-input matrix (external-signal perspective): phase-only targets
 *        (acceptance/parallel_impl_design/integ_join — vocab but not STAGES ids)
 *        must be ACCEPTED with the mapped role and never crash (review round-3
 *        regression guard); STAGES-only targets (acceptance_walkthrough/
 *        ui_evidence/suggest_next/design_integration_tests), "done", "" and None
 *        must be REFUSED: return fallback, refused logged, meta untouched, no
 *        timeline record; invalid fallback returns meta stage, never the bad value;
 *      - empty note still yields a non-empty rendered reason.
 *   B. Structural guards (user-visible invariants):
 *      - exactly ONE producer of state='rework' timeline records (no double trace);
 *      - merge-fail branch no longer stashes self._rework (would double-trace);
 *      - 7 internal call sites + 1 shell delegation = 8 _auto_rework call sites.
 *
 * Env half (SDK + Docker test Temporal + fixture clone required, otherwise ENV_FAIL exit 2):
 *   Scene F: real dev-lane ticket with stub brains -> send external rework signals
 *   against the t260901-04 matrix and assert on the real engine:
 *     F1. rework(target='acceptance') (vocab∩¬STAGES) is accepted: timeline gains
 *         exactly one state='rework'/stage='acceptance' record whose reason carries
 *         the note and signer — the workflow does NOT crash (the round-3 bug).
 *     F2. rework(target='done') and rework(target='suggest_next') are refused:
 *         refused count grows, the rework-record count stays exactly 1.
 *   The engine's own acceptance-failure auto-rework path is exercised in the pure
 *   half (real code exec); forcing a real agent to fail is out of stub-brain scope.
 *
 * Write-guard (this test creates tickets; it refuses an unclear target):
 *   SANDBAR_TARGET_HOST unset -> ENV_FAIL loudly; == production default 127.0.0.1:7233
 *   -> FAIL; anything else must equal the pinned test env 127.0.0.1:17233.
 *
 * Nested-run guard: inside a lane's mechanical integration step
 * (SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW present) the env half reports ENV_FAIL loudly —
 * same recursion guard as ticket-lifecycle; the pure half still runs.
 */

import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import {
  makeTally, writeGuard, findSdkPython, ensureTestTemporal, buildFixture,
  makeApi, startStubWorker, waitFor, cleanupTicket, SCENE_TIMEOUT_BUDGET_MS,
} from './ticket-lifecycle-scenes.mjs'

const REPO = process.cwd()
const DEV_LANE = join(REPO, 'server', 'engine', 'dev_lane.py')

let pass = 0, fail = 0, envFail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** The nested-run guard: any dedicated-worker env marker means "inside a lane". */
function nestedGuard(env = process.env) {
  return (env.SANDBAR_TASK_QUEUE || env.SANDBAR_WATCH_WORKFLOW) ? 'nested' : 'top'
}

/* ------------------------------------------------------------------ pure A */
/* Extract the real bookkeeping code from dev_lane.py and execute it verbatim.
 * Python side prints "ok/FAIL" lines plus a "PYDONE pass=N fail=M" summary. */

const PY = String.raw`
import json, re, sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

src = open(sys.argv[1], encoding='utf-8').read()

p_pass = 0
p_fail = 0
def ok(cond, label):
    global p_pass, p_fail
    if cond:
        p_pass += 1
        print("  ok [py] " + label)
    else:
        p_fail += 1
        print("  FAIL [py] " + label)

def extract_method(name):
    m = re.search(r'\n    def %s\(self[^\n]*\n' % re.escape(name), src)
    if not m:
        return None
    lines = src[m.start() + 1:].splitlines(keepends=True)
    body = [lines[0]]
    for ln in lines[1:]:
        if re.match(r'    (def |@|# -{3,})', ln):
            break
        if ln.strip() and not ln.startswith((' ', '\t')):
            break
        body.append(ln)
    return ''.join(body).rstrip() + '\n'

m_chain = re.search(r'PHASE_MAIN_CHAIN = frozenset\(\{.*?\}\)', src, re.S)
m_roles = re.search(r'PHASE_MAIN_ROLES: Dict\[str, str\] = \{.*?\n\}', src, re.S)
ok(m_chain is not None, 'PHASE_MAIN_CHAIN 常量可从源码抽出')
ok(m_roles is not None, 'PHASE_MAIN_ROLES 常量可从源码抽出')

ns = {
    'Dict': Dict, 'List': List, 'Any': Any, 'Optional': Optional,
    'workflow': SimpleNamespace(
        now=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None)),
}
exec(m_chain.group(0), ns)
exec(m_roles.group(0), ns)
PHASE_MAIN_CHAIN = ns['PHASE_MAIN_CHAIN']
PHASE_MAIN_ROLES = ns['PHASE_MAIN_ROLES']
ok(set(PHASE_MAIN_ROLES) == set(PHASE_MAIN_CHAIN),
   'PHASE_MAIN_ROLES 键集合与 PHASE_MAIN_CHAIN 一致（13 键）')
# 锁口径：len = 主链 phase 值全集；t260903-02 增第 13 键 arb_acc_parallel。
ok(len(PHASE_MAIN_CHAIN) == 13, 'PHASE_MAIN_CHAIN 恰 13 值')

methods = []
for name in ('_now_epoch', '_now_iso', '_log', '_mark', '_touch', '_auto_rework'):
    code = extract_method(name)
    ok(code is not None, '方法 %s 可从源码抽出' % name)
    methods.append(code)
exec('class FakeLane:\n' + ''.join(methods), ns)

def fresh(stage):
    lane = ns['FakeLane']()
    lane.ticket_id = 'integ-auto-rework'
    lane.meta = {'stage': stage, 'status': 'running', 'log': []}
    lane.timeline = []
    lane.refused = []
    return lane

# ---- A1: 五个自动打回场景，各产一条横幅可见记录（用户视角主契约） ----
scenarios = [
    ('acceptance', 'implement', '验收走查打回（第 2 轮）'),
    ('arbitrate', 'implement', 'code-fault 打回 → implement（第 1 轮）'),
    ('integration_review', 'implement', '机械复核强制打回 → implement（第 1 轮）'),
    ('integration_review', 'implement', '集成审读打回（第 1 轮）'),
    ('merge', 'merge_check', 'merge 失败（conflict）自动打回重验：预演冲突'),
]
for cur, target, note in scenarios:
    lane = fresh(cur)
    before = len(lane.timeline)
    ret = lane._auto_rework(target, note, 'workflow', cur)
    recs = lane.timeline[before:]
    ok(ret == target, '%s→%s：返回目标步' % (cur, target))
    ok(len(recs) == 1, '%s→%s：timeline 恰新增 1 条记录（不双落）' % (cur, target))
    r = recs[0] if recs else {}
    ok(r.get('state') == 'rework', '%s→%s：记录 state=rework（横幅消费口径）' % (cur, target))
    ok(r.get('stage') == target, '%s→%s：记录 stage=目标步' % (cur, target))
    ok(bool(r.get('at')), '%s→%s：记录带时间戳 at' % (cur, target))
    ok(note in (r.get('reason') or '') and 'workflow' in (r.get('reason') or ''),
       '%s→%s：reason 含打回理由与发起者 workflow' % (cur, target))
    ok(lane.meta.get('status') == 'rework' and lane.meta.get('stage_state') == 'awaiting',
       '%s→%s：meta 五件套 status/stage_state' % (cur, target))
    ok(lane.meta.get('last_rework_note') == note,
       '%s→%s：last_rework_note=打回理由' % (cur, target))
    ok(lane.meta.get('role') == PHASE_MAIN_ROLES[target],
       '%s→%s：role=%s（显式映射，不经 _step）' % (cur, target, PHASE_MAIN_ROLES[target]))
    ok(lane.meta.get('stage') == target, '%s→%s：meta.stage=目标步' % (cur, target))

# ---- A2: 畸形输入矩阵（外部 signal 视角） ----
# 反向三值：词表有、STAGES 无 —— review 第 3 轮回归护栏（旧码 _step 崩/新码须接受）
for tgt, want_role in (('acceptance', 'integration'),
                       ('parallel_impl_design', 'developer'),
                       ('integ_join', 'developer')):
    lane = fresh('implement')
    before = len(lane.timeline)
    try:
        ret = lane._auto_rework(tgt, '外部打回：%s' % tgt, 'e2e-human', 'implement')
        crashed = False
    except Exception as e:
        ret, crashed = repr(e), True
    ok(not crashed, '畸形输入 target=%s：不抛异常（不卡死 workflow）' % tgt)
    ok(ret == tgt, '畸形输入 target=%s：接受并返回该步' % tgt)
    ok(lane.meta.get('role') == want_role, '畸形输入 target=%s：role=%s' % (tgt, want_role))
    ok(len(lane.timeline) == before + 1 and lane.timeline[-1].get('state') == 'rework',
       '畸形输入 target=%s：留一条 rework 记录' % tgt)

# 拒绝方向：STAGES 有、词表无 + done + 空/None —— 拒绝语义与 _apply_rework 拒绝路径一致
for tgt in ('acceptance_walkthrough', 'ui_evidence', 'suggest_next',
            'design_integration_tests', 'done', '', None):
    lane = fresh('implement')
    meta_before = dict(lane.meta)
    tl_before = len(lane.timeline)
    try:
        ret = lane._auto_rework(tgt, '试打回', 'e2e-human', 'implement')
        crashed = False
    except Exception as e:
        ret, crashed = repr(e), True
    label = 'None' if tgt is None else repr(tgt)
    ok(not crashed, '畸形输入 target=%s：不抛异常' % label)
    ok(ret == 'implement', '畸形输入 target=%s：拒绝并返回 fallback（停原步）' % label)
    ok(len(lane.refused) == 1, '畸形输入 target=%s：refused 有账' % label)
    ok(lane.meta == meta_before, '畸形输入 target=%s：拒绝不改写 meta' % label)
    ok(len(lane.timeline) == tl_before, '畸形输入 target=%s：拒绝不留 rework 时间线' % label)

# fallback 非法：返回 meta 现值，绝不让非法值回流 phase
lane = fresh('implement')
ret = lane._auto_rework('implement', 'ok', 'workflow', '')
ok(ret == 'implement', 'fallback 非法：返回 meta.stage（合法值）')
ok(len(lane.refused) == 1, 'fallback 非法：refused 有账')
ok(len(lane.timeline) == 0, 'fallback 非法：无 rework 时间线')

# 空 note：留痕 reason 仍非空（横幅不渲染空理由）
lane = fresh('acceptance')
lane._auto_rework('implement', '', 'workflow', 'acceptance')
ok(bool(lane.timeline[-1].get('reason')), '空 note：reason 兜底非空')

# ---- B: 结构护栏（用户可见不变量） ----
# 'rework' 时间线记录的唯一生产者 = _auto_rework 内那处真实调用（docstring 提及不算）
ok(len(re.findall(r'^\s+self\._mark\(target,\s*["\']rework["\']', src, re.M)) == 1,
   'state=rework 时间线记录唯一生产者（恰好 1 处真实 _mark 调用）——不双落')
# merge 人审 reject 保留经壳留痕（既有行为）；merge 失败分支必须不再塞 self._rework
ok(len(re.findall(r'self\._rework = ReworkRequest\(', src)) == 1,
   'dev_lane.py 仅存 1 处 ReworkRequest 塞值（merge 人审 reject，经壳留痕）')
i_fail = src.find('if not mr.ok:')
i_fin = src.find('self._finish("merge"', i_fail)
ok(i_fail >= 0 and i_fin > i_fail and
   'self._rework = ReworkRequest(' not in src[i_fail:i_fin],
   'merge 失败分支（if not mr.ok → _finish(merge) 区间）无 ReworkRequest 塞值（直调 _auto_rework 防双落）')
# 锁口径：调用点计数 = 内部自动打回点 + 1 壳委托；t260903-02 增 arb_acc_parallel
# 分支 2 处（验收打回 + code-fault 打回）→ 8（7 internal + 1 shell delegation）。
ok(len(re.findall(r'self\._auto_rework\(', src)) == 8,
   '_auto_rework 调用点=8（1 壳委托 + 7 内部自动打回点）')

print('PYDONE pass=%d fail=%d' % (p_pass, p_fail))
sys.exit(0 if p_fail == 0 else 1)
`

function pureHalf() {
  section('pure A/B: real-code behavioral matrix + structural guards (dev_lane.py verbatim exec)')
  const r = spawnSync('python3', ['-', DEV_LANE], { input: PY, encoding: 'utf-8' })
  if (r.stdout) process.stdout.write(r.stdout)
  if (r.status !== 0) {
    ok(false, `pure half python exited ${r.status}: ${(r.stderr || '').split('\n')[0] ?? ''}`)
    return
  }
  const m = /PYDONE pass=(\d+) fail=(\d+)/.exec(r.stdout || '')
  ok(m !== null, 'pure half printed PYDONE summary')
  if (m) ok(Number(m[2]) === 0, `pure half python internal tally fail=0 (got pass=${m[1]} fail=${m[2]})`)
}

/* ------------------------------------------------------------------ env half */
// 计时探针（260909 并发提速战役）：envHalf 652s 单笔占 wall 52%，先量后动——
// 每段 wall 时间戳打 stdout，run_scenarios 汇总按段聚合。
const T0 = { at: Date.now() };
const stamp = (label) => console.log(`  [timing] ${((Date.now() - T0.at) / 1000).toFixed(1).padStart(7)}s  ${label}`);

async function sceneF(t, api, sdkPython, fixture) {
  const tid = `integ-auto-rework-${Date.now().toString(36)}`
  console.log(`  -- scene F: external rework signal matrix on ${tid}`)
  stamp('sceneF: ticket-start 开始')
  const started = await api.start(tid, ['integration/'])
  stamp('sceneF: ticket-start 回')
  t.ok(started.ok !== false, `ticket ${tid} started (${(started.body?.error ?? 'ok')})`)
  if (started.ok === false) return
  const worker = startStubWorker(fixture, sdkPython, tid)
  stamp('sceneF: stub worker 已起')
  try {
    const ready = await waitFor(api, tid,
      (s) => !!s?.meta?.workspace_prep?.ok, 'workspace ready', 120_000, t)
    stamp('sceneF: workspace_prep 就绪')
    if (!ready) return

    const reworkCount = (s) => (s?.timeline ?? []).filter((e) => e.state === 'rework').length
    const findAccept = (s) => (s?.timeline ?? []).find(
      (e) => e.state === 'rework' && e.stage === 'acceptance')

    // F1: 词表∩¬STAGES 目标（review 第 3 轮回归）——真实引擎不得崩
    const note = 'e2e: 外部打回到验收（词表∩¬STAGES 回归护栏）'
    api.rework(tid, 'acceptance', note, 'e2e-tester')
    stamp('sceneF: F1 信号已发')
    const s1 = await waitFor(api, tid,
      (s) => !!findAccept(s), 'rework(target=acceptance) accepted & traced',
      SCENE_TIMEOUT_BUDGET_MS, t)
    stamp('sceneF: F1 断言态达成')
    if (s1) {
      const rec = findAccept(s1)
      t.ok(reworkCount(s1) === 1, `F1: timeline 恰 1 条 rework 记录（实得 ${reworkCount(s1)}）`)
      t.ok((rec.reason ?? '').includes(note) && (rec.reason ?? '').includes('e2e-tester'),
        'F1: 记录 reason 含打回理由与发起者（横幅可读的打回原因）')
      t.ok(!!rec.at, 'F1: 记录带时间戳')
      t.ok(((s1.role ?? s1.meta?.role) === 'integration'),
        `F1: role=integration（显式映射，_step 未崩；实得 ${s1.role ?? s1.meta?.role}）`)
    }

    // F2: done / suggest_next 拒绝——refused 增长、rework 记录数不变
    const refusedOf = (s) => (s?.refused ?? []).length
    api.rework(tid, 'done', 'e2e: 终态不可为打回目标', 'e2e-tester')
    stamp('sceneF: F2a 信号已发')
    const s2 = await waitFor(api, tid,
      (s) => refusedOf(s) >= 1, 'rework(target=done) refused', SCENE_TIMEOUT_BUDGET_MS, t)
    stamp('sceneF: F2a 断言态达成')
    if (s2) {
      t.ok(reworkCount(s2) === 1, `F2a: done 被拒后 rework 记录仍恰 1 条（实得 ${reworkCount(s2)}）`)
    }
    api.rework(tid, 'suggest_next', 'e2e: 内联步不可为打回目标', 'e2e-tester')
    stamp('sceneF: F2b 信号已发')
    const s3 = await waitFor(api, tid,
      (s) => refusedOf(s) >= 2, 'rework(target=suggest_next) refused', SCENE_TIMEOUT_BUDGET_MS, t)
    stamp('sceneF: F2b 断言态达成')
    if (s3) {
      t.ok(reworkCount(s3) === 1, `F2b: suggest_next 被拒后 rework 记录仍恰 1 条（实得 ${reworkCount(s3)}）`)
    }
  } finally {
    stamp('cleanup: 开始（工单清理+worker 退役）')
    await cleanupTicket(t, api, worker, tid)
    stamp('cleanup: 回')
  }
}

async function envHalf() {
  section('env: real engine rework-signal matrix (Docker test Temporal + stub brains)')
  T0.at = Date.now()   // 计时零点对齐 envHalf 起点（pure half 不在本表口径内）
  stamp('envHalf: 入口')
  const t = makeTally()
  const guard = writeGuard()
  if (guard === 'env_fail') { envFail++; console.log('  ENV_FAIL write-guard: SANDBAR_TARGET_HOST not set explicitly -- refusing to create tickets on an unclear target (set SANDBAR_TARGET_HOST=127.0.0.1:17233)'); return }
  if (guard === 'fail') { fail++; console.error('  FAIL write-guard: SANDBAR_TARGET_HOST points at the production default'); return }
  const sdkPython = findSdkPython(t)
  stamp('envHalf: findSdkPython 回')
  if (!await ensureTestTemporal(t)) { envFail++; console.log('  ENV_FAIL env half: Docker test Temporal unavailable'); return }
  stamp('envHalf: ensureTestTemporal 回')
  const fixtureBuilt = await buildFixture(t)
  if (!fixtureBuilt) { envFail++; console.log('  ENV_FAIL env half: fixture clone failed'); return }
  stamp('envHalf: buildFixture 回')
  const { fixture, dispose } = fixtureBuilt   // buildFixture 回执是对象：路径字段叫 fixture（同 sc_ticket_lifecycle 解构口径）
  try {
    const api = makeApi(sdkPython, fixture)
    await sceneF(t, api, sdkPython, fixture)
  } finally {
    dispose()
    stamp('envHalf: fixture dispose 回')
  }
  pass += t.pass; fail += t.fail; envFail += t.envFail
  if (t.envFail) console.log(`  (env helpers: ${t.envFail} env_fail note(s) above)`)
}

async function main() {
  console.log('== auto-rework trace contract (t260901-04): banner-visible rework records for machine send-backs')
  const nested = nestedGuard() === 'nested'
  if (nested) {
    envFail++
    console.log('  ENV_FAIL env half: nested inside a lane integration step (SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW present) -- top-level runs carry the signal-matrix coverage')
  }
  pureHalf()
  if (!nested) await envHalf()
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=0`)
  const allNa = false
  process.exit(fail > 0 || allNa ? 1 : envFail > 0 ? 2 : 0)
}

main().catch((e) => { console.error('FATAL', e); process.exit(1) })

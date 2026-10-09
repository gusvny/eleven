#!/usr/bin/env node
/**
 * sc_t26100833_lane_env_anchor_boundary.mjs — t261008-33, grey-box L3, "ro" pool.
 *
 * User-perceivable face under test (ticket 261008 required outcome 1 + evidence
 * item "L1 env helper"): every engine-built env for LANE work must carry the
 * LANE root as the repo anchor — never the parent's inherited SANDBAR_REPO
 * value — whether the parent env carries the main-checkout value, a foreign
 * value, or nothing at all. This is the seam that made lane code write into
 * the main checkout (evidence PNGs rewritten there at 09:46:40, admin.log
 * anchored at the wrong tree).
 *
 * Harness: the engine's env-composition helpers are driven in a real python
 * child (offline, seconds, zero docker/Temporal/3099). The single-point rule is
 * asserted at the contract level: ONE strip family covers SANDBAR_REPO and ONE
 * lane helper sets it to the given lane root. Helpers missing = FAIL named
 * (TDD-phase red expected; arbitrate/merge must be green). The engine module
 * being unimportable for EXTERNAL dependency reasons = ENV_FAIL exit 2.
 *
 * Intent split: guard verdicts/name = sc_t26100833_anchor_guard_named_failure;
 * the end-to-end main-checkout-clean witness = sc_t26100833_main_checkout_witness;
 * python truth tables of the helpers = developer L1. This entry owns only the
 * env-boundary contract (what a lane child's environment looks like).
 */
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, realpathSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { emitCase } from '../lib_result.mjs'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = realpathSync(join(HERE, '..', '..'))

let passed = 0, failed = 0, envfail = 0
function judge(name, ok, reason = '', evidence = '') {
  if (ok) passed++; else failed++
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
  emitCase({ name, suite: 't261008-33', status: ok ? 'pass' : 'fail',
    cause: ok ? 'self' : 'unknown', reason: ok ? '' : reason, evidence: evidence || reason })
}
function envFail(name, reason) {
  envfail++
  console.log(`[ENV_FAIL] ${name} — ${reason}`)
  emitCase({ name, suite: 't261008-33', status: 'not-checked', cause: 'external', reason, evidence: reason })
}

// venv fallback chain, same shape as the verify.yaml test check.
const { existsSync } = await import('node:fs')
let PY = join(REPO, 'server', 'engine', '.venv', 'bin', 'python')
if (!existsSync(PY)) PY = 'python3'

const tmp = mkdtempSync(join(tmpdir(), 'sandbar-t26100833-env-'))
const lane = join(tmp, 'lane')
mkdirSync(lane, { recursive: true })
process.on('exit', () => { try { rmSync(tmp, { recursive: true, force: true }) } catch {} })

const CHILD = `
import json, os, sys
sys.path.insert(0, ${JSON.stringify(join(REPO, 'server', 'engine'))})
from agent_activities import integ_subprocess_env, lane_subprocess_env
lane = sys.argv[2]
def stripped(anchor):
    if anchor is None: os.environ.pop('SANDBAR_REPO', None)
    else: os.environ['SANDBAR_REPO'] = anchor
    return 'SANDBAR_REPO' not in integ_subprocess_env()
def lane_anchor(anchor):
    if anchor is None: os.environ.pop('SANDBAR_REPO', None)
    else: os.environ['SANDBAR_REPO'] = anchor
    env = lane_subprocess_env(lane)
    return env.get('SANDBAR_REPO')
main_like = ${JSON.stringify(tmp)}  # any non-lane value; the point is non-inheritance
foreign = os.path.join(${JSON.stringify(tmp)}, 'elsewhere')
out = {
  'stripped_main': stripped(main_like),
  'stripped_foreign': stripped(foreign),
  'stripped_absent': stripped(None),
  'lane_main': lane_anchor(main_like),
  'lane_foreign': lane_anchor(foreign),
  'lane_absent': lane_anchor(None),
}
print('RESULT=' + json.dumps(out))
`

function runChild() {
  return spawnSync(PY, ['-B', '-c', CHILD, 'prog', lane], {
    cwd: REPO, encoding: 'utf8', timeout: 60000,
    env: { ...process.env, SANDBAR_REPO: join(tmp, 'parent-carries-this') },
  })
}

let res = runChild()
if (res.error || res.status === null && res.signal) {
  envFail('engine-env-helpers-reachable', `python child failed to run: ${res.error || res.signal}`)
} else if (res.status !== 0) {
  const err = `${res.stderr || ''}\n${res.stdout || ''}`
  if (/ModuleNotFoundError|ImportError/.test(err) && !/lane_subprocess_env|cannot import name/.test(err)) {
    envFail('engine-env-helpers-reachable', `agent_activities unimportable for an external reason: ${err.split('\n').filter(l => l.includes('Error')).join(' | ').slice(0, 300)}`)
  } else {
    judge('lane-env-single-point-landed', false,
      'engine env seam not landed or broken (lane_subprocess_env / widened integ_subprocess_env): TDD-phase red expected pre-implement',
      err.slice(-400))
  }
} else {
  const line = (res.stdout || '').split('\n').find(l => l.startsWith('RESULT='))
  const out = line ? JSON.parse(line.slice(7)) : {}
  const laneReal = realpathSync(lane)
  const eq = (a, b) => a != null && String(a) === String(b)
  judge('strip-family-covers-main-value', out.stripped_main === true, `integ_subprocess_env stripped=${out.stripped_main}`)
  judge('strip-family-covers-foreign-value', out.stripped_foreign === true, `integ_subprocess_env stripped=${out.stripped_foreign}`)
  judge('strip-family-covers-absent-value', out.stripped_absent === true, `integ_subprocess_env stripped=${out.stripped_absent}`)
  judge('lane-helper-anchors-main-value-at-lane', eq(out.lane_main, laneReal) || eq(out.lane_main, lane), `lane anchor=${out.lane_main}`)
  judge('lane-helper-anchors-foreign-value-at-lane', eq(out.lane_foreign, laneReal) || eq(out.lane_foreign, lane), `lane anchor=${out.lane_foreign}`)
  judge('lane-helper-anchors-absent-value-at-lane', eq(out.lane_absent, laneReal) || eq(out.lane_absent, lane), `lane anchor=${out.lane_absent}`)
}

console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envfail}`)
process.exit(envfail ? 2 : failed ? 1 : 0)

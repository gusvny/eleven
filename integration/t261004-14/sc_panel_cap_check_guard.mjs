// sc_panel_cap_check_guard.mjs — t261004-14 mechanical cap check (grey-box L3,
// browser-free, offline, seconds; `ro` pool + serial).
//
// Intent (user-perceivable in the guard sense: the incident class — a silent
// inline cap hiding rows in a panel list — must be caught mechanically, not by
// reading code): the check lives in the plugin, scans render paths for cap-like
// constants (Math.min(len, <int literal>) loop bounds, .slice(0, <int literal>),
// equivalents), passes when every cap is a declared contract reference, and
// FAILS on any integer literal in a cap-like position — including a literal
// whose VALUE coincides with a declared cap (value-coincidence is a false-pass
// hole; the binding rule is by reference, not by number).
//   G1 The check exists and passes on the current tree (the incident's
//      Math.min(wakes.length,3) is gone / declared).
//   G2 An injected undeclared cap (Math.min(x.length, 5)) fails and names the
//      offending file (file:line or file).
//   G3 Value-coincidence fails: .slice(0, 12) where 12 equals the declared
//      recent-actions cap must still fail (not auto-whitelisted by value).
//   G4 The declared-reference form passes: a render loop bound to the contract
//      cap (non-literal operand) is not flagged.
//   D2 The contract doc states where the check lives and how to run it.
//
// Seam: server/plugins/executor-panel/check_list_caps.mjs; the script must
// accept a target directory (argv[2] or SANDBAR_CAP_CHECK_TARGET) so the guard
// can prove both faces without mutating the tree. Missing script or seam = FAIL
// with the name (TDD-phase red is expected; arbitrate/merge must be green).
// The script scans .ts files under the target dir.
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync, copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()
const CHECK = join(REPO, 'server/plugins/executor-panel/check_list_caps.mjs')
const SRC_DIR = join(REPO, 'server/plugins/executor-panel/src/host')
const DOC_PATH = join(REPO, 'docs/reference/panel-list-conventions.md')
const PANEL_PAGE = join(SRC_DIR, 'panel-page.ts')

/** Isolated fixture dir (lint L8: reclaimed on every exit path). */
function fixtureDir() {
  const dir = mkdtempSync(join(tmpdir(), 't261004-14-cap-'))
  const clean = () => rmSync(dir, { recursive: true, force: true })
  process.on('exit', clean)
  process.on('SIGINT', () => { clean(); process.exit(130) })
  return dir
}

/** Run the check against a directory; returns {code, out}. Prefers the argv seam
 *  (node check_list_caps.mjs <dir>); falls back to SANDBAR_CAP_CHECK_TARGET. */
function runCheck(dir) {
  const byArg = spawnSync('node', [CHECK, dir], { encoding: 'utf8', timeout: 30_000 })
  if (!byArg.error) return { code: byArg.status, out: (byArg.stdout || '') + (byArg.stderr || '') }
  const byEnv = spawnSync('node', [CHECK], { encoding: 'utf8', timeout: 30_000, env: { ...process.env, SANDBAR_CAP_CHECK_TARGET: dir } })
  if (byEnv.error) return { code: null, out: String(byEnv.error) }
  return { code: byEnv.status, out: (byEnv.stdout || '') + (byEnv.stderr || '') }
}

function writeFixture(withLines) {
  const dir = fixtureDir()
  mkdirSync(dir, { recursive: true })
  copyFileSync(PANEL_PAGE, join(dir, 'panel-page.ts'))
  if (withLines) {
    const src = readFileSync(PANEL_PAGE, 'utf8')
    writeFileSync(join(dir, 'panel-page.ts'), src + '\n' + withLines + '\n')
  }
  return dir
}

async function main() {
  // D2 doc face: states where the check lives and how to run it.
  if (!existsSync(DOC_PATH)) {
    C.case('D2-doc-states-check', false, 'docs/reference/panel-list-conventions.md missing')
  } else {
    const doc = readFileSync(DOC_PATH, 'utf8')
    C.case('D2-doc-states-check', /check_list_caps/.test(doc), 'doc must name the check script (where it lives, how to run)')
  }

  if (!existsSync(CHECK)) {
    C.case('G1-check-passes-current-tree', false, 'server/plugins/executor-panel/check_list_caps.mjs missing (Part B: mechanical check)')
    C.case('G2-undeclared-cap-fails', false, 'check script missing')
    C.case('G3-value-coincidence-fails', false, 'check script missing')
    C.case('G4-declared-reference-passes', false, 'check script missing')
    return C.exit()
  }
  if (!existsSync(PANEL_PAGE)) {
    C.case('G1-check-passes-current-tree', false, 'render source panel-page.ts missing')
    return C.exit()
  }

  // G1: current tree passes.
  const r1 = runCheck(join(REPO, 'server/plugins/executor-panel/src'))
  C.case('G1-check-passes-current-tree', r1.code === 0, `exit=${r1.code} out=${(r1.out || '').trim().slice(0, 160)}`)

  // G2: injected undeclared literal cap fails and names the file.
  const f2 = writeFixture('function renderX(list){ var h=""; for(var i=0;i<Math.min(list.length,5);i++){ h+=list[i]; } return h; }')
  const r2 = runCheck(f2)
  C.case('G2-undeclared-cap-fails', r2.code === 1 && /panel-page\.ts/.test(r2.out), `exit=${r2.code} out=${(r2.out || '').trim().slice(0, 160)}`)

  // G3: value-coincidence — slice(0, 12) with a value equal to a declared cap
  // (recent actions declares 12) must still fail: the rule is by reference.
  const f3 = writeFixture('function renderY(list){ return list.slice(0, 12); }')
  const r3 = runCheck(f3)
  C.case('G3-value-coincidence-fails', r3.code === 1, `exit=${r3.code} out=${(r3.out || '').trim().slice(0, 160)}`)

  // G4: declared-reference form (non-literal operand) passes.
  const f4 = writeFixture('function renderZ(list, CAP){ var h=""; for(var i=0;i<Math.min(list.length, CAP);i++){ h+=list[i]; } return h; }')
  const r4 = runCheck(f4)
  C.case('G4-declared-reference-passes', r4.code === 0, `exit=${r4.code} out=${(r4.out || '').trim().slice(0, 160)}`)

  return C.exit()
}

main().catch((e) => { C.case('scenario-crash', false, String(e).slice(0, 300)); C.exit() })

/**
 * narrow_dash_check.mjs — THE ONE NARROW CHECK, registered scenario face
 * (ticket t261026-11, piece 3; host ruling 261026).
 *
 * The rule lives in ONE implementation: integration/lint_face_dash.py
 * (battery rule L28, wired into lint_tests.py) against the ONE table
 * integration/face_dash_exemptions.json — outside the funnel module
 * (server/plugins/workbench/src/shared/face-value.ts) a bare placeholder
 * literal ('—' / "—") in a host face module is an error; the table only
 * shrinks (a stale exemption is itself an error); comments are skipped (a
 * dash mentioned is not a dash constructed). This scenario is that rule's
 * registered, intent-carrying face: same implementation, same table — never
 * a second hand-kept copy (a fork here would let the two tables drift).
 *
 * Exit mapping: L28 clean = PASS exit 0; any violation = FAIL exit 1;
 * the rule's inputs missing (trees/table/implementation) = ENV_FAIL exit 2.
 *
 * Run: node integration/t261026-11/narrow_dash_check.mjs   (cwd = repo root)
 */
import { execFileSync } from 'node:child_process'

let out = ''
try {
  out = execFileSync('python3', ['integration/lint_face_dash.py'], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
} catch (e) {
  const text = String(e.stdout || '') + String(e.stderr || '')
  if (text.includes('ENV_FAIL') || e.status === 2) {
    console.log(`ENV_FAIL: the L28 rule could not run: ${text.slice(-300)}`)
    process.exit(2)
  }
  for (const line of text.split('\n')) if (line.startsWith('L28 ') || line.startsWith('ERROR')) console.log(line)
  console.log('FAIL the one narrow check found violations (see L28 lines above)')
  process.exit(1)
}
for (const line of out.split('\n')) if (line.startsWith('L28 ')) console.log(`ok   ${line}`)
console.log('SUMMARY the one narrow check clean via the L28 implementation, ONE table (t261026-11)')
process.exit(0)

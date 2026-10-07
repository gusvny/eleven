// lib_t26100617.mjs — shared fixtures for the t261006-17 (CL-2) panel scenarios.
//
// Grey-box L3 seam reuse: the panel harness protocol lives in
// integration/t260929-03/lib_panel_harness.mjs (startHarness / makeCase /
// makeIsoDir). This ticket adds only concurrency-ledger fixtures.
//
// Engine faces consumed (public, pinned in the approved CL-2 plan):
//   READ : <enginePython> server/tools/ticket.py '{"op":"concurrency","project":<key>}'
//          with SANDBAR_PROJECTS_DIR=<isolated root> (the engine's declared
//          fixture env, same face t261004-32 uses). Receipt:
//          {project, limit, unlimited, decl, holders:[{ticket,since,reason,held_s}],
//           queue:[{ticket,position,since,waited_s}]}; named refusals otherwise.
//   WRITE: server/engine/client.py concurrency-limit-write (CL-2b, may be absent).
//   Panel: GET/POST /sandbar-executor-panel/api/concurrency?project=<key>.
import { spawnSync } from 'node:child_process'
import { existsSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'

export const REPO = join(import.meta.dirname, '..', '..')
export const TICKET = join(REPO, 'integration', 't261006-17')

export function enginePython() {
  if (process.env.SANDBAR_ENGINE_PYTHON) return process.env.SANDBAR_ENGINE_PYTHON
  const venv = join(REPO, 'server', 'engine', '.venv', 'bin', 'python')
  return existsSync(venv) ? venv : 'python3'
}

/** Seed one project's ledger under an isolated projects root. */
export function seedProject(root, key, decl, state, auditLines) {
  const dir = join(root, key)
  mkdirSync(dir, { recursive: true })
  if (decl !== null) writeFileSync(join(dir, 'concurrency-limit.json'), JSON.stringify(decl))
  if (state !== null) writeFileSync(join(dir, 'concurrency-state.json'), JSON.stringify(state))
  if (auditLines !== undefined) {
    writeFileSync(join(dir, 'concurrency-limit-audit.jsonl'), auditLines.join('\n') + '\n')
  }
  return dir
}

/** Run the REAL engine read face (ticket.py op=concurrency) against a root. */
export function engineRead(root, key, timeout = 60) {
  const p = spawnSync(enginePython(), ['-B', join(REPO, 'server', 'tools', 'ticket.py'),
    // caller_project rides the SAME call (L12): an inherited SANDBAR_CALLER_PROJECT
    // from an outer lane round must never let the cross-project gate refuse first.
    JSON.stringify({ op: 'concurrency', project: key, caller_project: key })],
    { cwd: REPO, encoding: 'utf8', timeout: timeout * 1000,
      env: { ...process.env, SANDBAR_PROJECTS_DIR: root } })
  return { rc: p.status, stdout: p.stdout || '', stderr: p.stderr || '' }
}

/** Does the CL-2b engine write entry exist yet? (system-state probe, never guessed) */
export function engineWriteEntryPresent(root) {
  const p = spawnSync(enginePython(), ['-B', join(REPO, 'server', 'engine', 'client.py'),
    'concurrency-limit-write',
    JSON.stringify({ project: 'probe-nonexistent-key', limit: 3, by: 'host', caller_project: 'probe-nonexistent-key' })],
    { cwd: REPO, encoding: 'utf8', timeout: 60 * 1000,
      env: { ...process.env, SANDBAR_PROJECTS_DIR: root } })
  // The subcommand exists if the engine did NOT answer "unknown subcommand/op".
  const out = (p.stdout || '') + (p.stderr || '')
  const unknown = /未知子命令|unknown (subcommand|op|command)|unrecognized|invalid choice/i.test(out)
  return { present: p.status === 0 && !unknown, probe: out.slice(0, 300), rc: p.status }
}

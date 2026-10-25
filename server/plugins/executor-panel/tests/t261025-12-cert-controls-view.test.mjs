/**
 * t261025-12-cert-controls-view.test.mjs — the two certification controls'
 * pure faces (ruling: executor-operational-envelope-v1 §5).
 *
 * Contract:
 *  - verdict pair: the rounds row renders BOTH verdicts (strict face pill AND
 *    record verdict labelled by its rule); missing record fields name the
 *    absence instead of collapsing into one word;
 *  - the promote dialog SHOWS the signer-to-be-recorded before the act (the
 *    prefill comes only from the declared owner) plus the eligible set from
 *    the writer's preview; a refused preview renders its named reason;
 *  - the queue note turns the queue route's answer into ONE honest sentence
 *    (queued / already queued + what it waits on / the verbatim refusal).
 * Every input is an in-memory fixture — no engine, no adapter, no network.
 */
import { assert, done } from './lib.mjs'
import { buildCertificationCore, buildRoundsRows, buildPromoteDialogCore, certQueueNoteText } from '../src/host/certification-view.ts'

let n = 0

// ---- C: the verdict pair ----
{
  const rf = {
    dir: '/r',
    live: { ok: false, reason: 'no live round' },
    rounds: [{
      run_id: 'run-260925-1000',
      face: {
        state: 'done', started_at: '2026-09-25T10:00:00Z',
        outcome: { verdict: 'red', reason: '14 environment-reds',
          record_verdict: 'green', record_rule: 'content-v1' },
        counts: { pass: 712, fail: 0, env_fail: 14 },
        revision: { repo: 'sandbar', revision: '6efc7b3eabcd' },
      },
    }],
  }
  const html = buildRoundsRows(rf, [], false)
  assert(html.includes('data-k="red"'), 'the strict face verdict renders its red pill (env_fail>0 means red)')
  assert(html.includes('>record green · content-v1<'), 'the record verdict renders beside it, labelled by its rule')
  assert(html.includes('14 environment-reds'), 'the strict reason stays visible too — neither word is collapsed away')

  // the pair works the other way too: record red, face green
  const rf2 = JSON.parse(JSON.stringify(rf))
  rf2.rounds[0].face.outcome = { verdict: 'green', record_verdict: 'red', record_rule: 'content-v1' }
  const html2 = buildRoundsRows(rf2, [], false)
  assert(html2.includes('data-k="green"') && html2.includes('>record red · content-v1<'), 'both words render whichever way they disagree')

  // a face without the record fields names the absence — never an invented word
  const rf3 = JSON.parse(JSON.stringify(rf))
  delete rf3.rounds[0].face.outcome.record_verdict
  delete rf3.rounds[0].face.outcome.record_rule
  const html3 = buildRoundsRows(rf3, [], false)
  assert(html3.includes('no record verdict'), 'a face without record fields names the absence')
  assert(!html3.includes('content-v1'), 'no record rule is invented when the face carries none')

  // malformed face shapes degrade to the absence, never a crash
  const rf4 = { dir: '/r', live: { ok: true, face: { state: 'done', outcome: 'garbage' } }, rounds: [] }
  const html4 = buildRoundsRows(rf4, [], false)
  assert(html4.includes('no record verdict') || html4.includes('unreadable outcome'), 'a malformed outcome degrades by name')
  n += 8
}

// ---- B: the signed-promotion dialog shows the signer before the act ----
{
  const preview = {
    ok: true, project: 'proj-x',
    lines: [{ ok: true, line_id: 'develop-buffer', cert_id: 'cert-01ABC', revisions: { sandbar: '6efc7b3eabcd0123' } }],
    promotable: 1, promoteBlock: '',
  }
  const html = buildPromoteDialogCore({ owner: '徐辛', line: 'develop-buffer', preview })
  assert(html.includes('id="promoteSigner" value="徐辛"'), 'the signer input is prefilled ONLY from the declared owner')
  assert(html.includes('an agent role name is refused by the engine'), 'the dialog names the engine-side identity rule')
  assert(html.includes('cert-01ABC') && html.includes('sandbar:6efc7b3e'), 'the eligible set (cert + revisions) is shown before the act')
  assert(html.includes('id="promoteGo"') && html.includes('id="promoteCancel"'), 'act and cancel controls render')

  // a refused preview renders the engine's named refusal verbatim
  const refused = buildPromoteDialogCore({ owner: '', line: 'develop-buffer',
    preview: { ok: false, reason: 'no_green_certification:develop-buffer' } })
  assert(refused.includes('no_green_certification:develop-buffer'), 'a refused preview shows the engine refusal verbatim')
  const absent = buildPromoteDialogCore({ owner: '', line: 'develop-buffer', preview: null })
  assert(absent.includes('the promotion face is not readable'), 'a missing preview names its absence, never an empty set')

  // an agent-role-looking owner still PREFILLS (the engine refuses it, the UI
  // does not silently look legitimate: the rule note is on the dialog itself)
  const agentOwner = buildPromoteDialogCore({ owner: 'developer', line: 'l', preview })
  assert(agentOwner.includes('value="developer"'), 'the agent-role owner is not silently swapped away')
  assert(agentOwner.includes('an agent role name is refused by the engine'), 'the identity rule stays visible beside it')
  n += 7
}

// ---- A: the queue note says one honest sentence ----
{
  const queued = certQueueNoteText({
    ok: true, state: 'queued',
    queue: { marker: { present: true, path: '/m' }, guard: { held: false, path: '/g' },
      in_flight: { running: false, run: null, note: null },
      runners: [{ line: 'develop-buffer', state: 'resolvable' }] },
  })
  assert(queued.startsWith('queued'), 'a queued answer says queued (never running)')
  assert(queued.includes('scan tick'), 'the latency is honest: the scan tick picks it up')

  const waiting = certQueueNoteText({
    ok: true, state: 'queued',
    queue: { marker: { present: true, path: '/m' }, guard: { held: true, path: '/g' },
      in_flight: { running: true, run: 'run-1', note: null },
      runners: [{ line: 'develop-buffer', state: 'runner_missing' }, { line: 'l2', state: 'resolvable' }] },
  })
  assert(waiting.includes('waiting on'), 'the waits are introduced')
  assert(waiting.includes('guard is held') && waiting.includes('in flight') && waiting.includes('runner is not resolvable'), 'each named wait renders')
  assert(waiting.includes('develop-buffer'), 'the missing runner names its line')

  const again = certQueueNoteText({ ok: true, state: 'already_queued', queue: { guard: { held: false }, in_flight: { running: false }, runners: [] } })
  assert(again.startsWith('already queued'), 'an idempotent second click reads already queued')

  const refused = certQueueNoteText({ ok: false, error: 'the queue state is not readable — the round was not queued: adapter failed' })
  assert(refused.startsWith('The round was not queued:') && refused.includes('adapter failed'), 'a refusal travels verbatim')
  n += 6
}

done(n)

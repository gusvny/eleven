/**
 * t261019-23-certification-host-findings.test.mjs — the host review 261019's
 * seven findings, locked as unit behavior (F3/F4/F6 here; F1/F2/F5/F7 have
 * their page-shape assertions in t261009-44 / t261016-09).
 *
 * Faces under test:
 *  - F3: every landing moment renders dated ('YYYY-MM-DD HH:MM'), never a
 *    bare clock.
 *  - F4 (review C1): certified AND waiting sort newest-first by the row's own
 *    waiting_since (the engine puts it on every wait-state row); a row with
 *    a missing/non-numeric moment sorts LAST and still renders.
 *  - F6: the measured cell reads 'line <repo>:<sha8>' — a labelled revision,
 *    never a bare short sha.
 * Every group carries malformed-input variants (the consumer-input rule):
 * nothing throws, nothing invents — the absence is named by an empty cell or
 * a sink-to-last sort.
 */
import { assert, done } from './lib.mjs'
import { buildCertificationCore, buildRoundDialogCore, buildRoundsRows, roundMeasured, ROUND_COPIES } from '../src/host/certification-view.ts'
import {
  deriveCertificationFace,
  formatStamp,
  measuredToken,
  waitingMoment,
} from '../../workbench/src/client/certification-model.ts'

let n = 0

const T0 = Date.UTC(2026, 9, 12, 14, 0, 0) // 2026-10-12T14:00:00Z

const baseInput = (waits, runs) => ({
  line: { line_id: 'develop-buffer' },
  freeze: { frozen: false, episode: null, cause: null, culprit: null, closed_at: null },
  waitStates: waits,
  outcomes: [],
  certs: [],
  runs,
  ticketMeta: {
    't-old': { title: 'Old landing', epic: 'epic-a' },
    't-new': { title: 'New landing', epic: 'epic-a' },
    't-bad': { title: 'Broken moment', epic: 'epic-a' },
  },
})

// ---- F3: moments carry their date -----------------------------------------
{
  const p = (x) => String(x).padStart(2, '0')
  const d = new Date(T0)
  const expected = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  assert(formatStamp(T0) === expected, 'formatStamp renders YYYY-MM-DD HH:MM (local)')
  assert(formatStamp('not a number') === '' && formatStamp(-1) === '' && formatStamp(undefined) === '',
    'formatStamp degrades to empty on garbage input (named by the empty cell)')
  const face = deriveCertificationFace(baseInput(
    [{ ticket: 't-new', state: 'waiting', waiting_since: T0 }],
    [],
  ))
  assert(face.ok === true && face.waiting[0].landedAt === expected,
    'a waiting row lands with its date')
  const html = buildCertificationCore({
    ok: true, project: 'p', line: 'develop-buffer',
    lines: [{ line_id: 'develop-buffer' }], face, raw: {}, notes: [], round_faces: { dir: '/r', rounds: [] },
  })
  assert(html.includes(expected), 'the rendered table carries the dated landing')
  n += 4
}

// ---- F4 (review C1): newest-first on BOTH lists, broken moments sink ------
{
  const waits = [
    { ticket: 't-old', state: 'certified', waiting_since: T0 - 86_400_000, covered_by: 'run-1' },
    { ticket: 't-new', state: 'certified', waiting_since: T0, covered_by: 'run-2' },
    { ticket: 't-bad', state: 'certified', waiting_since: 'not-a-number', covered_by: 'run-3' },
  ]
  const face = deriveCertificationFace(baseInput(waits, []))
  assert(face.certified.map((c) => c.ticket).join(',') === 't-new,t-old,t-bad',
    'certified sorts newest-first, the unreadable moment last (never dropped)')
  const newStamp = formatStamp(T0)
  assert(face.certified[0].landedAt === newStamp && face.certified[2].landedAt === '',
    'each certified row names its moment; the unreadable one names the absence')
  const wface = deriveCertificationFace(baseInput([
    { ticket: 't-old', state: 'waiting', waiting_since: T0 - 86_400_000 },
    { ticket: 't-new', state: 'waiting', waiting_since: T0 },
    { ticket: 't-bad', state: 'red_implicated', waiting_since: null },
  ], []))
  assert(wface.waiting.map((w) => w.ticket).join(',') === 't-new,t-old,t-bad',
    'waiting sorts newest-first, the unreadable moment last')
  assert(waitingMoment({}) === -Infinity && waitingMoment(null) === -Infinity && waitingMoment({ waiting_since: 5 }) === 5,
    'the sort key sinks missing/non-object moments without throwing')
  n += 4
}

// ---- F6: the measured cell is a labelled revision --------------------------
{
  assert(measuredToken([{ repo: 'sandbar', revision: '5bb7de8dabcdef12' }]) === 'line sandbar:5bb7de8d',
    'measured reads line <repo>:<sha8>')
  assert(measuredToken([{ revision: '5bb7de8d' }]) === 'line 5bb7de8d',
    'an absent repo name falls back to the bare revision (never invented)')
  assert(measuredToken([]) === 'line ?' && measuredToken(null) === 'line ?' && measuredToken([{ repo: 7 }]) === 'line ?',
    'absent/malformed revision sets stay line ? (the named absence)')
  const rows = buildRoundsRows({
    dir: '/r',
    rounds: [{ run_id: 'run-a', face: { run_id: 'run-a', state: 'done', started_at: '2026-10-12T14:00:00Z', outcome: { verdict: 'green', reason: '' }, revision: { sandbar: '5bb7de8dabcdef12' } } }],
  }, [])
  assert(rows.includes('line sandbar:5bb7de8d'), 'the Rounds table renders the labelled revision')
  // t261019-23 rework: the Measured cell prefers the run header's own repos
  // entry (the model's measuredToken rule); the face revision stays the
  // fallback for a run no header names.
  const rowsH = buildRoundsRows({
    dir: '/r',
    rounds: [
      { run_id: 'run-a', face: { run_id: 'run-a', state: 'done', started_at: '2026-10-12T14:00:00Z', outcome: { verdict: 'green', reason: '' }, revision: { repo: 'other', revision: 'ffffffffffffffff' } } },
      { run_id: 'run-nohdr', face: { run_id: 'run-nohdr', state: 'done', started_at: '2026-10-12T13:00:00Z', outcome: { verdict: 'green', reason: '' }, revision: { repo: 'sandbar', revision: '5bb7de8dabcdef12' } } },
      { run_id: 'run-bad', face: { run_id: 'run-bad', state: 'done', started_at: '2026-10-12T12:00:00Z', outcome: { verdict: 'green', reason: '' } } },
    ],
  }, [
    { id: 'run-a', source: 'scheduled', repos: [{ repo: 'sandbar', revision: 'c'.repeat(40) }] },
    { id: 'run-bad', source: 'scheduled', repos: [{ repo: 'sandbar' }] },
  ])
  assert(rowsH.includes('line sandbar:cccccccc'), 'the header repos entry drives the Measured cell')
  assert(rowsH.includes('line sandbar:5bb7de8d'), 'a run no header names falls back to its face revision')
  assert(rowsH.includes('line ?'), 'a header entry without a readable revision names line ?')
  // t261019-23 rework: the face writer's OWN shape is one {repo, revision}
  // entry (not a repo-keyed map) — and the fallback/absence shapes hold.
  assert(roundMeasured({ repo: 'sandbar', revision: 'c'.repeat(40) }) === 'line sandbar:cccccccc',
    'a {repo,revision} face entry reads line <repo>:<sha8>')
  assert(roundMeasured({ revision: 'c'.repeat(40) }) === 'line cccccccc',
    'a repo-less entry renders the plain sha fallback, never a made-up label')
  assert(roundMeasured({ revision: null }) === 'line ?' && roundMeasured({}) === '—',
    'an unreadable revision names line ?; an absent set renders the em-dash')
  n += 3
}

// ---- F5: running pills carry their last write; unbacked running = stale ---
{
  const face = (stamp) => ({ run_id: 'run-live', state: 'running', started_at: '2026-10-12T14:39:43Z', updated_at: stamp })
  const rf = (stamp) => ({ dir: '/r', live: { ok: true, face: face(stamp) }, rounds: [] })
  const backed = buildRoundsRows(rf('2026-10-12T14:39:48Z'), [], true)
  assert(backed.includes('>running · last write 2026-10-12T14:39:48Z<'),
    'a backed running pill carries its own last-write moment')
  const stale = buildRoundsRows(rf('2026-10-12T14:39:48Z'), [], false)
  assert(stale.includes('>stale · no write since 2026-10-12T14:39:48Z<') && !stale.includes('>running<'),
    'a running face the engine does not back reads stale')
  const nostamp = buildRoundsRows(rf(undefined), [], true)
  assert(nostamp.includes(ROUND_COPIES.writeUnreadable),
    'a face without updated_at names the unreadable write time')
  const dialog = buildRoundDialogCore({ ok: true, run: 'run-live', wrote: [], face: face('2026-10-12T14:39:48Z') })
  assert(dialog.includes('running · last write 2026-10-12T14:39:48Z'),
    'the round dialog claims its last write too')
  n += 4
}

// ---- F4: the Rounds table sorts newest-first ------------------------------
{
  const rows = buildRoundsRows({
    dir: '/r',
    rounds: [
      { run_id: 'run-old', face: { run_id: 'run-old', state: 'done', started_at: '2026-10-11T14:46:00Z', outcome: { verdict: 'green', reason: '' } } },
      { run_id: 'run-new', face: { run_id: 'run-new', state: 'done', started_at: '2026-10-12T14:46:00Z', outcome: { verdict: 'red', reason: 'x' } } },
      { run_id: 'run-bad', face: { run_id: 'run-bad', state: 'done', outcome: { verdict: 'green', reason: '' } } },
    ],
  }, [])
  const iNew = rows.indexOf('data-round-link="run-new"')
  const iOld = rows.indexOf('data-round-link="run-old"')
  const iBad = rows.indexOf('data-round-link="run-bad"')
  assert(iNew !== -1 && iNew < iOld && iOld < iBad,
    'rounds sort newest-first; the face without started_at sinks last, still rendered')
  n += 1
}

done(n)

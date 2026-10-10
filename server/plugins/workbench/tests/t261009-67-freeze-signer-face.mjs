/**
 * t261009-67 — the signer's freeze face in the certification model.
 *
 * Covers, against the workbench model (the ONE derivation both surfaces
 * read): the engine's `open_freeze_summary` output reaches `frozenFace` as
 * the cause certification and the chain of fixes (design items 166/167) —
 *   - frozen + summary present: cause and chain carried, unresolved repairs
 *     stay visible as `repaired: null` (never guessed closed);
 *   - frozen + summary ABSENT (an older adapter receipt): empty signer face
 *     rides along, the face stays ok;
 *   - frozen + summary MALFORMED: the whole face degrades BY NAME — a frozen
 *     line whose signer face cannot be read is never rendered as if it could;
 *   - unfrozen: the summary is irrelevant, face ok.
 */
import assert from 'node:assert/strict'
import { deriveCertificationFace } from '../src/client/certification-model.ts'

let n = 0

function input(over = {}) {
  return {
    line: { line_id: 'develop-buffer' },
    freeze: { frozen: true, episode: 'frz-01', cause: 'cert-01',
              culprit: 'ldg-a01', closed_at: null },
    freezeSummary: {
      frozen: true, freeze: 'frz-01', cause: 'cert-01',
      culprit: 'ldg-a01', opened_at: 3000,
      fix_landings: [
        { landing: 'ldg-f01', ticket: 't-fix', at: 3500,
          repairs: [{ id: 'rel-r01', repaired: 'ldg-a01' }] },
        { landing: 'ldg-f02', ticket: 't-fix2', at: 3600,
          repairs: [{ id: 'rel-r02', repaired: null }] },
      ],
    },
    waitStates: [], outcomes: [], certs: [], runs: [], ticketMeta: {},
    ...over,
  }
}

// ---- frozen + summary: cause and chain reach the signer face ----
{
  const f = deriveCertificationFace(input())
  assert(f.ok && f.frozen, `frozen face ok (${++n})`)
  assert(f.frozenFace.cause === 'cert-01', `cause carried (${++n})`)
  assert.deepEqual(f.frozenFace.fixChain, [
    { landing: 'ldg-f01', ticket: 't-fix', repaired: 'ldg-a01' },
    { landing: 'ldg-f02', ticket: 't-fix2', repaired: null },
  ], `fix chain with the unresolved gap visible (${++n})`)
}

// ---- frozen + summary ABSENT (older adapter receipt): rides along ----
{
  const f = deriveCertificationFace(input({ freezeSummary: null }))
  assert(f.ok && f.frozen, `absent summary stays ok (${++n})`)
  assert(f.frozenFace.cause === '' && f.frozenFace.fixChain.length === 0,
    `absent summary = empty signer face (${++n})`)
}

// ---- frozen + summary MALFORMED: degrade by name, never render blind ----
for (const bad of [7, 'junk', { cause: 7 }, { cause: 'cert-01', fix_landings: 'x' },
                   { cause: 'cert-01', fix_landings: [null, 7] }]) {
  const f = deriveCertificationFace(input({ freezeSummary: bad }))
  assert(!f.ok, `malformed summary ${JSON.stringify(bad)} degrades (${++n})`)
  assert(f.reason === 'freeze summary unreadable',
    `degradation named (${++n})`)
}

// ---- unfrozen: the summary is irrelevant ----
{
  const f = deriveCertificationFace(input({
    freeze: { frozen: false, episode: null, cause: null, culprit: null,
              closed_at: null },
    freezeSummary: { frozen: false, freeze: null, cause: null,
                     culprit: null, opened_at: null, fix_landings: [] },
  }))
  assert(f.ok && !f.frozen && f.frozenFace === null,
    `unfrozen face ok (${++n})`)
}

console.log(`t261009-67 freeze signer face: ${n} assertions ok`)

/**
 * t261009-67 — the Certification tab renders the signer's freeze face.
 *
 * The view core is a pure function over the route answer: when the line is
 * frozen and the derived face carries the cause certification and the chain
 * of fixes (from the engine's `open_freeze_summary` via the adapter), the
 * frozen banner names the cause and renders the chain — the promotion
 * signer sees "the buffer was frozen, for what, and which fix reopened it"
 * (design item 167). Unresolved repairs render without a fabricated target.
 */
import assert from 'node:assert/strict'
import { buildCertificationCore } from '../src/host/certification-view.ts'

let n = 0

function answer(over = {}) {
  return {
    ok: true,
    line: 'develop-buffer',
    face: {
      ok: true, reason: '', lineId: 'develop-buffer', state: 'FROZEN',
      frozen: true,
      frozenFace: {
        banner: 'Frozen by a red round — new landings stop; the certified part can still be promoted.',
        blockers: ['ldg-a01'],
        cause: 'cert-01',
        fixChain: [
          { landing: 'ldg-f01', ticket: 't-fix', repaired: 'ldg-a01' },
          { landing: 'ldg-f02', ticket: 't-fix2', repaired: null },
        ],
      },
      deliveredTotal: 1, certified: [], waiting: [], promotable: 2,
      boundary: null, rounds: [], roundState: 'idle',
    },
    lines: [{ line_id: 'develop-buffer', scope: 'epic x', owner: 'integration' }],
    ...over,
  }
}

// ---- frozen: cause + chain rendered, ids intact, unresolved not invented ----
{
  const html = buildCertificationCore(answer())
  assert(html.includes('id="certCause"'), `cause element (${++n})`)
  assert(html.includes('cause cert-01'), `cause id shown (${++n})`)
  assert(html.includes('id="certFixChain"'), `chain element (${++n})`)
  assert(html.includes('t-fix (ldg-f01 repairs ldg-a01)'),
    `resolved repair named (${++n})`)
  assert(html.includes('t-fix2 (ldg-f02)'), `unresolved repair has no target invented (${++n})`)
  assert(!html.includes('repairs null') && !html.includes('undefined'),
    `no null/undefined leaks into the chain (${++n})`)
}

// ---- frozen WITHOUT summary fields (older receipt): banner only, no crash ----
{
  const html = buildCertificationCore(answer({
    face: { ok: true, reason: '', lineId: 'l', state: 'FROZEN', frozen: true,
            frozenFace: { banner: 'Frozen by a red round', blockers: [],
                          cause: '', fixChain: [] },
            deliveredTotal: 0, certified: [], waiting: [], promotable: 0,
            boundary: null, rounds: [], roundState: 'idle' },
  }))
  assert(!html.includes('certCause') && !html.includes('certFixChain'),
    `no empty signer elements (${++n})`)
  assert(html.includes('FROZEN'), `banner still rendered (${++n})`)
}

// ---- not frozen: neither element exists ----
{
  const html = buildCertificationCore(answer({
    face: { ok: true, reason: '', lineId: 'l', state: 'GREEN', frozen: false,
            frozenFace: null, deliveredTotal: 0, certified: [], waiting: [],
            promotable: 0, boundary: null, rounds: [], roundState: 'idle' },
  }))
  assert(!html.includes('certCause') && !html.includes('certFixChain'),
    `unfrozen renders no signer face (${++n})`)
}

console.log(`t261009-67 certification view freeze face: ${n} assertions ok`)

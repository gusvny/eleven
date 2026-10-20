/**
 * t261019-09-close-overlay.mjs — the console side of the panel's close request.
 *
 * t261019-09: when the panel switches its own content (showTab) or opens a read
 * face, the console's ticket-detail overlay must not keep floating over content
 * the panel replaced. The contract gains ONE panel-to-console type
 * (sandbar-executor-panel:close-overlay, payload-less) and one console branch.
 *
 * Faces covered here:
 *  - closeOverlayFromMessage (face-overlay-model.ts, pure gate over external
 *    postMessage input): valid shape accepted; malformed shapes (null / numbers /
 *    strings / arrays / missing or wrong type) rejected without throwing;
 *  - constant pairing: the workbench constant and the panel page's copy are
 *    byte-identical (paired-constant discipline, same anchor shape as t261008-36);
 *  - source contract: executor-view.tsx wires the branch to a closeTicketOverlay
 *    prop; sidebar.tsx passes that prop through the existing listNonce channel
 *    (the declared sidebar->overlay seam, t260825-05).
 *  - no-op discipline (review R5): closing with nothing open is a no-op —
 *    asserted at the behavioural layer by exercising the same shape the
 *    WorkbenchSection listNonce effect performs (clear-only state writes), plus a
 *    source lock that the effect returns early on an unchanged nonce.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { closeOverlayFromMessage, CLOSE_OVERLAY_MSG_TYPE, OPEN_FACE_MSG_TYPE } from '../src/client/face-overlay-model.ts'

let n = 0
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
const viewSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/executor-view.tsx'), 'utf8')
const panelSrc = readFileSync(join(repo, 'server/plugins/executor-panel/src/host/panel-page.ts'), 'utf8')
const sidebarSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
const indexSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')

// ---- valid payload: exactly the declared type, nothing else required ----
assert.equal(closeOverlayFromMessage({ type: CLOSE_OVERLAY_MSG_TYPE }), true, `valid close accepted (${++n})`)
assert.equal(closeOverlayFromMessage({ type: CLOSE_OVERLAY_MSG_TYPE, extra: 1 }), true, `extra fields tolerated (payload-less by design) (${++n})`)

// ---- malformed external input: rejected, never thrown (fault modes carried over
// from panelFaceFromMessage: non-object / wrong type / never-throws; whitelist
// and projectKey dropped — no payload, no identity) ----
for (const bad of [null, undefined, 42, 'sandbar-executor-panel:close-overlay', [], {}, { type: 'sandbar-executor-panel:open-ticket' }, { type: CLOSE_OVERLAY_MSG_TYPE.toUpperCase() }, { Type: CLOSE_OVERLAY_MSG_TYPE }]) {
  assert.equal(closeOverlayFromMessage(bad), false, `malformed ${JSON.stringify(bad)} rejected (${++n})`)
}
// never-throws: exotic prototypes too
assert.equal(closeOverlayFromMessage(new Date()), false, `non-plain object rejected (${++n})`)

// ---- paired constants: workbench <-> panel byte-identical ----
assert.ok(panelSrc.includes(`'${CLOSE_OVERLAY_MSG_TYPE}'`), `panel page carries the same literal (${++n})`)
const wbLiteral = CLOSE_OVERLAY_MSG_TYPE
const panelLiteral = panelSrc.match(/var CLOSE_OVERLAY_MSG_TYPE = '([^']+)'/)?.[1]
assert.equal(panelLiteral, wbLiteral, `panel constant byte-identical to the model (${++n})`)
assert.notEqual(CLOSE_OVERLAY_MSG_TYPE, OPEN_FACE_MSG_TYPE, `close type distinct from open-face (${++n})`)

// ---- source contract: one console branch, wired to the prop, sidebar passes it ----
assert.ok(viewSrc.includes('closeTicketOverlay'), `executor-view has the close prop (${++n})`)
assert.ok(viewSrc.includes('if (d.type === CLOSE_OVERLAY_MSG_TYPE)'), `executor-view has exactly the close branch (${++n})`)
assert.equal((viewSrc.match(/CLOSE_OVERLAY_MSG_TYPE\) {/g) || []).length, 1, `exactly one close dispatch branch (${++n})`)
assert.ok(sidebarSrc.includes('closeTicketOverlay={() => setListNonce(n => n + 1)}'), `sidebar wires close through the listNonce channel (${++n})`)
// Bundle/source skew guard (t261019-09 arbitration fault mode: the settle gate
// reverted the source line while the bundle kept it — either side alone is a
// no-op or a lie). The SERVED bundle must carry the compiled wiring.
const bundleSrc = readFileSync(join(repo, 'server/plugins/workbench/lib/client.js'), 'utf8')
assert.ok(bundleSrc.includes('closeTicketOverlay: () => setListNonce((n) => n + 1)'), `served bundle carries the compiled wiring (no source/bundle skew) (${++n})`)

// ---- R5 no-op discipline, behavioural layer: the listNonce close effect is
// clear-only state writes and skips an unchanged nonce (source lock on the
// WorkbenchSection effect) ----
const closeEffect = indexSrc.match(/const listNonceRef[\s\S]*?\}, \[listNonce\]\)/)?.[0] ?? ''
assert.ok(closeEffect.includes('if (listNonceRef.current === listNonce) return'), `unchanged nonce = early return (close of nothing is a no-op) (${++n})`)
assert.ok(closeEffect.includes('setOverlayNav(EMPTY_OVERLAY)') && closeEffect.includes('setSelectedId(null)'), `close = clear-only state writes, no fetch no throw (${++n})`)

// ---- the panel page guards the post behind embedded-only ----
assert.ok(/if\(window\.parent !== window\)\{\s*window\.parent\.postMessage\(\{ type: CLOSE_OVERLAY_MSG_TYPE \}/.test(panelSrc), `showTab posts close only when embedded (${++n})`)
// face entry posts close BEFORE open-face (FIFO ordering, review R4)
const faceClick = panelSrc.match(/btn\.onclick = function\(\)\{[\s\S]*?\n    \};/)?.[0] ?? ''
assert.ok(faceClick.indexOf('CLOSE_OVERLAY_MSG_TYPE') !== -1 && faceClick.indexOf('CLOSE_OVERLAY_MSG_TYPE') < faceClick.indexOf('OPEN_FACE_MSG_TYPE'), `face entry posts close before open-face (${++n})`)

console.log(`done ${n}`)

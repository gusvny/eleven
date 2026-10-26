/**
 * face-value.test.mjs — the funnel's unit truth table (t261026-11).
 * Run: node integration/t261026-11/face-value.test.mjs  (cwd = repo root)
 * Zero io, zero network; imports the pure module from the workbench src.
 */
import assert from 'node:assert/strict'
import { FACE_DASH, absent, value, renderFace, reasonOf } from '../../server/plugins/workbench/src/shared/face-value.ts'

let n = 0
const ok = (cond, msg, detail = '') => { n += 1; assert.ok(cond, msg + (detail ? ' — ' + detail : '')) }
const throws = (fn, msg) => { n += 1; assert.throws(fn, msg) }

// ---- the one literal ----
ok(FACE_DASH === '—', 'F1 the funnel owns the one placeholder literal')

// ---- the union halves ----
ok(value(7).kind === 'value' && value(7).v === 7, 'F2 value() wraps without judging')
ok(absent('the metrics file was unreadable').kind === 'absent', 'F3 absent() takes the reason')

// ---- the type refuses the wrong shape: empty reasons do not pass ----
throws(() => absent(''), 'F4 absent("") throws (empty reason)')
throws(() => absent('   '), 'F5 absent("   ") throws (whitespace reason)')
throws(() => absent(undefined), 'F6 absent(undefined) throws (non-string)')
throws(() => absent(null), 'F7 absent(null) throws (non-string)')
throws(() => absent(42), 'F8 absent(42) throws (non-string)')
throws(() => absent('—'), 'F9 absent("—") throws (a dash is not a reason)')

// ---- render: value renders, absent renders THE dash ----
ok(renderFace(value(7)) === '7', 'F10 renderFace(value) renders the value')
ok(renderFace(value(412600000), (v) => (v / 1e6).toFixed(1) + 'M') === '412.6M', 'F11 renderFace honours the formatter')
ok(renderFace(absent('no coverage answer was served')) === '—', 'F12 renderFace(absent) renders the dash')
throws(() => renderFace({ kind: 'nope' }), 'F13 renderFace refuses a hand-built literal (wrong shape)')
throws(() => renderFace(null), 'F14 renderFace refuses null')

// ---- reasons stay reachable ----
ok(reasonOf(absent('the ledger line was malformed')) === 'the ledger line was malformed', 'F15 reasonOf(absent) keeps the sentence')
ok(reasonOf(value(1)) === '', 'F16 reasonOf(value) is empty')

// ---- words unchanged: the funnel does not invent sentences ----
ok(renderFace(value('')) === '', 'F17 an empty-string value is a value (the funnel does not second-guess)')

console.log(`face-value.test.mjs: ${n} checks, all green`)

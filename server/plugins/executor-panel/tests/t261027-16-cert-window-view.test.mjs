/**
 * t261027-16 — the certification view's runs-window word.
 *
 * The receipt states the runs window (deliverable a: the panel names the
 * bound, never a silent truncate). The view repeats it verbatim when
 * older > 0; absent or zero windows render nothing.
 */
import assert from 'node:assert/strict'
import { runsWindowNote } from '../src/host/certification-view.ts'

assert.ok(runsWindowNote({ shown: 20, total: 3600, older: 3580, cap: 20 })
  .includes('showing 20 of 3600 run headers (3580 older rounds not shown, cap 20)'),
'older > 0 renders the named window')
assert.ok(runsWindowNote({ shown: 20, total: 3600, older: 3580, cap: 20 })
  .includes('id="certRunsWindow"'), 'the window note carries its dom id')
assert.equal(runsWindowNote({ shown: 5, total: 5, older: 0, cap: 20 }), '', 'nothing hidden: no note')
assert.equal(runsWindowNote(undefined), '', 'absent window (older receipt): no note')
assert.equal(runsWindowNote('garbage'), '', 'malformed window: no note, no crash')
assert.equal(runsWindowNote({ older: 'many' }), '', 'non-numeric older: no note')
console.log('ok 6')

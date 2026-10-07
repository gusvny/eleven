/**
 * inspection-view.test.mjs — Inspection tab pure render model tests (t261006-15).
 *  - findings count and named items are two numbers written apart (N named of M counted);
 *  - coverage: 'not reviewed' never reads as 'no problem' — an unstated coverage is said so;
 *  - past-period read-only banner verbatim; every empty-state copy verbatim (EMPTY_COPIES contract);
 *  - the report JSON is untrusted external input: malformed/missing fields degrade, no throw, no fabrication (malformed-input stubs included).
 * Zero DOM, zero io, zero network.
 */
import assert from 'node:assert/strict'
import { buildPeriodView, EMPTY_COPIES, instanceLabel, INSTANCE_LABELS } from '../src/host/inspection-view.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

const slot = (report) => ({ ok: true, report })
const INSTANCES = ['integration-tests', 'simplify', 'docs-sync']
const reportOf = (inst, p) => p.reports[inst]

// ---- current period, healthy reports ----
const current = {
  period: '20261004',
  reports: {
    'integration-tests': slot({ findings: { high: 4, med: 2, low: 3 }, named: ['A guard watches a deleted file', { text: 'One row counted twice' }], coverage: { reviewed: ['a.ts', 'b.ts'], not_reviewed: ['c.ts'], reviewed_count: 2, total_count: 3 } }),
    'simplify': slot({ findings: { high: 1, med: 2, low: 4 }, named: [], coverage: { reviewed_count: 17, total_count: 1298 } }),
    'docs-sync': slot({}), // a report with nothing usable in it
  },
}
const v = buildPeriodView(current, '20261004', INSTANCES)
ok(v.read_only === false && v.banner === '', 'current period is not read-only')
const t = v.cards.find(c => c.instance === 'integration-tests')
ok(t.counts.total === 9 && /high 4/.test(t.counts_copy), 'counts extracted and worded')
ok(t.named.length === 2 && t.named_copy === '2 named of 9 counted', 'named vs counted are two numbers, stated apart')
ok(t.coverage_copy.includes('2 of 3 reviewed'), 'coverage line names the slice numbers')
ok(t.not_reviewed.length === 1 && t.not_reviewed[0] === 'c.ts', 'not-reviewed list is carried verbatim (never reads as no problem)')
const s = v.cards.find(c => c.instance === 'simplify')
ok(s.named_copy === '0 named of 7 counted', 'zero named items is explicit, not blank')
const d = v.cards.find(c => c.instance === 'docs-sync')
ok(d.counts === null && /gives no severity counts/.test(d.counts_copy), 'absent counts degrade to a stated absence, never 0')
ok(/does not state coverage/.test(d.coverage_copy), 'absent coverage stated as absent')

// ---- past period: read-only banner verbatim ----
const past = { period: '20261003', reports: { 'integration-tests': slot({ findings: { high: 1, med: 0, low: 0 } }) } }
const vp = buildPeriodView(past, '20261004', ['integration-tests'])
ok(vp.read_only === true && vp.banner === 'This period is closed. Shown read-only from its report.', 'past-period banner verbatim')

// ---- period absent from the archive: explicit not-available, never blank ----
const va = buildPeriodView(null, '20261004', INSTANCES)
ok(va.banner === EMPTY_COPIES.not_available && va.cards.length === 0, 'absent period renders the named not-available state')

// ---- a slot that failed to read (fail-closed) shows the reason on its card ----
const vbad = buildPeriodView(
  { period: '20261004', reports: { 'simplify': { ok: false, reason: 'report file is 300000 bytes (over the read cap)' } } },
  '20261004', ['simplify'])
const bc = vbad.cards[0]
ok(bc.report_error.includes('over the read cap'), 'failed report slot shows its named reason')
ok(bc.counts === null && /No counts without a report/.test(bc.counts_copy), 'failed slot shows no invented numbers')

// ---- malformed report shapes (untrusted external input): degrade, never throw ----
for (const junk of [null, 42, 'x', [], { findings: 'x' }, { findings: { high: 'a', med: 1, low: 2 } }, { coverage: 7 }]) {
  const vj = buildPeriodView({ period: '20261004', reports: { simplify: slot(junk) } }, '20261004', ['simplify'])
  ok(vj.cards.length === 1 && vj.cards[0].counts === null, `malformed report degrades: ${JSON.stringify(junk)?.slice(0, 30)}`)
}
// named accepts both string items and {text} items, drops junk items silently
const vn = buildPeriodView({ period: '20261004', reports: { simplify: slot({ findings: { high: 0, med: 0, low: 0, named: ['ok one', { text: 'ok two' }, 42, '', { nope: 1 }] } }) } }, '20261004', ['simplify'])
ok(vn.cards[0].named.join('|') === 'ok one|ok two', 'named items accept string and {text} shapes, drop junk')

// ---- instance labels: known mapped, unknown falls back to the id (never invented, never hidden) ----
ok(instanceLabel('integration-tests') === 'Integration tests', 'known instance mapped')
ok(instanceLabel('docs-sync') === 'Documents', 'doc face mapped')
ok(instanceLabel('mystery-face') === 'mystery-face', 'unknown instance falls back to its id')
ok(Object.keys(INSTANCE_LABELS).length === 3, 'label table stays the declared three faces')

// ---- range note is strictly informational (no claim that data exists elsewhere today) ----
ok(!/already|available at|see /.test(EMPTY_COPIES.range_note), 'range note makes no today-elsewhere claim')

console.log(`inspection-view.test: ${n} checks passed`)

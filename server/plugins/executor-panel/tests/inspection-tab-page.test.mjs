/**
 * inspection-tab-page.test.mjs — Inspection tab page-contract tests (t261006-15).
 *  - the tab slot is reachable in the static page (radio + label + pane + PANES entry);
 *  - every verbatim copy from EMPTY_COPIES appears in the page HTML (the single copy
 *    source stays inspection-view.ts; this test locks the page to it);
 *  - the host-only trigger copy and the mandatory-reason copy are present;
 *  - the embedded period-view core and the JSON tables are in the page script;
 *  - the layout discipline: ONE gutter variable (--igx) is used by card padding,
 *    section titles, note lines, table cells and the metrics grid (source-level check
 *    of the rule's structure; the Range measurement runs in the integration gate).
 * Importing PANEL_HTML compiles the whole page (TS strip), so a broken template fails
 * this file first. Zero DOM, zero network.
 */
import assert from 'node:assert/strict'
import { PANEL_HTML } from '../src/host/panel-page.ts'
import { EMPTY_COPIES, INSTANCE_LABELS } from '../src/host/inspection-view.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

// ---- slot reachable ----
ok(PANEL_HTML.includes('id="t-inspection"'), 'inspection radio present')
ok(PANEL_HTML.includes('data-tab="inspection"'), 'inspection label present (t261005-10 data-tab contract)')
ok(PANEL_HTML.includes('id="paneInsp"'), 'this ticket\'s pane body present')
ok(PANEL_HTML.includes("['t-inspection','paneInsp']"), 'pane registered in PANES (tab switching reaches it)')
ok((PANEL_HTML.match(/id="t-inspection"/g) || []).length === 1, 'exactly ONE inspection slot (reconcile done: t261005-10\'s radio kept, our duplicate dropped)')
ok(!PANEL_HTML.includes('paneInspection') && !PANEL_HTML.includes('loadInspection'), 'the placeholder scan-report face is fully retired (its content face replaced by this ticket\'s)')

// ---- verbatim copies (EMPTY_COPIES is the single source) ----
for (const [k, copy] of Object.entries(EMPTY_COPIES)) {
  ok(PANEL_HTML.includes(copy), `verbatim copy present in page: ${k}`)
}
ok(!PANEL_HTML.includes('No problem') && !PANEL_HTML.includes('all clear'), 'the page never reads "no problem"/"all clear"')

// ---- trigger faces ----
ok(PANEL_HTML.includes('Only you can start a full review. The executor cannot. A review is recorded when it starts.'), 'host-only copy verbatim')
ok(PANEL_HTML.includes('A reason is required — it is recorded with the trigger.'), 'mandatory-reason copy present')
ok(PANEL_HTML.includes('/sandbar-executor-panel/api/inspection/trigger'), 'trigger POST wired')
ok(PANEL_HTML.includes('/sandbar-workbench/api/wf/inspection-archive'), 'archive fetch wired')
ok(PANEL_HTML.includes('/sandbar-executor-panel/api/inspection/trigger-records'), 'records fetch wired')

// ---- embedded model + tables ----
ok(PANEL_HTML.includes('function buildPeriodViewCore('), 'period-view core embedded (one implementation with the unit tests)')
ok(PANEL_HTML.includes('"INSTANCE_LABELS"') && PANEL_HTML.includes('"Documents"'), 'instance label table embedded as JSON')
ok(PANEL_HTML.includes('INSP.tables.EMPTY_COPIES'), 'page consumes the embedded copies (no second copy source)')

// ---- layout discipline: one gutter variable across the named faces ----
const css = PANEL_HTML.slice(PANEL_HTML.indexOf('.inspCard{'), PANEL_HTML.indexOf('.inspFld select'))
ok(css.includes('--igx'), 'inspection CSS declares the shared gutter variable')
ok(css.includes('--isect') && css.includes('--icard') && css.includes('--iline'), 'three vertical rhythm steps declared')
ok((css.match(/var\(--igx/g) || []).length >= 5, `gutter reused across faces (got ${(css.match(/var\(--igx/g) || []).length} uses)`)
ok(css.includes('repeat(auto-fit,minmax(150px,1fr))'), 'metrics use an equal-width grid')
ok(css.includes('.inspCard th') && css.includes('padding:6px var(--igx'), 'table cells carry the same gutter')
ok(css.includes('.inspMeta') && css.includes('text-align:right'), 'right-aligned meta face declared')
ok(!/max-width:\s*900px/.test(PANEL_HTML), 'no narrow fixed page width (full-window rule)')

// ---- ordering declared in code (P2) ----
ok(PANEL_HTML.includes('inspection-archive.ts sortPeriodsDesc'), 'the page names the ordering single point')
ok(PANEL_HTML.includes('function inspLatestReported()'), 'the newest-reported scan is explicit page code')


// ---- arbitrate gen1 L1 fixes (regression locks) ----
ok(!PANEL_HTML.includes('class="pad inspSect" style="padding-left:0"'), 'block title carries no gutter-breaking inline override')
ok(PANEL_HTML.includes('#paneInsp summary::-webkit-details-marker{display:none}'), 'summary marker indent killed (webkit)')
ok(PANEL_HTML.includes("#paneInsp summary::marker{content:''}"), 'summary marker indent killed (standard)')
ok(PANEL_HTML.includes('state · result</th>') && PANEL_HTML.includes(`text-align:right">'+st+' · '+esc(res)`), 'records state+result share one right-aligned last column (right line)')


// ---- arbitrate gen2 residual fixes (regression locks) ----
ok(!PANEL_HTML.includes('padding-left:0">Reviewed'), 'reviewed summary carries no gutter-cancelling inline zero')
ok(PANEL_HTML.includes('#paneInsp details{padding:0;margin:0}'), 'details element is zero-inset (gutter comes from .inspNote alone)')
ok(PANEL_HTML.includes('#inspRunBtn{margin-right:2px}'), 'toolbar button box pulled onto the meta text line (2px, arbitrate gen2)')


// ---- 404 fix (rework): the Inspection faces load lazily on first tab open ----
ok(!PANEL_HTML.includes('loadGrants(); inspLoad()'), 'setProject does NOT eagerly fetch the inspection endpoints')
ok(PANEL_HTML.includes("if(r.id === 't-inspection') inspEnsureLoaded();"), 'first tab open triggers the lazy load')
ok(PANEL_HTML.includes('function inspEnsureLoaded()'), 'lazy-load gate present (one fetch per project)')
ok(PANEL_HTML.includes('A tab that is never opened must never'), 'the no-request-until-open rule is declared in code')


// ---- arbitrate gen4 fixes (regression locks) ----
ok(!PANEL_HTML.includes('style="margin:0" id="inspRunBtn"'), 'button carries no inline margin:0 override (the 2px right-line rule must win)')
ok(PANEL_HTML.includes('.inspCard table th:first-child,.inspCard table td:first-child{padding-left:12px}'), 'table first column pulled onto the text gutter (box +2 compensated)')

console.log(`inspection-tab-page.test: ${n} checks passed`)

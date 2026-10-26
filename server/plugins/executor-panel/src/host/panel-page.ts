/**
 * panel-page.ts —— 面板静态页（t261003-06 按 261003 定稿 mock 全面改版）。
 *
 * 为什么是「插件自服务的静态页」而不是 tsdown 构建包：零构建步骤 → 宿主交接=
 * 控制台重启一次装载插件 + 之后纯浏览器刷新；且 beep 决策/降级挑选等纯逻辑
 * **从 page-logic.ts 经 String(fn) 原样嵌入**——单测与页面永远同一份实现，不漂移。
 * 界面文案全英文（宿主令 260925：英文界面+数据不译），且全量按设计 note §4 的
 * 80% ASD-STE100 口径改写（短句、主动语态、固定术语、无缩略、无行话）。
 *
 * 版面（设计 note §2 / mock 261003）：顶部只有 Executor + 项目标签——项目选择器
 * （下拉/手填/Load）与轮询状态行**不存在**；项目来自 ?project= 深链（workbench
 * project row). Tabs (t261005-10 UI-2 consolidated order; t261009-37 removed Ledger+Alerts):
 * Overview / Epics / Inspection / Metrics / Docs / Grants / Settings——
 * Epics/Docs/Metrics/Inspection are read-only faces (source = same-origin workbench
 * GET endpoints; unreachable = a named degraded face, never a blank pane). The
 * Overview carries ONE concurrency-limit row (the CL-1 read face; the write face
 * belongs to CL-2 — this ticket adds no second knob).
 * Overview 两栏并列（左=等你回，右=最近动作），窄于 760px 叠放（.cols media query）。
 *
 * 语义（设计 note §3）：Overview 的 Disable executor 与 Grants 总开关是**同一份状态**
 * （POST /api/grants op:'master'）——关=收回全部授权（只读和问），会话点名保留，
 * watchdog.json 不动（守望者照常运行）。Settings 里的「Disable watchdog」是另一个面
 * （enabled:false），文案与代码都分开命名，一个词不表两义。
 *
 * 契约偏差（如实声明，沿用 t260929-03 review #1）：notify.beep 的已读清除走页面本地
 * seen-set（localStorage per project）；watchdog 侧 per-key 清除端点属守望者插件改动，
 * out-of-scope——后果（第二台设备会再响一声）写进交接报告，后续票收口。
 */

import {
  beepDecision, pickDegraded, fmtProportion, fmtWaiting, fmtAge, groupByProject,
  splitWaiting, hasOptions, chipLabel, masterOn, localDateTime, newestFirst, wakeRowSentence, themeParamOf,
  // t261008-19: docs tree page count + the mock's two entry rows (single implementation).
  countDocsTree, docEntryRow,
  // t261019-43: the reply face — collapsed badge + expanded per-reply named lines
  // (single implementation, embedded via String(fn) below).
  replyBadge, replyFace,
} from './page-logic.ts'
import { LIST_CONTRACTS } from './list-contracts.ts'
import { renderMarkdown } from './markdown.ts'
// t261006-15: the Inspection tab's period-view model — embedded into the page via
// String() like page-logic, so the unit test and the page run one implementation.
// buildPeriodViewCore is closure-free (tables passed in, embedded as JSON below).
import { buildPeriodViewCore, EMPTY_COPIES, INSTANCE_LABELS } from './inspection-view.ts'
// t261009-49: the period-x-face coverage answer — a pure core embedded via String(fn)
// like buildPeriodViewCore; recordsToAttempts turns the untrusted disposition/trigger
// rows into the per (instance/period) attempts map; the page renders the named
// 'produced nothing' block verbatim.
// t261026-10 (defect C): ticketRowsToAttempts turns the inspection TICKET BOARD rows
// (the already-served /wf/inspection/tickets route) into the same attempts map, so a
// scheduled period with a real ticket reads failed-with-evidence instead of not_run.
import { buildCoverageCore, COVERAGE_COPIES, recordsToAttempts, ticketRowsToAttempts } from './inspection-coverage.ts'
// t261005-05 (UI-4): project identity badge single source, imported across plugins
// from workbench shared (both plugins load as raw TS via node native type-stripping;
// the relative path stays inside the repo). The function sources are embedded into
// the page via String(), same pattern as page-logic — the UT and the page always run
// one implementation. If the loader rejects the cross-plugin path, the declared
// fallback is a local copy plus a drift-guard test (plan alternative 2; never a
// silent copy).
import {
  PROJECT_PALETTE_12, IDENTITY_OUTLINES, IDENTITY_STRUCTURES, FALLBACK_IDENTITY,
  projectIdentity, identityOutlinePath, identityBadgeSvg,
  baseIdentity, identityId, walkOffset, fnv1a, isProjectKeyLike,
} from '../../../workbench/src/shared/project-identity.ts'
// t261006-17 (CL-2): the limit knob step and the three-state chip classifier are
// embedded the same way — the UT and the page always run one implementation. The
// CONC_LIMITS constant table is embedded as JSON next to them (the embedded function
// sources read it from page scope).
import { limitStep, concChipState, CONC_LIMITS } from './concurrency.ts'
// t261009-44: the Certification tab's render core — embedded via String() like
// the other pure cores, so the UT and the page run one implementation. The
// CERT_COPIES copy table rides along as JSON (single copy source).
import { buildCertificationCore, buildRoundDialogCore, buildPromoteDialogCore, certQueueNoteText, buildRoundsRows, countsCell, roundPill, roundReason, roundTrigger, roundTriggerWord, roundMeasured, roundsSectionNote, CERT_COPIES, ROUND_COPIES } from './certification-view.ts'
// t261021-07: the Metrics tab v2 model + chart option factories — pure,
// closure-free, embedded via String(fn) like the other cores, so the UT and
// the page run one implementation. The chart factories shape echarts OPTIONS
// only (no echarts import here; the browser owns init/dispose behind the
// page's one module script over the vendor route).
 import {
  METRICS_TAB_COPIES, metricsV2Of, kpiTilesOf, workflowRowsOf, stageRowsOf,
  epicCardsOf, certSummaryOf, throughputSpecOf, tokensStackOf, sessionRowsOf, roleRowsOf,
  fmtInt, fmtTokensM, fmtPct01, fmtMs, fmtAgo,
} from './metrics-tab-model.ts'
// t261021-07 rework (gate round 1): the embedded cores' TRANSITIVE closure
// must ride along — the page runs the String(fn) sources, so every
// module-level identifier a body references has to exist at page scope (the
// arbitrate red: typeof mnum === 'undefined' inside the served page).
// mnum/mstr/mdash/shareBarPct/colorAt/commonAxes/commonGrid are function
// embeds; DASH/GRID_LINE/LABEL ride the JSON table; METRICS_SERIES_COLORS is
// aliased from the same table below.
import {
  mnum, mstr, mdash, shareBarPct, DASH,
} from './metrics-tab-model.ts'
import {
  colorAt, commonAxes, commonGrid, GRID_LINE, LABEL,
} from './metrics-tab-charts.ts'
import { METRICS_SERIES_COLORS, throughputOption, tokensOption } from './metrics-tab-charts.ts'

/** 纯函数源码嵌入（strip 后即等价 JS；单测直接测这些函数本体）。 */

// ---- t261009-57: alerts face core (coalesce first, cap second; relative time) ----
// Closure-free pure functions, embedded via String(fn) like the other cores, so the
// UT and the page run one implementation.

/** Relative elapsed time: "just now" / "3m ago" / "2h ago" / "1d ago". Malformed or
 *  future input renders the honest dash (no fabricated time). Fixed by the caller
 *  per render — the poll loop re-renders, so labels recompute on every refresh. */
export function relTimeAgo(atMs: unknown, nowMs: number): string {
  if (typeof atMs !== 'number' || !Number.isFinite(atMs) || atMs > nowMs + 60_000) return '—'
  const s = Math.max(0, Math.floor((nowMs - atMs) / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return m + 'm ago'
  const h = Math.floor(m / 60)
  if (h < 24) return h + 'h ago'
  return Math.floor(h / 24) + 'd ago'
}

/** One coalesced alert row: a run of consecutive same-key payload rows. */
export interface CoalescedAlert {
  key: string
  rule: string
  target: string
  level: string
  title: string
  count: number
  first_at: number
  last_at: number
  night_muted: boolean
  /** True when this group's oldest row IS the oldest payload row — the run may
   *  predate the 200-row window, so first_at is a lower bound, not a fact. The
   *  face renders "first ≥ …" and the window start on hover for this group. */
  at_window_edge: boolean
}

/** Coalesce payload rows into condition rows. Identity = the payload's own `key`
 *  (rule:target[@scope], t261001-19) — nothing is invented face-side. Only CONSECUTIVE
 *  same-key rows merge: a same-key row after a different key means the condition
 *  cleared and refired, and that refire is its own group (never merged across the
 *  cleared period). Rows the window cannot parse (non-object, missing/bad `at`)
 *  pass through as count-1 rows with NaN times — the coalescer never throws, and
 *  the ledger keeps every line (presentation only). Output is newest-first.
 *  SELF-CONTAINED (t261009-37 lesson): every predicate lives INSIDE the function —
 *  the page embeds this source verbatim, so a module-level helper here would be a
 *  ReferenceError at page runtime (silent, try/catch-wrapped empty face). */
export function coalesceAlerts(rows: unknown): CoalescedAlert[] {
  const ok = (r: unknown): r is Record<string, unknown> =>
    r !== null && typeof r === 'object' && !Array.isArray(r)
    && typeof (r as Record<string, unknown>).at === 'number'
    && Number.isFinite((r as Record<string, unknown>).at as number)
  const out: CoalescedAlert[] = []
  if (!Array.isArray(rows)) return out
  // PAYLOAD ORDER, not time-sorted: the payload is the heartbeat append order, and
  // that is the order "cleared and refired" is observable in (a different key fired
  // in between). Sorting by `at` first would artificially interleave two persisting
  // conditions that share a cadence and shred them into one-row groups.
  const valid = rows.filter(ok) as Array<Record<string, unknown>>
  const malformed = rows.filter(r => !ok(r))
  const atWindowEdge = valid.length > 0 ? valid[0] : null
  let lastKey: string | null = null
  for (const r of valid) {
    const k = typeof r.key === 'string' && r.key !== '' ? r.key : null
    const g = (out.length > 0 && k !== null && k === lastKey) ? out[out.length - 1] : null
    if (g) {
      g.count++
      g.last_at = r.at as number
      if (typeof r.title === 'string' && r.title !== '') g.title = r.title
      if (r.night_muted === true) g.night_muted = true
    } else {
      out.push({
        key: k ?? '', rule: String(r.rule ?? ''), target: String(r.target ?? ''),
        level: String(r.level ?? ''), title: String(r.title ?? ''),
        count: 1, first_at: r.at as number, last_at: r.at as number,
        night_muted: r.night_muted === true,
        at_window_edge: r === atWindowEdge,
      })
    }
    lastKey = k
  }
  for (const r of malformed) {
    // Keep every readable field — only the malformed `at` degrades to the dash.
    // Zeroing the whole record here would silently drop the alert text (the exact
    // information the reader needs) whenever one field is bad: shape validation is
    // a degrade-factory, not a filter (t261009-57 arbitrate round 1, W1).
    const o: Record<string, unknown> = (r !== null && typeof r === 'object' && !Array.isArray(r) ? r : {})
    out.push({
      key: String(o.key ?? ''), rule: String(o.rule ?? ''), target: String(o.target ?? ''),
      level: String(o.level ?? ''), title: String(o.title ?? ''),
      count: 1, first_at: NaN, last_at: NaN, night_muted: o.night_muted === true,
      at_window_edge: false,
    })
  }
  return out.reverse()
}

/** Cap the COALESCED rows to alerts.display_max (the ONE host number; it arrives on
 *  the same payload as the rows). 0 = show all — an explicit branch, never
 *  slice(-max) (slice(-0) returns the whole array and would silently look right). */
export function capCoalesced(groups: CoalescedAlert[], max: unknown): { rows: CoalescedAlert[]; total: number; capped: boolean } {
  const m = (typeof max === 'number' && Number.isInteger(max) && max >= 0) ? max : 8
  const total = groups.length
  const rows = m === 0 ? groups : groups.slice(0, m)
  return { rows, total, capped: m !== 0 && total > m }
}


// t261009-37 (defect found by the colour-bar work): the two module-private
// constants the embedded identity functions close over. project-identity.ts does
// not export them, so the embedded isProjectKeyLike/baseIdentity sources used to
// hit a ReferenceError at call time — the badge silently never rendered (the
// render is wrapped in try/catch). The values are pinned from OUTSIDE by a
// behavior unit test against the real module (tests/t261009-37-overview-blocks):
// if the module ever changes them, that test goes red here.
const EMBED_CONSTS =
  'var STREAM2_SALT = ' + JSON.stringify('\u0000wb-identity') + ';\n' +
  'var KEY_MAX_LEN = 64;\n'
const EMBEDDED = EMBED_CONSTS + [
  String(beepDecision), String(pickDegraded), String(fmtProportion),
  String(fmtWaiting), String(fmtAge), String(groupByProject),
  String(splitWaiting), String(hasOptions), String(chipLabel), String(masterOn),
  String(localDateTime), String(newestFirst), String(wakeRowSentence), String(themeParamOf),
  // t261019-43: reply face cores (badge + named per-reply lines; escaping at the page).
  String(replyBadge), String(replyFace),
  // t261004-16：markdown 渲染器同样单实现嵌入（UT 与页面同一份函数源码）。
  String(renderMarkdown),
  // t261005-05 (UI-4): badge runtime (closure = the IDENTITY_DATA JSON constant
  // below + cross references inside this group; editing project-identity.ts follows
  // automatically — there is no second implementation).
  String(fnv1a), String(isProjectKeyLike), String(baseIdentity), String(identityId),
  String(walkOffset),
  String(projectIdentity), String(identityOutlinePath), String(identityBadgeSvg),
  // t261006-15: Inspection period-view core (self-contained; tables via INSP_TABLES).
  String(buildPeriodViewCore),
  // t261009-49: coverage core + attempts-map builder (both closure-free; tables via
  // INSP_COVERAGE_TABLES — COVERAGE_COPIES stays the single copy source).
  String(buildCoverageCore), String(recordsToAttempts), String(ticketRowsToAttempts),
  // t261006-17 (CL-2): concurrency knob + chip classifier (same single implementation).
  String(limitStep), String(concChipState),
  // t261008-19: docs tree page count + the mock's two entry rows (same single implementation).
  String(countDocsTree), String(docEntryRow),
  // t261009-44 + t261012-03: the Certification tab's render core and the
  // rounds-faces helpers + the round dialog core (closure-free; the copy
  // tables ride as JSON below).
  String(buildCertificationCore), String(buildRoundsRows), String(roundsSectionNote), String(roundTriggerWord),
  String(countsCell), String(roundPill), String(roundReason), String(roundTrigger), String(roundMeasured),
  String(buildRoundDialogCore),
  // t261025-12: the two controls' pure faces — the signed-promotion dialog
  // body and the queue note text (one implementation with the UT).
  String(buildPromoteDialogCore), String(certQueueNoteText),
  // t261009-57: alerts face core — relative time, coalesce-then-cap (one implementation).
  String(relTimeAgo), String(coalesceAlerts), String(capCoalesced),
  // t261021-07: the Metrics tab v2 model + chart option factories (one
  // implementation with the UT; the copy/palette tables ride as JSON below).
  String(metricsV2Of), String(kpiTilesOf), String(workflowRowsOf), String(stageRowsOf),
  String(epicCardsOf), String(certSummaryOf), String(throughputSpecOf), String(tokensStackOf),
  String(sessionRowsOf), String(roleRowsOf),
  String(fmtInt), String(fmtTokensM), String(fmtPct01), String(fmtMs), String(fmtAgo),
  // t261021-07 rework: the transitive closure of the embedded cores (the
  // arbitrate family sweep — each of these is referenced inside an embedded
  // body above; leaving one out is a ReferenceError at first render).
  String(mnum), String(mstr), String(mdash), String(shareBarPct),
  String(colorAt), String(commonAxes), String(commonGrid),
  String(throughputOption), String(tokensOption),
].join('\n')

/** t261021-07: the Metrics tab's copy table + series palette as JSON — the
 *  data half of the embedded model/chart cores. METRICS_TAB_COPIES and
 *  METRICS_SERIES_COLORS stay the single copy/palette sources. DASH/GRID_LINE/
 *  LABEL ride here too: the embedded function bodies reference them as
 *  identifiers, so the page aliases them below. */
const METRICS_TABLES = JSON.stringify({
  COPIES: METRICS_TAB_COPIES, COLORS: METRICS_SERIES_COLORS,
  DASH, GRID_LINE, LABEL,
})

/** t261009-44 + t261012-03: the Certification tab's copy tables as JSON — the
 *  data half of the embedded render cores. CERT_COPIES / ROUND_COPIES
 *  (certification-view.ts) stay the single copy sources; the page JS reads the
 *  named-absence sentences from here. */
const CERT_TABLES = JSON.stringify({ COPIES: CERT_COPIES, ROUND: ROUND_COPIES })

/** t261006-15: Inspection tables (verbatim empty copies + instance labels) as JSON —
 *  the data half of the embedded period-view core. EMPTY_COPIES (inspection-view.ts)
 *  stays the single copy source; a unit test locks the page HTML to these strings. */
const INSP_TABLES = JSON.stringify({
  EMPTY_COPIES, INSTANCE_LABELS,
  // t261009-49: the two run-state copies the period-view core may print on a card.
  RUN_COPIES: { produced: COVERAGE_COPIES.produced, blocked: COVERAGE_COPIES.blocked },
})

/** t261009-49: coverage tables (copy single source COVERAGE_COPIES). t261026-10: the
 *  FACES map is no longer hardcoded empty on this surface — the served archive payload
 *  carries the DECLARATION faces (scan_face per declared instance) and inspLoad swaps
 *  them in (defect B of host report 261026). The empty map here is only the pre-fetch
 *  default; a genuinely unknown instance still reads the named 'decl-unreadable'
 *  marker, defined in one place, never rewritten here. */
const INSP_COVERAGE_TABLES = JSON.stringify({
  COPIES: COVERAGE_COPIES, FACES: {}, ATTEMPT_CAP: 5,
})

/** Constant closure for the badge runtime (the page-side projectIdentity reads these tables; embedded as JSON). */
const IDENTITY_DATA = JSON.stringify({
  PROJECT_PALETTE_12,
  IDENTITY_OUTLINES,
  IDENTITY_STRUCTURES,
  FALLBACK_IDENTITY,
})

export const PANEL_ROUTE = '/sandbar-executor-panel'
export const PANEL_PAGE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Executor</title>
<style>
/* t261003-09 缺陷 2：双调色板，随 ?theme= 切（workbench 深链恒带）；缺席/畸形 →
   不设 data-theme，落 prefers-color-scheme 显式降级（standalone 场景），浅色兜底。
   词表对齐控制台 --dsw-alias/--dsw-derive 家族（light=GitHub 浅档、dark=原深档）。 */
html[data-theme="light"],html:not([data-theme]){--bg:#ffffff;--panel:#f6f8fa;--panel2:#eaeef2;--line:#d0d7de;--line-soft:#e4e9ee;--fg:#1f2328;--fg-soft:#424a53;--muted:#57606a;--faint:#6e7781;--blue:#0969da;--red:#cf222e;--amber:#9a6700;--green:#1a7f37;--hover:#eef1f4;--badge-fg:#ffffff;--accent-soft:#dbe9ff;--accent-line:#7aa7e8;--dot-grey:#99a3ad;--sw-off:#d7dde3;--knob:#57606a;--warn-soft:#fff8c5;--danger-soft:#ffebe9;--pill-sign-bg:#ddf4ff;--pill-sign-fg:#0550ae;--pill-open-bg:#dafbe1;--pill-open-fg:#116329;--pill-retry-bg:#fff8c5;--pill-retry-fg:#7d4e00;--pill-send-bg:#fff1d6;--pill-send-fg:#9a5b00;--pill-cancel-bg:#ffebe9;--pill-cancel-fg:#cf222e;--pill-pause-bg:#e7ebef;--pill-pause-fg:#57606a}
html[data-theme="dark"]{--bg:#141a24;--panel:#1b2330;--panel2:#222c3c;--line:#2e394d;--line-soft:#232c3a;--fg:#dbe4f0;--fg-soft:#c3cfdf;--muted:#8ea0b8;--faint:#5b6880;--blue:#4da3ff;--red:#ff6b6b;--amber:#ffb454;--green:#7ad48a;--hover:#1f2937;--badge-fg:#0e1420;--accent-soft:#1d3550;--accent-line:#2f5b8a;--dot-grey:#46536a;--sw-off:#39465c;--knob:#8ea0b8;--warn-soft:#2a2313;--danger-soft:#2a1414;--pill-sign-bg:#183153;--pill-sign-fg:#79b8ff;--pill-open-bg:#16351f;--pill-open-fg:#7ad48a;--pill-retry-bg:#3a2d13;--pill-retry-fg:#ffb454;--pill-send-bg:#3a2a13;--pill-send-fg:#ffc07a;--pill-cancel-bg:#3a1a1a;--pill-cancel-fg:#ff8b8b;--pill-pause-bg:#262f3d;--pill-pause-fg:#9fb0c8}
@media (prefers-color-scheme: dark){ html:not([data-theme]){--bg:#141a24;--panel:#1b2330;--panel2:#222c3c;--line:#2e394d;--line-soft:#232c3a;--fg:#dbe4f0;--fg-soft:#c3cfdf;--muted:#8ea0b8;--faint:#5b6880;--blue:#4da3ff;--red:#ff6b6b;--amber:#ffb454;--green:#7ad48a;--hover:#1f2937;--badge-fg:#0e1420;--accent-soft:#1d3550;--accent-line:#2f5b8a;--dot-grey:#46536a;--sw-off:#39465c;--knob:#8ea0b8;--warn-soft:#2a2313;--danger-soft:#2a1414;--pill-sign-bg:#183153;--pill-sign-fg:#79b8ff;--pill-open-bg:#16351f;--pill-open-fg:#7ad48a;--pill-retry-bg:#3a2d13;--pill-retry-fg:#ffb454;--pill-send-bg:#3a2a13;--pill-send-fg:#ffc07a;--pill-cancel-bg:#3a1a1a;--pill-cancel-fg:#ff8b8b;--pill-pause-bg:#262f3d;--pill-pause-fg:#9fb0c8} }
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.45 ui-sans-serif,system-ui,sans-serif}
/* t261004-16 Req1：页面用满窗宽（1600 视口两侧留白各 ≤5%），超宽屏 1440 封顶，
   左右 padding 随窗宽缩放（16–28px）。container-type 保留（两栏断点按容器宽）。 */
.wrap{max-width:min(1440px,100%);margin:0 auto;padding:18px clamp(16px,2vw,28px) 48px;container-type:inline-size}
.top{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.top h1{font-size:14px;font-weight:600;margin:0}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:999px;padding:2px 9px;font-size:11px}
.seg{display:flex;gap:2px;background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:2px;width:max-content;margin-bottom:16px;flex-wrap:wrap}
input.tab{position:absolute;opacity:0;pointer-events:none}
.seg label{color:var(--muted);cursor:pointer;padding:5px 12px;border-radius:7px;display:flex;align-items:center;gap:6px;font-size:12px}
.seg label:hover{color:var(--fg)}
#t-overview:checked~.seg label[for=t-overview],#t-epics:checked~.seg label[for=t-epics],#t-inspection:checked~.seg label[for=t-inspection],#t-certification:checked~.seg label[for=t-certification],#t-metrics:checked~.seg label[for=t-metrics],#t-docs:checked~.seg label[for=t-docs],#t-grants:checked~.seg label[for=t-grants],#t-settings:checked~.seg label[for=t-settings]{background:var(--panel2);color:var(--fg)}.badge{min-width:18px;height:18px;border-radius:9px;background:var(--blue);color:var(--badge-fg);font-size:11px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;padding:0 5px}
.badge.zero{background:var(--panel2);color:var(--muted);font-weight:500}
.sect{margin:0 0 6px;font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted);display:flex;align-items:center;gap:8px}
.sect.lead{margin-top:18px}
/* t261021-12: the Epics-tab card is a CONTAINER, not a section heading. It used to
   borrow .sect (a one-line heading style), so text-transform:uppercase cascaded to
   every descendant — epic code, summary, ticket titles, counts all rendered in
   capitals. The card carries its own box style; descendants inherit normal case. */
.epicCard{display:block;border:1px solid var(--line);border-radius:8px;margin-bottom:8px;text-transform:none;letter-spacing:normal}
.row{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:8px;overflow:hidden}
.row.wait{border-left:3px solid var(--amber)}
.row.done{border-left:3px solid var(--line);background:transparent}
.head{display:flex;align-items:baseline;gap:8px;padding:10px 12px;cursor:pointer;user-select:none}
.head:hover{background:var(--hover)}
.row.done .head .txt{color:var(--muted)}
.txt{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* t261009-57: alert titles wrap — the whole text is readable, no ellipsis cut.
   The shared .txt above keeps its nowrap shape for the other faces. */
.altxt{flex:1;min-width:0;overflow-wrap:anywhere;word-break:break-word;white-space:normal}
.dot{width:7px;height:7px;border-radius:50%;flex:0 0 auto;margin-top:5px}
.dot.amber{background:var(--amber)}.dot.grey{background:var(--dot-grey)}.dot.red{background:var(--red)}.dot.blue{background:var(--blue)}
/* t261006-17 (CL-2), renamed t261008-20: the Concurrent limit block — knob buttons, limit value, three-state chip. */
.concBtn{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;width:28px;height:24px;font:inherit;cursor:pointer;line-height:1;padding:0}
.concBtn:hover{border-color:var(--blue)}
.concVal{display:inline-block;min-width:80px;text-align:center;font-weight:600}
.pill.conc-room{background:var(--pill-open-bg);color:var(--pill-open-fg)}
.pill.conc-at{background:var(--pill-sign-bg);color:var(--pill-sign-fg)}
.pill.conc-over{background:var(--warn-soft);color:var(--amber)}
.meta{color:var(--muted);font-size:11px;white-space:nowrap}
.chev{color:var(--muted);font-size:10px;flex:0 0 auto;transition:transform .15s}
.row[data-open="true"] .chev{transform:rotate(90deg)}
.body{display:none;padding:0 12px 11px 12px;border-top:1px solid var(--line-soft)}
.row[data-open="true"] .body{display:block}
/* t261004-16 Req4：详情限高 170→440px（票面要求 ≥420），字号 12→13px；内部滚动保留。
   正文行长封顶 90ch——限的是内容，不是页面。markdown 元素全部只用既有主题词表
   （t261004-10 教训：零硬编码色）。 */
.detail{margin-top:9px;max-height:440px;overflow:auto;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:9px 11px;color:var(--fg-soft);font-size:13px}
.detail>*{max-width:90ch}
.detail h1,.detail h2,.detail h3,.detail h4,.qfull h1,.qfull h2,.qfull h3,.qfull h4{margin:8px 0 4px;font-weight:600;line-height:1.3}
.detail h1,.qfull h1{font-size:15px}.detail h2,.qfull h2{font-size:14px}.detail h3,.qfull h3,.detail h4,.qfull h4{font-size:13px}
.detail p,.qfull p{margin:4px 0;white-space:pre-wrap}
.detail ul,.detail ol,.qfull ul,.qfull ol{margin:4px 0;padding-left:22px}
.detail li,.qfull li{margin:2px 0;white-space:pre-wrap}
.detail code,.qfull code{font-family:ui-monospace,monospace;font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:0 4px}
.detail pre{margin:6px 0;padding:8px 10px;background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:auto}
.detail pre code{background:transparent;border:0;padding:0;white-space:pre}
.detail blockquote,.qfull blockquote{margin:6px 0;padding:2px 10px;border-left:3px solid var(--line);color:var(--muted)}
.detail a,.qfull a{color:var(--blue)}
.md-clipped{color:var(--muted);font-size:11px}
/* t261004-16 Req3：展开行的完整问题放正文顶部，按格式渲染（行头收起态仍是单行省略）。 */
.qfull{margin-top:9px;font-size:13px;color:var(--fg)}
.qfull p:first-child{margin-top:0}
.opts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}
/* t261004-17：选项块可挂在收起行内（不展开也能一键答），默认动作行随卡在收起态可见。 */
.opts.inline{margin-top:0;padding:9px 12px 11px 12px;border-top:1px solid var(--line-soft)}
.dflt{color:var(--muted);font-size:11px;margin-top:8px}
.gtag{color:var(--muted)}
.opts button{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;padding:6px 14px;font:inherit;cursor:pointer}
.opts button:hover{border-color:var(--blue);color:var(--blue)}
.opts button.primary{background:var(--accent-soft);border-color:var(--accent-line)}
.other{border:0;background:transparent;color:var(--faint);font:inherit;cursor:pointer;padding:6px 4px;text-decoration:underline dotted}
.answer{display:flex;gap:8px;margin-top:10px}
/* t261004-17：应答框从单行 input 换成多行 textarea（宿主要能贴多行答复）。 */
.answer input,.answer textarea{flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:7px;padding:6px 9px;font:inherit;resize:vertical;min-height:44px}
.answer input:focus,.answer textarea:focus{outline:0;border-color:var(--blue)}
.answer button{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer}
.given{color:var(--green);font-size:12px;padding:0 12px 10px 12px}
.trace{color:var(--faint);font-size:11px;margin-top:9px}
/* t261019-43: the reply face — readable lines above the trace, not an 11px trace
 * fragment; intent/source-class bits take the faint tone, text stays fg. */
.replies{margin-top:10px;display:grid;gap:6px;font-size:13px;border-left:2px solid var(--line);padding-left:10px}
.replies .rby{font-weight:600}
.replies .ri{color:var(--faint);font-size:12px}
.replies .rtxt{color:var(--fg)}
.strip{display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);font-size:12px;color:var(--muted);margin-bottom:14px;flex-wrap:wrap}
.strip .live{color:var(--green)}
.strip .ro{color:var(--amber)}
.power{border:1px solid var(--line);border-radius:7px;padding:5px 12px;font:inherit;cursor:pointer;background:var(--panel2);color:var(--fg)}
.power[data-on="true"]:hover{border-color:var(--red);color:var(--red)}
.power[data-on="false"]:hover{border-color:var(--green);color:var(--green)}
.openBtn{border:1px solid var(--line);border-radius:7px;padding:3px 10px;font:inherit;font-size:12px;cursor:pointer;background:var(--panel2);color:var(--fg)}
.openBtn:disabled{opacity:.45;cursor:not-allowed}
/* t261004-16 Req2：请求/应答栏拿宽侧（1.85fr），Recent actions 拿窄侧（1fr）。
   容器断点、两栏各自限高内滚（展开只长自己那栏）两条既有规则不动。 */
.cols{display:grid;grid-template-columns:minmax(0,1.85fr) minmax(0,1fr);gap:16px;align-items:start}
/* t261003-09 缺陷 1：断点按真实容器宽（container query——面板是 iframe/独立窗口，
   视口宽≠内容盒宽），且两栏各自限高内滚——展开任何一条请求只在**自己那栏**长高，
   另一栏与下方内容永不位移；行内 detail 的 170px 限高不变（滚动锚定稳定）。 */
/* t261009-37 (host order 261009): the columns scroll with the page again — the
   right column is a stack of bordered blocks, so the per-column height cap and
   inner scroll are gone (the mock is the yardstick). The 760px collapse stays. */
.cols>div{min-width:0}
.cols>div:last-child{display:flex;flex-direction:column}
@container (max-width:760px){ .cols{grid-template-columns:1fr} }
.act{display:flex;align-items:center;gap:9px;padding:7px 10px;border-bottom:1px solid var(--line-soft)}
.act:last-child{border-bottom:0}
.act .t{color:var(--muted);font-size:11px;width:74px;flex:0 0 auto}
.pill{font-size:10px;font-weight:700;letter-spacing:.6px;border-radius:5px;padding:2px 7px;min-width:52px;text-align:center}
.pill.sign{background:var(--pill-sign-bg);color:var(--pill-sign-fg)}
.pill.open{background:var(--pill-open-bg);color:var(--pill-open-fg)}
.pill.retry{background:var(--pill-retry-bg);color:var(--pill-retry-fg)}
.pill.sendback{background:var(--pill-send-bg);color:var(--pill-send-fg)}
.pill.cancel{background:var(--pill-cancel-bg);color:var(--pill-cancel-fg)}
.pill.pause{background:var(--pill-pause-bg);color:var(--pill-pause-fg)}
.act .tk{font-weight:600}
.act .say{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.cell{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px 11px}
.cell b{display:block;font-size:15px;font-weight:600}
.cell span{color:var(--muted);font-size:11px}
.file{color:var(--faint);font-size:11px;margin-top:8px}
.grp{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
.line{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--line-soft)}
.line:last-child{border-bottom:0}
.line .lab{flex:1;min-width:0}
.line .lab small{display:block;color:var(--muted);font-size:11px}
.line input[type=text],.line input[type=number],.line input[type=time],.line select{background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:7px;padding:5px 8px;font:inherit;width:150px}
.sw{width:38px;height:21px;border-radius:11px;background:var(--sw-off);border:1px solid var(--line);position:relative;cursor:pointer;flex:0 0 auto;transition:background .15s}
.sw::after{content:"";position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:50%;background:var(--knob);transition:left .15s,background .15s}
.sw[data-on="true"]{background:var(--accent-soft);border-color:var(--accent-line)}
.sw[data-on="true"]::after{left:18px;background:var(--blue)}
.sw.locked{opacity:.35;cursor:not-allowed}
.linkbtn{border:0;background:transparent;color:var(--muted);font:inherit;cursor:pointer;text-decoration:underline dotted;margin-left:auto}
.linkbtn:hover{color:var(--blue)}
.bar{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.bar button{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;padding:7px 14px;font:inherit;cursor:pointer}
.bar button.primary{background:var(--accent-soft);border-color:var(--accent-line)}
.bar button:hover{border-color:var(--blue)}
.doneWrap{margin-top:14px}
.doneHead{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;padding:4px 0}
.chev2{color:var(--muted);transition:transform .15s}
.doneWrap[data-open="false"] .chev2{transform:rotate(-90deg)}
.doneWrap[data-open="false"] .doneList{display:none}
.empty{color:var(--muted);padding:22px 4px}
.banner{border:1px solid var(--amber);color:var(--amber);background:var(--warn-soft);border-radius:10px;padding:9px 12px;margin-bottom:10px;font-size:12px}
.banner.red{border-color:var(--red);color:var(--red);background:var(--danger-soft)}
.knob{display:grid;grid-template-columns:200px 1fr 240px;gap:6px;padding:5px 12px;border-bottom:1px solid var(--line-soft);align-items:center;font-size:12px}
.knob .src{color:var(--muted);font-size:11px;font-family:ui-monospace,monospace}
table{width:100%;border-collapse:collapse;font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:11px}
.good{color:var(--green)} .bad{color:var(--red)} .muted{color:var(--muted)}
/* t261005-10 (UI-2): clickable rows of the Epics/Docs read-only faces — the .line
   row shape with the .head hover feedback. */
.mrow{cursor:pointer}
.mrow:hover{background:var(--hover)}
.docfile{font-family:ui-monospace,monospace;font-size:12px}
.backbtn{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;padding:4px 12px;font:inherit;cursor:pointer;margin-bottom:8px}
.backbtn:hover{border-color:var(--blue);color:var(--blue)}
.foot{margin-top:26px;color:var(--faint);font-size:11px}
/* t261006-15 Inspection tab — layout discipline (P6): ONE text gutter (--igx) for
   card text, block titles, description lines, table first column and metric keys;
   containers keep their own edge; three vertical steps (--isect/--icard/--iline);
   right edges share one line (right-aligned meta, table last column, toolbar);
   metrics in an equal-width grid, never one squeezed row. The acceptance is the
   RULE (Range-measured left edges within 1px / right edges on one line), not these
   pixel values. */
.inspCard{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:0 0 var(--icard,8px);padding:var(--iline,10px) 0}
.inspCard .pad{padding:0 var(--igx,14px)}
.inspSect{margin:var(--isect,20px) 0 6px;padding-left:var(--igx,14px);font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted)}
.inspNote{padding-left:var(--igx,14px);color:var(--muted);font-size:11px;margin:6px 0 0}
.inspMeta{color:var(--muted);font-size:11px;white-space:nowrap;text-align:right}
.inspNums{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 20px;padding:0 var(--igx,14px);margin-top:8px}
.inspNums .kv{display:flex;flex-direction:column;gap:1px;font-size:11px;color:var(--muted)}
.inspNums .kv b{color:var(--fg);font-weight:600;font-size:15px;line-height:1.2}
.inspCard table{width:100%;border-collapse:collapse;font-size:12px}
/* P6 (arbitrate gen4): the table box itself sits +2px right of the card text line, so
   the FIRST column's text gets -2px to land on the shared gutter (122-line); the rule
   is the line, not these pixels — a width change must still hold <=1px. */
.inspCard table th:first-child,.inspCard table td:first-child{padding-left:12px}
.inspCard th{text-align:left;color:var(--muted);font-weight:500;padding:6px var(--igx,14px);border-bottom:1px solid var(--line)}
.inspCard td{padding:7px var(--igx,14px);border-bottom:1px solid var(--line-soft,var(--panel2));vertical-align:top}
.inspCard tr:last-child td{border-bottom:0}
.inspCard th.num,.inspCard td.num{text-align:right}
.inspPeriods{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:0 0 8px;padding:0 var(--igx,14px)}
.inspPeriods .lbl{color:var(--muted);font-size:11px}
.inspPeriods button{border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:999px;padding:3px 11px;font:inherit;font-size:12px;cursor:pointer;line-height:18px}
.inspPeriods button[data-on="true"]{background:var(--accent-soft,var(--panel2));border-color:var(--blue);color:var(--fg)}
.inspFld{display:grid;grid-template-columns:96px 1fr;gap:8px 10px;align-items:center;padding:0 var(--igx,14px)}
.inspFld label{color:var(--muted);font-size:12px}
.inspFld select,.inspFld input{background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:7px;padding:5px 8px;font:inherit;width:100%;max-width:340px}
/* P6: the reviewed-list summary must sit exactly on the text gutter — kill the
   disclosure marker's indent on every engine (arbitrate gen1: 2.4px off the line). */
#paneInsp summary{list-style:none;display:block}
#paneInsp summary::-webkit-details-marker{display:none}
#paneInsp summary::marker{content:''}
/* P6 residual (arbitrate gen2): the reviewed block must take its gutter ONLY from
   .inspNote's padding — the details element itself is zero-inset, so summary and
   disclosed content start exactly where every other .pad/.inspNote line starts. */
#paneInsp details{padding:0;margin:0}
/* P6 residual (arbitrate gen2): toolbar button box edge vs meta text edge sat 2px
   apart; pull the button box onto the meta's text line (mock v8 precedent: button
   aligns by box edge, meta by text edge, SAME line). */
#inspRunBtn{margin-right:2px}

/* ---- t261009-37 mock deltas (261009 host orders; yardstick notes/discussions/261009-executor-panel-overview-mock.html) ---- */
/* Project identity colour bar. --proj default is the grey stand-in for "no project
   resolved yet": renderProjBadge sets the real colour from projectIdentity(key); a
   failed/absent status fetch leaves the grey default — the bar states that no
   identity is known, it never guesses one. */
:root{--proj:#9ca3af}
.top{position:relative}
.top::before{content:'';position:absolute;left:0;right:0;top:-11px;height:3px;background:var(--proj)}
.tk{white-space:nowrap}
.evhealth{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:2px 0 0}
.evhealth .file{font-family:ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis;max-width:46ch;white-space:nowrap}
.concRow{display:flex;align-items:center;gap:10px;height:34px}
.blk .bbd .concBox{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:0 9px;height:28px;width:max-content}
.concBox .concBtn{width:24px;height:22px}
.concBox .concVal{min-width:22px}
#ledgerFile{overflow-wrap:anywhere}
/* the right-column blocks: one border each, header row carrying the name and the count */
.blk{border:1px solid var(--line);border-radius:10px;background:var(--bg);margin:0 0 12px 0}
.colstk .blk:last-child{margin-bottom:0}
.blk .bhd{display:flex;align-items:center;gap:8px;padding:7px 12px;border-bottom:1px solid var(--line-soft)}
.blk .bhd .n{color:var(--muted)}
.blk .bhd .grow{flex:1}
.blk .bhd .muted{font-size:11px;min-width:0;overflow:hidden;text-overflow:ellipsis}
.blk .bbd{padding:6px 12px 10px}
.blk .bbd .row{padding:4px 0}
.blk .bbd .act{border-bottom:1px solid var(--line-soft)}
.blk .bbd .act:last-child{border-bottom:0}
.pill.refused{border-color:var(--red);background:var(--danger-soft,var(--soft-red));color:var(--red)}
/* the action row into columns: the mark of a refused action is a pill in the op column, so nothing sits outside the aligned grid */
.blk .bbd .act .pill{flex:0 0 66px;text-align:center;justify-content:center}
.blk .bbd .act .t{flex:0 0 96px;white-space:nowrap}
.blk .bbd .act .tk{flex:0 0 88px;overflow:hidden;text-overflow:ellipsis}
.evfile{font-family:ui-monospace,monospace;font-size:11px;color:var(--faint);overflow:hidden;text-overflow:ellipsis;max-width:22ch;white-space:nowrap}
/* ---- t261009-44: the Certification tab (mock v15's layout law) ---- */
/* t261019-23 (F1/F2): the .linebar segment styles and the .certsw/.certTrack/
   .certKnob switch styles are gone — the proportional bar became three
   labelled figures (sharing .lbt below) and the handler-less auto-rounds
   switch was removed; only the round-state word remains. */
.lbt{display:flex;align-items:center;gap:14px;margin-top:6px;font-size:12px;color:var(--muted)}
.flow{display:flex;align-items:center;gap:10px;margin-top:10px}
#paneCert select{border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:8px;padding:5px 9px;font:inherit;font-size:12.5px}
#paneCert .card{border:1px solid var(--line);border-radius:10px;background:var(--bg);margin-top:12px}
#paneCert .card .hd{display:flex;align-items:center;gap:10px;padding:11px 14px;flex-wrap:wrap}
#paneCert .card h3{margin:0;padding:8px 14px;border-top:1px solid var(--line-soft);border-bottom:1px solid var(--line-soft);font-size:11.5px;letter-spacing:.35px;text-transform:uppercase;color:var(--muted)}
#paneCert .card .pad{padding:10px 14px 14px}
#paneCert table{width:100%;border-collapse:collapse;font-size:12.5px}
#paneCert th,#paneCert td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line-soft)}
#paneCert th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.3px;font-weight:600}
#paneCert tr:last-child td{border-bottom:0}
#paneCert .pick{display:flex;align-items:center;gap:10px;padding:2px 0}
#paneCert .lbl{color:var(--muted);font-size:12.5px}
#paneCert .state{font-weight:650;font-size:15px}
#paneCert .st.g{color:var(--green)}#paneCert .st.r{color:var(--red)}
/* t261012-03: the rounds faces' state pills + the round dialog (the mock's
   own classes: .dlg/.top/.x/.kv; pill keys green/red/run/none). */
/* t261016-09 (D1): the round dialog's backdrop used to carry an inline
   display:flex next to the hidden attribute — an author inline rule outranks
   the UA [hidden]{display:none}, so the grey overlay was visible (and
   click-blocking) from page load. The layout lives HERE now; the hidden
   attribute alone is the open/close state, and the page JS only ever toggles
   that attribute. */
#roundDlgWrap{position:fixed;inset:0;background:rgba(0,0,0,.45);align-items:flex-start;justify-content:center;padding:48px 16px;z-index:40;display:none}
#roundDlgWrap:not([hidden]){display:flex}
#paneCert .pill[data-k]{font-size:10.5px;font-weight:700;border-radius:999px;padding:2px 9px;border:1px solid var(--line);color:var(--muted);background:var(--bg)}
#paneCert .pill[data-k=green]{border-color:var(--green);color:var(--green);background:var(--green-soft,transparent)}
#paneCert .pill[data-k=red]{border-color:var(--red);color:var(--red);background:var(--red-soft,transparent)}
#paneCert .pill[data-k=run]{border-color:var(--accent-line);color:var(--blue)}
#paneCert .dlg{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 32px rgba(0,0,0,.35);max-width:640px;width:100%;overflow:hidden;font-size:12.5px}
#paneCert .dlg .top{display:flex;align-items:center;gap:8px;padding:11px 14px;border-bottom:1px solid var(--line)}
#paneCert .dlg .x{margin-left:auto;color:var(--muted);cursor:pointer}
#paneCert .dlg .kv{display:grid;grid-template-columns:132px 1fr;gap:5px 10px}
#paneCert .dlg .kv b{color:var(--muted);font-weight:600}
#paneCert [data-round-link]{cursor:pointer}
#paneCert .who{color:var(--faint);font-size:11.5px;margin-top:8px}
</style>
</head>
<body>
<div class="wrap">
  <div class="top"><h1>Executor</h1><span class="chip" id="projChip"><span id="projBadge"></span><span id="projKey"></span></span></div>

  <input class="tab" type="radio" name="tb" id="t-overview" checked>
  <input class="tab" type="radio" name="tb" id="t-epics">
  <input class="tab" type="radio" name="tb" id="t-inspection">
  <input class="tab" type="radio" name="tb" id="t-certification">
  <input class="tab" type="radio" name="tb" id="t-metrics">
  <input class="tab" type="radio" name="tb" id="t-docs">
  <input class="tab" type="radio" name="tb" id="t-grants">
  <input class="tab" type="radio" name="tb" id="t-settings">

  <div class="seg">
    <!-- t261005-10 (UI-2): data-tab anchors in the fixed declared order (the
         tab-order contract scenario asserts this exact sequence). -->
    <label for="t-overview" data-tab="overview">Overview <span id="reqBadge" class="badge zero">0</span></label>
    <label for="t-epics" data-tab="epics">Epics</label>
    <label for="t-inspection" data-tab="inspection">Inspection</label>
    <label for="t-certification" data-tab="certification">Certification</label>
    <label for="t-metrics" data-tab="metrics">Metrics</label>
    <label for="t-docs" data-tab="docs">Docs</label>
    <label for="t-grants" data-tab="grants">Grants</label>
    <label for="t-settings" data-tab="settings">Settings</label>  </div>

  <div id="noProject" class="banner red" style="display:none">No project is selected. Open this panel from a project row, or add ?project=&lt;project-key&gt; to the address.</div>

  <section id="paneOv">
    <div class="strip">
      <span id="liveDot" class="ro">● read-only</span>
      <span id="stateTxt">The executor state is not known yet.</span>
      <span id="grantChip" class="chip">Permissions: 0 of 6</span>
      <span id="sessionChip" class="chip">Session: none</span>
      <span class="meta" id="sessionMsg"></span>
      <button class="power" id="powerBtn" data-on="false" style="margin-left:auto">Enable executor</button>
    </div>
    <div id="ovBanners"></div>
    <!-- t261009-37 (host order 261009): the Overview right column is FOUR bordered
         blocks — Concurrent limit / Alerts / Recent actions / Events — in the same
         .blk chrome with the same gap (the mock is the yardstick). The limit block
         carries its counts in the header row; its knob, three-state chip, write
         path and refusal copy stay. The Alerts tab and the source-event dialog are
         gone: both faces live here (t261008-20 put the Ledger face in a dialog;
         host order 261009-(2) replaces that pattern with this inline block). -->
    <div class="cols">
      <div>
        <div class="sect" id="waitHead">Needs your answer · 0</div>
        <!-- t261009-37 rework (arbitrate round 1): the old .cols>div carried
             overflow:auto and CLIPPED child overflow; with the block-stack layout the
             page scrolls instead, so this meta line's min-content width used to
             propagate to the document and reintroduced a 10px horizontal overflow at
             narrow viewports (t261004-16 T7). The line is bounded again: one line,
             ellipsised, never widening the page. -->
        <div id="bridgeLine" class="meta" style="margin:-4px 0 6px 0;min-width:0;overflow:hidden;text-overflow:ellipsis"></div>
        <div id="waitList"></div>
        <div class="empty" id="waitEmpty" style="display:none">Nothing waits on you.</div>
        <div class="doneWrap" data-open="false" id="doneWrap" style="display:none">
          <div class="doneHead" id="doneHeadBtn">
            <span class="chev2">&#9662;</span><span class="sect" style="margin:0" id="doneHead2">Answered · 0</span>
          </div>
          <div class="doneList" id="doneList"></div>
        </div>
        <!-- t261007-01: the Dismissed group (collapsed, next to Answered). A
             dismissed card carries no decision — the copy says so. -->
        <div class="doneWrap" data-open="false" id="dismissedWrap" style="display:none">
          <div class="doneHead" id="dismissedHeadBtn">
            <span class="chev2">&#9662;</span><span class="sect" style="margin:0" id="dismissedHead">Dismissed · 0</span>
          </div>
          <div class="doneList" id="dismissedList"></div>
        </div>
      </div>
      <div class="colstk">
        <div class="blk" id="concBlock">
          <div class="bhd"><span class="sect">Concurrent limit</span><span id="concChip" class="pill conc-room" style="display:none"></span><span class="grow"></span><span class="muted" id="concCounts"></span></div>
          <div class="bbd">
            <span class="concBox" id="concBox">
              <span class="lab" style="flex:0 0 auto">Limit</span>
              <button class="concBtn" id="concMinus" title="One fewer ticket at the same time">&minus;</button>
              <span class="concVal" id="concLimit">–</span>
              <button class="concBtn" id="concPlus" title="One more ticket at the same time">+</button>
              <button id="concSave">Save</button>
            </span>
            <span class="meta" id="concMsg"></span>
            <!-- t261009-37: the CL-1 read sentence (declaration path / refusal copy)
                 moved from the standalone #limitRow strip line into the block body —
                 same element id, same producer (renderLimitRow), one face. -->
            <div id="limitRow" class="meta" style="margin:6px 0 0;width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis"></div>
          </div>
        </div>

        <div class="blk">
          <div class="bhd"><span class="sect">Alerts</span><span class="n" id="alertHead">0</span><span class="grow"></span><span class="muted">Times show how long ago. Hover for the exact time.</span></div>
          <div class="bbd">
            <div id="alertBanner"></div>
            <div id="alertList"></div>
          </div>
        </div>

        <div class="blk">
          <div class="bhd"><span class="sect">Recent actions</span><span class="n" id="actCount">0</span><span class="grow"></span><span class="muted">Times are local.</span></div>
          <div class="bbd"><div id="actList"></div></div>
        </div>

        <div class="blk">
          <div class="bhd"><span class="sect" id="eventsHead" title="what the watchdog read and acted on, newest first">Events</span><span class="n" id="wakeCount">0</span><span class="grow"></span><span class="evfile" id="ledgerFile"></span></div>
          <div class="bbd">
            <div class="evhealth"><span class="meta" id="ledgerHealth" title="the watchdog's own ledger: rows read, duplicates skipped, bad rows, gaps"></span></div>
            <div id="ledgerEvents"></div>
            <div class="muted" style="margin:4px 0 0;font-size:11px">Times are local. The watchdog status keeps the last 20 wakes. <!-- t261009-37 review #1: a display of the full-list fact (every row renders, cap 'all' since t261008-20), deliberately NOT a control — no click handler is wired, and a unit test pins that. --><button class="linkbtn" id="wakesShowAll">Show all</button></div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- t261005-10 (UI-2): Epics tab — read-only face over the workbench epics API.
       Epic rows drill in-tab (single layer, ← Back); a ticket row asks the host
       console (postMessage) to open the ticket-detail overlay (UI-3 machinery). -->
  <section id="paneEpics" style="display:none">
    <div id="epicsBanner"></div>
    <div id="epicsList"></div>
    <div id="epicDetail"></div>
  </section>


  <!-- t261005-10 (UI-2): Metrics tab — facts-only face over the project metrics API
       (KPI cards + freshness line). No second chart engine in the panel. -->
  <!-- t261008-19: Metrics tab — the t261005-10 KPI face stays; below it the 261004
       mock's Charts box (metricsTabHtml) as semantic text anchors only. No chart
       engine is added (t261005-10 ruling stands); the conflict with
       docs/design/metrics-panel-ui-plan.md (ECharts, four views) is REPORTED to the
       adjudication surface, not resolved here. The three label strings are
       byte-identical to the mock. The value-side copy states the real data state:
       there is no chart data drawn in this build (named degraded face, not silence). -->
  <!-- t261009-44: the Certification tab — the develop ledgers' face, drawn as the
       approved mock v15 draws it. The body is rendered by the embedded pure core
       buildCertificationCore; this section only carries the mount points. -->
  <section id="paneCert" style="display:none">
    <div id="certBody"></div>
    <!-- t261012-03: the round dialog (mock §2) — one overlay, filled by the
         embedded buildRoundDialogCore on a run-id click; never pre-rendered. -->
    <div id="roundDlgWrap" hidden>
      <div class="dlg" id="roundDlg" role="dialog" aria-label="round record"></div>
    </div>
    <!-- t261025-12 (ruling §5): the signed-promotion dialog — shows the human
         signer before the act; filled by the embedded buildPromoteDialogCore. -->
    <div id="promoteDlgWrap" hidden>
      <div class="dlg" id="promoteDlg" role="dialog" aria-label="signed promotion"></div>
    </div>
  </section>

  <!-- t261021-07: Metrics tab v2 — the approved mock (host 261021,
       metrics-tab-mock.html) reproduced: header selects, six KPI tiles,
       Where-the-time-goes (fixed-height card, workflow chips + type-to-match,
       in-card stage drill), Certification (green/red/flaky + strip + time to
       green), Epics (five cards + sort + type-to-match), Throughput chart,
       Where-the-tokens-go beside Tokens by role and Project sessions.
       Supersedes the t261005-10 "no second chart engine" ruling for this tab;
       echarts rides the vendor route behind metrics-tab-charts.ts (the option
       factories) — the mock's geometry is not a technical instruction, the
       chart bodies are echarts. The mock's explanatory behaviour sentences are
       banned here: labels, values, axis titles and legends only. Data faces:
       metrics v2 (view=time blocks), view=health (daily opened/closed),
       view=token (daily stacked by model), /api/certification (round faces).
       A face the transport does not carry renders its named empty state —
       never a fabricated number. -->
  <section id="paneMetrics" style="display:none">
    <div id="metricsBanner"></div>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:4px 0">
      <select id="metricsProject" aria-label="project"></select>
      <select id="metricsWindow" aria-label="window">
        <option value="7d">last 7 days</option>
        <option value="30d" selected>last 30 days</option>
        <option value="all">all time</option>
      </select>
    </div>
    <div id="metricsKpis" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;padding:6px 0"></div>
    <div style="display:flex;flex-direction:column">
      <div class="sect lead">Where the time goes</div>
      <div id="mtTimeCard" style="border:1px solid var(--line);border-radius:10px;height:330px;overflow:auto;padding:8px 10px">
        <div id="mtChips" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:2px 0">
          <input id="mtWfPick" list="mtWfList" placeholder="+ workflow" style="min-width:140px">
          <datalist id="mtWfList"></datalist>
        </div>
        <div id="mtWfRows" style="padding:4px 0"></div>
      </div>
    </div>
    <div class="sect lead">Certification</div>
    <div id="mtCert" style="padding:2px 0"></div>
    <div class="sect lead">Epics</div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:2px 0">
      <select id="mtEpicSort" aria-label="epic sort">
        <option value="activity" selected>Last activity</option>
        <option value="tickets">Tickets</option>
        <option value="elapsed">Elapsed</option>
        <option value="tokens">Tokens</option>
      </select>
      <input id="mtEpicPick" list="mtEpicList" placeholder="+ epic" style="min-width:140px">
      <datalist id="mtEpicList"></datalist>
      <span id="mtEpicChips" style="display:flex;gap:8px;flex-wrap:wrap"></span>
    </div>
    <div id="mtEpicCards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px;padding:6px 0"></div>
    <div class="sect lead">Throughput</div>
    <div id="mtThroughput" style="height:260px;min-width:0"></div>
    <div style="display:grid;grid-template-columns:2fr 1fr;gap:12px">
      <div style="min-width:0">
        <div class="sect lead">Where the tokens go</div>
        <div id="mtTokens" style="height:260px;min-width:0"></div>
      </div>
      <div style="min-width:0">
        <div class="sect lead">Tokens by role</div>
        <div id="mtRoles" style="padding:2px 0"></div>
        <div class="sect lead">Project sessions</div>
        <div id="mtSessions" style="padding:2px 0"></div>
      </div>
    </div>
  </section>

  <!-- t261005-10 (UI-2): Docs tab — read-only tree + markdown reader over the
       workbench docs API (same renderer as the rest of the page). -->
  <section id="paneDocs" style="display:none">
    <div id="docsBanner"></div>
    <!-- t261008-19: the 261004 mock's two entry rows (docsTabHtml) — docs/ the
         library, notes/ the ledger, real page counts (countDocsTree; unknown shows
         '— pages', never a fabricated number) and an Open action. The mock is silent
         on the Open target; the in-tab reader/scope switch is chosen, no new endpoint. -->
    <div class="bar" id="docsEntries" style="margin-top:0"></div>
    <div class="bar" style="margin-top:0" id="docsScopeBar"></div>
    <div id="docsTree"></div>
    <div id="docsReader"></div>
  </section>

  <section id="paneGrants" style="display:none">
    <div id="grantsBanner"></div>
    <div class="sect">Executor
      <button class="linkbtn" id="giveAllBtn">Give all</button>
      <button class="linkbtn" id="giveNoneBtn" style="margin-left:0">Give none</button>
    </div>
    <div class="grp">
      <div class="line"><div class="lab">Executor permissions <small>Off: the executor can only read and ask. The watchdog keeps running.</small></div>
        <div class="sw" id="masterSw" data-on="false"></div></div>
      <div class="line"><div class="lab">Executor session <small>The session that works as the executor.</small></div>
        <input type="text" id="grantSession" placeholder="session id"></div>
    </div>
    <div class="sect lead">Permissions you can give</div>
    <div class="grp" id="permList"></div>
    <div class="sect lead">Your permissions only</div>
    <div class="grp">
      <div class="line"><div class="lab">Change permissions <small>Only you can change this list.</small></div>
        <div class="sw locked" data-on="false"></div></div>
    </div>
    <div class="bar">
      <button class="primary" id="grantsSave">Save</button>
      <span id="grantsSaveOut" class="meta"></span>
    </div>
    <div id="grantsReadout" class="muted" style="margin-top:10px"></div>
    <div id="grantsMatrix"></div>
    <div id="openEpics"></div>
  </section>

  <!-- t261009-37 (host order 261009-(1)): paneAlert is gone — the Alerts tab left
       the strip and its face moved into the Overview right column as the Alerts
       block (#alertBanner / #alertList / #alertHead unchanged). -->

  <!-- t261008-20 (host order): paneLedger is gone — the Ledger tab left the strip; -->
  <!-- t261009-37 (host order 261009-(2)): the source-event dialog is gone too — the
       face lives inline in the Overview Events block (#ledgerFile / #ledgerHealth /
       #ledgerEvents). -->

  <section id="paneInsp" style="display:none">
    <div id="inspBanner"></div>
    <div class="strip">
      <span class="ro">● host action</span>
      <span>Full-codebase review</span>
      <span class="grow" style="flex:1"></span>
      <button class="bar" id="inspRunBtn">Run a full review…</button>
    </div>
    <div class="inspNote" style="margin-top:-6px">Only you can start a full review. The executor cannot. A review is recorded when it starts.</div>
    <div class="inspCard" id="inspDlg" data-open="false" style="display:none">
      <div class="pad inspSect">Run a full-codebase review</div>
      <div class="inspFld">
        <label for="inspScope">Scope</label>
        <select id="inspScope">
          <option value="everything">Everything</option>
          <option value="server/plugins only">server/plugins only</option>
          <option value="server/engine only">server/engine only</option>
          <option value="integration/ only">integration/ only</option>
          <option value="docs/ + notes/ only">docs/ + notes/ only</option>
        </select>
        <label for="inspReason">Reason</label>
        <input type="text" id="inspReason" placeholder="why now — recorded">
      </div>
      <div class="bar" style="padding:0 var(--igx,14px)">
        <button class="primary" id="inspStartBtn">Start</button>
        <button id="inspCancelBtn">Cancel</button>
        <span class="meta" id="inspMsg"></span>
      </div>
    </div>
    <div class="inspSect">Period</div>
    <div class="inspPeriods"><span class="lbl">Period</span><span id="inspPeriodBtns" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
    <div id="inspPeriodNote" class="inspNote" style="display:none"></div>
    <div id="inspBody"></div>
    <div class="inspSect lead" style="margin-top:20px;padding-left:var(--igx,14px);font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted)">Reviews you started</div>
    <div class="inspCard"><table id="inspRecords">
      <thead><tr><th>when</th><th>who</th><th>scope</th><th>reason</th><th style="text-align:right">state · result</th></tr></thead>
      <tbody id="inspRecordsBody"></tbody>
    </table></div>
    <div class="inspNote">Newest first · kept after the review ends</div>
    <div id="inspEmpty" class="empty" style="display:none;padding-left:var(--igx,14px)">No reviews started yet.</div>
  </section>

  <section id="paneSet" style="display:none">
    <div id="setBanners"></div>
    <!-- t261008-36: the two face entries the 261004 mock puts in this tab ("Model
         routes - moved into the panel - Settings tab" / "Project settings - moved
         into the panel - Settings tab"). The buttons do not render the faces here —
         they post one message to the parent console over the existing same-origin
         postMessage seam, and the console mounts the EXISTING faces (ProvidersSection
         / ProjectSettingsModal). The panel gains no second read or write path for
         model routes: no YAML access, no validation copy, no cached routes table.
         Fixed-shape list — declared in LIST_CONTRACTS (settings_faces). -->
    <div class="grp" id="faceEntries">
      <div class="line"><div class="lab">Model routes</div>
        <span class="meta">Providers, keys, and the routing table</span>
        <button class="openBtn" id="faceRoutesBtn" data-wb-panel-face="routes" style="margin-left:auto">Open</button></div>
      <div class="line"><div class="lab">Project settings</div>
        <span class="meta">Registry entry, ticket counts, and the danger zone</span>
        <button class="openBtn" id="faceSettingsBtn" data-wb-panel-face="project-settings" style="margin-left:auto">Open</button></div>
    </div>
    <div class="sect lead">Watchdog</div>
    <div class="grp" id="setKnobs"></div>
    <div class="bar">
      <button class="primary" id="saveBtn">Save</button>
      <button id="sleepBtn">Sleep until morning</button>
      <button id="wakeBtn">Revert the night policy</button>
      <button id="revokeBtn">Disable watchdog</button>
      <span id="saveResult" class="meta"></span>
    </div>
    <div class="muted" style="margin-top:8px;font-size:11px">Save writes the file only after the real loader accepts it. A rejected save does not change the file. Disable watchdog stops all watchdog behavior. It does not change the grants.</div>
  </section>

  <div class="foot" id="footNote"></div>
</div>
<script>
` + EMBEDDED + `
  // t261004-14：列表契约一处声明（list-contracts.ts 编译期校验，此处 JSON 嵌页）。
  // Render paths reach the empty copy through emptyCopyOf only (since t261008-20
  // capOf retired with the last numeric cap — every list is cap:'all'); cap numbers
  // stay out of the render paths.
  //（机械检查 check_list_caps.mjs 扫渲染源码里的截断形状整数常量）。
  var LIST_CONTRACTS = ${JSON.stringify(LIST_CONTRACTS)};
  // t261005-05 (UI-4): badge runtime constant closure (the page-side projectIdentity reads these tables).
  var IDENTITY_RUNTIME = ${IDENTITY_DATA};
  // t261006-17 (CL-2): the limit-range table the embedded limitStep/concChipState read.
  var CONC_LIMITS = ${JSON.stringify(CONC_LIMITS)};
  // t261009-44: the Certification tab's copy table (the named promote-dialog
  // absence sentence lives here — one copy source).
  var CERT_RUNTIME = ${CERT_TABLES};
  // the embedded render core reads the copy table by its module name (one source)
  var CERT_COPIES = CERT_RUNTIME.COPIES;
  var ROUND_COPIES = CERT_RUNTIME.ROUND;
  // t261021-07: the Metrics tab's copy table + series palette (one source).
  var METRICS_RUNTIME = ${METRICS_TABLES};
  var METRICS_COPIES = METRICS_RUNTIME.COPIES;
  var METRICS_COLORS = METRICS_RUNTIME.COLORS;
  // t261021-07 rework: the embedded model/chart bodies reference these as
  // identifiers — each must exist at page scope (the transitive closure).
  var DASH = METRICS_RUNTIME.DASH;
  var GRID_LINE = METRICS_RUNTIME.GRID_LINE;
  var LABEL = METRICS_RUNTIME.LABEL;
  var METRICS_SERIES_COLORS = METRICS_COLORS;
  var PROJECT_PALETTE_12 = IDENTITY_RUNTIME.PROJECT_PALETTE_12;
  var IDENTITY_OUTLINES = IDENTITY_RUNTIME.IDENTITY_OUTLINES;
  var IDENTITY_STRUCTURES = IDENTITY_RUNTIME.IDENTITY_STRUCTURES;
  var FALLBACK_IDENTITY = IDENTITY_RUNTIME.FALLBACK_IDENTITY;
  // Badge render (13px, the design-note §2.5 panel-chip size). Malformed/missing
  // project = no badge (no silent stand-in; an empty slot IS the "unset identity"
  // fact). Render errors are swallowed so the page never breaks. Self-contained DOM
  // access (getElementById, NOT the IIFE-local el()): this function lives in the
  // outer script scope, so the closure helper is invisible here — reaching for it
  // threw at call time and aborted the rest of setProject (found by
  // browser-page-contract: the settings knobs vanished because loadSettings never ran).
  function renderProjBadge(key){
    var slot = document.getElementById('projBadge');
    if(!slot) return;
    slot.innerHTML = '';
    // t261009-37 (host order 261009-(6)): the page carries the project colour as a
    // 3px bar across the top — derived from the SAME projectIdentity() the badge
    // uses (no second hash, no hand-picked value). Identity colour goes on identity
    // surfaces only (this bar, the badge); never on buttons, status chips, alert
    // rows or pills — the semantic colours carry meaning there. If the fetch for
    // this project failed or no project is set, the grey :root default stays: the
    // bar states "no identity known", it never guesses.
    try{ document.documentElement.style.setProperty('--proj', projectIdentity(key).color); }catch(e){}
    if(!key) return;
    try{ slot.innerHTML = identityBadgeSvg(projectIdentity(key), 13); }catch(e){}
  }
  function emptyCopyOf(id){
    var c = LIST_CONTRACTS[id];
    return (c && c.empty_copy) || '';
  }
  // t261008-20: capOf removed with the last numeric cap — every list the page renders
  // now declares cap:'all' (LIST_CONTRACTS is the truth; no render path truncates).

(function(){
  var state = { project:'', status:null, reachable:null, requests:null, actions:null, grants:null, settings:null, session:'',
    // t261005-10 (UI-2): the four read-only tab faces + the Overview limit row.
    concurrency:null, epics:null, epicsReason:'', epicTickets:{}, epicOpen:'', epicShowAll:{},
    inspection:null, inspectionError:'',
    docs:null, docsScope:'docs', docSel:'' };
  // t261006-17 (CL-2): the concurrency face + the knob draft (null = follow the saved limit).
  state.conc = null;
  state.concDraft = null;
  var saveMsg = '';
  var grantsSaveMsg = '';
  // t261003-14：UI 态搬到 JS state（键=请求 id），轮询重建 DOM 不再抹掉宿主视图。
  // openIds=宿主展开的行；drafts=自由文本草稿（含展开出的「Type an answer」框）；
  // revealedIds=点过「Type an answer」的行（下次渲染直接给输入框，不再给按钮排）；
  // detailScroll=详情块滚动位置。id 从台账消失的行下一次渲染自然缺席，不会复活。
  state.openIds = new Set();
  state.drafts = {};
  state.revealedIds = new Set();
  state.detailScroll = {};
  var POLL_MS = 5000;
  // 声明键（与引擎 GRANT_OPS 同一词表；'send-back' 是声明键，显示名 Send back）。
  var PERMS = [
    ['sign','Sign','Agree to a gate or a merge.'],
    ['send-back','Send back','Send a ticket to the previous stage.'],
    ['rerun','Rerun','Run the checks of a stage again.'],
    ['open-ticket','Open ticket','Start a new ticket.'],
    ['pause-resume','Pause and resume','Stop or continue a ticket between stages.'],
    ['cleanup','Cleanup','Cancel a ticket.']
  ];
  function beepCountKey(){ return 'sandbar-panel-beepcount-' + (state.project||'global'); }
  try{ window.__panelBeepCount = Number(localStorage.getItem(beepCountKey())||'0')||0; }catch(e){ window.__panelBeepCount = 0; }
  function seenKey(p){ return 'sandbar-panel-seen-' + p; }
  function seenSet(p){ try{ return new Set(JSON.parse(localStorage.getItem(seenKey(p))||'[]')); }catch(e){ return new Set(); } }
  function saveSeen(p,s){ try{ localStorage.setItem(seenKey(p), JSON.stringify(Array.from(s))); }catch(e){} }
  var audioCtx = null;
  function playBeepOnce(){
    // WebAudio oscillator: the page produces the sound (dsh has no sound capability — epic-verified).
    try{
      audioCtx = audioCtx || new (window.AudioContext||window.webkitAudioContext)();
      var o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type='sine'; o.frequency.value=880; g.gain.value=0.08;
      o.connect(g); g.connect(audioCtx.destination);
      var t = audioCtx.currentTime; o.start(t);
      g.gain.setValueAtTime(0.08,t); g.gain.exponentialRampToValueAtTime(0.0001,t+0.35);
      o.stop(t+0.4);
    }catch(e){}
    window.__panelBeepCount += 1;
    try{ localStorage.setItem(beepCountKey(), String(window.__panelBeepCount)); }catch(e){}
  }
  function el(id){ return document.getElementById(id); }
  function esc(s){ var d=document.createElement('span'); d.textContent=String(s==null?'':s); return d.innerHTML; }
  function bannerHtml(label,red){ return '<div class="banner'+(red?' red':'')+'">'+esc(label)+'</div>'; }
  // 时间口径（t261004-14）：全部走 localDateTime（本地时区、带日期），页头带「Times are local.」标签。

  // ---- polling + beep ----
  function poll(){
    if(!state.project) return;
    fetch('/sandbar-watchdog/api/status?project='+encodeURIComponent(state.project))
      .then(function(r){ return r.json().then(function(j){ return { http:r.status, j:j }; }); })
      .then(function(res){
        var okDoc = res.j && res.j.ok === true && res.j.result;
        state.status = okDoc ? res.j.result : null;
        state.reachable = !!okDoc;
        renderOverviewStrip();
        renderAlertsLedger();
        tryBeep();
      })
      .catch(function(){
        state.status = null; state.reachable = false;
        renderOverviewStrip();
        renderAlertsLedger();
      });
  }
  function tryBeep(){
    var st = state.status;
    if(!st || !st.notify) return;
    var seen = seenSet(state.project);
    var d = beepDecision(st.notify, st.alerts, state.project, seen);
    if(d.play){
      for(var i=0;i<d.keys.length;i++){ playBeepOnce(); seen.add(d.keys[i]); }
      saveSeen(state.project, seen);
    }
  }

  // ---- Overview: strip + two columns ----
  function degradedBanners(){
    var st = state.status, b='';
    var dg = pickDegraded({ reachable: state.reachable === true, declared: st?st.declared:undefined, alive: st&&st.heartbeat?st.heartbeat.alive:undefined, config_error: st?st.config_error:null });
    if(dg.kind==='route-down') b += bannerHtml(dg.label, true);
    // t261003-06 rework（仲裁 code-fault D2）：not-declared 是显式非正常态，必须在
    // Overview 落一条横幅——改版时这一支被漏掉，未声明项目首次到达只剩标题（读起来
    // 像「一切正常但没数据」，正是 panel 契约禁止的冒充）。label 由 pickDegraded 给出
    // （「Not enrolled — no watchdog.json … zero behavior by design」），单测有锚。
    if(dg.kind==='not-declared') b += bannerHtml(dg.label, false);
    if(dg.kind==='stale') b += bannerHtml(dg.label + '. Reason: ' + (st&&st.heartbeat?st.heartbeat.reason:''), true);
    if(dg.kind==='config-error') b += bannerHtml(dg.label, true);
    if(st && st.config_error && dg.kind!=='config-error') b += bannerHtml('The watchdog rejected the declaration: '+st.config_error, true);
    if(st && st.last_error) b += bannerHtml('The last watchdog error: '+st.last_error, true);
    if(st && st.ledger && st.ledger.unreadable) b += bannerHtml('The event ledger is unreadable: '+st.ledger.unreadable, true);
    if(st && st.liveness && st.liveness.engine && st.liveness.engine.online === null) b += bannerHtml('Engine state unknown: '+(st.liveness.engine.detail||''), false);
    if(st && st.self_lock && st.self_lock.state === 'unknown') b += bannerHtml('Self-lock state unknown: '+(st.self_lock.reason||''), false);
    return b;
  }
  function renderOverviewStrip(){
    el('ovBanners').innerHTML = degradedBanners();
    var st = state.status;
    var g = state.grants && state.grants.ok !== false ? state.grants : null;
    var count = g && g.granted_ops ? g.granted_ops.length : null;
    var total = g && typeof g.granted_total === 'number' ? g.granted_total : 6;
    var on = count !== null ? masterOn(count) : false;
    el('grantChip').textContent = chipLabel(count !== null ? count : 0, total);
    el('powerBtn').dataset.on = String(on);
    el('powerBtn').textContent = on ? 'Disable executor' : 'Enable executor';
    el('liveDot').className = on ? 'live' : 'ro';
    el('liveDot').textContent = on ? '● active' : '● read-only';
    var sr = g && g.session_readout ? g.session_readout : null;
    // 点名回落链：读出面 sessions → 声明顶层 executor_sessions（读出面缺席时的声明位）。
    var sess = (sr && sr.sessions && sr.sessions.length ? sr.sessions[0] : '')
      || (g && g.executor_sessions && g.executor_sessions.length ? g.executor_sessions[0] : '');
    state.session = sess;
    el('sessionChip').textContent = 'Session: ' + (sess ? sess : 'none');
    var stTxt = st && st.heartbeat ? (st.heartbeat.alive ? 'The watchdog is alive. Last beat: '+fmtAge(st.heartbeat.age_seconds) : 'The watchdog is not alive.') : 'The watchdog state is not known.';
    el('stateTxt').textContent = stTxt + (on ? '' : ' The executor can only read and ask. The watchdog keeps running.');
    renderWaitColumn();
    renderActions();
  }
  // ---- requests (left column) ----
  function normalizeRequests(j){
    var rows = [];
    if(j && Array.isArray(j.rows)) rows = j.rows;
    else if(j && Array.isArray(j.groups)){
      j.groups.forEach(function(g){ (g.rows||[]).forEach(function(r){ rows.push(Object.assign({}, r, {project:r.project||g.project})); }); });
    }
    var msOf = function(v){ return typeof v==='number'? v : (typeof v==='string'? (Date.parse(v)||0) : 0); };
    rows.sort(function(a,b){ return msOf(b.at)-msOf(a.at); });
    return { rows: rows, malformed_rows: (j && j.malformed_rows) || 0, ok: !!(j && (j.ok===true||j.rows||j.groups)) };
  }
  function urgencyOf(r){
    if(r.urgency) return r.urgency;
    var at = typeof r.at==='number'? r.at : Date.parse(r.at);
    return { waiting_ms: Math.max(0, Date.now()-(isNaN(at)?Date.now():at)),
      expired: r.status==='waiting' && r.expires_at!=null && Date.now()>Date.parse(r.expires_at),
      answered: r.status==='answered' };
  }
  function loadRequests(){
    if(!state.project){ state.requests=null; renderWaitColumn(); return; }
    fetch('/sandbar-executor-panel/api/requests?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.requests = normalizeRequests(j);
      renderWaitColumn();
    }).catch(function(){ state.requests = null; renderWaitColumn(); });
    loadBridgeStatus();
  }
  // t261004-44 (KI-196): the question-bridge status line -- mounted flag / mirror
  // counters / latest event. A bridge that does not fire must not be silent: this line
  // is the human-readable "is the bridge alive" face; a read failure is an explicit
  // unknown, never a fake healthy state.
  function loadBridgeStatus(){
    var el = document.getElementById('bridgeLine');
    if(!el) return;
    fetch('/sandbar-executor-panel/api/bridge/status').then(function(r){return r.json();}).then(function(j){
      if(!j || j.ok!==true){ el.textContent = 'Question bridge: status unreadable.'; return; }
      var c = j.counters || {};
      var mirrored = c.mirrored || 0, refused = (c['mirror-refused']||0) + (c['mirror-failed']||0);
      var last = (j.last_events && j.last_events[0]) || null;
      var txt = 'Question bridge: ' + (j.mounted ? 'mounted' : 'NOT MOUNTED') +
        ' — mirrored ' + mirrored + ', refused/failed ' + refused;
      if(last){ txt += '; last event ' + last.kind + ' (' + fmtWaiting(Math.max(0, Date.now()-last.at)) + ' ago)'; }
      if(!j.mounted || mirrored===0){ txt += ' — if a session is waiting on a question, the bridge is not delivering (KI-196).'; }
      el.textContent = txt;
    }).catch(function(){
      el.textContent = 'Question bridge: status face unreachable (named unknown — the face may not be wired).';
    });
  }
  function traceLine(r){
    var t = 'Request id: ' + r.id;
    if(r.raised_by) t = 'Raised by session ' + r.raised_by + '. ' + t;
    // t261007-02: the two ownership fields (source ticket = fact, owning epic =
    // judgement, 'none' carries its reason) and the judged source class.
    if(r.source_ticket) t += ' Source ticket: ' + r.source_ticket + '.';
    if(r.epic) t += ' Owning epic: ' + r.epic
      + (r.epic === 'none' && r.epic_reason ? ' (' + r.epic_reason + ')' : '') + '.';
    if(r.source_class) t += ' Source: ' + r.source_class + '.';
    t += ' State: ' + (r.state || 'open') + '.';
    t += ' Default action: ' + (r.default_action ? r.default_action : 'none') + '.';
    // Thread face: links (a duplicates link without 'from' = a re-file that was
    // linked, never a dangling id). t261019-43: replies left this trace — they have
    // their own face now (replyBlock below); the trace keeps the audit fields only.
    var links = r.links || [];
    for(var j=0;j<links.length;j++){
      var l = links[j];
      t += ' Link ' + l.kind + (l.from ? ' from ' + l.from : ' (re-file linked, no new item opened)')
        + ' to ' + l.to + '.';
    }
    return t;
  }
  function rowHead(r, cls, groupTag){
    var u = urgencyOf(r);
    var meta = esc(r.kind) + ' · ' + esc(fmtWaiting(u.waiting_ms));
    if(groupTag) meta += ' · <span class="gtag">'+esc(groupTag)+'</span>';
    if(u.expired) meta += ' · expired. It still waits.';
    if(r.status==='answered') meta = esc(r.kind);
    // t261007-02: closed states show their name on the collapsed head, and the two
    // ownership fields travel on every head (empty on legacy rows = not shown).
    if(r.status==='resolved'||r.status==='dismissed'||r.status==='superseded'){
      meta = esc(r.kind) + ' · ' + esc(r.state||r.status);
    }
    if(r.epic) meta += ' · ' + esc(r.epic);
    if(r.source_ticket) meta += ' · ' + esc(r.source_ticket);
    // t261007-01: a dismissed card names what happened, in one line.
    if(r.status==='dismissed') meta = esc(r.kind) + ' · dismissed';
    // t261019-43: a collapsed row must not hide replies — the badge rides the head
    // meta ('1 reply' / 'N replies'; empty string when none).
    var rbadge = replyBadge(r.replies);
    if(rbadge) meta += ' · ' + esc(rbadge);
    return '<div class="head" data-id="'+esc(r.id)+'"><span class="dot '+cls+'"></span>'
      + '<span class="txt">'+esc(r.question)+'</span>'
      + '<span class="meta">'+meta+'</span><span class="chev">&#9656;</span></div>';
  }
  // t261004-17：waiting 行的选项块直接挂在收起行内（不展开就能一键答）；无选项时
  // 收起行内给默认动作行。展开后的 body 不再重复选项块。
  // t261004-16 Req3：选项标签走 renderMarkdown 的 inline 面（行内标记保留，块结构
  // 对按钮无意义）——与 main 侧正文同一只渲染器。
  function inlineBlock(r){
    if(r.status!=='waiting') return '';
    // t261007-01: the Dismiss action — "I saw it, I do not rule on it". One
    // click moves the card out of Needs your answer; the default action still
    // applies and the executor still runs it. It rides the same inline block
    // as the options so the collapsed row never clips it.
    var dismissBtn = '<button class="other" data-dismiss="1">Dismiss</button>';
    var html = '';
    if(hasOptions(r) && !state.revealedIds.has(r.id)){
      html += '<div class="opts inline">';
      var opts = r.options;
      for(var i=0;i<opts.length;i++){
        html += '<button data-answer="'+esc(opts[i])+'"'+(i===0?' class="primary"':'')+'>'+renderMarkdown(opts[i],{inline:true})+'</button>';
      }
      html += '<button class="other" data-reveal="1">Type an answer</button>' + dismissBtn + '</div>';
    } else {
      html += '<div class="opts inline">' + dismissBtn + '</div>';
    }
    if(r.default_action) html += '<div class="dflt">If you do not answer: '+esc(r.default_action)+'.</div>';
    return html;
  }
  // t261004-16 Req3：详情体与应答回显走唯一的 renderMarkdown（转义先行，敌意输入
  // 只能落成字面文本）；展开行把完整问题按格式渲染在正文顶部（行头收起态保持单行省略）。
  // t261019-43: the reply block — every reply as its own readable line above the
  // trace, naming intent and source class ('fact · project-session — session-…: …').
  // Text goes through renderMarkdown (escape-first renderer, same as the body);
  // meta fields go through esc(). Malformed entries are literal placeholders that
  // replyFace already counted — never silent, never a crash.
  function replyBlock(r){
    var f = replyFace(r.replies);
    if(!f.lines.length) return '';
    var html = '<div class="replies">';
    for(var i=0;i<f.lines.length;i++){
      var p = f.lines[i];
      var headBits = [];
      if(p.intent) headBits.push(esc(p.intent));
      if(p.source_class) headBits.push(esc(p.source_class));
      var meta = headBits.length ? ' <span class="ri">'+headBits.join(' · ')+'</span>' : '';
      html += '<div class="rp"><span class="rby">'+esc(p.by)+'</span>'+meta
        + (p.via ? ' <span class="ri">decided by '+esc(p.via)+'</span>' : '')
        + (p.anchor ? ' <span class="ri">anchor: "'+esc(p.anchor)+'"</span>' : '')
        + ': <span class="rtxt">'+renderMarkdown(p.text)+'</span></div>';
    }
    if(f.malformed > 0) html += '<div class="ri">'+f.malformed+' malformed reply row(s) shown as placeholders — never dropped.</div>';
    return html + '</div>';
  }
  function rowBody(r){
    var qfull = '<div class="qfull">'+renderMarkdown(r.question||'')+'</div>';
    // t261007-01: the dismissed card copy — no decision was made; the default
    // action still applies and the executor still runs it.
    if(r.status==='dismissed'){
      return '<div class="body">'+qfull+'<div class="detail">'+renderMarkdown(r.detail||'(no detail was given)')+'</div>'
        + '<div class="given">Dismissed by you. Your default action applies.</div>'
        + replyBlock(r) + '<div class="trace">'+esc(traceLine(r))+'</div></div>';
    }
    if(r.status==='answered'){
      // t261006-06: an answered request can be run as ONE high-privilege
      // one-shot unit -- the approval is the gate; the watchdog re-checks it
      // and consumes it (one execution per approval). The action text is
      // typed by the host in the prompt box.
      return '<div class="body">'+qfull+'<div class="detail">'+renderMarkdown(r.detail||'(no detail was given)')+'</div>'
        + '<div class="given">You answered: '+renderMarkdown(r.answer||'')+'</div>'
        + '<div class="oneshot"><textarea placeholder="Exact privileged action to run" data-shotactionbox="1"></textarea><button data-shotrun="1">Run as one-shot</button></div>'
        + replyBlock(r) + '<div class="trace">'+esc(traceLine(r))+'</div></div>';
    }
    var inlineOpts = hasOptions(r) && !state.revealedIds.has(r.id);
    var controls = '';
    // t261003-14（review #2）：宿主点过「Type an answer」的行，下次渲染直接给输入框，
    // 不再给按钮排——否则 revealed 的草稿在重建时无处安放。
    // t261004-17：有选项且未 reveal 时选项块已在收起行内（标签走 renderMarkdown
    // inline 面），body 不重复；应答框是多行 textarea（Enter 换行，点 Send 发送）。
    if(!inlineOpts){
      controls = '<div class="answer"><textarea placeholder="Type an answer" data-answerbox="1"></textarea><button data-sendbox="1">Send</button></div>';
    }
    return '<div class="body">'+qfull+'<div class="detail">'+renderMarkdown(r.detail||'(no detail was given)')+'</div>'
      + controls
      + replyBlock(r) + '<div class="trace">'+esc(traceLine(r))+'</div></div>';
  }
  // t261009-37 (host order 261009-(3)): updateOpenBtn and the Open session button
  // are gone — the session chip is the state display; no session entry postMessage
  // is sent from this page anymore.
  function renderWaitColumn(){
    var st = state.requests;
    var waitHtml = '', doneHtml = '', dismissedHtml = '';
    var waiting = [], answered = [], dismissed = [];
    if(st && st.ok===true){
      // t261004-14：两个列表都最新在前（at 降序，at 畸形排最后）——契约见 LIST_CONTRACTS。
      // t261007-01: third group, dismissed, same newest-first order (a dismiss
      // = seen but not ruled; the card lands in the collapsed group).
      var sp = splitWaiting(st.rows);
      waiting = newestFirst(sp.waiting); answered = newestFirst(sp.answered); dismissed = newestFirst(sp.dismissed);
    }
    else if(!st){ waitHtml = '<div class="act" style="border:0"><span class="say muted">The request ledger could not be reached. This is not an empty inbox.</span></div>'; }
    // t261003-14：展开态来自 state.openIds（键=id），轮询重建不折叠宿主展开的行。
    var openOf = function(id){ return state.openIds.has(String(id)) ? 'true' : 'false'; };
    // t261004-17：同 group_id 的行=一次多问 ask，头上一枚「question i of n」组标签；
    // 每行仍是独立卡、独立可答（一问一行镜像的面板半）。
    var groupCount = {};
    var groupTag = {};
    Array.prototype.forEach.call(waiting.concat(answered), function(r){
      if(!r.group_id) return;
      groupCount[r.group_id] = (groupCount[r.group_id] || 0) + 1;
    });
    // 组内序号按提问时刻（at 升序）定，与行落在 waiting/answered 哪个区无关——
    // 组里答掉一问，剩下那问的标签不变。
    var grouped = waiting.concat(answered).filter(function(r){ return r.group_id && groupCount[r.group_id] > 1; });
    grouped.sort(function(a,b){ return a.at - b.at; });
    var groupSeen2 = {};
    Array.prototype.forEach.call(grouped, function(r){
      groupSeen2[r.group_id] = (groupSeen2[r.group_id] || 0) + 1;
      groupTag[r.id] = 'question ' + groupSeen2[r.group_id] + ' of ' + groupCount[r.group_id];
    });
    var groupTagOf = function(r){ return groupTag[r.id] || ''; };
    for(var i=0;i<waiting.length;i++) waitHtml += '<div class="row wait" data-open="'+openOf(waiting[i].id)+'" data-row="'+esc(waiting[i].id)+'">'+rowHead(waiting[i],'amber',groupTagOf(waiting[i]))+inlineBlock(waiting[i])+rowBody(waiting[i])+'</div>';
    for(var j=0;j<answered.length;j++) doneHtml += '<div class="row done" data-open="'+openOf(answered[j].id)+'" data-row="'+esc(answered[j].id)+'">'+rowHead(answered[j],'grey',groupTagOf(answered[j]))+inlineBlock(answered[j])+rowBody(answered[j])+'</div>';
    // t261007-01: dismissed cards render into their own collapsed group.
    for(var k=0;k<dismissed.length;k++) dismissedHtml += '<div class="row done" data-open="'+openOf(dismissed[k].id)+'" data-row="'+esc(dismissed[k].id)+'">'+rowHead(dismissed[k],'grey',groupTagOf(dismissed[k]))+inlineBlock(dismissed[k])+rowBody(dismissed[k])+'</div>';
    // 重建前快照焦点（输入框光标）与各详情块滚动位置，重建后原样放回。
    // 滚动位置直接从 DOM 读——scroll 事件是异步派的，程序化滚动在重建前可能还没派到，
    // 只靠监听器记会有竞态（t261003-14 截图证据里真实踩到过）。
    var focusSnap = null;
    var active = document.activeElement;
    if(active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')){
      var frow = active.closest('[data-row]');
      if(frow) focusSnap = { id: frow.dataset.row, selStart: active.selectionStart, selEnd: active.selectionEnd };
    }
    var scrollSnap = {};
    Array.prototype.forEach.call(document.querySelectorAll('[data-row] .detail'), function(d){
      scrollSnap[d.closest('[data-row]').dataset.row] = d.scrollTop;
    });
    el('waitList').innerHTML = waitHtml;
    el('doneList').innerHTML = doneHtml;
    el('dismissedList').innerHTML = dismissedHtml;
    el('waitHead').textContent = 'Needs your answer · ' + waiting.length;
    el('waitEmpty').textContent = emptyCopyOf('overview_waits');
    el('waitEmpty').style.display = (waiting.length===0 && st && st.ok===true) ? '' : 'none';
    el('doneHead2').textContent = 'Answered · ' + answered.length;
    el('doneWrap').style.display = answered.length===0 ? 'none' : '';
    // t261007-01: third group header/count; hidden while empty, like Answered.
    el('dismissedHead').textContent = 'Dismissed · ' + dismissed.length;
    el('dismissedWrap').style.display = dismissed.length===0 ? 'none' : '';
    var badge = el('reqBadge');
    badge.textContent = String(waiting.length);
    badge.className = 'badge' + (waiting.length===0 ? ' zero' : '');
    bindRows(el('waitList'));
    bindRows(el('doneList'));
    bindRows(el('dismissedList'));
    restoreRowState(focusSnap, scrollSnap);
  }
  // t261003-14：重建后按 id 放回滚动位置、草稿文本与焦点光标。
  // 滚动优先用重建前的 DOM 快照（无竞态），缺席才回落 onscroll 监听器记下的值。
  function restoreRowState(focusSnap, scrollSnap){
    Array.prototype.forEach.call(document.querySelectorAll('[data-row]'), function(row){
      var id = row.dataset.row;
      if(id in state.drafts){
        var box = row.querySelector('[data-answerbox]');
        if(box) box.value = state.drafts[id];
      }
      var det = row.querySelector('.detail');
      if(det){
        var top = scrollSnap && (id in scrollSnap) ? scrollSnap[id] : state.detailScroll[id];
        if(top) det.scrollTop = top;
      }
    });
    if(focusSnap){
      var escId = window.CSS && window.CSS.escape ? window.CSS.escape(focusSnap.id) : focusSnap.id.replace(/"/g, '\\"');
      var frow = document.querySelector('[data-row="'+escId+'"]');
      var input = frow && frow.querySelector('[data-answerbox]');
      if(input){
        input.focus();
        try{ input.setSelectionRange(focusSnap.selStart, focusSnap.selEnd); }catch(e){}
      }
    }
  }
  function bindRows(root){
    Array.prototype.forEach.call(root.querySelectorAll('.head[data-id]'), function(h){
      h.onclick = function(){
        var row = h.parentElement;
        // t261003-14：开合写进 state（真源），dataset 只是渲染投影。
        var id = row.dataset.row;
        if(state.openIds.has(id)){ state.openIds.delete(id); row.dataset.open = 'false'; }
        else { state.openIds.add(id); row.dataset.open = 'true'; }
      };
    });
    // 详情块滚动位置：滚动即记，重建后放回（读长内容跨轮询不掉位）。
    Array.prototype.forEach.call(root.querySelectorAll('.detail'), function(d){
      d.onscroll = function(){ state.detailScroll[d.closest('[data-row]').dataset.row] = d.scrollTop; };
    });
    // 自由文本草稿：每敲一次记一次，轮询重建后原样填回。t261004-17：应答框是多行
    // textarea——Enter=换行（宿主要能贴多行答复），Ctrl/Cmd+Enter=发送。
    Array.prototype.forEach.call(root.querySelectorAll('textarea[data-answerbox]'), function(inp){
      var rowId = inp.closest('[data-row]').dataset.row;
      inp.addEventListener('input', function(){ state.drafts[rowId] = inp.value; });
      inp.onkeydown = function(e){ if(e.key==='Enter' && (e.ctrlKey || e.metaKey) && inp.value.trim()!=='') sendAnswer(rowId, inp.value); };
    });
    Array.prototype.forEach.call(root.querySelectorAll('button[data-answer]'), function(b){
      b.onclick = function(){ sendAnswer(b.closest('[data-row]').dataset.row, b.dataset.answer); };
    });
    // t261007-01: the Dismiss click — one click, no decision, out of the
    // waiting list into the Dismissed group.
    Array.prototype.forEach.call(root.querySelectorAll('button[data-dismiss]'), function(b){
      b.onclick = function(){ sendDismiss(b.closest('[data-row]').dataset.row); };
    });
    Array.prototype.forEach.call(root.querySelectorAll('button[data-reveal]'), function(b){
      b.onclick = function(){
        var opts = b.parentElement;
        var box = document.createElement('div');
        box.className = 'answer';
        box.innerHTML = '<textarea placeholder="Type an answer"></textarea><button>Send</button>';
        opts.replaceWith(box);
        var input = box.querySelector('textarea');
        var rowId = box.closest('[data-row]').dataset.row;
        // t261003-14：点开即记 revealedIds + 草稿监听——下一次轮询渲染直接给输入框并填回草稿。
        state.revealedIds.add(rowId);
        input.addEventListener('input', function(){ state.drafts[rowId] = input.value; });
        box.querySelector('button').onclick = function(){ if(input.value.trim()!=='') sendAnswer(rowId, input.value); else input.focus(); };
        input.onkeydown = function(e){ if(e.key==='Enter' && (e.ctrlKey || e.metaKey) && input.value.trim()!=='') sendAnswer(rowId, input.value); };
        input.focus();
      };
    });
    Array.prototype.forEach.call(root.querySelectorAll('button[data-sendbox]'), function(b){
      b.onclick = function(){
        var input = b.parentElement.querySelector('textarea');
        if(input.value.trim()!=='') sendAnswer(b.closest('[data-row]').dataset.row, input.value); else input.focus();
      };
    });
    Array.prototype.forEach.call(root.querySelectorAll('button[data-shotrun]'), function(b){
      b.onclick = function(){
        var input = b.parentElement.querySelector('textarea');
        var rowId = b.closest('[data-row]').dataset.row;
        if(input.value.trim()!=='') runOneShot(rowId, input.value); else input.focus();
      };
    });
  }
  function runOneShot(id, action){
    postJson('/sandbar-executor-panel/api/one-shot/spawn', {project: state.project, request_id: id, action: action})
      .then(function(j){
        var sp = j && j.spawn;
        if(j && j.ok===true && sp && sp.spawned===true){
          alert('One-shot unit spawned: session '+(sp.sessionId||'?'));
        } else {
          alert('The one-shot spawn was refused: '+((sp&&sp.reason)||(j&&j.error)||'?'));
        }
        loadRequests();
      })
      .catch(function(e){ alert('The one-shot spawn failed to send: '+((e&&e.message)||e)); });
  }
  function sendAnswer(id, answer){
    // t261004-18（KI-193）：不发送 by——写者由服务端凭据定名（'host'），调用方
    // 自报不再被信任；发了也会被记成 by_claimed 错配位。
    postJson('/sandbar-executor-panel/api/requests/answer', {project: state.project, id: id, answer: answer})
      .then(function(j){
        if(j.ok!==true){ alert('The answer was rejected: '+(j.error||'?')); }
        else {
          // t261003-14（review #3）：发送成功才清草稿与 reveal 态——被拒的草稿原样保留。
          delete state.drafts[id];
          state.revealedIds.delete(id);
        }
        loadRequests();
      })
      .catch(function(e){ alert('The answer failed to send: '+((e&&e.message)||e)); });
  }
  // t261007-01: the dismiss POST — the writer is server-derived from the console
  // session ('host'), so nothing about the writer is sent from the page (same
  // discipline as sendAnswer, KI-193).
  function sendDismiss(id){
    postJson('/sandbar-executor-panel/api/requests/dismiss', {project: state.project, id: id})
      .then(function(j){
        if(j.ok!==true){ alert('The dismiss was rejected: '+(j.error||'?')); }
        loadRequests();
      })
      .catch(function(e){ alert('The dismiss failed to send: '+((e&&e.message)||e)); });
  }
  // ---- recent actions (right column) ----
  function loadActions(){
    if(!state.project){ state.actions=null; renderActions(); return; }
    fetch('/sandbar-executor-panel/api/actions?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.actions = j; renderActions();
    }).catch(function(){ state.actions = {ok:false, reason:'the actions endpoint could not be reached'}; renderActions(); });
  }
  function renderActions(){
    var a = state.actions, html = '';
    if(!state.project){ html = ''; el('actCount').textContent = '0'; }
    else if(!a || a.ok!==true){
      // 显式降级：点名原因（新源缺席=「记录启动以来无动作」+文件路径），绝不冒充空列表。
      el('actCount').textContent = '0';
      html = '<div class="act" style="border:0"><span class="say muted">' + esc(a&&a.reason ? a.reason : 'The action record is not known.') + '</span></div>';
    } else if(a.actions.length===0){
      // t261004-21：空态文案取自契约（emptyCopyOf），不再内联重复——契约改词即页面
      // 改词，渲染面守卫（b5 的 innerText 断言）才看得见契约文案。
      el('actCount').textContent = '0';
      html = '<div class="act" style="border:0"><span class="say muted">' + esc(emptyCopyOf('overview_recent_actions')) + ' Full history: ' + esc(a.source) + '.</span></div>';
    } else {
      el('actCount').textContent = String(a.actions.length);
      for(var i=0;i<a.actions.length;i++){
        var x = a.actions[i];
        var refused = x.result==='refused';
        // t261009-37 (host order 261009-(5)): the refused fact moved from an inline
        // red dot before the time into a red 'refused' pill in the op column, and
        // the sentence names what was refused and why — the row's meaning never
        // depends on a tooltip (the title stays as a duplicate, not as the carrier).
        var cls = refused ? 'refused' : ({Sign:'sign','Send back':'sendback',Rerun:'retry','Open ticket':'open',Pause:'pause',Resume:'pause','Pause or resume':'pause',Cancel:'cancel'}[x.action]||'pause');
        // hover copy carries permission + session (t261004-11).
        // 文案前缀写在属性字面量里（title="Allowed by the … / title="Refused: …），
        // 页面源码即可断言 hover 形状（场景 B3 的锁定面）。
        // 时间口径走 localDateTime（t261004-14：行时间带日期，旧的时分格式已退役）。
        var attr = function(v){ return esc(v).replace(/"/g,'&quot;'); };  // 属性面：引号也逃
        var perm = attr(x.permission||'declared default');
        var sess = attr(x.session||'none');
        var titleAttr = refused
          ? '"Refused: '+attr(x.reason||'no reason recorded')+' · session '+sess+'."'
          : '"Allowed by the '+perm+' permission · session '+sess+'."';
        var say = refused
          ? esc(x.action||'') + ' · ' + esc(x.reason||'no reason recorded')
          : esc(x.result||'done');
        html += '<div class="act">'
          + '<span class="t">'+esc(localDateTime(x.at))+'</span>'
          + '<span class="pill '+cls+'" title='+titleAttr+'>'+esc(refused?'refused':x.action)+'</span>'
          + '<span class="tk">'+esc(x.ticket)+'</span>'
          // t261004-19：open-ticket 行带 epic（行数据缺席/旧行=不渲染标签，不吞行）。
          + (x.epic ? '<span class="say muted">· epic '+esc(x.epic)+'</span>' : '')
          + '<span class="say">'+say+'</span></div>';
      }
      if(a.older_rows>0 && a.note){ html += '<div class="act" style="border:0"><span class="say muted">'+esc(a.note)+'</span></div>'; }
    }
    // status face：引擎落账失败（gaps 旁账非空）在此可见，绝不静默。
    if(a && a.ok===true && a.gaps_recent>0){
      html += '<div class="act" style="border:0"><span class="say muted">The engine failed to record ' + esc(a.gaps_recent) + ' action(s). See ' + esc(a.gaps_file||'the gap file') + '.</span></div>';
    }
    // t261005-12: the engine-written last-failure marker (last_record_failure) is
    // visible here — an empty record with a marker present = the failure is named
    // explicitly, never the silent "no actions" empty state (this ticket's defect
    // face).
    if(a && a.last_record_failure){
      var lf = a.last_record_failure;
      html += '<div class="act" style="border:0"><span class="say muted">The engine failed to record the latest action at ' + esc(localDateTime(lf.at)) + ': ' + esc(lf.why||'no reason recorded') + (lf.error ? ' (' + esc(lf.error) + ')' : '') + '.</span></div>';
    }
    el('actList').innerHTML = html;
  }

  // ---- concurrency (t261006-17, CL-2): limit knob + running list ----
  // The read face only reads the engine ledger (passed through the API); the panel
  // never recomputes. Refusal text renders verbatim — never a faked empty list.
  function concChipLabel(kind){
    return { room:'room to start one', at:'at the limit', over:'over the limit' }[kind] || kind;
  }
  function loadConcurrency(){
    // ONE fetch feeds BOTH faces (t261006-17 block + t261005-10 limit row): the CL-2
    // api response is the superset, and state.concurrency is derived from it — the
    // two renderers never disagree about the numbers.
    if(!state.project){ state.conc=null; state.concurrency=null; renderConcurrency(); renderLimitRow(); return; }
    fetch('/sandbar-executor-panel/api/concurrency?project='+encodeURIComponent(state.project)).then(function(r){ return r.json(); }).then(function(j){
      state.conc = j; state.concDraft = null;
      state.concurrency = { ok:true, declared:j.declared !== false,
        limit:j.limit, unlimited:j.unlimited === true, path:j.decl || j.path,
        refusal:j.declared === false, reason:j.reason };
      renderConcurrency(); renderLimitRow();
    }).catch(function(){ state.conc = {ok:false, reason:'The concurrency endpoint could not be reached.'}; state.concurrency={ok:false}; renderConcurrency(); renderLimitRow(); });
  }
  function concDraftValue(){
    if(state.concDraft !== null) return state.concDraft;
    var c = state.conc;
    if(!c || c.ok !== true) return null;
    return c.unlimited === true ? CONC_LIMITS.unlimited : c.limit;
  }
  function renderConcurrency(){
    var c = state.conc;
    var chip = el('concChip'), box = el('concBox');
    // t261008-20 (host order): the block lists no tickets (the console's left column
    // already shows what is running) and shows no audit stamp. The refusal / error
    // copy that used to land in the removed #concList now lands in #concCounts
    // (t261009-37: the counts + refusal copy moved into the block header row).
    if(!state.project){
      chip.style.display='none'; box.style.display='none';
      el('concCounts').textContent=''; el('concLimit').textContent='–';
      return;
    }
    if(!c || c.ok !== true){
      chip.style.display='none'; box.style.display='none';
      el('concCounts').textContent = c && c.reason ? c.reason : 'The concurrency state is not known yet.';
      return;
    }
    if(c.declared === false){
      // Absent/malformed declaration: the engine refuses to run without a usable
      // declaration — show the named refusal, never a guessed default number.
      chip.style.display='none'; box.style.display='none';
      el('concCounts').textContent = c.reason || c.note || 'No concurrency limit is declared.';
      return;
    }
    box.style.display='';
    var kind = concChipState(c.limit, c.unlimited === true, c.at_work);
    // The over state carries its amber marking in a class name (conc-amber) so a
    // capture face can read it from the attribute instead of guessing colors.
    chip.style.display=''; chip.className='pill conc-'+kind+(kind==='over'?' conc-amber':''); chip.textContent=concChipLabel(kind);
    el('concCounts').textContent = c.at_work + ' at work · ' + c.waiting + ' waiting';
    var v = concDraftValue();
    el('concLimit').textContent = v === CONC_LIMITS.unlimited ? 'Unlimited' : String(v);
  }
  el('concMinus').onclick = function(){ var v=concDraftValue(); if(v===null) return; state.concDraft=limitStep(v,-1); renderConcurrency(); };
  el('concPlus').onclick  = function(){ var v=concDraftValue(); if(v===null) return; state.concDraft=limitStep(v,1); renderConcurrency(); };
  el('concSave').onclick = function(){
    if(!state.project) return;
    var v = concDraftValue();
    if(v === null){ el('concMsg').textContent='The current limit is not known yet.'; return; }
    postJson('/sandbar-executor-panel/api/concurrency?project='+encodeURIComponent(state.project), { limit: v })
      .then(function(j){
        if(j.saved !== true){ el('concMsg').innerHTML = '<span class="bad">REJECTED: '+esc(j.reason || j.error || '?')+'</span>'; }
        else { el('concMsg').textContent='The limit is saved.'; state.concDraft = null; }
        loadConcurrency();
      })
      .catch(function(e){ el('concMsg').innerHTML = saveFailHtml(e); });
  };

  // ---- Alerts / Ledger (STE copy) ----
  function renderAlertsLedger(){
    var st = state.status;
    if(!st){
      el('alertBanner').innerHTML = bannerHtml(pickDegraded({reachable: state.reachable===true}).label, true);
      el('alertList').innerHTML=''; el('alertHead').textContent='0';
      el('ledgerHealth').textContent=''; el('ledgerFile').textContent=''; el('ledgerEvents').innerHTML='';
      el('wakeCount').textContent='0';
      return;
    }
    // t261009-57: coalesce FIRST (runs of the same condition key, consecutive only),
    // THEN cap to alerts.display_max — the ONE host number, delivered on the same
    // status payload as the rows (st.alerts_display_max), so the two can never
    // disagree. The ledger keeps every row; this is presentation only.
    var co = coalesceAlerts(st.alerts||[]);
    var cap = capCoalesced(co, st.alerts_display_max);
    var rows = cap.rows;
    // The header names both numbers when the knob truncated, so the host can see a
    // deeper window exists and turn alerts.display_max.
    el('alertHead').textContent = cap.capped ? (rows.length+' of '+cap.total+' conditions') : String(rows.length);
    var nowMs = Date.now(); // captured once per render; the poll loop re-renders
    var html = '';
    for(var i=0;i<rows.length;i++){
      var a2 = rows[i];
      var cls = a2.level==='redline' ? 'red' : (a2.night_muted ? 'blue' : 'amber');
      var levelWord = a2.level==='redline' ? 'redline' : (a2.level==='warn' ? 'warn' : (a2.level==='info' ? 'info' : ''));
      var timeHtml = function(at, label){
        // <time datetime> for semantics, the absolute moment on hover (title);
        // relative first — the two are never shown at once. Malformed at = dash.
        var rel = relTimeAgo(at, nowMs);
        if(rel==='—') return '<span class="t">'+esc(rel)+'</span>';
        return '<time datetime="'+esc(new Date(at).toISOString())+'" title="'+esc(localDateTime(at))+'">'+esc((label||'')+rel)+'</time>';
      };
      var times = a2.count>1
        ? timeHtml(a2.first_at, (a2.at_window_edge?'first ≥ ':'first ')) + ' · last ' + timeHtml(a2.last_at, '')
        : timeHtml(a2.last_at, '');
      // Full text on hover plus a wrapping title — the ellipsis cut is gone. A
      // malformed at adds no absolute (nothing is fabricated from NaN).
      var tip = a2.title
        + (isNaN(a2.last_at) ? '' : ' · ' + localDateTime(a2.last_at))
        + (a2.at_window_edge ? ' (first seen may predate the status window)' : '');
      html += '<div class="row" title="'+esc(tip)+'"><div class="head" style="cursor:default"><span class="dot '+cls+'"></span>'
        + '<span class="txt altxt">'+esc(a2.title)+(a2.count>1?' <span class="meta">x'+a2.count+'</span>':'')+'</span>'
        + '<span class="meta">'+esc(levelWord)+(levelWord?' · ':'')+times+(a2.night_muted?' · night-muted':'')+'</span></div></div>';
    }
    if(rows.length===0) html = '<div class="empty">'+esc(emptyCopyOf('alerts'))+'</div>';
    el('alertList').innerHTML = html;
    el('alertBanner').innerHTML = rows.some(function(x){return x.night_muted;}) ? bannerHtml('Rows marked night-muted were silenced by the night policy. Redline alerts still play a sound.') : '';
    var lg = st.ledger||{};
    // t261009-37: the health facts are ONE line (rows / duplicates / bad rows /
    // gaps) in the Events block body; the ledger path lives in the block header
    // (monospace, ellipsised) and its full value travels on the title attribute.
    el('ledgerHealth').innerHTML =
      esc(lg.rows_seen!=null?lg.rows_seen:'—') + ' rows · '
      + esc(fmtProportion(lg.dupes_skipped, lg.rows_seen)) + ' duplicates · '
      + esc(lg.malformed_rows!=null?lg.malformed_rows:'—') + ' bad rows · '
      + esc(lg.gaps_seen!=null?lg.gaps_seen:'—') + ' gaps';
    el('ledgerFile').textContent = lg.path || 'The ledger path is not known.';
    el('ledgerFile').title = lg.path || '';
    var ev = '';
    // t261008-20 (host order): the wakes face moved from the Ledger tab into the
    // Overview source-event dialog and no longer takes the first three rows — render
    // every row the status API returned (cap='all', see LIST_CONTRACTS). The real
    // ceiling is the watchdog status payload's own 20-row window; the dialog copy
    // names that number instead of truncating silently. The newest-first sort is
    // still the t261004-14 fix. Missing st / missing st.wakes / empty wakes all fall
    // through to the declared empty copy — no fabricated rows.
    var wakes = newestFirst(st.wakes||[]);
    el('wakeCount').textContent = String(wakes.length);
    for(var k=0;k<wakes.length;k++){
      var w2 = wakes[k];
      // t261003-13 rework (re-exposed by the t261008-20 uncap): the renderer never
      // dereferences the row unchecked — a non-object row (null / string / number)
      // renders the honest face (dash time, unknown sentence) instead of aborting
      // the whole ledger face. wakeRowSentence and localDateTime are already
      // null-safe pure helpers; the guard here only keeps the field reads safe.
      var bad = !w2 || typeof w2 !== 'object' || Array.isArray(w2);
      var when = bad ? '—' : localDateTime(w2.at);
      var tk = bad ? '' : (w2.ticket||w2.id||'');
      ev += '<div class="act"><span class="t">'+esc(when)+'</span><span class="pill open">WAKE</span>'
        + '<span class="tk">'+esc(tk)+'</span><span class="say">'+esc(wakeRowSentence(w2))+'</span></div>';
    }
    if(!ev) ev = '<div class="act" style="border:0"><span class="say muted">'+esc(emptyCopyOf('ledger_last_wakes'))+'</span></div>';
    el('ledgerEvents').innerHTML = ev;
  }

  // t261009-37 (host order 261009-(2)): the source-event dialog is retired with its
  // pattern — the entry button, the overlay, the Esc/focus machinery and the
  // keydown listener are all gone. The face lives inline in the Events block.

  // ---- t261005-10 (UI-2): Overview limit row (render only; the loader is CL-2's
  // loadConcurrency above — one fetch feeds both faces, no duplicate loader). ----
  function renderLimitRow(){
    var c = state.concurrency;
    var e = el('limitRow');
    if(!state.project || !c){ e.textContent=''; return; }
    if(c.ok!==true){ e.textContent='Running limit: unknown — the concurrency face could not be reached.'; return; }
    if(c.refusal===true){ e.textContent='The concurrency face refused: '+c.reason; return; }
    if(c.declared===true){
      e.textContent='Running limit: '+(c.unlimited?'unlimited':c.limit)+' — declared in '+c.path+'.';
    } else if(c.reason){
      e.textContent='No usable concurrency limit: '+c.reason+' The engine default applies. The write control lands with CL-2.';
    } else {
      e.textContent='No concurrency limit declared — the engine default applies. The write control lands with CL-2.';
    }
  }

  // ---- t261005-10 (UI-2): Epics tab (read-only face) ----
  // ---- t261019-12: Epics tab — the host-approved mock (out/mocks/epics-tab-261019.html).
  // One list, no separate detail page: a row IS the epic. Collapsed = code + retired
  // badge + one-line summary + ticket count + last activity. Click expands in place to
  // the full summary, the started date, three counts (in flight / waiting on you /
  // landed today), the document link, and the newest five tickets (title on every
  // row) plus a 'Show N more' fold. The badge and the summary are the ONLY document
  // fields on the surface (host order: no Chinese in the UI — the summary is English
  // front-matter by design; status/progress prose is never rendered).
  // Ticket source = the per-epic /epics/<code>/tickets endpoint (the endpoint does
  // the epic filtering; the page never guesses membership).
  function epicCodeOf(e){ return (e && (e.code || e.id)) ? String(e.code || e.id) : ''; }
  function loadEpics(){
    if(!state.project){ state.epics=null; state.epicTickets={}; renderEpics(); return; }
    fetch('/sandbar-workbench/api/epics?project='+encodeURIComponent(state.project))
      .then(function(r){ return r.json(); })
      .then(function(j){
        state.epics=(j && j.ok===true && j.result && Array.isArray(j.result.epics)) ? j.result.epics : null;
        state.epicsReason=(j && j.ok===false && j.error) ? String(j.error) : '';
        state.epicTickets={};
        renderEpics();
        if(!state.epics) return;
        // One fetch per epic (small N = the docs/epics/ entry count); one failed
        // fetch degrades its own group row by name and never takes the face down.
        state.epics.forEach(function(e){
          var code=epicCodeOf(e);
          if(!code) return;
          fetch('/sandbar-workbench/api/epics/'+encodeURIComponent(code)
            +'/tickets?project='+encodeURIComponent(state.project))
            .then(function(r){ return r.json(); })
            .then(function(tj){
              var res=tj && tj.ok===true ? tj.result : null;
              state.epicTickets[code]={ rows:(res && Array.isArray(res.tickets))?res.tickets:[],
                degraded:!(res && Array.isArray(res.tickets)),
                reason:(res && res.reason)?String(res.reason):((tj && tj.error)?String(tj.error):'') };
              renderEpics();
            })
            .catch(function(){
              state.epicTickets[code]={ rows:[], degraded:true, reason:'the ticket source could not be reached' };
              renderEpics();
            });
        });
      })
      .catch(function(){ state.epics=null; state.epicTickets={}; renderEpics(); });
  }
  // epic_tickets contract order: newest first by updated_ts; missing/malformed
  // sorts last; equal values keep the payload order (stable).
  function byUpdatedDesc(a,b){
    var ta=typeof a.updated_ts==='number'?a.updated_ts:-1, tb=typeof b.updated_ts==='number'?b.updated_ts:-1;
    return tb-ta;
  }
  function epicTicketRows(code){
    var f=state.epicTickets[code];
    if(!f || !f.rows) return [];
    var rows=f.rows.slice(); // LIST-CAP-OK: copy for sort, not a list cap
    rows.sort(byUpdatedDesc);
    return rows;
  }
  // Newest ticket activity of an epic = the max updated_ts across its rows; an epic
  // with no readable rows has no activity and sorts last (stable within ties).
  function epicLastActivity(code){
    var rows=epicTicketRows(code), m=-1;
    for(var i=0;i<rows.length;i++){ if(typeof rows[i].updated_ts==='number' && rows[i].updated_ts>m) m=rows[i].updated_ts; }
    return m;
  }
  function relTime(ts, now){
    if(typeof ts!=='number' || ts<=0) return 'no activity';
    var s=Math.max(0, Math.floor((now-ts)/1000));
    if(s<60) return 'just now';
    var m=Math.floor(s/60); if(m<60) return m+'m ago';
    var h=Math.floor(m/60); if(h<24) return h+'h ago';
    return Math.floor(h/24)+'d ago';
  }
  function epicCounts(rows, now){
    var inFlight=0, waiting=0, landedToday=0;
    for(var i=0;i<rows.length;i++){
      var t=rows[i];
      if(t.stage_state==='awaiting-human') waiting++;
      else if(t.stage_state==='running') inFlight++;
      if(t.status==='closed' && typeof t.updated_ts==='number' && (now-t.updated_ts)<=24*3600*1000) landedToday++;
    }
    return { inFlight:inFlight, waiting:waiting, landedToday:landedToday };
  }
  function epicBadge(e){
    // retired is the ONLY state; a defective registry row (unreadable front-matter)
    // fails closed as retired too. Draft = retired:false = online.
    return (e && e.retired===false && !e.defect)
      ? '<span class="chip" style="border-color:#9ec9a8;color:#1a7f37;background:#f0fff4">online</span>'
      : '<span class="chip" style="border-color:#eac54f;color:#9a6700;background:#fff8c5">retired</span>';
  }
  // t261021-13: the epic document opens in the console's own Docs reader, never a
  // raw api/ JSON tab. The control carries data-epicdoc only — no href, no
  // target — so no anchor on this page can navigate straight at an api/ route
  // (page-wide sweep rule, enforced by integration/t261021-13).
  function epicDocLink(code){
    return '<a class="btn" style="text-decoration:none;cursor:pointer" role="button" tabindex="0" '
      +'data-epicdoc="'+esc(code)+'">Open docs/epics/'+esc(code)+'.md</a>';
  }
  // t261021-13: reuse the Docs tab reader path — set the docs scope and the
  // document selection first, then select the tab so its lazy loader fetches the
  // tree; renderDocs() renders the reader because state.docSel is already set.
  // If the tree answers empty (the file vanished), renderDocBody() still renders
  // the named error banner — never an empty box.
  function openEpicDoc(code){
    state.docsScope='docs'; state.docs=null; state.docSel='epics/'+code+'.md';
    var radio=el('t-docs');
    if(radio) radio.checked=true;
    showTab('t-docs');
  }
  function renderEpics(){
    var list=el('epicsList'), det=el('epicDetail');
    det.innerHTML='';
    if(!state.project){ list.innerHTML=''; el('epicsBanner').innerHTML=''; return; }
    if(!state.epics){
      el('epicsBanner').innerHTML=bannerHtml(state.epicsReason
        ? 'The epic list could not be read. Reason: '+state.epicsReason
        : 'The epic list could not be reached (the workbench plugin may not be loaded).', true);
      list.innerHTML=''; return;
    }
    el('epicsBanner').innerHTML='';
    if(state.epics.length===0){ list.innerHTML='<div class="empty">'+esc(emptyCopyOf('epics_list'))+'</div>'; return; }
    var now=Date.now();
    // Merged list, newest activity first (the mock's "Sort: last activity ↓");
    // epics without readable ticket activity keep the payload order at the bottom.
    var order=state.epics.slice().sort(function(a,b){
      return epicLastActivity(epicCodeOf(b))-epicLastActivity(epicCodeOf(a));
    });
    var html='<div class="line" style="border-bottom:0"><span class="meta">'+order.length+' epics · newest activity first</span></div>';
    for(var i=0;i<order.length;i++){
      var e=order[i], code=epicCodeOf(e);
      if(!code) continue;
      var f=state.epicTickets[code];
      var rows=epicTicketRows(code);
      var open = state.epicOpen===code;
      var counts=epicCounts(rows, now);
      var last=epicLastActivity(code);
      // t261021-12: the card is a container — .epicCard carries the box style;
      // .sect (uppercase one-line heading) must never wrap the whole card.
      html+='<div class="epicCard" style="'+(open?'box-shadow:0 1px 3px rgba(31,35,40,.06)':'')+'">'
        +'<div class="eh" data-epic-head="'+esc(code)+'" role="button" tabindex="0" style="display:flex;gap:8px;align-items:center;padding:8px 11px;cursor:pointer">'
        +'<span class="muted">'+(open?'▾':'▸')+'</span><b>'+esc(code)+'</b> '+epicBadge(e)
        +'<span style="margin-left:auto;display:flex;gap:8px;align-items:center">'
        +'<span class="meta">'+rows.length+' ticket(s)</span>'
        +'<span class="meta">'+esc(relTime(last, now))+'</span></span></div>';
      // The summary — the only prose from the document that reaches the surface
      // (English front-matter; one clipped line when collapsed).
      var sum=typeof e.summary==='string' ? e.summary : (e.defect ? 'Defective registry entry: '+e.defect : '');
      html+='<div class="sum" style="padding:0 11px 9px 30px;font-size:12px;color:var(--muted);line-height:1.45;'
        +(open?'':'white-space:nowrap;overflow:hidden;text-overflow:ellipsis')+'">'+esc(sum)+'</div>';
      if(open){
        html+='<div style="padding:2px 11px 10px 30px;display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--faint)">'
          +'<span>started <b>'+esc(e.started||'—')+'</b></span>'
          +'<span>in flight <b>'+counts.inFlight+'</b></span>'
          +'<span>waiting on you <b>'+counts.waiting+'</b></span>'
          +'<span>landed today <b>'+counts.landedToday+'</b></span>'
          +epicDocLink(code)+'</div>';
        if(!f){
          html+='<div class="line"><span class="say muted">Loading tickets…</span></div>';
        } else if(f.degraded){
          html+='<div class="line"><span class="say muted">The ticket source could not be read. Reason: '+esc(f.reason||'?')+'</span></div>';
        } else if(rows.length===0){
          html+='<div class="line"><span class="say muted">'+esc(emptyCopyOf('epic_tickets'))+'</span></div>';
        } else {
          var shown=state.epicShowAll[code] ? rows.length : Math.min(5, rows.length); // LIST-CAP-OK: the mock's newest-five fold, not a data cap — 'Show N more' reveals the rest
          for(var k=0;k<shown;k++){
            var t=rows[k];
            html+='<div class="line mrow" data-ticket="'+esc(t.id)+'" data-epic="'+esc(code)+'" role="button" tabindex="0">'
              +'<div class="lab"><b>'+esc(t.id)+'</b> '+esc(t.title||'')
              +'<small>'+esc(t.stage||'')+' · '+esc(t.stage_state||'')+(t.status?' · '+esc(t.status):'')+'</small></div>'
              +'<span class="meta">Open in the console</span></div>';
          }
          if(rows.length>shown){
            html+='<div class="line" data-epic-more="'+esc(code)+'" role="button" tabindex="0" '
              +'style="cursor:pointer;color:var(--blue)">Show '+(rows.length-shown)+' more tickets →</div>';
          }
        }
      }
      html+='</div>';
    }
    list.innerHTML=html;
    Array.prototype.forEach.call(list.querySelectorAll('[data-epic-head]'), function(n){
      var toggle=function(){ state.epicOpen = state.epicOpen===n.dataset.epicHead ? '' : String(n.dataset.epicHead); renderEpics(); };
      n.onclick=toggle;
      n.onkeydown=function(ev){ if(ev.key==='Enter'||ev.key===' '){ ev.preventDefault(); toggle(); } };
    });
    Array.prototype.forEach.call(list.querySelectorAll('[data-epic-more]'), function(n){
      var expand=function(){ state.epicShowAll[n.dataset.epicMore]=true; renderEpics(); };
      n.onclick=expand;
      n.onkeydown=function(ev){ if(ev.key==='Enter'||ev.key===' '){ ev.preventDefault(); expand(); } };
    });
    Array.prototype.forEach.call(list.querySelectorAll('[data-ticket]'), function(n){
      var open=function(){ openTicketInHost(n.dataset.ticket, n.dataset.epic); };
      n.onclick=open;
      n.onkeydown=function(ev){ if(ev.key==='Enter'||ev.key===' '){ ev.preventDefault(); open(); } };
    });
    Array.prototype.forEach.call(list.querySelectorAll('[data-epicdoc]'), function(n){
      var openDoc=function(){ openEpicDoc(String(n.dataset.epicdoc||'')); };
      n.onclick=openDoc;
      n.onkeydown=function(ev){ if(ev.key==='Enter'||ev.key===' '){ ev.preventDefault(); openDoc(); } };
    });
  }
  // t261024-21: the stale no-epicCode twin of openTicketInHost (same name at
  // closure top level) is deleted — hoisting made the epicCode-bearing version
  // below the only executing body, so this is dead-code removal.
  // Ticket row -> the host console opens the existing ticket overlay (UI-3; the
  // overlay machinery lives in the host since t261005-04). Standalone (no parent
  // page) = a no-op — the overlay is not this page's to build. The tab also flips
  // to that epic's SOURCE detail: design §7.8's epic detail and the overlay
  // coexist without stacking (the overlay is the host's face).
  function openTicketInHost(id, epicCode){
    if(!id) return;
    if(epicCode){ state.epicOpen=String(epicCode); renderEpics(); }
    if(window.parent===window) return;
    window.parent.postMessage({ type:'sandbar-executor-panel:open-ticket', ticketId:String(id) }, window.location.origin);
  }

  // ---- t261021-07: Metrics tab v2 (the approved mock) ----
  // Tab-local state (never on state.* — the poll loop does not touch it).
  var MT = {
    vm: null, vmError: '', window: '30d', allProjects: false,
    selected: [], drill: null,               // where-the-time-goes
    cert: null,                              // certification summary
    epicSort: 'activity', epicPicked: [],    // epics
    throughput: null, tokens: null,          // chart specs (null = named empty)
  }
  // The chart bridge: the option factories above produce plain option objects;
  // the vendored echarts build owns init/dispose. It loads LAZILY on the first
  // Metrics-tab open (arbitrate round 11, defect B: a page-load module import
  // taxed every PANEL_HTML consumer — harnesses without the vendor route got a
  // deterministic module MIME/404 error and their zero-error legs went red;
  // lazy load = only Metrics-visiting faces need the route). Every failure
  // path (route down, MIME refused, JS error, 4s no-report timeout) flushes
  // the queued charts to the named 'charts could not load' empty state —
  // never a silent blank.
  var MTC = { lib: null, pending: [], failed: false, timer: null, loading: false }
  function mtEnsureChartLib() {
    if (MTC.lib || MTC.failed || MTC.loading) return
    MTC.loading = true
    // D1 fix (gate round 2) still applies: the route is interpolated RAW.
    import('${PANEL_ROUTE}/vendor/echarts.mjs').then(function (mod) {
      var echarts = (mod && mod.default && typeof mod.default.init === 'function') ? mod.default : mod
      if (!echarts || typeof echarts.init !== 'function') throw new Error('echarts build has no init')
      var insts = new WeakMap()
      if (typeof window.__metricsChartLibReady === 'function') {
        window.__metricsChartLibReady({
          draw: function (mount, option) {
            var prev = insts.get(mount)
            if (prev) { try { prev.dispose() } catch (e) { /* dispose is idempotent-tolerant */ } insts.delete(mount) }
            var inst = echarts.init(mount, null, { renderer: 'canvas' })
            insts.set(mount, inst)
            inst.setOption(option)
          },
          dispose: function (mount) {
            var inst = insts.get(mount)
            if (inst) { try { inst.dispose() } catch (e) { /* same */ } insts.delete(mount) }
          },
        })
      }
    }).catch(function () {
      if (typeof window.__metricsChartLibFail === 'function') window.__metricsChartLibFail()
    })
  }
  function mtDraw(id, option) {
    var mount = el(id)
    if (!mount) return
    if (MTC.lib) { MTC.lib.draw(mount, option); return }
    mtEnsureChartLib()
    MTC.pending.push([mount, option])
    if (MTC.failed) mtFlushFailed()
  }
  function mtFlushFailed() {
    MTC.failed = true
    var q = MTC.pending; MTC.pending = []
    q.forEach(function (p) {
      p[0].innerHTML = '<div class="empty">' + esc('charts could not load') + '</div>'
    })
  }
  window.__metricsChartLibReady = function (lib) {
    if (MTC.timer) { clearTimeout(MTC.timer); MTC.timer = null }
    MTC.lib = lib
    var q = MTC.pending; MTC.pending = []
    q.forEach(function (p) { lib.draw(p[0], p[1]) })
  }
  window.__metricsChartLibFail = function () {
    if (MTC.timer) { clearTimeout(MTC.timer); MTC.timer = null }
    mtFlushFailed()
  }
  // The load-failure face must not wait forever: if the module script never
  // reports (route down, MIME refused, JS error), flush after 4s.
  MTC.timer = setTimeout(function () { if (!MTC.lib) mtFlushFailed() }, 4000)

  function mtProjectParam() { return MT.allProjects ? 'all' : state.project }
  function metricsBaseQuery() {
    return 'window=' + MT.window + '&epic=all&project=' + encodeURIComponent(mtProjectParam()) + '&template=dev-lane'
  }
  function loadMetrics() {
    mtWireHeader()
    if (!state.project) { MT.vm = null; renderMetrics(); return }
    var q = metricsBaseQuery() + '&view=time&mode=full'
    fetch('/sandbar-workbench/api/wf/metrics?' + q).then(function (r) { return r.json() }).then(function (j) {
      // A render/embed throw must never dress up as 'could not be reached'
      // (the arbitrate misreport finding): the two failure stages are named
      // apart — this catch names the RENDER stage, the outer one the FETCH.
      try {
        MT.vm = metricsV2Of(j)
        MT.vmError = (MT.vm && MT.vm.ok === false) ? String(MT.vm.reason || '') : ''
        renderMetrics()
        loadMetricsSide()
      } catch (e) {
        MT.vm = null
        MT.vmError = 'metrics render failed: ' + (e && e.message ? e.message : String(e))
        renderMetrics()
      }
    }).catch(function () { MT.vm = null; MT.vmError = ''; renderMetrics(); loadMetricsSide() })
  }
  // The three side reads (throughput / tokens / certification) fail one per
  // face: each catch nulls only its own spec, never the whole tab.
  function loadMetricsSide() {
    var base = '/sandbar-workbench/api/wf/metrics?' + metricsBaseQuery() + '&mode=full&view='
    fetch(base + 'health').then(function (r) { return r.json() }).then(function (j) {
      try { MT.throughput = throughputSpecOf(j); renderThroughput() }
      catch (e) { MT.throughput = null; renderThroughput() }
    }).catch(function () { MT.throughput = null; renderThroughput() })
    fetch(base + 'token').then(function (r) { return r.json() }).then(function (j) {
      try { MT.tokens = tokensStackOf(j); renderTokens() }
      catch (e) { MT.tokens = null; renderTokens() }
    }).catch(function () { MT.tokens = null; renderTokens() })
    fetch('/sandbar-executor-panel/api/certification?project=' + encodeURIComponent(state.project))
      .then(function (r) { return r.json() }).then(function (j) {
        try { MT.cert = certSummaryOf(j); renderMetricsCert() }
        catch (e) { MT.cert = null; renderMetricsCert() }
      }).catch(function () {
        // The named degrade path: the renderer only writes #mtCert's innerHTML,
        // so a throw here would be an unhandled rejection — contained, and the
        // face keeps whatever the last good render left (never a blank pane).
        MT.cert = null
        try { renderMetricsCert() } catch (e) { /* contained degrade */ }
      })
  }
  // Header wiring runs once per load: the project select is pre-filled with
  // the executor tab's project (the deep link the panel was opened from) and
  // gains the widening 'all projects' option; the window select keeps its
  // three windows. A change re-fetches the tab.
  var mtHeaderWired = false
  function mtWireHeader() {
    if (mtHeaderWired) return
    mtHeaderWired = true
    var p = el('metricsProject')
    if (p) {
      p.innerHTML = ''
      var here = document.createElement('option')
      here.value = state.project || ''
      here.textContent = state.project || '(no project)'
      here.selected = true
      var all = document.createElement('option')
      all.value = 'all'
      all.textContent = METRICS_COPIES.allProjects
      p.appendChild(here); p.appendChild(all)
      p.onchange = function () {
        MT.allProjects = (p.value === 'all')
        MT.selected = []; MT.drill = null
        loadMetrics()
      }
    }
    var w = el('metricsWindow')
    if (w) w.onchange = function () { MT.window = w.value || '30d'; loadMetrics() }
    var wp = el('mtWfPick')
    if (wp) wp.onchange = function () {
      var name = (wp.value || '').trim()
      wp.value = ''
      if (!name || MT.selected.indexOf(name) >= 0) return
      MT.selected.push(name); MT.drill = null
      renderMetrics()
    }
    var es = el('mtEpicSort')
    if (es) es.onchange = function () { MT.epicSort = es.value; renderMetrics() }
    var ep = el('mtEpicPick')
    if (ep) ep.onchange = function () {
      var name = (ep.value || '').trim()
      ep.value = ''
      if (!name || MT.epicPicked.indexOf(name) >= 0) return
      MT.epicPicked.push(name); renderMetrics()
    }
  }
  function mtEmpty(id, word) { var e = el(id); if (e) e.innerHTML = '<div class="empty">' + esc(word) + '</div>' }
  function renderMetrics() {
    var banner = el('metricsBanner')
    if (!state.project) { if (banner) banner.innerHTML = ''; mtEmpty('metricsKpis', 'no project selected'); return }
    if (!MT.vm || MT.vm.ok === false) {
      if (banner) banner.innerHTML = bannerHtml(MT.vmError
        ? 'Metrics could not be read. Reason: ' + MT.vmError
        : 'Metrics could not be reached (the workbench plugin may not be loaded).', true)
      // review_plan gen1 item 2: the KPI row's degraded empty state renders
      // through the DECLARED contract copy (emptyCopyOf('metrics_kpis')) so the
      // original page-contract assertion holds un-weakened; the v2 sections'
      // named faces stay on METRICS_COPIES.
      mtEmpty('metricsKpis', emptyCopyOf('metrics_kpis'))
      mtEmpty('mtWfRows', METRICS_COPIES.noData); mtEmpty('mtEpicCards', METRICS_COPIES.noData)
      mtEmpty('mtRoles', METRICS_COPIES.noData); mtEmpty('mtSessions', METRICS_COPIES.noData)
      renderMetricsCert(); renderThroughput(); renderTokens()
      return
    }
    if (banner) banner.innerHTML = ''
    var vm = MT.vm
    // KPI row — six tiles (mock order), values may be the honest dash.
    var kpis = kpiTilesOf(vm)
    el('metricsKpis').innerHTML = kpis.map(function (t) {
      return '<div class="cell" style="display:flex;flex-direction:column;gap:4px">'
        + '<span class="meta" style="letter-spacing:.04em">' + esc(t.title) + '</span>'
        + '<b style="font-size:22px">' + esc(t.value) + '</b>'
        + '<span class="meta">' + esc(t.sub) + '</span></div>'
    }).join('')
    renderTimeCard()
    renderMetricsEpics()
    // Tokens by role + Project sessions (real rows where the payload has them).
    el('mtRoles').innerHTML = roleRowsOf(vm).map(function (r) {
      return '<div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0">'
        + '<span>' + esc(r.name) + '</span><b class="mono">' + esc(r.value) + '</b></div>'
        + (r.sub && r.sub !== METRICS_COPIES.dash ? '<div class="meta">' + esc(r.sub) + '</div>' : '')
    }).join('')
    el('mtSessions').innerHTML = sessionRowsOf(vm).map(function (r) {
      return '<div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0">'
        + '<span>' + esc(r.name) + '</span><b class="mono">' + esc(r.value) + '</b></div>'
        + (r.sub && r.sub !== METRICS_COPIES.dash ? '<div class="meta">' + esc(r.sub) + '</div>' : '')
    }).join('')
    renderMetricsCert(); renderThroughput(); renderTokens()
  }
  // Where-the-time-goes: chips + rows inside the fixed-height card; clicking a
  // row opens that workflow's stages IN THE SAME CARD (the card never grows —
  // the drill replaces the row list, a Back chip returns).
  function renderTimeCard() {
    var chips = el('mtChips')
    if (!chips) return
    var vm = MT.vm
    var names = (vm && vm.workflows ? vm.workflows : []).map(function (w) { return String(w.name) })
    var list = el('mtWfList')
    if (list) list.innerHTML = names.map(function (n) { return '<option value="' + esc(n) + '"></option>' }).join('')
    var chipHtml = MT.selected.map(function (n) {
      return '<span data-mtchip="' + esc(n) + '" style="border:1px solid #0f766e;color:#0f766e;border-radius:13px;padding:2px 10px;cursor:pointer;font-size:12px">'
        + esc(n) + ' <b>×</b></span>'
    }).join('')
    var back = MT.drill
      ? '<span data-mtback="1" style="border:1px solid var(--line);border-radius:13px;padding:2px 10px;cursor:pointer;font-size:12px">← ' + esc(String(MT.drill)) + '</span>'
      : ''
    chips.innerHTML = chipHtml + back
    Array.prototype.forEach.call(chips.querySelectorAll('[data-mtchip]'), function (b) {
      b.onclick = function () {
        MT.selected = MT.selected.filter(function (x) { return x !== b.getAttribute('data-mtchip') })
        MT.drill = null; renderMetrics()
      }
    })
    var backBtn = chips.querySelector('[data-mtback]')
    if (backBtn) backBtn.onclick = function () { MT.drill = null; renderMetrics() }
    var rows = el('mtWfRows')
    if (!rows) return
    if (!vm) { mtEmpty('mtWfRows', METRICS_COPIES.noData); return }
    if (MT.drill) {
      var stages = stageRowsOf(vm, String(MT.drill))
      rows.innerHTML = stages.length === 0
        ? '<div class="empty">' + esc(METRICS_COPIES.noData) + '</div>'
        : stages.map(function (s) { return mtRowHtml(s, String(s.stage)) }).join('')
      Array.prototype.forEach.call(rows.querySelectorAll('[data-mtrow]'), function (b) { b.onclick = null })
      return
    }
    var wf = workflowRowsOf(vm, MT.selected)
    rows.innerHTML = wf.length === 0
      ? '<div class="empty">' + esc(METRICS_COPIES.noData) + '</div>'
      : wf.map(function (r) { return mtRowHtml(r, String(r.name)) }).join('')
    Array.prototype.forEach.call(rows.querySelectorAll('[data-mtrow]'), function (b) {
      b.onclick = function () { MT.drill = b.getAttribute('data-mtrow'); renderMetrics() }
    })
  }
  function mtRowHtml(r, drillKey) {
    return '<div data-mtrow="' + esc(drillKey) + '" style="padding:6px 0;border-bottom:1px solid var(--line);cursor:pointer">'
      + '<div style="display:flex;gap:10px;align-items:baseline">'
      + '<b class="mono" style="min-width:110px">' + esc(String(r.name || r.stage || '')) + '</b>'
      + '<span style="flex:1;height:14px;background:var(--panel2);border-radius:3px;overflow:hidden">'
      + '<span style="display:block;height:100%;width:' + Number(r.bar || 0) + '%;background:#63b3ac"></span></span>'
      + '<span class="mono meta" style="min-width:64px;text-align:right">' + esc(String(r.elapsed)) + '</span>'
      + '<span class="mono" style="min-width:44px;text-align:right">' + esc(String(r.rounds)) + '</span></div>'
      + '<div class="meta">' + esc(String(r.sub)) + '</div></div>'
  }
  // t261024-21: renamed from renderEpics — a same-name twin at closure top level
  // shadowed the Epics-tab renderer and left that tab blank (see the guard test
  // t261024-21-no-duplicate-top-level-functions.test.mjs).
  function renderMetricsEpics() {
    var vm = MT.vm
    var list = el('mtEpicList')
    if (list) {
      var names = (vm && vm.epics ? vm.epics : []).map(function (e) { return String(e.name) })
      list.innerHTML = names.map(function (n) { return '<option value="' + esc(n) + '"></option>' }).join('')
    }
    var chips = el('mtEpicChips')
    if (chips) {
      chips.innerHTML = MT.epicPicked.map(function (n) {
        return '<span data-mtepic="' + esc(n) + '" style="border:1px solid #0f766e;color:#0f766e;border-radius:11px;padding:1px 9px;cursor:pointer;font-size:11.5px">'
          + esc(n) + ' <b>×</b></span>'
      }).join('')
      Array.prototype.forEach.call(chips.querySelectorAll('[data-mtepic]'), function (b) {
        b.onclick = function () {
          MT.epicPicked = MT.epicPicked.filter(function (x) { return x !== b.getAttribute('data-mtepic') })
          renderMetrics()
        }
      })
    }
    var cards = el('mtEpicCards')
    if (!cards) return
    if (!vm) { mtEmpty('mtEpicCards', METRICS_COPIES.noData); return }
    var rows = epicCardsOf(vm, MT.epicSort, MT.epicPicked, Date.now())
    cards.innerHTML = rows.length === 0
      ? '<div class="empty">' + esc(METRICS_COPIES.noData) + '</div>'
      : rows.map(function (c) {
          return '<div class="cell" style="display:flex;flex-direction:column;gap:4px">'
            + '<b>' + esc(String(c.name)) + '</b>'
            + '<span class="meta">' + esc(String(c.activity)) + '</span>'
            + '<div><b style="font-size:20px">' + esc(String(c.tickets)) + '</b> <span class="meta">' + esc(METRICS_COPIES.ticketsWord) + '</span></div>'
            + '<div style="display:flex;justify-content:space-between"><span class="mono">' + esc(String(c.elapsed)) + '</span><span class="meta">' + esc(METRICS_COPIES.elapsedWord) + '</span></div>'
            + '<div style="display:flex;justify-content:space-between"><span class="mono">' + esc(String(c.tokens)) + '</span><span class="meta">' + esc(METRICS_COPIES.tokensWord) + '</span></div>'
            + '<span style="height:4px;background:var(--panel2);border-radius:2px;overflow:hidden;display:block">'
            + '<span style="display:block;height:100%;width:' + Number(c.bar || 0) + '%;background:#0f766e"></span></span></div>'
        }).join('')
  }
  function renderMetricsCert() {
    var e = el('mtCert')
    if (!e) return
    var c = MT.cert
    if (!c || c.ok === false) {
      e.innerHTML = '<div class="empty">' + esc(METRICS_COPIES.reasonNoCert) + '</div>'
      return
    }
    var strip = (c.strip || []).map(function (v) {
      var color = v === 'green' ? '#15803d' : (v === 'red' ? '#b91c1c' : '#c2700f')
      return '<span style="display:inline-block;width:18px;height:26px;border-radius:4px;background:' + color + ';opacity:.85"></span>'
    }).join('')
    e.innerHTML = '<div style="display:flex;gap:28px;align-items:baseline;flex-wrap:wrap;padding:4px 0">'
      + '<span><b style="font-size:28px;color:#15803d">' + esc(String(c.green ?? METRICS_COPIES.dash)) + '</b> <span class="meta">' + esc(METRICS_COPIES.greenWord) + '</span></span>'
      + '<span><b style="font-size:26px;color:#b91c1c">' + esc(String(c.red ?? METRICS_COPIES.dash)) + '</b> <span class="meta">' + esc(METRICS_COPIES.redWord) + '</span></span>'
      + '<span><b style="font-size:22px;color:#c2700f">' + esc(c.flaky == null ? METRICS_COPIES.dash : String(c.flaky)) + '</b> <span class="meta">'
      + esc(c.flaky == null ? METRICS_COPIES.reasonNoFlakyFace : METRICS_COPIES.flakyWord) + '</span></span></div>'
      + (strip ? '<div style="display:flex;gap:3px;flex-wrap:wrap;padding:4px 0">' + strip + '</div>' : '')
      + '<div style="padding:4px 0"><b>' + esc(METRICS_COPIES.timeToGreen) + ': P50 ' + esc(String(c.ttg)) + '</b></div>'
  }
  function renderThroughput() {
    var e = el('mtThroughput')
    if (!e) return
    if (!MT.throughput) { e.innerHTML = '<div class="empty">' + esc(METRICS_COPIES.noData) + '</div>'; return }
    e.innerHTML = ''
    mtDraw('mtThroughput', throughputOption(MT.throughput))
  }
  function renderTokens() {
    var e = el('mtTokens')
    if (!e) return
    if (!MT.tokens) {
      e.innerHTML = '<div class="empty">' + esc(METRICS_COPIES.reasonNoDailyTokens) + '</div>'
      return
    }
    e.innerHTML = ''
    mtDraw('mtTokens', tokensOption(MT.tokens))
  }

  // ---- t261005-10 (UI-2): Docs tab (read-only tree + markdown reader) ----
  function loadDocs(){
    if(!state.project){ state.docs=null; renderDocs(); return; }
    var scope=state.docsScope;
    var url='/sandbar-workbench/api/wf/docs/tree?scope='+scope+'&project='+encodeURIComponent(state.project);
    fetch(url).then(function(r){ return r.json(); }).then(function(j){
      state.docs=j;
      // t261008-19: remember the real page count per scope (malformed → null, shown
      // as '— pages'; never a fabricated count).
      state.docsCounts=state.docsCounts||{};
      state.docsCounts[scope]=countDocsTree(j);
      renderDocs();
    }).catch(function(){ state.docs=null; renderDocs(); });
  }
  function renderDocEntries(){
    var entries=el('docsEntries');
    var counts=state.docsCounts||{};
    entries.innerHTML=
      docEntryRow('docs','the library',counts.docs===undefined?null:counts.docs)
      +docEntryRow('notes','the ledger',counts.notes===undefined?null:counts.notes);
    Array.prototype.forEach.call(entries.querySelectorAll('[data-docopen]'), function(b){
      b.onclick=function(){
        // The mock is silent on the Open target; the chosen target is the existing
        // in-tab face (switch scope, reload the tree, keep the reader) — no new endpoint.
        if(state.docsScope!==b.dataset.docopen){ state.docsScope=b.dataset.docopen; state.docs=null; state.docSel=''; loadDocs(); }
      };
    });
  }
  function renderDocs(){
    var e=el('docsBanner'), bar=el('docsScopeBar'), tree=el('docsTree'), reader=el('docsReader');
    if(!state.project){ e.innerHTML=''; bar.innerHTML=''; el('docsEntries').innerHTML=''; tree.innerHTML=''; reader.innerHTML=''; return; }
    renderDocEntries();
    bar.innerHTML=['docs','notes'].map(function(s){
      return '<button class="backbtn" data-scope="'+s+'"'+(s===state.docsScope?' style="border-color:var(--blue);color:var(--blue)"':'')+'>'+s+'/</button>';
    }).join('');
    Array.prototype.forEach.call(bar.querySelectorAll('[data-scope]'), function(b){
      b.onclick=function(){ if(state.docsScope!==b.dataset.scope){ state.docsScope=b.dataset.scope; state.docs=null; state.docSel=''; loadDocs(); } };
    });
    // t261019-04: the workbench endpoint answers the {ok,result} envelope; reading
    // groups off the envelope made every project look empty ('The library is empty
    // for this scope.') while the payload actually carried the tree (measured:
    // /api/wf/docs/tree?scope=docs&project=sandbar -> result.groups x4). Accept
    // both shapes: the envelope (t261016-07 family) and a bare tree.
    var d=(state.docs && state.docs.result) ? state.docs.result : state.docs;
    if(!d){ e.innerHTML=bannerHtml('The doc tree could not be reached (the workbench plugin may not be loaded).', true); tree.innerHTML=''; reader.innerHTML=''; return; }
    e.innerHTML='';
    // t261021-13: an empty tree must not wipe an in-flight reader selection (an
    // epic document click can land here when the library answers empty) — the
    // reader renders the document body or its own named error instead.
    if(d.empty===true){ tree.innerHTML='<div class="empty">'+esc(d.reason||emptyCopyOf('docs_tree'))+'</div>'; if(state.docSel) renderDocBody(); else reader.innerHTML=''; return; }
    var groups=Array.isArray(d.groups)?d.groups:[];
    var html='';
    for(var i=0;i<groups.length;i++){
      var g=groups[i];
      var files=Array.isArray(g.files)?g.files:[];
      if(files.length===0) continue;
      html+='<div class="sect lead">'+esc(g.label||g.dir||'')+'</div><div class="grp">';
      for(var k2=0;k2<files.length;k2++){
        var f=files[k2];
        html+='<div class="line mrow" data-doc="'+esc(f.rel)+'"><div class="lab docfile">'+esc(f.rel)+'</div>'
          +'<span class="meta">'+esc(f.title||'')+'</span></div>';
      }
      html+='</div>';
    }
    if(Array.isArray(d.skipped)&&d.skipped.length>0){
      html+='<div class="file">'+esc(d.skipped.length)+' file(s) skipped (outside the readable whitelist).</div>';
    }
    tree.innerHTML=html||('<div class="empty">'+esc(emptyCopyOf('docs_tree'))+'</div>');
    Array.prototype.forEach.call(tree.querySelectorAll('[data-doc]'), function(n){
      n.onclick=function(){ openDoc(n.dataset.doc); };
    });
    if(state.docSel) renderDocBody();
    else reader.innerHTML='';
  }
  function openDoc(rel){
    state.docSel=rel; renderDocBody();
  }
  function renderDocBody(){
    var reader=el('docsReader');
    var rel=state.docSel;
    if(!rel){ reader.innerHTML=''; return; }
    reader.innerHTML='<div class="muted" style="font-size:11px">Loading '+esc(rel)+' …</div>';
    var url='/sandbar-workbench/api/wf/docs/doc?scope='+state.docsScope+'&project='+encodeURIComponent(state.project)
      +'&path='+encodeURIComponent(rel);
    fetch(url).then(function(r){ return r.json(); }).then(function(j){
      var body=j && (j.body!==undefined ? j.body : (j.result && j.result.body));
      if(typeof body!=='string'){
        reader.innerHTML='<div class="banner red">The document could not be read'+(j&&j.error?': '+esc(String(j.error)):'')+'</div>';
        return;
      }
      reader.innerHTML='<div class="sect">'+esc(rel)+'</div><div class="detail" style="max-height:none">'+renderMarkdown(body)+'</div>';
    }).catch(function(err){
      reader.innerHTML='<div class="banner red">The document could not be loaded: '+esc(String(err&&err.message||err))+'</div>';
    });
  }

  // ---- Grants tab ----
  function loadGrants(){
    if(!state.project){ state.grants=null; renderGrants(); return; }
    fetch('/sandbar-executor-panel/api/grants?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.grants = j; renderGrants(); renderOverviewStrip();
    }).catch(function(){ state.grants = {ok:false, error:'the grants endpoint could not be reached'}; renderGrants(); });
  }
  function declaredSessions(){
    var g = state.grants;
    if(g && g.session_readout && Array.isArray(g.session_readout.sessions)) return g.session_readout.sessions;
    var d = g && g.declaration;
    return d && Array.isArray(d.executor_sessions) ? d.executor_sessions : [];
  }
  function renderGrants(){
    if(state.grants && state.grants.ok===false){
      el('grantsBanner').innerHTML = bannerHtml('Grants are not available. Reason: '+(state.grants.error||'?'), true);
      return;
    }
    var g = state.grants || {};
    var sr = g.session_readout || null;
    var sessions = declaredSessions();
    if(!el('grantSession').value) el('grantSession').value = sessions[0] || '';
    // 有活跃夜间档=读出面的 granted_ops 已含全部六项——开关跟着 granted_ops 走。
    var grantedSet = {};
    (g.granted_ops||[]).forEach(function(op){ grantedSet[op]=1; });
    var html = '';
    for(var i=0;i<PERMS.length;i++){
      var p = PERMS[i];
      var on = grantedSet[p[0]]===1;
      html += '<div class="line"><div class="lab">'+esc(p[1])+' <small>'+esc(p[2])+'</small></div>'
        + '<div class="sw grant" data-op="'+esc(p[0])+'" data-on="'+String(on)+'"></div></div>';
    }
    el('permList').innerHTML = html;
    Array.prototype.forEach.call(el('permList').querySelectorAll('.sw.grant'), function(s){
      s.onclick = function(){ s.dataset.on = s.dataset.on==='true' ? 'false' : 'true'; syncMaster(); };
    });
    var count = g.granted_ops ? g.granted_ops.length : 0;
    el('masterSw').dataset.on = String(masterOn(count));
    el('masterSw').onclick = function(){
      var on = el('masterSw').dataset.on==='true';
      setAllSwitches(!on);
      syncMaster();
    };
    el('grantsReadout').textContent = sr ? sr.sentence : (g.grants && g.grants.readout_note ? g.grants.readout_note : '');
    if(g.declaration_state && g.declaration_state.kind && g.declaration_state.kind!=='ok'){
      el('grantsBanner').innerHTML = bannerHtml('The grants declaration cannot be read ('+g.declaration_state.kind+'). Nothing is granted. Detail: '+(g.declaration_state.error||'none'), true);
    } else if(!g.declaration_state || g.declaration_state.declared===false){
      el('grantsBanner').innerHTML = bannerHtml('No grants declaration exists yet. Save once to create it. Nothing is granted before that.', false);
    } else {
      el('grantsBanner').innerHTML = '';
    }
    el('grantsMatrix').innerHTML = g.grants && g.grants.rows && g.grants.rows.length
      ? '<div class="sect lead">Capability matrix</div><div class="muted" style="font-size:11px">The list below shows what each permission means per template. A row here is not a grant. Only the switches above grant.</div><table style="margin-top:6px"><tr><th>Permission</th><th>Template</th><th>Granted</th></tr>'
        + g.grants.rows.map(function(r){ return '<tr><td>'+esc(r.op)+'</td><td>'+esc(r.template)+'</td><td>'+(r.granted===true?'<span class="good">yes</span>':'<span class="muted">no</span>')+'</td></tr>'; }).join('') + '</table>'
      : '';
    renderOpenEpics(g);
    el('grantsSaveOut').innerHTML = grantsSaveMsg;
  }
  // ---- t261004-19：「Open tickets in these epics」节（宿主专属授权面） ----
  // 数据源=GET /api/grants 的 open_ticket_epics 读面（全部 epic + 状态行原文 +
  // 当前是否授权）。解析不出=显式降级卡（点名原因），绝不渲染成「无 epic」空表。
  function renderOpenEpics(g){
    var face = g && g.open_ticket_epics;
    if(!face){ el('openEpics').innerHTML = ''; return; }
    if(face.ok !== true){
      el('openEpics').innerHTML = '<div class="sect lead">Open tickets in these epics</div>'
        + '<div class="muted" style="font-size:11px">The epic list cannot be read. Reason: '+esc(face.reason||'?')+'</div>';
      return;
    }
    var cap = (typeof g.open_ticket_cap === 'number') ? g.open_ticket_cap : 3;
    var html = '<div class="sect lead">Open tickets in these epics</div>'
      + '<div class="muted" style="font-size:11px">An executor ticket-start must name one of these epics; every other epic stays closed. Cap: '+cap+' open ticket(s) per epic. Saving here goes through the audited grants declaration.</div>';
    for(var i=0;i<face.epics.length;i++){
      var e = face.epics[i];
      html += '<div class="line"><div class="lab">'+esc(e.code)+' <small>'+esc(e.status||'(no status line)')+'</small></div>'
        + '<div class="sw grant" data-epic="'+esc(e.code)+'" data-on="'+String(e.authorized===true)+'"></div></div>';
    }
    if(face.epics.length===0){
      html += '<div class="muted" style="font-size:11px">This project has no epic yet (docs/epics/ is empty or absent). Nothing can be authorized.</div>';
    }
    el('openEpics').innerHTML = html;
    Array.prototype.forEach.call(el('openEpics').querySelectorAll('.sw.grant'), function(s){
      s.onclick = function(){ s.dataset.on = s.dataset.on==='true' ? 'false' : 'true'; };
    });
  }
  function selectedOpenEpics(){
    var out = [];
    Array.prototype.forEach.call(el('openEpics').querySelectorAll('.sw.grant'), function(s){
      if(s.dataset.on==='true' && s.dataset.epic && out.indexOf(s.dataset.epic)<0) out.push(s.dataset.epic);
    });
    return out;
  }
  function setAllSwitches(on){
    Array.prototype.forEach.call(el('permList').querySelectorAll('.sw.grant'), function(s){ s.dataset.on = String(on); });
  }
  function syncMaster(){
    var n = el('permList').querySelectorAll('.sw.grant[data-on="true"]').length;
    el('masterSw').dataset.on = String(masterOn(n));
    el('grantChip').textContent = chipLabel(n, 6);
  }
  function saveGrants(){
    if(!state.project) return;
    var grants = {};
    Array.prototype.forEach.call(el('permList').querySelectorAll('.sw.grant'), function(s){
      if(s.dataset.on==='true') grants[s.dataset.op] = true;
    });
    // t261004-18（KI-193）：不带 by——写者由服务端凭据定名。
    var body = { grants: grants };
    var sess = el('grantSession').value.trim();
    if(sess) body.executor_sessions = [sess];
    body.open_ticket_epics = selectedOpenEpics();
    postJson('/sandbar-executor-panel/api/grants?project='+encodeURIComponent(state.project), body)
      .then(function(j){
        grantsSaveMsg = j.saved===true ? '<span class="good">Saved.</span>'
          : '<span class="bad">The save was rejected. The file did not change. Reason: '+esc(j.error||j.reason||'?')+'</span>';
        el('grantsSaveOut').innerHTML = grantsSaveMsg;
        loadGrants();
      })
      .catch(function(e){ grantsSaveMsg = '<span class="bad">The save failed to send: '+esc((e&&e.message)||String(e))+'</span>'; el('grantsSaveOut').innerHTML = grantsSaveMsg; });
  }
  function masterSwitch(enabled){
    if(!state.project) return;
    postJson('/sandbar-executor-panel/api/grants?project='+encodeURIComponent(state.project), {op:'master', enabled: enabled})
      .then(function(j){
        if(j.saved!==true){ alert('The change was rejected: '+(j.error||j.reason||'?')); }
        loadGrants();
      })
      .catch(function(e){ alert('The change failed to send: '+((e&&e.message)||e)); });
  }

  // ---- Settings (watchdog knobs; a different face from the executor switch) ----
  function loadSettings(){
    if(!state.project){ return; }
    fetch('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.settings = j; renderSettings();
    }).catch(function(){ state.settings={ok:false,error:'the settings endpoint could not be reached'}; renderSettings(); });
  }
  var KNOBS = [
    ['enabled','boolean','The watchdog runs.'],
    ['executor_session','string','The session the watchdog serves.'],
    ['stall_minutes','number','Minutes without motion raise a stall alert.'],
    ['reconcile_seconds','number','Seconds between two reconciles.'],
    ['alerts.enabled','boolean','The watchdog raises alerts.'],
    ['alerts.sound','boolean','A new alert plays a sound.'],
    ['alerts.desktop','boolean','A new alert shows on the desktop.'],
    ['alerts.night.start','hhmm','Night starts at this time.'],
    ['alerts.night.end','hhmm','Night ends at this time.'],
    ['alerts.night.policy','policy','The night alert policy.'],
    ['alerts.redline','string[]','These rules always alert, even at night.'],
    ['alerts.keep_days','number','Days to keep alerts.'],
    ['alerts.display_max','number','Coalesced alert rows to show. 0 shows all.']
  ];
  function getIn(o,path){ var parts=path.split('.'); for(var i=0;i<parts.length;i++){ if(o==null) return undefined; o=o[parts[i]]; } return o; }
  function setIn(o,path,v){ var parts=path.split('.'); var c=o; for(var i=0;i<parts.length-1;i++){ c[parts[i]]=c[parts[i]]||{}; c=c[parts[i]]; } c[parts[parts.length-1]]=v; }
  function provenanceMap(st){
    return (st && (st.config_provenance && st.config_provenance.keys || st.provenance && st.provenance.keys)) || {};
  }
  function provenanceFor(st, path){
    if(st && st.night_override && st.night_override_active && path==='alerts.night.policy') return 'The sleep toggle set this. It ends at '+new Date(st.night_override.until).toISOString().slice(0,16)+'.'; // LIST-CAP-OK: date string formatting cut, not a list cap
    var m = provenanceMap(st);
    return m[path] ? String(m[path]) : 'The factory default sets this.';
  }
  function renderSettings(){
    var st = state.settings;
    if(!st || st.ok===false){ el('setBanners').innerHTML = bannerHtml(st && st.error ? st.error : 'The settings endpoint could not be reached.', true); el('setKnobs').innerHTML=''; return; }
    var b='';
    if(st.config_error) b += bannerHtml('The loader rejected the declaration: '+st.config_error, true);
    if(st.declared===false) b += bannerHtml('No watchdog declaration exists. A save creates it.');
    if(st.night_override_expired) b += bannerHtml('The night policy expired. The policy is still "'+esc(st.night_override&&st.night_override.policy)+'". Save to change it. Nothing reverts on its own.');
    el('setBanners').innerHTML=b;
    var cfg = st.config||{};
    var html = '';
    for(var i=0;i<KNOBS.length;i++){
      var path=KNOBS[i][0], type=KNOBS[i][1], v=getIn(cfg,path);
      html += '<div class="knob"><div>'+esc(path)+'</div><div>'+inputFor(path,type,v)+'</div><div class="src">'+esc(provenanceFor(st,path))+'</div></div>';
    }
    el('setKnobs').innerHTML = html;
    el('saveResult').innerHTML = saveMsg;
  }
  // idFor 是 id 生成的唯一真源（inputFor 建面 + readInput 读面共用）——
  // 用 split/join 而不是正则（模板字符串吃反斜杠的教训，t261001-10）。
  function idFor(path){ return 'kb_'+path.split('.').join('_'); }
  function inputFor(path,type,v){
    var id=idFor(path);
    if(type==='boolean') return '<input type="checkbox" id="'+id+'"'+(v?' checked':'')+'>';
    if(type==='policy'){ return '<select id="'+id+'">'+['silent','redline-only','normal'].map(function(p){return '<option'+(p===v?' selected':'')+'>'+p+'</option>';}).join('')+'</select>'; }
    if(type==='string[]') return '<input type="text" id="'+id+'" value="'+esc((v||[]).join(','))+'" size="40">';
    return '<input type="text" id="'+id+'" value="'+esc(v==null?'':v)+'" size="36">';
  }
  function readInput(path,type){
    var n=el(idFor(path));
    if(type==='boolean') return n.checked;
    if(type==='number'){ var x=Number(n.value); return Number.isFinite(x)?x:n.value; }
    if(type==='string[]') return n.value.split(',').map(function(s){return s.trim();}).filter(Boolean);
    return n.value;
  }
  el('saveBtn').onclick = function(){
    if(!state.project) return;
    var st = state.settings; if(!st || st.ok===false) return;
    var cfg = st.config||{};
    var next = JSON.parse(JSON.stringify(cfg));
    for(var i=0;i<KNOBS.length;i++){ setIn(next, KNOBS[i][0], readInput(KNOBS[i][0], KNOBS[i][1])); }
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'save', config:next})
      .then(function(j){
        saveMsg = j.saved===true ? '<span class="good">Saved. The loader accepted the file.</span>'
          : '<span class="bad">REJECTED. The file did not change: '+esc(j.error||j.reason||'?')+'</span>';
        el('saveResult').innerHTML = saveMsg;
        loadSettings();
      })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  el('revokeBtn').onclick = function(){
    if(!state.project) return;
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'revoke'})
      .then(function(j){ if(j.saved!==true){ saveMsg='<span class="bad">REJECTED: '+esc(j.error||'?')+'</span>'; el('saveResult').innerHTML = saveMsg; } loadSettings(); })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  el('sleepBtn').onclick = function(){
    if(!state.project) return;
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'sleep', policy:'redline-only', until: Date.now()+8*3600*1000})
      .then(function(j){ if(j.ok!==true){ saveMsg = '<span class="bad">The sleep toggle was rejected: '+esc(j.error||'?')+'</span>'; el('saveResult').innerHTML = saveMsg; } loadSettings(); })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  el('wakeBtn').onclick = function(){
    if(!state.project) return;
    var st = state.settings; if(!st || st.ok===false) return;
    var cfg = st.config||{};
    var next = JSON.parse(JSON.stringify(cfg));
    setIn(next,'alerts.night.policy', st.factory_defaults? st.factory_defaults.alerts.night.policy : 'redline-only');
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'save', config:next})
      .then(function(){ loadSettings(); })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  function saveFailHtml(e){
    return '<span class="bad">SAVE FAILED. Nothing was written: '+esc((e&&e.message)||String(e))+'</span>';
  }
  function postJson(url, obj){
    return fetch(url, {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(obj)})
      .then(function(r){ return r.json(); });
  }

  // ---- Inspection tab (t261006-15) ----
  var INSP = {
    archive: null,        // the served archive payload (workbench inspection-archive route)
    archiveReason: '',
    records: null,
    selected: '',         // the selected period ('' = latest reported / first render)
    loadedFor: '',        // project the faces were loaded for (lazy-load gate, inspEnsureLoaded)
    tables: ${INSP_TABLES},
    coverageTables: ${INSP_COVERAGE_TABLES},
    ticketRows: null,     // t261026-10: the inspection ticket board rows (attempt source)
    dispositions: null,   // retired fetch face (t261009-49 rework, gate round 1 Red 2)
  };
  // t261006-15 rework (404 fix): the Inspection faces load LAZILY — on first open of
  // the tab, not on every setProject. The two inspection endpoints do not exist in
  // other scenarios' page-boundary stub environments, and an eager fetch there 404s
  // into the console, tripping the panel family's zero-pageerror guards
  // (t261003-13 / t260929-03 / t261003-06). A tab that is never opened must never
  // request anything.
  function inspEnsureLoaded(){
    if(!state.project) return;
    if(INSP.loadedFor === state.project) return;
    INSP.loadedFor = state.project;
    inspLoad();
  }
  function inspLatestReported(){
    // Ordering contract: the SERVER declares periods newest-first
    // (inspection-archive.ts sortPeriodsDesc — never a payload iteration order).
    // This scan is a belt-and-braces explicit pass over that declared sequence.
    var ps = (INSP.archive && INSP.archive.periods) || [];
    var latest = null, best = -1;
    for(var i=0;i<ps.length;i++){
      if(ps[i].any_report){
        var n = Number(ps[i].period);
        if(!isNaN(n) && n > best){ best = n; latest = ps[i].period; }
      }
    }
    return latest;
  }
  function inspLoad(){
    if(!state.project){ INSP.archive=null; INSP.records=null; INSP.ticketRows=null; INSP.coverageTables = JSON.parse(${JSON.stringify(INSP_COVERAGE_TABLES)}); inspRender(); return; }
    var key = encodeURIComponent(state.project);
    fetch('/sandbar-workbench/api/wf/inspection-archive?project='+key).then(function(r){return r.json();}).then(function(j){
      INSP.archive = (j && j.result && j.result.ok === true) ? j.result : null;
      INSP.archiveReason = (j && j.result && j.result.reason) || 'The period archive is not available.';
      // t261026-10 (defect B): the faces map is the DECLARATION's scan_face per
      // declared instance, served on the archive payload. Swapped in before render;
      // an absent/malformed map degrades to the empty default (decl-unreadable).
      // t261026-10 rework (arbitration round 3): COPIES comes from the ALREADY-
      // INTERPOLATED default tables, never a bare module binding — inspLoad runs
      // inside the SERVED page script where module imports do not exist (the
      // ReferenceError that blanked the whole period row in the merged-tree red).
      var faces = (INSP.archive && INSP.archive.faces !== null && typeof INSP.archive.faces === 'object') ? INSP.archive.faces : {};
      INSP.coverageTables = { COPIES: INSP.coverageTables.COPIES, FACES: faces, ATTEMPT_CAP: 5 };
      inspRenderPeriods();
    }).catch(function(){ INSP.archive=null; INSP.archiveReason='The period archive could not be loaded.'; inspRenderPeriods(); });
    fetch('/sandbar-workbench/api/wf/inspection/tickets?project='+key).then(function(r){return r.json();}).then(function(j){
      // t261026-10 (defect C): the attempt source is the inspection TICKET BOARD (an
      // already-served route, not a new fetch face — t261008-19 E1 pins NEW endpoints
      // only). A failed board read keeps ticketRows null = the named attempts-
      // unavailable degrade; a readable board lights failed/not_run evidence up.
      var res = (j && j.result) || null;
      INSP.ticketRows = (res && Array.isArray(res.tickets)) ? res.tickets : null;
      inspRenderRecords();
    }).catch(function(){ INSP.ticketRows = null; inspRenderRecords(); });
    fetch('/sandbar-executor-panel/api/inspection/trigger-records?project='+key).then(function(r){return r.json();}).then(function(j){
      INSP.records = j || null;
      inspRenderRecords();
    }).catch(function(){ INSP.records = {ok:false, rows:[], reason:'The trigger records could not be loaded.'}; inspRenderRecords(); });
    // t261009-49 rework (gate round 1, Red 2): NO disposition-records fetch on this
    // surface. The t261008-19 pinned hit-endpoint anchor (E1) forbids a new fetch
    // face here, and that anchor's contract may only change through its owner's
    // review (protected asset; t260916-19/-21 discipline). The coverage answer
    // renders from the ledgers and, until a period-keyed attempts source arrives
    // inside an already-served payload, names itself attempts-unavailable; the
    // module's attempts machinery stays unit-pinned in
    // integration/t261009-49/inspection-coverage.test.mjs (P2/P5 faces kept).
  }
  function inspRenderPeriods(){
    var host = el('inspPeriodBtns'); host.innerHTML='';
    var note = el('inspPeriodNote'); note.style.display='none';
    if(!INSP.archive){
      el('inspBody').innerHTML = '<div class="inspCard"><div class="pad inspNote" style="padding-left:var(--igx,14px)">'+esc(INSP.archiveReason)+'</div></div>';
      el('inspBanner').innerHTML='';
      INSP.selected=''; inspRenderBody(); return;
    }
    // The items list already carries the merge/missing semantics (server-computed).
    var items = INSP.archive.items || [];
    var first = null;
    items.forEach(function(it){
      var b = document.createElement('button');
      b.textContent = it.kind === 'no-report-run' ? it.label : it.period;
      b.onclick = function(){ INSP.selected = (it.kind==='no-report-run') ? '' : it.period; inspRenderBody(items); };
      host.appendChild(b);
      if(first === null) first = { it: it, btn: b };
    });
    // Default selection: the newest reported period (first item that carries one).
    var def = null;
    for(var i=0;i<items.length;i++){
      if(items[i].kind === 'period'){ def = items[i]; break; }
      if(items[i].kind === 'no-report-run' && def === null) def = items[i];
    }
    var sel = INSP.selected || (def && def.kind === 'period' ? def.period : '');
    INSP.selected = sel;
    inspRenderBody(items);
  }
  function inspMarkActive(items){
    var btns = el('inspPeriodBtns').children;
    var items2 = items || (INSP.archive && INSP.archive.items) || [];
    for(var i=0;i<btns.length && i<items2.length;i++){
      var it = items2[i];
      var on = (it.kind==='period') ? (it.period === INSP.selected) : (INSP.selected === '');
      btns[i].setAttribute('data-on', on ? 'true' : 'false');
    }
  }
  // t261009-49 rework (gate round 1, Red 2): the attempts map comes ONLY from
  // payloads already served on this surface. t261026-10 (defect C): the ticket board
  // rows are the second source — merged with the trigger-record attempts at this one
  // wiring point; BOTH sources unavailable = null = the named attempts-unavailable
  // degrade. The board rows are project-filtered inside ticketRowsToAttempts (review
  // C1: a same-named instance from another project must not light up these cells).
  function inspAttempts(){
    var map = null;
    var t = INSP.records && INSP.records.rows;
    if(Array.isArray(t)) map = recordsToAttempts(t);
    var tk = INSP.ticketRows;
    if(Array.isArray(tk)){
      var tmap = ticketRowsToAttempts(tk, state.project);
      if(tmap){
        if(map === null){ map = tmap; }
        else {
          for(var k in tmap){
            if(Object.prototype.hasOwnProperty.call(tmap, k)){
              map[k] = (Array.isArray(map[k]) ? map[k] : []).concat(tmap[k]);
            }
          }
        }
      }
    }
    return map;
  }
  // t261009-49: the named 'produced nothing' block — one line per (period x face)
  // that produced nothing, with period, face id, last success (or never) and the
  // attempt evidence; visible without counting rows.
  function inspCoverageBlockHtml(cov){
    if(!cov || !cov.block || !cov.block.visible) return '';
    var h = '<div class="inspCard"><div class="pad" style="padding:0 var(--igx,14px)"><b>'+esc(cov.block.title)+'</b></div>';
    if(!cov.attempts_available){
      h += '<div class="pad inspNote" style="padding-left:var(--igx,14px)">'+esc(INSP.coverageTables.COPIES.attempts_unavailable)+'</div>';
    }
    h += '<table><tbody>';
    cov.block.lines.forEach(function(l){ h += '<tr><td>'+esc(l)+'</td></tr>'; });
    h += '</tbody></table></div>';
    return h;
  }
  function inspRenderBody(items){
    items = items || (INSP.archive && INSP.archive.items) || [];
    inspMarkActive(items);
    var banner = el('inspBanner'); var body = el('inspBody');
    var C = INSP.tables.EMPTY_COPIES;
    if(!INSP.archive){ body.innerHTML=''; return; }
    // Find the selected item.
    var item = null;
    for(var i=0;i<items.length;i++){
      if(items[i].kind==='no-report-run' && INSP.selected===''){ item = items[i]; break; }
      if(items[i].kind==='period' && items[i].period===INSP.selected){ item = items[i]; break; }
    }
    if(!item){ body.innerHTML=''; banner.innerHTML=''; return; }
    if(item.kind==='no-report-run'){
      banner.innerHTML='';
      // t261009-49 rework (gate round 1, Red 1): the coverage block on THIS face is
      // scoped to the run's OWN periods (t261006-15 §7 adjacency ruling — the merge
      // is adjacency-only; a far period must not leak into this view). The
      // full-window coverage answer stays on the per-period card face.
      var runPeriodKeys = {};
      (item.periods||[]).forEach(function(q){ runPeriodKeys[q.period] = true; });
      var runPeriods = (INSP.archive.periods||[]).filter(function(p){ return runPeriodKeys[p.period] === true; });
      var covGap = buildCoverageCore(runPeriods, INSP.archive.instances||[], inspAttempts(), INSP.coverageTables);
      var rows = '';
      for(var j=0;j<item.periods.length;j++){
        var p = item.periods[j];
        var per = [];
        for(var inst in p.reports){ if(p.reports[inst] && p.reports[inst].reason) per.push(inst+': '+p.reports[inst].reason); }
        rows += '<tr><td>'+esc(p.period)+'</td><td class="num">'+esc(per.length?per.join(' · '):'no report file in the archive')+'</td></tr>';
      }
      body.innerHTML =
        '<div class="inspCard"><div class="pad inspNote" style="padding-left:var(--igx,14px)">'+esc(C.no_reports)+' '+esc(item.label)+'</div>'+
        inspCoverageBlockHtml(covGap)+
        '<table><tbody>'+rows+'</tbody></table></div>';
      return;
    }
    // A real period: view model (same implementation as the unit tests).
    var latest = inspLatestReported();
    // t261009-49: the period-x-face coverage answer over the WHOLE archive window —
    // the named 'produced nothing' block, not a row count for the reader to do.
    var cov = buildCoverageCore(INSP.archive.periods||[], INSP.archive.instances||[], inspAttempts(), INSP.coverageTables);
    var v = buildPeriodViewCore(
      (INSP.archive.periods||[]).filter(function(p){ return p.period===item.period; })[0] || null,
      latest,
      INSP.archive.instances || [],
      INSP.tables);
    banner.innerHTML = v.read_only ? '<div class="banner">'+esc(v.banner)+'</div>' : '';
    var html = inspCoverageBlockHtml(cov);
    v.cards.forEach(function(c){
      html += '<div class="inspCard"><div class="pad" style="display:flex;align-items:baseline;gap:8px;padding:0 var(--igx,14px)">'+
        '<b>'+esc(c.label)+'</b><span class="inspMeta" style="margin-left:auto">'+esc(c.instance)+'</span></div>';
      if(c.report_error){
        html += '<div class="pad inspNote" style="padding-left:var(--igx,14px)">'+esc(c.report_error)+'</div></div>';
        return;
      }
      html += '<div class="inspNums">'+
        '<div class="kv"><span>Findings</span><b>'+(c.counts?c.counts.total:'—')+'</b><span>'+esc(c.counts_copy)+'</span></div>'+
        '<div class="kv"><span>Named items</span><b>'+c.named.length+'</b><span>'+esc(c.named_copy)+'</span></div>'+
        '<div class="kv"><span>High</span><b>'+(c.counts?c.counts.high:'—')+'</b><span>severity: high</span></div>'+
        '<div class="kv"><span>Med · low</span><b>'+(c.counts?(c.counts.med+' · '+c.counts.low):'—')+'</b><span>severity: med, low</span></div>'+
        '</div>';
      if(c.findings_copy) html += '<div class="pad inspNote" style="padding-left:var(--igx,14px)">'+esc(c.findings_copy)+'</div>';
      if(c.named.length){
        html += '<table><thead><tr><th>Named findings</th></tr></thead><tbody>';
        c.named.forEach(function(n2){ html += '<tr><td>'+esc(n2)+'</td></tr>'; });
        html += '</tbody></table>';
      }
      html += '<div class="pad inspNote" style="padding-left:var(--igx,14px)"><b>Coverage</b> · '+esc(c.coverage_copy)+'</div>';
      if(c.coverage_run_copy) html += '<div class="pad inspNote" style="padding-left:var(--igx,14px)"><b>Run</b> · '+esc(c.coverage_run_copy)+'</div>';
      if(c.not_reviewed && c.not_reviewed.length){
        html += '<div class="pad inspNote" style="padding-left:var(--igx,14px)">Not reviewed (this is not a clean result):</div>';
        html += '<table><tbody>';
        c.not_reviewed.forEach(function(f){ html += '<tr><td>'+esc(f)+'</td></tr>'; });
        html += '</tbody></table>';
      }
      if(c.reviewed && c.reviewed.length){
        html += '<details style="padding:0;margin:0"><summary class="inspNote">Reviewed ('+c.reviewed.length+')</summary><div class="inspNote">'+c.reviewed.map(esc).join('<br>')+'</div></details>';
      }
      html += '<div class="pad inspNote" style="padding-left:var(--igx,14px)">'+esc(v.range_note)+'</div>';
      html += '</div>';
    });
    body.innerHTML = html;
  }
  function inspRenderRecords(){
    var body = el('inspRecordsBody'); var empty = el('inspEmpty');
    var j = INSP.records;
    var rows = (j && j.rows) || [];
    body.innerHTML = rows.map(function(r){
      var st = r.spawn && r.spawn.ok === true
        ? '<span style="color:var(--green)">started</span>'
        : '<span style="color:var(--red)">failed</span>';
      var res = r.spawn ? (r.spawn.ok === true ? (r.spawn.ticket_id || 'workflow started') : (r.spawn.error || 'failed')) : '—';
      // state+result live in ONE right-aligned last column: the table's right text
      // edge must sit on the shared right line (P6; arbitrate gen1 L1-right fix).
      return '<tr><td>'+esc(new Date(r.at).toLocaleString())+'</td><td>'+esc(r.by)+
        '</td><td>'+esc(r.scope)+'</td><td>'+esc(r.reason)+'</td><td style="text-align:right">'+st+' · '+esc(res)+'</td></tr>';
    }).join('');
    empty.style.display = rows.length ? 'none' : '';
    el('inspRecords').style.display = rows.length ? '' : 'none';
  }
  el('inspRunBtn').onclick = function(){
    el('inspDlg').style.display=''; el('inspDlg').setAttribute('data-open','true');
    el('inspMsg').textContent='';
  };
  el('inspCancelBtn').onclick = function(){
    el('inspDlg').style.display='none'; el('inspDlg').setAttribute('data-open','false');
  };
  el('inspStartBtn').onclick = function(){
    var reason = el('inspReason').value;
    if(!reason || !reason.trim()){ el('inspMsg').textContent='A reason is required — it is recorded with the trigger.'; return; }
    el('inspMsg').textContent='Starting…';
    postJson('/sandbar-executor-panel/api/inspection/trigger', {
      project: state.project, instance: 'integration-tests', scope: el('inspScope').value, reason: reason
    }).then(function(j){
      if(j && j.ok === true){
        el('inspMsg').textContent='The review was started and recorded.';
        el('inspReason').value='';
        inspLoad();
      } else {
        el('inspMsg').textContent='The review did not start: '+((j && (j.error||'')) || 'refused')+' (the attempt stays recorded).';
      }
    }).catch(function(e){
      el('inspMsg').textContent='The review did not start: '+((e&&e.message)||e);
    });
  };

  // ---- Certification tab (t261009-44; rounds faces t261012-03; the two
  // controls wired t261025-12 per ruling §5) ----
  // Lazy like the other reference faces: a tab that is never opened must never
  // request anything. t261025-12: Queue round POSTs the engine's own round
  // marker seam (queued, never run in the request); Promote opens the dialog
  // that SHOWS the signer before the act, and the act POSTs the engine writer
  // route — the answer is the ledger read-back row, never a guess.
  // t261012-03 degrade rule: the LAST GOOD round-faces section is kept
  // per-SECTION (CERT.roundFaces) — a live-face read that degrades leaves the
  // previous Rounds table standing and never rolls back the rest of the tab,
  // which re-renders from the fresh answer as before.
  var CERT = { loadedFor: '', data: null, roundFaces: null };
  function renderCert(){
    var body = el('certBody');
    if(CERT.roundFaces && CERT.data && CERT.data.ok === true){
      CERT.data.round_faces = CERT.roundFaces;
    }
    body.innerHTML = buildCertificationCore(CERT.data || {ok:false, reason:'the certification face has not been read yet'});
    var line = el('certLine');
    if(line) line.onchange = function(){ loadCertification(); };
    // t261025-12: the queue control's handler — POST the queue route, then
    // render the ONE honest note sentence (pure builder, same as the UT).
    var queueBtn = el('certQueue');
    if(queueBtn) queueBtn.onclick = function(){
      var note = el('certQueueNote');
      if(!note) return;
      if(!state.project){ note.hidden = false; note.textContent = 'No project is selected — nothing can be queued.'; return; }
      note.hidden = false;
      note.textContent = 'Queueing…';
      postJson('/sandbar-executor-panel/api/certification/queue', { project: state.project })
        .then(function(j){ note.textContent = certQueueNoteText(j); loadCertification(); })
        .catch(function(e){ note.textContent = certQueueNoteText({ ok:false, error:String((e&&e.message)||e) }); });
    };
    // t261025-12: the promote control's handler — open the dialog that shows
    // the signer (prefilled only from the declared owner, never an agent role
    // name list); the act POSTs after the human confirms the shown value.
    var promo = el('certPromo');
    if(promo) promo.onclick = function(){
      if(!state.project || promo.disabled) return;
      var wrap = document.getElementById('promoteDlgWrap');
      var dlg = document.getElementById('promoteDlg');
      if(!wrap || !dlg) return;
      var data = CERT.data || {};
      var owner = '';
      var lines = data.lines || [];
      for(var i=0;i<lines.length;i++){
        if(String(lines[i].line_id) === String(data.line)) owner = String(lines[i].owner || '');
      }
      dlg.innerHTML = buildPromoteDialogCore({ owner: owner, line: data.line, preview: data.promote_preview });
      wrap.hidden = false;
      var cancel = el('promoteCancel');
      if(cancel) cancel.onclick = function(){ wrap.hidden = true; };
      if(wrap.onclick === null){
        wrap.onclick = function(ev){ if(ev.target === wrap) wrap.hidden = true; };
      }
      var go = el('promoteGo');
      if(go) go.onclick = function(){
        var signer = (el('promoteSigner') && el('promoteSigner').value || '').trim();
        var note = el('promoteNote');
        if(!note) return;
        if(!signer){ note.hidden = false; note.textContent = 'The signer is required — the recorded row must name the human who signed.'; return; }
        note.hidden = false;
        note.textContent = 'Signing…';
        postJson('/sandbar-executor-panel/api/certification/promote', {
          project: state.project, line: data.line, signer: signer
        }).then(function(j){
          if(j && j.ok === true){
            var row = j.promotion || {};
            note.textContent = CERT_RUNTIME.COPIES.promoteRecorded + ': ' + String(row.signer || signer)
              + ' · cert ' + String(row.certification || '?')
              + ' · ' + Object.keys(row.main_after || {}).map(function(k){
                  return k + ':' + String(row.main_after[k]).slice(0,8); // LIST-CAP-OK: revision-label width, not a list cap
                }).join(' · ');
            loadCertification();
          } else {
            note.textContent = CERT_RUNTIME.COPIES.promoteRefusedWhy + ' ' + String((j && j.error) || 'refused');
          }
        }).catch(function(e){
          note.textContent = CERT_RUNTIME.COPIES.promoteRefusedWhy + ' ' + String((e&&e.message)||e);
        });
      };
    };
    var rows = el('certRoundRows');
    if(rows) rows.onclick = function(ev){
      var t = ev.target && ev.target.closest ? ev.target.closest('[data-round-link]') : null;
      if(t) openRoundDialog(t.getAttribute('data-round-link'));
    };
    var wrap = el('roundDlgWrap');
    if(wrap) wrap.onclick = function(ev){
      if(ev.target === wrap) closeRoundDialog();
      var x = ev.target && ev.target.closest ? ev.target.closest('[data-round-close]') : null;
      if(x) closeRoundDialog();
    };
  }
  function closeRoundDialog(){
    var wrap = el('roundDlgWrap');
    if(wrap){ wrap.hidden = true; }
  }
  function openRoundDialog(runId){
    var dlg = el('roundDlg'), wrap = el('roundDlgWrap');
    if(!dlg || !wrap || !runId || !state.project) return;
    dlg.innerHTML = '<div class="pad k">reading the round record…</div>';
    wrap.hidden = false;
    fetch('/sandbar-executor-panel/api/certification/round?project='+encodeURIComponent(state.project)+'&run='+encodeURIComponent(runId))
      .then(function(r){ return r.json(); })
      .then(function(j){ dlg.innerHTML = buildRoundDialogCore(j); })
      .catch(function(e){ dlg.innerHTML = buildRoundDialogCore({ok:false, reason:String((e&&e.message)||e)}); });
  }
  // Close paths: the ✕ button and the backdrop click (the mock's own close
  // affordance). No global Escape listener — the page is pinned Escape-free
  // by the t261008-20 contract (the retired ledger dialog's machinery).
  function loadCertification(){
    if(!state.project){ CERT.data={ok:false, reason:'no project is selected — the develop ledgers cannot be resolved'}; renderCert(); return; }
    var lineSel = el('certLine');
    var q = '/sandbar-executor-panel/api/certification?project='+encodeURIComponent(state.project);
    var want = lineSel && lineSel.value;
    if(want) q += '&line='+encodeURIComponent(want);
    fetch(q).then(function(r){ return r.json(); }).then(function(j){
      CERT.loadedFor = state.project; CERT.data = j;
      // t261012-03 fault 2: a refusal receipt still carries the section —
      // the last-good section updates from it too.
      if(j && j.round_faces && !j.round_faces.error){
        CERT.roundFaces = j.round_faces;
      }
      renderCert();
    }).catch(function(e){
      CERT.data = {ok:false, reason:String((e && e.message) || e)}; renderCert();
    });
  }

  // ---- tab switching ----
  // t261005-10 (UI-2): the nine-tab fixed order (mock v11); the four read-only
  // faces load on first activation (lazy — they are reference faces, not live
  // state, so they stay out of the 5s poll).
  var PANES = [['t-overview','paneOv'],['t-epics','paneEpics'],
    ['t-inspection','paneInsp'],['t-certification','paneCert'],['t-metrics','paneMetrics'],['t-docs','paneDocs'],['t-grants','paneGrants'],['t-settings','paneSet']];
  var TAB_LOADER = { 't-epics': loadEpics, 't-inspection': inspEnsureLoaded, 't-certification': loadCertification, 't-metrics': loadMetrics, 't-docs': loadDocs };  function showTab(id){
    for(var i=0;i<PANES.length;i++){
      el(PANES[i][1]).style.display = (PANES[i][0]===id) ? '' : 'none';
    }
    // t261019-09: the panel changed its own content, so the console's
    // ticket-detail overlay must go — it would float over content this page
    // replaced. Single choke point: showTab runs on tab radios, the show-tab /
    // show-epic wayfinding branches, and boot alike. Embedded-only: standalone
    // (no parent) there is no overlay to talk to. Fire-and-forget, no receipt
    // (closing is visible; closing when nothing is open is the host's no-op).
    if(window.parent !== window){
      window.parent.postMessage({ type: CLOSE_OVERLAY_MSG_TYPE }, window.location.origin);
    }
    var loader = TAB_LOADER[id];
    if(loader && state.project) loader();
  }
  Array.prototype.forEach.call(document.querySelectorAll('input.tab'), function(r){
    r.onchange = function(){
      if(r.checked){
        showTab(r.id);
        // t261006-15: first open of the Inspection tab loads its faces (lazy — the
        // two inspection endpoints are not served by every page-boundary stub env).
        if(r.id === 't-inspection') inspEnsureLoaded();
      }
    };
  });
  function currentTabId(){
    var on=document.querySelector('input.tab:checked');
    return on ? on.id : 't-overview';
  }

  // ---- boot ----
  el('giveAllBtn').onclick = function(){ setAllSwitches(true); syncMaster(); };
  el('giveNoneBtn').onclick = function(){ setAllSwitches(false); syncMaster(); };
  el('grantsSave').onclick = saveGrants;
  el('powerBtn').onclick = function(){
    masterSwitch(el('powerBtn').dataset.on !== 'true');
  };
  // t261009-37 (host order 261009-(3)): the open-session click handler and its
  // postMessage are gone with the button.
  // t261008-36: the Settings tab's two face entries. One postMessage each to the
  // parent console (paired constant on the host side: OPEN_FACE_MSG_TYPE in
  // executor-view.tsx). The payload carries this panel's own project key (state.project,
  // from the ?project= deep link) so the host can verify the request matches the
  // project it embedded — the identity comes from the panel's own context, never
  // from the console's view registry. Without a parent (panel opened standalone)
  // the buttons are disabled with a title naming where the panel must be opened
  // from — an explicit degraded face, never a dead silent button. Repeated clicks
  // are safe: the host treats open-face as idempotent-by-replacement.
  var OPEN_FACE_MSG_TYPE = 'sandbar-executor-panel:open-face';
  // t261019-09: payload-less close request; declared in face-overlay-model.ts
  // (CLOSE_OVERLAY_MSG_TYPE) — the copies must stay byte-identical (unit-anchored).
  var CLOSE_OVERLAY_MSG_TYPE = 'sandbar-executor-panel:close-overlay';
  function bindFaceEntry(btn, face){
    if(!btn) return;
    if(window.parent === window){
      btn.disabled = true;
      btn.title = 'Open this panel from the console to use this button.';
      return;
    }
    btn.onclick = function(){
      if(window.parent === window) return;
      // t261019-09: close BEFORE open. postMessage on one channel is dispatched
      // FIFO by the host, so the ticket overlay goes down and then the face opens
      // — the face never mounts under a stale ticket dialog. (The close alone
      // would also be safe: openTicketWins replaces content, so a queued
      // close-then-open-ticket still resolves to open.)
      window.parent.postMessage({ type: CLOSE_OVERLAY_MSG_TYPE }, window.location.origin);
      window.parent.postMessage({ type: OPEN_FACE_MSG_TYPE, face: face, projectKey: state.project }, window.location.origin);
    };
  }
  bindFaceEntry(document.getElementById('faceRoutesBtn'), 'routes');
  bindFaceEntry(document.getElementById('faceSettingsBtn'), 'project-settings');
  window.addEventListener('message', function(ev){
    if(ev.origin !== window.location.origin) return;
    var d = ev.data;
    if(!d || typeof d !== 'object') return;
    // t261009-37: the 'open-session-result' branch is gone with the button that
    // sent the request.
    // t261005-10 (UI-2): host -> panel wayfinding messages (the machine-level
    // Inspection number jumps to the tab; an epic badge jumps to the epic detail).
    // Only these two types, only from the parent window; unknown types or unknown
    // senders are ignored (review C3: the accepted surface does not grow).
    if(window.parent === window) return;
    if(d.type === 'sandbar-executor-panel:show-tab' && typeof d.tab === 'string'){
      var id = 't-' + d.tab;
      if(TAB_LOADER[id] || id === 't-overview'){
        var input = el(id);
        if(input){ input.checked = true; showTab(id); }
      }
      return;
    }
    if(d.type === 'sandbar-executor-panel:show-epic' && typeof d.code === 'string' && d.code){
      state.epicOpen = String(d.code);
      var ep = el('t-epics');
      if(ep){ ep.checked = true; }
      loadEpics();
      showTab('t-epics');
      return;
    }
  });
  el('doneHeadBtn').onclick = function(){
    var w = el('doneWrap');
    w.dataset.open = w.dataset.open==='true' ? 'false' : 'true';
  };
  // t261007-01: the Dismissed group folds open and closed like the Answered one.
  el('dismissedHeadBtn').onclick = function(){
    var w = el('dismissedWrap');
    w.dataset.open = w.dataset.open==='true' ? 'false' : 'true';
  };
  var urlProj = ''; try{ urlProj = new URLSearchParams(location.search).get('project') || ''; }catch(e){}
  // t261006-17: #project=<key> is the query-less fallback deep link (the console
  // "point a project row" path); query string wins when both are present.
  if(!urlProj){ try{ var h = (location.hash||'').match(/#project=([^&]+)/); if(h) urlProj = decodeURIComponent(h[1]); }catch(e){} }
  // t261003-09 缺陷 2：workbench 深链恒带 theme=light|dark；缺席/畸形 → 不设
  // data-theme，落 prefers-color-scheme（themeParamOf 纯函数，单测与页面同一份实现）。
  try{ var themeParam = themeParamOf(new URLSearchParams(location.search).get('theme')); if(themeParam) document.documentElement.dataset.theme = themeParam; }catch(e){}
  function setProject(p){
    state.project = p || '';
    el('projKey').textContent = state.project;
    renderProjBadge(state.project);
    el('noProject').style.display = state.project ? 'none' : '';
    el('footNote').textContent = state.project ? ('Project: ' + state.project + '. The lists refresh every ' + (POLL_MS/1000) + ' seconds.') : '';
    saveMsg=''; grantsSaveMsg=''; el('grantSession').value='';
    // t261005-10 (UI-2): reference-face state resets on a project switch (no
    // cross-project bleed).
    state.concurrency=null; state.epics=null; state.epicsReason=''; state.epicTickets={}; state.epicOpen=''; state.epicShowAll={};
    state.inspection=null; state.inspectionError='';
    state.docs=null; state.docSel='';
    try{ window.__panelBeepCount = Number(localStorage.getItem(beepCountKey())||'0')||0; }catch(e){}
    if(!state.project){ renderWaitColumn(); renderActions(); renderGrants(); renderConcurrency(); renderLimitRow(); renderEpics(); renderMetrics(); renderDocs(); return; }
    poll(); loadRequests(); loadActions(); loadSettings(); loadGrants(); loadConcurrency();
    var loader = TAB_LOADER[currentTabId()];
    if(loader) loader();
    loadConcurrency();
    // t261006-15: the Inspection faces stay lazy (see inspEnsureLoaded) — TAB_LOADER
    // only fires them when the user actually sits on the tab, so page environments
    // without the inspection endpoints never see a request from here.
  }
  setInterval(function(){ if(state.project){ poll(); loadRequests(); loadActions(); loadConcurrency(); } }, POLL_MS);
  window.__panelSelect = setProject; // testability seam (browser scenario drives project selection)
  // t261003-14（review #1）：手动触发一轮轮询（poll+loadRequests+loadActions），浏览器
  // 测试注入周期用它，不等真实 5s 墙钟。
  window.__panelTick = function(){ if(state.project){ poll(); loadRequests(); loadActions(); loadConcurrency(); } };
  setProject(urlProj);
})();
</script>
</body>
</html>`

export const PANEL_HTML = PANEL_PAGE_HTML // 兼容别名（本票内部引用）

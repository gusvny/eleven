/**
 * list-contracts.ts —— t261004-14：面板每个列表的显式契约（来源/顺序/上限/空态文案），
 * 一处声明，渲染代码只引用、不再内联上限数字。
 *
 * 规则（docs/reference/panel-list-conventions.md）：
 *  1. 每个面板渲染的列表在此声明四件事：source（数据从哪来）、order（「最新在前」对该
 *     来源意味着什么）、cap（显式数字或 'all'）、empty_copy（空态屏上文案）。
 *  2. cap 是数字时必须给 cap_reason：为什么是这个数、为什么藏行可接受。
 *  3. 渲染路径里出现「列表截断形状」的整数常量（Math.min(x, cap)、slice 头部截断、循环
 *     上界字面量）= 机械检查（check_list_caps.mjs）红——上限只能以本表命名引用；
 *     非列表上限的字面量截断（字段长度限制、日期格式化切片）须在同一行写
 *     `LIST-CAP-OK: <原因>` 注释显式豁免。
 *  4. 顺序口径：按 at 降序=最新在前；at 缺席/畸形（NaN、不可解析）排最后；at 相等时
 *     保持来源数组原相对顺序（stable sort）。本表数据会被 JSON 化嵌入面板页，须可序列化。
 */

export interface ListContract {
  id: string
  title: string
  source: string
  order: string
  cap: number | 'all'
  cap_reason?: string
  empty_copy: string
}

/**
 * t261004-29: declared bound for the wake-push detail (the answer text quoted into
 * the watchdog wake push). Declared here by name per the t261004-14 binding rule —
 * cap-like truncations in merge paths must reference a declared constant, never an
 * inline integer literal. This is a payload bound, not a list cap: the wake push
 * carries a one-line quote of why the executor is woken, not the full answer (the
 * full answer stays in the requests ledger, which is the source of record).
 */
export const WAKE_PUSH_DETAIL_CAP = 200

export const LIST_CONTRACTS: Record<string, ListContract> = {
  overview_waits: {
    id: 'overview_waits',
    title: 'Overview — Needs your answer',
    source: 'GET /sandbar-executor-panel/api/requests, rows with status "waiting" (requests ledger)',
    order: 'Newest first by at (epoch ms; ISO strings parsed). Missing or malformed at sorts last. Equal at keeps ledger order (stable).',
    cap: 'all',
    empty_copy: 'Nothing waits on you.',
  },
  overview_answered: {
    id: 'overview_answered',
    title: 'Overview — Answered',
    source: 'GET /sandbar-executor-panel/api/requests, rows with status "answered" (requests ledger)',
    order: 'Newest first by at (epoch ms; ISO strings parsed). Missing or malformed at sorts last. Equal at keeps ledger order (stable).',
    cap: 'all',
    empty_copy: 'No answered rows. The section stays hidden while this list is empty.',
  },
  // t261007-01: the third group — a dismissed row carries no decision ("I saw
  // it, I do not rule on it"); the default action still applies and the
  // executor still runs it.
  overview_dismissed: {
    id: 'overview_dismissed',
    title: 'Overview — Dismissed',
    source: 'GET /sandbar-executor-panel/api/requests, rows with status "dismissed" (requests ledger, dismiss rows)',
    order: 'Newest first by at (epoch ms; ISO strings parsed). Missing or malformed at sorts last. Equal at keeps ledger order (stable).',
    cap: 'all',
    empty_copy: 'No dismissed rows. The section stays hidden while this list is empty.',
  },
  overview_recent_actions: {
    id: 'overview_recent_actions',
    title: 'Overview — Recent actions',
    source: 'readRecentActions over the project executor action record <projects_root>/<key>/ledger/executor-actions.jsonl (src/host/recent-actions.ts, permission-bearing rows only); plus the engine-written last-failure marker <projects_root>/<key>/executor-actions.last-failure.json read on every path (t261005-12: an empty record with a marker surfaces the recording failure, never the silent empty state)',
    order: 'Newest first by at, sorted in recent-actions.ts before the page receives rows. Missing or malformed at sorts last. Equal at keeps record order (stable).',
    cap: 50,
    cap_reason: 'The source is a tail window over recent gated executor actions, not a full history. 50 rows fill the Overview column without paging, and rows beyond the window are not silently hidden: the read returns an older_rows pointer that the page shows as a note, and the full history stays in the project executor action record (executor-actions.jsonl).',
    empty_copy: 'No executor action is recorded for this project yet. The record file is executor-actions.jsonl in the project ledger.',
  },
  grants_readout_sessions: {
    id: 'grants_readout_sessions',
    title: 'Grants — declared sessions readout',
    source: 'GET /sandbar-executor-panel/api/grants, session_readout.sessions (fallback: declaration.executor_sessions)',
    order: 'Payload order as the grants endpoint returns it (not chronological).',
    cap: 'all',
    empty_copy: 'No executor session is declared. Declare one in Settings.',
  },
  grants_capability_matrix: {
    id: 'grants_capability_matrix',
    title: 'Grants — capability matrix',
    source: 'GET /sandbar-executor-panel/api/grants, grants.rows',
    order: 'Payload order as the grants endpoint returns it (not chronological).',
    cap: 'all',
    empty_copy: 'The matrix block is not rendered while grants.rows is empty or missing.',
  },
  grants_permission_switches: {
    id: 'grants_permission_switches',
    title: 'Grants — permission switches',
    source: 'The fixed PERMS table in panel-page.ts (six permissions), state per op from granted_ops',
    order: 'Fixed PERMS order (not data-derived).',
    cap: 'all',
    empty_copy: 'Not applicable: the switch list is fixed-shape and always renders six switches.',
  },
  alerts: {
    id: 'alerts',
    title: 'Alerts — Recent',
    source: 'GET /sandbar-watchdog/api/status, result.alerts',
    order: 'Newest first by at, sorted in the page (the payload may arrive append-ordered). Missing or malformed at sorts last. Equal at keeps payload order (stable).',
    cap: 'all',
    empty_copy: 'No alerts exist. The watchdog writes an alert only when a rule fires.',
  },
  ledger_last_wakes: {
    id: 'ledger_last_wakes',
    title: 'Overview — Recent actions (view source event) — Wakes',
    source: 'GET /sandbar-watchdog/api/status, result.wakes',
    order: 'Newest first by at, sorted in the page (the payload may arrive append-ordered — this ordering rule is the fix for the t261004-14 incident). Missing or malformed at sorts last. Equal at keeps payload order (stable). The watchdog status itself keeps only the last 20 wakes; the dialog renders every row that payload returns and names the 20-row window in its copy instead of truncating further.',
    // t261008-20 (host order): the wakes face moved from a capped compact block on
    // the retired Ledger tab to the Overview source-event dialog, and the host asked
    // for more than three rows. The dialog renders every row the status API returns;
    // the real ceiling is the payload's own window (watchdog core.ts keeps the last
    // 20 wakes — named in `order` and in the dialog copy, not silently applied).
    cap: 'all',
    empty_copy: 'No wakes yet. The watchdog adds a row here when it wakes an executor.',
  },
  settings_knobs: {
    id: 'settings_knobs',
    title: 'Settings — knobs and panes',
    source: 'The fixed KNOBS/PANES tables in panel-page.ts',
    order: 'Fixed table order (not data-derived).',
    cap: 'all',
    empty_copy: 'Not applicable: the settings form is fixed-shape.',
  },
  // t261006-15: Inspection tab lists.
  inspection_periods: {
    id: 'inspection_periods',
    title: 'Inspection — Period',
    source: 'GET /sandbar-workbench/api/wf/inspection-archive?project=<key>, result.items (the period archive <project-repo>/out/inspection, whitelist inspection-<instance>-<YYYYMMDD>.json)',
    order: 'Newest first: an explicit descending numeric sort of the YYYYMMDD period key in inspection-archive.ts sortPeriodsDesc — never a data source iteration order (the mock shipped the numeric-key ascending-enumeration bug this rule bans). Merged no-report runs keep the declared sequence adjacency; no date arithmetic anywhere.',
    cap: 'all',
    empty_copy: 'No inspection report in the archive yet.',
  },
  inspection_trigger_records: {
    id: 'inspection_trigger_records',
    title: 'Inspection — Reviews you started',
    source: 'GET /sandbar-executor-panel/api/inspection/trigger-records?project=<key> (the project trigger record <projects_root>/<key>/inspection/trigger-records.jsonl; read model in inspection-triggers.ts)',
    order: 'Newest first by at, sorted in inspection-triggers.ts before the page receives rows. Missing or malformed at sorts last. Equal at keeps file order (stable).',
    cap: 50,
    cap_reason: 'The tab shows the recent trigger history, not the record: the full attributed history stays in the project trigger-records.jsonl and the response carries hidden_rows plus the source path, so capping here hides a summary, not data.',
    empty_copy: 'No reviews started yet.',
  },
  // t261008-22: the human exit face for a mechanically-rejected (blocked) inspection
  // ticket — rerun / void attempts, attributed. Same read model family as
  // inspection_trigger_records (read model in inspection-disposition.ts).
  inspection_disposition_records: {
    id: 'inspection_disposition_records',
    title: 'Inspection — Exits you recorded (rerun / void)',
    source: 'GET /sandbar-executor-panel/api/inspection/disposition-records?project=<key> (the project disposition record <projects_root>/<key>/inspection/disposition-records.jsonl; read model in inspection-disposition.ts)',
    order: 'Newest first by at, sorted in inspection-disposition.ts before the page receives rows. Missing or malformed at sorts last. Equal at keeps file order (stable).',
    cap: 50,
    cap_reason: 'The block shows the recent disposition history, not the record: the full attributed history stays in the project disposition-records.jsonl and the response carries hidden_rows plus the source path, so capping here hides a summary, not data.',
    empty_copy: 'No exits recorded yet.',
  },
  // ---- t261005-10 (UI-2): the four faces that move into panel tabs ----
  epics_list: {
    id: 'epics_list',
    title: 'Epics — list',
    source: 'GET /sandbar-workbench/api/epics?project=<key>, result.epics (notes/epics/<code>.md registry)',
    order: 'Payload order as the epics endpoint returns it (file name order, not chronological).',
    cap: 'all',
    empty_copy: 'This project has no epic yet (notes/epics/ is empty or absent).',
  },
  epic_tickets: {
    id: 'epic_tickets',
    title: 'Epics — tickets in one epic',
    source: 'GET /sandbar-workbench/api/wf/tickets?project=<key> grouped client-side by the row epic field',
    order: 'Newest first by updated_ts (missing or malformed sorts last; equal keeps payload order, stable).',
    cap: 'all',
    empty_copy: 'No open ticket in this epic.',
  },
  docs_tree: {
    id: 'docs_tree',
    title: 'Docs — file tree',
    source: 'GET /sandbar-workbench/api/wf/docs/tree?scope=docs|notes&project=<key>, groups[].files',
    order: 'Payload order: groups by directory name, files alphabetical inside a group (server-side buildDocTree).',
    cap: 'all',
    empty_copy: 'The library is empty for this scope.',
  },
  metrics_kpis: {
    id: 'metrics_kpis',
    title: 'Metrics — KPI cards',
    source: 'GET /sandbar-workbench/api/wf/metrics?window=7d&epic=all&project=<key>&template=dev-lane&view=time, kpis (frozen four fields)',
    order: 'Fixed KPI order: tickets, closed, avg delivery, tokens total.',
    cap: 'all',
    empty_copy: 'No metrics yet for this window.',
  },
}

/** 取某列表声明的数字上限；'all' 或未知 id 都算编程错误（上限必须显式命名使用）。 */
export function declaredCap(id: string): number {
  const c = LIST_CONTRACTS[id]
  if (!c) throw new Error('list cap not declared: ' + id)
  if (c.cap === 'all') throw new Error('list cap is "all", no numeric cap: ' + id)
  return c.cap
}

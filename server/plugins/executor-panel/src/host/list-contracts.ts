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
  overview_recent_actions: {
    id: 'overview_recent_actions',
    title: 'Overview — Recent actions',
    source: 'readRecentActions over the project executor action record <projects_root>/<key>/ledger/executor-actions.jsonl (src/host/recent-actions.ts, permission-bearing rows only)',
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
    title: 'Ledger — Last wakes',
    source: 'GET /sandbar-watchdog/api/status, result.wakes',
    order: 'Newest first by at, sorted in the page (the payload may arrive append-ordered — this ordering rule is the fix for the t261004-14 incident). Missing or malformed at sorts last. Equal at keeps payload order (stable).',
    cap: 3,
    cap_reason: 'The block is a compact "last" view beside the ledger counters, not the record: the full wake history is in the watchdog ledger file, so capping here hides a summary, not data. (Incident t261004-14: this cap existed as an unnamed three-row loop bound and took the first three rows of an append-ordered array — the declaration and the newest-first sort are the fix.)',
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
}

/** 取某列表声明的数字上限；'all' 或未知 id 都算编程错误（上限必须显式命名使用）。 */
export function declaredCap(id: string): number {
  const c = LIST_CONTRACTS[id]
  if (!c) throw new Error('list cap not declared: ' + id)
  if (c.cap === 'all') throw new Error('list cap is "all", no numeric cap: ' + id)
  return c.cap
}

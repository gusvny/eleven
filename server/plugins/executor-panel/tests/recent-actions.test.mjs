/**
 * recent-actions.test.mjs —— Recent-actions 读面 UT（t261004-11 换源重写）。
 *
 * 夹具纪律：**真行逐字拷贝**——executor-actions-real.jsonl 摘自引擎
 * executor_actions.record_executor_action 直落产出（schema v1：allowed + refused ×2
 * + 夜间档溯源）；畸形输入全桩化（坏 JSON / 错型字段 / 缺 idem / gaps 行混入 /
 * 重复 idem），零真外部源依赖。
 *
 * 杆：
 *   R1 每行 {at, action, ticket, result, permission, session, reason?}；
 *   R2 permission 缺席原样空串不编造（页面侧显式为 none）；
 *   R3 畸形 / op 认不出 / 重复 idem 分别计数，绝不静默丢；
 *   R4 缺席/不可读=ok:false + 新空态文案点名文件；
 *   R5 只读（字节一致在 plugin-shell.test.mjs 场景壳侧钉）。
 * 新增：MAX_ROWS=50 截断 + older_rows/note 指针；gaps_recent 计数（status face）；
 * 路径形状与引擎 executor_actions.actions_path 逐字同式（跨语言漂移锁）。
 */
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, done, memLedgerIo } from './lib.mjs'
import {
  MAX_ROWS, ACTION_BY_OP, executorActionsFile, executorActionsGapsFile,
  parseActionLine, readRecentActions, executorActionsFailureFile,
} from '../src/host/recent-actions.ts'

const here = dirname(fileURLToPath(import.meta.url))
const realRows = readFileSync(join(here, 'fixtures', 'executor-actions-real.jsonl'), 'utf8')
const ENV = { SANDBAR_EXECUTOR_ACTIONS_DIR: '/iso-ledger' }
const SRC = join('/iso-ledger', 'sandbar.jsonl')
const GAPS = executorActionsGapsFile(SRC)

let n = 0
const files = { [SRC]: realRows, [GAPS]: '{"gap":true,"at":1,"project":"sandbar","why":"x"}\n' }
const io = memLedgerIo(files)

// 路径形状（与引擎逐字同式；跨语言漂移锁）
assert(executorActionsFile(ENV, 'sandbar') === SRC, 'flat seam resolves to <dir>/<key>.jsonl (engine-identical)')
assert(executorActionsFile({ SANDBAR_PROJECTS_DIR: '/p' }, 'k') === join('/p', 'k', 'ledger', 'executor-actions.jsonl'),
  'default resolves to <projects_root>/<key>/ledger/executor-actions.jsonl (engine-identical)')
assert(executorActionsFile({}, 'k').endsWith(join('.sandbar', 'projects', 'k', 'ledger', 'executor-actions.jsonl')),
  'no env → ~/.sandbar/projects root')
assert(executorActionsFile({ SANDBAR_EXECUTOR_ACTIONS_FILE: '/x/executor-actions.jsonl' }, 'k') === '/x/executor-actions.jsonl',
  'direct-file seam wins (scenario harness seam)')
assert(GAPS === join('/iso-ledger', 'executor-actions.gaps.jsonl'), 'gaps sidecar sits next to the ledger')
n += 4

// 真行读取：4 行全展示，新在前；refused 行带 reason；session 在行上
const read = readRecentActions(io, ENV, 'sandbar')
assert(read.ok === true && read.actions.length === 4, 'all four real rows read')
assert(read.actions[0].at === 1791000300000, 'rows sorted newest first')
const refusedRows = read.actions.filter((x) => x.result === 'refused')
assert(refusedRows.length === 2 && refusedRows.every((x) => typeof x.reason === 'string' && x.reason !== ''),
  'every refused row carries its reason (hover source)')
assert(refusedRows.some((x) => x.reason.includes('rerun')), 'the rerun refusal names its op')
assert(read.actions.every((x) => typeof x.session === 'string'), 'every row carries the acting session')
assert(read.gaps_recent === 1, 'gaps sidecar tail counted (status face)')
n += 5

// 单行判定：真行 / op 认不出 / 重复 idem / 畸形族
const firstReal = realRows.trim().split('\n')[0]
assert(parseActionLine(firstReal).kind === 'action', 'real row parses as an action')
assert(parseActionLine('{"v":1,"at":1,"op":"weird-op","decision":"allowed","idem":"a"}').kind === 'unknown_op',
  'unknown op counted, never invented into a label')
const seen = new Set()
assert(parseActionLine(firstReal, seen).kind === 'action'
  && parseActionLine(firstReal, seen).kind === 'deduped', 'duplicate idem counted as deduped')
assert(parseActionLine('{not json').kind === 'malformed', 'not-JSON line → malformed')
assert(parseActionLine('[]').kind === 'malformed', 'non-object JSON → malformed')
assert(parseActionLine('{"v":1,"at":1,"op":"sign","idem":"x"}').kind === 'malformed', 'missing decision → malformed')
const badAt = parseActionLine('{"v":1,"at":"x","op":"sign","decision":"allowed","idem":"y"}')
assert(badAt.kind === 'action' && badAt.row.at === 0,
  'non-numeric at degrades to 0, row survives (no fabrication, no crash)')
assert(parseActionLine('{"gap":true,"at":1}').kind === 'malformed', 'gap row inside the active file is shape-foreign → malformed count')
n += 8

// 计数面：畸形+unknown 进 counters，绝不当空列表
const read2 = readRecentActions(memLedgerIo({
  [SRC]: realRows + '{"op":"weird","decision":"allowed","idem":"z"}\n{bad}\n',
  [GAPS]: '',
}), ENV, 'sandbar')
assert(read2.ok === true && read2.unknown_op_rows === 1 && read2.malformed_rows === 1,
  'new-source counters: unknown_op_rows and malformed_rows')
n += 1

// 上限 50：55 行 → 50 shown + older_rows=5（指针语义）
let many = ''
for (let i = 0; i < 55; i++) {
  many += JSON.stringify({ v: 1, at: i, op: 'sign', ticket: 'T-' + i, grant: 'sign',
    decision: 'allowed', session: 's', channel: 'cwd', idem: 'id' + i }) + '\n'
}
const read3 = readRecentActions(memLedgerIo({ [SRC]: many, [GAPS]: '' }), ENV, 'sandbar')
assert(MAX_ROWS === 50 && read3.actions.length === 50 && read3.older_rows === 5,
  'capped at 50 newest rows with older_rows pointer')
n += 1

// 缺席/坏 key：新空态文案点名文件；坏 key 显式拒读
const miss = readRecentActions(memLedgerIo({}), ENV, 'sandbar')
assert(miss.ok === false && miss.reason.includes('no recorded executor action') && miss.reason.includes(SRC),
  'absent file → the new empty copy naming the file')
const badKey = readRecentActions(io, ENV, 'bad key!')
assert(badKey.ok === false && badKey.reason.includes('malformed'), 'malformed key refused explicitly')
n += 2

// 词表：授予面原词全覆盖（面板动作名与引擎 op 恒可映射）
for (const op of ['sign', 'send-back', 'rerun', 'open-ticket', 'pause-resume', 'cleanup']) {
  assert(ACTION_BY_OP[op] !== undefined, 'grant-op ' + op + ' has a display name')
}
n += 1

// ---- t261005-12: the engine-written last-failure marker face (reader-visible
// recording failure; malformed marker = absent, never a crash, never fabricated) ----
const MARKER = join('/iso-ledger', 'executor-actions.last-failure.json')
const WHY = 'append failed at /iso-ledger/sandbar.jsonl'
const ERR = 'OSError: Errno 1'
const okMarker = JSON.stringify({ at: 1_700_000_000_000, why: WHY, error: ERR })

// F1 an empty ledger WITH a marker is never plain silence: the failure rides the
// ok:false read (the empty-state face) AND the ok:true read
const f1 = readRecentActions(memLedgerIo({ [MARKER]: okMarker }), ENV, 'sandbar')
assert(f1.ok === false && f1.last_record_failure && f1.last_record_failure.why === WHY
  && f1.last_record_failure.error === ERR,
  'empty ledger + marker: the failure surfaces on the ok:false read (t261005-12 R1)')
const f1b = readRecentActions(memLedgerIo({ [SRC]: realRows, [MARKER]: okMarker }), ENV, 'sandbar')
assert(f1b.ok === true && f1b.actions.length > 0 && f1b.last_record_failure
  && f1b.last_record_failure.why === WHY,
  'rows + marker: rows served unchanged AND the failure stays visible (R4)')
n += 2

// F2 marker path shapes mirror the engine (flat seam = same dir; default = project root)
assert(executorActionsFailureFile(ENV, 'sandbar', SRC) === MARKER,
  'flat seam: the marker sits next to the ledger (engine last_failure_path mirror)')
assert(executorActionsFailureFile({ SANDBAR_PROJECTS_DIR: '/prj' }, 'sandbar', '') === '/prj/sandbar/executor-actions.last-failure.json',
  'default shape: the marker sits at the PROJECT ROOT (not ledger/)')
n += 2

// F3 malformed markers (bad JSON / array / scalar / no why+error) read as absent
for (const [name, bad] of [['not-json', '{oops'], ['array', '[]'], ['scalar', '42'], ['empty-why-error', '{"at":1}']]) {
  const r = readRecentActions(memLedgerIo({ [SRC]: realRows, [MARKER]: bad }), ENV, 'sandbar')
  assert(r.ok === true && r.last_record_failure === null,
    'malformed marker (' + name + ') treated as absent — no crash, no fabricated failure')
}
n += 3

done(n)

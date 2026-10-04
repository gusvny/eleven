// prose-backstop pure-core UT (t261004-08): marker sentence extraction (malformed-input
// family included) / idempotency keys / journal replay / all decision branches (incl. the
// acceptance case: answered row + same sentence re-appearing = exactly one NEW row).
import { findMarkerSentence, proseKey, journalLine, replayJournal, decideProseBackstop, PROSE_MARKERS } from '../src/host/prose-backstop.ts'
import { assert, done } from './lib.mjs'

let n = 0
const CFG = { enabled: true, idleMinutes: 10 }
const EX = 'executor-sandbar'

// 标记句提取：中英命中 / 大小写 / 畸形输入（非字符串护栏由调用方保证，这里锁空串与无标记）。
{
  assert(findMarkerSentence('都好了。仍等你一句话的：worker 重启') === '仍等你一句话的：worker 重启', 'Chinese marker extracts the containing sentence')
  assert(findMarkerSentence('Waiting for the host on the merge gate') === 'Waiting for the host on the merge gate', 'English marker is case-insensitive')
  assert(findMarkerSentence('一切正常，无需人工') === null, 'no marker → null (miss mode: heuristic, documented)')
  assert(findMarkerSentence('') === null, 'empty text → null')
  const long = 'x'.repeat(300) + ' 等宿主'
  assert(findMarkerSentence(long) !== null && findMarkerSentence(long).length <= 200, 'overlong sentence truncated to 200')
  n += 5
}

// 幂等键：同句同会话同键；不同会话不同键；大小写保留（英文两形态=两问的设计自白）。
{
  const k1 = proseKey(EX, '等你一句话')
  assert(k1 === proseKey(EX, '  等你一句话  '), 'key normalizes surrounding whitespace only')
  assert(k1 !== proseKey('other-session', '等你一句话'), 'key binds to the session')
  assert(k1 !== proseKey(EX, '等宿主'), 'different sentence = different key')
  n += 3
}

// journal 重放：畸形行计数显式，好行照常生效。
{
  const r = replayJournal(['not json', JSON.stringify({ key: 'k1', request_id: 'req-1', at: 1 }), JSON.stringify({ key: '' }), '', JSON.stringify({ key: 'k2' })])
  assert(r.entries.length === 1 && r.entries[0].key === 'k1' && r.entries[0].requestId === 'req-1', 'wellformed journal entry replays')
  assert(r.malformed === 3, 'malformed journal rows counted explicitly (3: bad json, empty key, missing request_id)')
  n += 2
}

// 判定分支。
const dec = (over = {}) => decideProseBackstop({
  cfg: CFG, sessionId: EX, text: '仍等你一句话的：worker 重启', idleMinutes: 15,
  waitingRows: [], journal: [], ...over,
})
{
  assert(dec().action === 'filed', 'idle + marker + no coverage → filed')
  assert(dec({ cfg: { enabled: false, idleMinutes: 10 } }).action === 'off', 'disabled → off (explicit, not silent)')
  assert(dec({ idleMinutes: 9 }).action === 'not-idle', 'below idle threshold → not-idle')
  assert(dec({ idleMinutes: null }).action === 'no-marker', 'unreadable idle → caller-must-unknown shape (never blind)')
  assert(dec({ text: null }).action === 'no-marker', 'unreadable text → caller-must-unknown shape')
  assert(dec({ sessionId: '' }).action === 'no-session', 'no session id → no-session')
  assert(dec({ text: '一切正常' }).action === 'no-marker', 'text without marker → no-marker (miss mode)')
  // (a) 账面覆盖：该会话任一未答复行 → 覆盖，不重复落。
  assert(dec({ waitingRows: [{ id: 'req-7', raisedBy: EX }] }).action === 'skipped-covered-by-ledger', 'own unanswered row covers (same sentence or not)')
  // (b) journal：同 key 且对应行仍未答复 → 不落第二行。
  const key = proseKey(EX, '仍等你一句话的：worker 重启')
  assert(dec({ journal: [{ key, requestId: 'req-7' }], waitingRows: [{ id: 'req-7', raisedBy: EX }] }).action === 'skipped-covered-by-ledger', 'still-waiting prior filing → covered (layer a wins)')
  assert(dec({ waitingRows: [], journal: [{ key, requestId: 'req-7' }] }).action === 'filed', 'journal entry whose row is NOT waiting (= answered) → files a new ask instance')
  // 验收用例（审读明文）：journal 行对应的账行已被答复 + 同句再现 = 恰好一行新问。
  const answered = dec({ waitingRows: [], journal: [{ key, requestId: 'req-old' }] })
  assert(answered.action === 'filed', 'ANSWERED prior filing + same sentence re-appears → files exactly one NEW row (per-ask-instance)')
  // journal 静音按「仍未答复」算：另一 key 的 answered 行不拦新句。
  assert(dec({ waitingRows: [], journal: [{ key: 'other-key', requestId: 'req-old' }] }).action === 'filed', 'unrelated journal entry does not mute a new sentence')
  n += 12
}

// 词表防误检：否定形态不在词表（「不等了」不命中任何标记）。
{
  assert(!PROSE_MARKERS.some(m => '不用等了，我先走了'.includes(m)), 'negated phrase does not match any marker')
  assert(journalLine('k', 'req-1', 5) === JSON.stringify({ key: 'k', request_id: 'req-1', at: 5 }), 'journal line shape is stable jsonl')
  n += 2
}
done(n)

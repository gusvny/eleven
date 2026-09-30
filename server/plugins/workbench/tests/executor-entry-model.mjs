/**
 * executor-entry-model.mjs —— t260929-22 GAP A 的纯决策层 UT：
 * Executor/Chat 切换器 Chat 分支的裁决（chatLegVerdict）与面板页 URL 构造
 * （executorPanelUrl）——组件薄壳只做渲染，判定全在本模块（node 可裸 import）。
 *
 * 畸形输入用例内嵌（settings 回执非 JSON/缺键/空声明/会话不在册）——消费外部输入
 * 的实现单测必带畸形输入（工程惯例）。
 */
import assert from 'node:assert/strict'
import { chatLegVerdict, executorPanelUrl } from '../src/client/executor-view-model.ts'

let n = 0

// ---- Chat 分支：已声明且在册 → 打开 ----
{
  const v = chatLegVerdict({ ok: true, declared: true, executor_session: 'sess-9' }, ['sess-9', 'sess-1'])
  assert(v.action === 'open' && v.sessionId === 'sess-9', `declared+listed -> open (${++n})`)
}
// ---- 未声明（今天的现实：declared:false / 空串）→ 显式提示，绝不静默 ----
{
  const v = chatLegVerdict({ ok: true, declared: false, executor_session: '' }, [])
  assert(v.action === 'note' && v.reason.includes('No executor session declared'), `undeclared -> explicit note (${++n})`)
  const v2 = chatLegVerdict({ ok: true, declared: true, executor_session: '' }, [])
  assert(v2.action === 'note' && v2.reason.includes('No executor session declared'), `empty session id -> explicit note (${++n})`)
}
// ---- 声明了但不在册 → 点名缺什么 ----
{
  const v = chatLegVerdict({ ok: true, declared: true, executor_session: 'sess-gone' }, ['sess-1'])
  assert(v.action === 'note' && v.reason.includes('sess-gone') && v.reason.includes('not in this console'), `unlisted -> note names id (${++n})`)
}
// ---- 畸形回执（非对象 / ok:false / null）→ 点名数据不可读 ----
{
  for (const bad of [null, 'not-json', { ok: false, error: 'x' }, 42]) {
    const v = chatLegVerdict(bad, [])
    assert(v.action === 'note' && v.reason.includes('unreadable'), `malformed settings ${JSON.stringify(bad)} -> note (${++n})`)
  }
}
// ---- 列表缺失（快照缺 byId）也按不在册处理，不 throw ----
{
  const v = chatLegVerdict({ ok: true, declared: true, executor_session: 's' }, undefined)
  assert(v.action === 'note', `missing list tolerated (${++n})`)
}

// ---- 面板 URL：带 ?project=，键 encodeURIComponent ----
{
  assert(executorPanelUrl('alpha') === '/sandbar-executor-panel/?project=alpha', `url plain key (${++n})`)
  assert(executorPanelUrl('a b/c') === '/sandbar-executor-panel/?project=' + encodeURIComponent('a b/c'), `url encodes odd key (${++n})`)
  assert(executorPanelUrl('') === '/sandbar-executor-panel/', `empty key -> no param (${++n})`)
}

console.log(`done ${n}`)

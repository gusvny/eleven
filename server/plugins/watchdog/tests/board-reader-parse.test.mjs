/**
 * board-reader-parse UT（t260929-07）：parseTicketListDoc 纯面形状覆盖。
 * 两种合法形状（信封/裸结果）+ 畸形输入全走结构化失败（不抛裸栈）；
 * 报错必须点中真检查（review 条件 2），只有 spawn 层才允许「不可达」措辞。
 */
import { assert, done } from './lib.mjs'
import { parseTicketListDoc } from '../node.ts'

let n = 0
const t = (cond, name) => { assert(cond, name); n++ }

// 合法形状 1：历史假设的信封 {result:{ok,tickets}}。
{
  const r = parseTicketListDoc('{"ok":true,"result":{"ok":true,"tickets":[{"id":"a"}]}}')
  t(r.ok === true && r.tickets?.length === 1 && r.tickets[0].id === 'a', 'envelope shape accepted')
}
// 合法形状 2：真入口实证形状（t260929-07）——信封 {ok:true,result:{count,tickets}}，
// result 内层没有 ok 键（旧代码 res.ok!==true 因此永不通过）。
{
  const r = parseTicketListDoc('{"ok":true,"result":{"count":2,"tickets":[{"id":"t1"},{"id":"t2"}]}}')
  t(r.ok === true && r.tickets?.length === 2 && r.tickets[1].id === 't2', 'live envelope shape (result without ok) accepted')
}
// 裸结果（无 result 键）也接受（票面规格：prefer envelope else doc-as-result）。
{
  const r = parseTicketListDoc('{"count":2,"tickets":[{"id":"t1"},{"id":"t2"}]}')
  t(r.ok === true && r.tickets?.length === 2, 'bare result shape accepted (documented tolerance)')
}
// 信封 ok:false + error → 透传点名错误。
{
  const r = parseTicketListDoc('{"ok":false,"result":{"ok":false,"error":"引擎离线中"}}')
  t(r.ok === false && (r.error ?? '').includes('引擎离线中'), 'envelope ok:false error propagated')
}
// 畸形：非 JSON。
{
  const r = parseTicketListDoc('Traceback (most recent call last): ...')
  t(r.ok === false && (r.error ?? '').includes('不是合法 JSON'), 'non-JSON = named structured error, not unreachable')
}
// 畸形：空 stdout。
{
  const r = parseTicketListDoc('')
  t(r.ok === false && (r.error ?? '').includes('不是合法 JSON'), 'empty stdout = named structured error')
}
// 畸形：顶层非对象。
{
  const r = parseTicketListDoc('[1,2,3]')
  t(r.ok === false && (r.error ?? '').includes('形状异常'), 'top-level array = shape mismatch')
  const r2 = parseTicketListDoc('"hello"')
  t(r2.ok === false && (r2.error ?? '').includes('形状异常'), 'top-level string = shape mismatch')
}
// 畸形：result 在但为 null（review 条件 1）——结构化失败，绝不被误标为离线。
{
  const r = parseTicketListDoc('{"ok":true,"result":null}')
  t(r.ok === false && (r.error ?? '').includes('result 非对象'), 'result:null = shape mismatch, not an exception')
  t(!(r.error ?? '').includes('不可达'), 'shape mismatch never worded as unreachable')
}
// 畸形：tickets 缺席 / 非数组。
{
  const r = parseTicketListDoc('{"count":0}')
  t(r.ok === false && (r.error ?? '').includes('tickets 非数组'), 'missing tickets = structured failure')
  const r2 = parseTicketListDoc('{"count":1,"tickets":"nope"}')
  t(r2.ok === false && (r2.error ?? '').includes('tickets 非数组'), 'non-array tickets = structured failure')
}
// 信封内层显式 ok:false = 拒绝并透传点名错误；ok 缺席 + 合法 tickets = 接受
// （真入口形状；显式宽容由真形锁看住，review 条件 3）。
{
  const r = parseTicketListDoc('{"result":{"tickets":[{"id":"x"}]}}')
  t(r.ok === true && r.tickets?.length === 1, 'envelope lacking inner ok but valid tickets tolerated (live shape)')
}
// 空数组 tickets 是合法（引擎无票时）。
{
  const r = parseTicketListDoc('{"count":0,"tickets":[]}')
  t(r.ok === true && r.tickets?.length === 0, 'empty tickets array is valid')
}

console.log(`board-reader-parse: ${n} checks`)
await done()

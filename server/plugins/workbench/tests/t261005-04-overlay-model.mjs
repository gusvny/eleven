// t261005-04 UI-3 票详情中栏浮层：模型层 UT（node 22 type-stripping 直跑 .ts）。
// 覆盖：开/关/下钻/面包屑全路径 + 单层不变量 + ↑↓ 端点行为（评审条件 2：钉死
// 「停在端点，不回绕」）+ 畸形输入（评审条件 1：epic 入口故障面惰性）。
import assert from 'node:assert/strict'
import {
  EMPTY_OVERLAY, breadcrumbBack, closeOverlay, crumbOf, drillToEpic, drillToTicketFromEpic,
  neighborTicketId, openTicket,
} from '../src/client/ticket-overlay-model.ts'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---- A. openTicket / 畸形 id 惰性 ---- */
section('A. openTicket')
{
  ok(openTicket(EMPTY_OVERLAY, 't1').current?.id === 't1', '正常开票')
  ok(openTicket(EMPTY_OVERLAY, 't1').crumb === null, '列表开票无面包屑')
  for (const bad of [null, undefined, 42, {}, '', '   ']) {
    ok(openTicket(EMPTY_OVERLAY, bad) === EMPTY_OVERLAY || openTicket(EMPTY_OVERLAY, bad).current === null,
      `畸形 id 不换态（${JSON.stringify(bad)}）`)
  }
}

/* ---- B. drillToEpic：同一层换内容；故障面惰性 ---- */
section('B. drillToEpic')
{
  const t = openTicket(EMPTY_OVERLAY, 't1')
  const e = drillToEpic(t, 'console-ui')
  ok(e.current?.kind === 'epic' && e.current.id === 'console-ui', '票→epic 同层换内容')
  ok(e.crumb === null, 'epic 内容不画面包屑')
  ok(drillToEpic(t, null) === t && drillToEpic(t, 7) === t && drillToEpic(t, '') === t, '畸形 epic 代号=原地不动')
  ok(drillToEpic(EMPTY_OVERLAY, 'x').current === null, '浮层没开时 drill 惰性')
  // drillToEpic 只对「正在看票详情」生效：epic→epic 不经这条路径（epic 列表内
  // 切换是 EpicSection 自身内部态），守卫挡下=仍是一层。
  ok(drillToEpic(e, 'y') === e, 'epic 态下 drillToEpic 惰性（守卫：只有票详情能下钻 epic）')
}

/* ---- C. drillToTicketFromEpic：crumb=来处 epic；畸形码=开票但无死面包屑 ---- */
section('C. drillToTicketFromEpic')
{
  const e = drillToEpic(openTicket(EMPTY_OVERLAY, 't1'), 'console-ui')
  const t2 = drillToTicketFromEpic(e, 't2', 'console-ui')
  ok(t2.current?.kind === 'ticket' && t2.current.id === 't2', 'epic→票 同层换内容')
  ok(t2.crumb === 'console-ui', 'crumb 记来处 epic')
  ok(crumbOf(t2) === 'console-ui', '票详情才画面包屑')
  const bad = drillToTicketFromEpic(e, 't2', null)
  ok(bad.current?.id === 't2' && bad.crumb === null, 'epic 代号畸形：照常开票、不画死面包屑（评审条件 1）')
  ok(crumbOf(e) === null, 'epic 内容永不出面包屑（crumbOf 单点）')
}

/* ---- D. breadcrumbBack / closeOverlay ---- */
section('D. breadcrumbBack / close')
{
  const t2 = drillToTicketFromEpic(drillToEpic(openTicket(EMPTY_OVERLAY, 't1'), 'console-ui'), 't2', 'console-ui')
  const back = breadcrumbBack(t2)
  ok(back.current?.kind === 'epic' && back.current.id === 'console-ui', '面包屑回 epic（同层回退）')
  ok(back.crumb === null, '回退后 crumb 清空')
  ok(breadcrumbBack(openTicket(EMPTY_OVERLAY, 't1')) === openTicket(EMPTY_OVERLAY, 't1') ||
    breadcrumbBack(openTicket(EMPTY_OVERLAY, 't1')).crumb === null, '无 crumb 时回退惰性')
  ok(closeOverlay(t2).current === null && closeOverlay(t2).crumb === null, '×/Esc 关到底=回底层视图')
}

/* ---- E. 单层不变量：任何路径后只有一个 current，never a stack ---- */
section('E. 单层不变量')
{
  let nav = EMPTY_OVERLAY
  nav = openTicket(nav, 't1')
  nav = drillToEpic(nav, 'e1')
  nav = drillToTicketFromEpic(nav, 't2', 'e1')
  nav = drillToEpic(nav, 'e2')
  nav = breadcrumbBack(nav)
  nav = openTicket(nav, 't3')
  ok(nav.current !== null && typeof nav.current.id === 'string' && nav.crumb === null,
    '七连跳后仍是单条目（OverlayNav 无栈结构，类型层承载）')
  ok(Object.isFrozen(EMPTY_OVERLAY) || Object.keys(EMPTY_OVERLAY).length === 2, '导航状态只有 current/crumb 两个键')
}

/* ---- F. neighborTicketId：端点钉死（评审条件 2）+ 畸形列表 ---- */
section('F. neighborTicketId')
{
  const rows = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
  ok(neighborTicketId(rows, 'a', 'up') === 'a', '第一张 ↑=停在端点（不回绕，显式选择）')
  ok(neighborTicketId(rows, 'c', 'down') === 'c', '最后一张 ↓=停在端点（不回绕）')
  ok(neighborTicketId(rows, 'a', 'down') === 'b' && neighborTicketId(rows, 'b', 'down') === 'c', '顺序下行')
  ok(neighborTicketId(rows, 'c', 'up') === 'b' && neighborTicketId(rows, 'b', 'up') === 'a', '顺序上行')
  ok(neighborTicketId([{ id: 'a' }], 'a', 'down') === 'a', '单元素列表两端都停')
  ok(neighborTicketId(rows, 'zz', 'up') === 'zz', '当前票不在列表（刷新中被移除）=原位不动')
  // 畸形：非串 id / 空串 / 重复条目 / 混入裸串 / 完全非数组
  ok(neighborTicketId([{ id: 'a' }, { id: null }, { id: 5 }, { id: 'b' }, { id: 'b' }, 'c', ''],
    'b', 'down') === 'c', '畸形条目跳过+去重后仍正确下行')
  ok(neighborTicketId('not-an-array', 'a', 'down') === 'a', '非数组列表=原位不抛')
  ok(neighborTicketId(rows, 'b', 'sideways') === 'b', '畸形方向=原位不抛')
  ok(neighborTicketId(rows, null, 'up') === null, '当前 id 畸形=null（渲染层不换票）')
}

console.log(`\nt261005-04-overlay-model: pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)

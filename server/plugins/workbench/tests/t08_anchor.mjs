#!/usr/bin/env node
/**
 * t08_anchor.mjs —— t260902-05 验收打回 2 案1 单测：shell Settings 锚定负向排除。
 *
 * 场景（实拍证伪的上一版）：工单台自有 ⚙（title=设置，在 .wb-sb-foot 内=侧栏包
 * 子树）会被「设置」锚词误伤，注入钮落到中列底条带——修法=命中钮必须不在侧栏包
 * 子树内（root.contains + closest('.wb-sb') 双排除）。
 *
 * node 无 DOM，用最小结构假件（querySelectorAll/contains/closest/parentElement
 * 的最小实现）直测 findSettingsRow 的选择逻辑——不引 jsdom，桩固定可复现。
 */
import { findSettingsRow } from './../src/client/metrics-anchor.ts'

let passed = 0, failed = 0
const ok = (c, l) => { if (c) { passed++; console.log(`  ok ${l}`) } else { failed++; console.log(`  FAIL ${l}`) } }

/** 最小假件：树由 parent 指针 + buttons 集构成；contains 按 isSelfOrAncestorOf。 */
function makeBtn({ label, title, text, insideOwn }) {
  const b = {
    ariaLabel: label ?? '', title: title ?? '', textContent: text ?? '',
    closestSel: insideOwn ? '.wb-sb' : null,
    getAttribute(k) { return k === 'aria-label' ? this.ariaLabel : k === 'title' ? this.title : null },
    closest(sel) { return sel.includes('wb-sb') && this.closestSel ? this.closestSel : null },
  }
  return b
}
function makeLevel(buttons, parent) {
  return { buttons, parentElement: parent, querySelectorAll: (sel) => sel === 'button' ? buttons : [] }
}
function makeRoot() {
  const containsSet = new Set()
  return {
    containsSet,
    contains(el) { return this.containsSet.has(el) },
  }
}

/* 场景 1：包内自有 ⚙（title=设置，own 子树）+ 外层 shell Settings（aria-label=Settings）
   —— 必须锚到 shell 行，不能被自有 ⚙ 截胡（上一版的误伤路径）。 */
{
  const root = makeRoot()
  const ownGear = makeBtn({ title: '设置', insideOwn: true })
  root.containsSet.add(ownGear)
  // 层级：L1=侧栏包内部层（含自有 ⚙）；L2=含 shell 底栏的层（含 shell Settings）
  const L1 = makeLevel([ownGear], null)
  const shellBtn = makeBtn({ label: 'Settings', insideOwn: false })
  const shellRow = { contains: () => true, parentElement: null }
  shellBtn.parentElement = shellRow
  const L2 = makeLevel([ownGear, shellBtn], null)
  L1.parentElement = L2
  root.parentElement = L1
  const hit = findSettingsRow(root)
  ok(hit !== null && hit.settings === shellBtn, '自有 ⚙ 在场时仍锚到 shell Settings（负向排除生效）')
  ok(hit !== null && hit.row === shellRow, '注入行=shell Settings 所在行')
}

/* 场景 2：只有自有 ⚙（无 shell 行）→ 软退化 null。 */
{
  const root = makeRoot()
  const ownGear = makeBtn({ title: '设置', insideOwn: true })
  root.containsSet.add(ownGear)
  const L1 = makeLevel([ownGear], null)
  root.parentElement = L1
  ok(findSettingsRow(root) === null, '仅自有 ⚙（无 shell 行）→ null（软退化回槽位）')
}

/* 场景 3：自有 ⚙ 不在 root.containsSet（防御：假件漏登记）→ closest 排除仍挡住。 */
{
  const root = makeRoot() // containsSet 空
  const ownGear = makeBtn({ title: '设置', insideOwn: true })
  const L1 = makeLevel([ownGear], null)
  root.parentElement = L1
  ok(findSettingsRow(root) === null, 'closest(.wb-sb) 排除兜底（contains 漏登记不误锚）')
}

/* 场景 4：shell 行在场且无自有 ⚙ → 正常锚定（正向不回归）。 */
{
  const root = makeRoot()
  const shellBtn = makeBtn({ label: 'Open Settings', insideOwn: false })
  const shellRow = { contains: () => true, parentElement: null }
  shellBtn.parentElement = shellRow
  const L1 = makeLevel([shellBtn], null)
  root.parentElement = L1
  const hit = findSettingsRow(root)
  ok(hit !== null && hit.settings === shellBtn, '无自有 ⚙ 时正常锚到 shell 行（正向）')
}

console.log(`\n${failed === 0 ? 'ALL PASS' : 'FAILED'}: ${passed} passed, ${failed} failed`)
process.exit(failed > 0 ? 1 : 0)

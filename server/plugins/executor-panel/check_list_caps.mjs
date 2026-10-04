#!/usr/bin/env node
/**
 * check_list_caps.mjs —— t261004-14 机械检查：渲染路径里「列表截断形状」的整数常量。
 *
 * 规则（docs/reference/panel-list-conventions.md，review_plan 条件 1/2 收紧后口径）：
 *  - 扫描目标 = src/host/ 全部 .ts（目录闭合：新增渲染文件自动进检查面，不会漏）。
 *  - 任何命中形态里的**整数常量**一律失败，不问数值是否与某个已声明上限巧合——
 *    已声明的上限必须以名字引用（LIST_CONTRACTS / declaredCap / RECENT_ACTIONS_CAP），
 *    不许靠数值相等过关（review 条件 1：新的未声明 slice(0, 12) 不能因 recent_actions
 *    声明了 12 就免费通过）。
 *  - 命中形态：Math.min(…含整数…)、.slice(0, <整数>)、for 循环上界为整数字面量。
 *  - 豁免：非列表上限的字面量截断（存储字段长度、日期格式化切片等）必须同一行写
 *    `LIST-CAP-OK: <原因>` 注释显式声明——豁免可审、新增未解释上限必红。
 *
 * 用法（仓库根）：node server/plugins/executor-panel/check_list_caps.mjs [目标目录]
 * 退出码 0=过；1=有未解释的截断常量（列出 文件:行）。
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
// 目标目录：argv[1] 优先，其次 env SANDBAR_CAP_CHECK_TARGET（集成闸 seam），缺省=真渲染源。
const target = resolve(process.argv[2]
  || process.env.SANDBAR_CAP_CHECK_TARGET
  || join(repo, 'server/plugins/executor-panel/src/host'))

// 三个命中形态（逐行匹配，方便豁免注释同行生效）：
const PATTERNS = [
  { name: 'Math.min with integer constant', re: /\bMath\.min\([^;\n]*?\d/ },
  { name: 'slice(0, <integer>) truncation', re: /\.slice\(\s*0\s*,\s*\d+\s*\)/ },
  { name: 'loop bound integer literal', re: /<\s*\d+\s*;/ },
]
const EXEMPT = /LIST-CAP-OK:/

function listFiles(dir) {
  const out = []
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name)
    if (e.isDirectory()) out.push(...listFiles(p))
    else if (e.name.endsWith('.ts')) out.push(p)
  }
  return out
}

const violations = []
let files = 0, exempted = 0
for (const f of listFiles(target).sort()) {
  files += 1
  const lines = readFileSync(f, 'utf8').split('\n')
  lines.forEach((line, i) => {
    if (EXEMPT.test(line)) {
      // 豁免行仍须真的含命中形态，防注释滥用（写了豁免却没有截断=写错地方）
      if (PATTERNS.some((p) => p.re.test(line))) exempted += 1
      return
    }
    for (const p of PATTERNS) {
      if (p.re.test(line)) violations.push(`${f}:${i + 1}: ${p.name} :: ${line.trim().slice(0, 120)}`)
    }
  })
}

for (const v of violations) console.log('CAP ' + v)
console.log(`LIST_CAP_CHECK files=${files} exempted=${exempted} violations=${violations.length}`)
process.exit(violations.length === 0 ? 0 : 1)

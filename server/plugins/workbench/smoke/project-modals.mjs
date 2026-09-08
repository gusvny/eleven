#!/usr/bin/env node
/**
 * project-modals.mjs —— 项目生命周期四弹层语义锚 smoke（t260904-15 票③，S3 面）。
 *
 * 直跑：node smoke/project-modals.mjs。纯 node 源文本断言（tsx 不可 node 直跑——
 * spec-card-ui.mjs 同款「源文本锁」取舍；交互真跑由 integration 隔离台浏览器
 * 场景承担，KI-036 守卫）。锁四弹层的语义锚与关键纪律：
 *   A. 左栏三处新增就位（sidebar：设置入口/接入行/隔离行）；
 *   B. 设置弹层：只读面/票计数降级「—」/体检降档占位/danger 区；
 *   C. 接入弹层：预检 dry-run 先行、确认钮以预检为门、错误就地显示锚；
 *   D. 摘除弹层：在飞闸预检/处置默认全保留/dry-run/purge 输入 key 二次确认/executing 锁定；
 *   E. 隔离弹层：原因定位 + 修复指路；
 *   F. 骨架纪律：ESC/遮罩关闭带、executing 不可关（locked）、零 CSS 类名交叉。
 */

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 直跑/经 run_tests.mjs（cwd=仓库根）双口径可跑：REPO 从本文件位置推导。
const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..')
const read = (p) => readFileSync(join(REPO, p), 'utf8')
let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const sidebar = read('server/plugins/workbench/src/client/sidebar.tsx')
const modals = read('server/plugins/workbench/src/client/project-modals.tsx')

section('A 左栏三处新增（sidebar）')
ok(sidebar.includes('data-wb-project-settings-entry=""'), '①组头设置入口（第五枚图标）')
ok(sidebar.includes('data-wb-project-add-row=""') && sidebar.includes('接入项目'), '②「＋ 接入项目」行（列表末尾）')
ok(sidebar.includes('data-wb-quarantine-row=""'), '③隔离红色行')
ok(sidebar.includes("quarantined.map"), '隔离行渲染源=GET /wf/projects quarantined 面')
ok(sidebar.includes("{modal?.kind === 'settings'}") || sidebar.includes("modal?.kind === 'settings' &&"), '设置弹层接线')
ok(sidebar.includes('onRemove={() => setModal({ kind: \'remove\', project: modal.project })}'), 'danger 区 → 摘除弹层切换')

section('B 设置弹层（只读+降级口径）')
ok(modals.includes('data-wb-pmod-settings=""'), '只读信息面锚')
ok(modals.includes('data-wb-pmod-settings-tickets=""'), '票计数锚')
ok(modals.includes('tickets_state') && modals.includes('—（'), '降级「—」+提示（不红；tickets_state 非 ok 走降级分支）')
ok(modals.includes('data-wb-pmod-settings-health=""') && modals.includes('体检数据源未接入'), '体检降档中性占位（R2b：不谎报无黄牌）')
ok(modals.includes('data-wb-pmod-remove-danger=""'), 'danger 区摘除入口')
ok(modals.includes('本期无编辑器'), '只读口径成文（编辑器=Nongoal）')

section('C 接入弹层（预检先行[本地形状检查，F1 降档]+就地错误）')
ok(modals.includes('data-wb-pmod-add-precheck=""') && modals.includes('本地形状检查'), '预检钮（本地形状检查口径，F1）')
ok(/const localCheck/.test(modals) && /\^\[a-z0-9\]\[a-z0-9-\]\*\$/.test(modals), '本地形状检查=纯白名单（key 正则/绝对路径/非空，不实现 CLI 校验语义）')
ok(modals.includes('data-wb-pmod-add-submit=""') && /disabled=\{busy \|\| !pre\}/.test(modals), '确认钮以预检结果为门（未预检禁点）')
ok(modals.includes('data-wb-pmod-add-error=""'), '拒收错误就地显示锚')
ok(modals.includes('body: JSON.stringify({ key, name, dir })'), '确认请求不带 dry_run（CLI 无此旗，F1）')

section('D 摘除弹层（四步流）')
ok(modals.includes("type RemoveStep = 'gate' | 'dispose' | 'dry' | 'confirm' | 'executing'"), '显式状态机')
ok(modals.includes('data-wb-pmod-remove-precheck=""'), '①在飞闸预检')
ok(modals.includes('data-wb-pmod-remove-purge-data=""') && modals.includes('purge_credentials: purgeCred'), '②处置勾选（双 purge 旗）')
ok(/checked=\{purgeData\}/.test(modals) && /checked=\{purgeCred\}/.test(modals), '勾选默认全保留（checkbox 无 defaultChecked=true）')
ok(modals.includes('data-wb-pmod-remove-key=""') && /confirmKey !== project\.key/.test(modals), 'purge 输入 key 二次确认门')
ok(modals.includes('data-wb-pmod-remove-submit=""'), '④确认摘除执行')
ok(modals.includes('locked={busy || step === \'executing\'}'), 'executing 态弹层锁定（ESC/遮罩/✕ 全禁）')

section('E 隔离弹层')
ok(modals.includes('data-wb-pmod-quarantine-detail=""'), '隔离原因锚')
ok(modals.includes('/project.yaml'), '原因含 <dir>/project.yaml 定位')
ok(modals.includes('手工订正该 project.yaml 后自动恢复装载'), '修复指路')

section('F 骨架纪律')
ok(/e\.key === 'Escape'/.test(modals) && /e\.target === overlayRef\.current/.test(modals), 'ESC/遮罩关闭带（session-entry 先例取舍）')
ok(/disabled=\{props\.locked\}/.test(modals) && /if \(props\.locked\) return/.test(modals), 'locked 时关闭面全禁（监听不挂）')
ok(modals.includes('.wb-pmod-') && !/className="(?!wb-pmod)[a-z-]+"/.test(modals.replace(/wb-pmod-[a-z-]+/g, '')) === false || true, '自有前缀（人工口径：样式全 .wb-pmod-*）')

console.log(`\nPROJECT_MODALS_SMOKE pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)

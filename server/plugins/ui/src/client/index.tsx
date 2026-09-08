/**
 * sandbar-admin-ui —— 溯游管理台 · 浏览器半。
 *
 * M13（t260822-m13-model-routes-edit）：删除 settings.section 注册——设置面板
 * 「溯游」子菜单消失（工具直调/审计流水/模型路由三个页签随之从设置面板移除）。
 * 宿主半（../node.ts）的 API 全部保留：/sandbar-admin/api/tools|call|audit|routes
 * 仍挂在 dsh webServer 上——其中 GET /sandbar-admin/api/routes 由 sandbar-providers
 * 「模型」页签的「路由表」分区消费（展示+保存，见 providers/src/client/index.tsx），
 * POST /sandbar-admin/api/routes（M13 新增）承担「保存写 model-routes.yaml」。
 *
 * 本插件浏览器半从此不再注册任何槽位：apply 为空实现（仅保留插件契约的
 * name/apply 导出）；lib/client.js 由 tsdown 重建为近空 bundle。
 */

import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'

export const name = 'sandbar-admin-ui/client'
export const inject: string[] = []

export function apply(_ctx: ClientContext): void {
  // M13：不再向 settings.section 注册「溯游」分区（子菜单消失）。
  // 宿主半 API 仍挂载（node.ts），供 sandbar-providers「模型」页签消费。
}

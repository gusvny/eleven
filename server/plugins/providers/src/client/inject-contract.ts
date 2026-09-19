/**
 * sandbar-providers · client entry inject 契约（单一真源）。
 *
 * 【为什么收窄到 ['slots']（工单 t260916-26，dsh 升级 epic T6）】
 * dsh 0.1.1（现生产）的浏览器半由 dsh-client-runtime 提供 `conversationViews`
 * 服务（0.1.1 lib/client.js：super(ctx, 「conversationViews」)）；0.1.5 起
 * dsh-client-runtime 整包移除，会话视图扩展面迁到 dsh-client-ui-conversation 的
 * `uiConversation.views.register`，且 0.1.5 全包已无任何服务注册在
 * 「conversationViews」键下。宿主（与浏览器 web boot）按 entry 的 `inject`
 * 声明等待服务注入——声明了不存在的服务 = 永久 pending = UI 顶部
 * 「Failed to load plugins / web boot: N entries did not activate」。
 *
 * 双版本容错口径：inject 只声明两版皆存在的服务，同一份 bundle 在 0.1.1 与
 * 0.1.5 下都能激活（零运行时分支、零构建期二选一）。白名单取证：
 *   - `slots`：0.1.1/0.1.5 皆在（0.1.5 实台活证=workbench 注入
 *     ['slots','sessions','workspaces'] 正常激活）；
 *   - `sessions`/`workspaces`：同上双版皆在，本插件当前不消费，不声明。
 * 本插件 apply 为空操作（260823 起视图由 sandbar-workbench 侧栏承载），
 * 对 `uiConversation`/`conversationViews` 均零消费——收窄不改变任何行为。
 *
 * 【白名单纪律】未来若要恢复插件自持页签：0.1.5 用
 * `uiConversation.views.register`、0.1.1 用 `conversationViews.register`
 * 双轨探测实现，且必须先核实目标服务在两版都真实存在（宿主 stage +
 * 生产各一条活证）再进白名单；同步更新 index.tsx 与 smoke/client-contract.mjs
 * 的产物断言。
 *
 * validateInject 仅供测试与未来装载前校验调用——严禁放进 entry 激活路径
 * （浏览器半抛错 = 激活失败 = 恰好炸出本票要避免的整屏横幅）。
 *
 * 与 sandbar-knowledge/src/client/inject-contract.ts 同构（插件独立可装载，
 * 不跨插件 import 契约模块）；两处必须同步修改，smoke 断言双份兜底。
 */

/** 双版本（dsh 0.1.x 生产/stage）皆存在的客户端服务白名单——本 entry 消费的子集。 */
export const CLIENT_INJECT: string[] = ['slots']

/** 未来可加入白名单的候选（须先按上方纪律取双版活证，勿直接搬用）。 */
export const KNOWN_STABLE_SERVICES: readonly string[] = [
  'slots',
  'sessions',
  'workspaces',
]

/**
 * 校验一个待声明的 inject 数组：非字符串数组 / 空串 / 空数组 / 白名单外
 * 服务名一律抛错。返回规范化后的新数组。
 */
export function validateInject(value: unknown): string[] {
  if (!Array.isArray(value)) {
    throw new TypeError(`inject 必须是字符串数组，收到 ${typeof value}`)
  }
  if (value.length === 0) {
    throw new TypeError('inject 不得为空数组：entry 至少依赖 slots（视图槽契约）')
  }
  const out: string[] = []
  for (const item of value) {
    if (typeof item !== 'string' || item === '') {
      throw new TypeError(`inject 元素必须是非空字符串，收到 ${JSON.stringify(item) ?? String(item)}`)
    }
    if (!KNOWN_STABLE_SERVICES.includes(item)) {
      throw new TypeError(
        `inject 服务 "${item}" 不在双版本稳定白名单 ${JSON.stringify(KNOWN_STABLE_SERVICES)} 内`
        + '——先按 inject-contract.ts 头注纪律取 0.1.1/0.1.5 双版活证',
      )
    }
    if (!out.includes(item)) out.push(item)
  }
  return out
}

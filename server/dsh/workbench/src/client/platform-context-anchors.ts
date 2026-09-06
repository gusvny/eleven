/**
 * suyou-workbench · 平台自启上下文内容锚真源（t260905-09）。
 *
 * 职责：给「dsh 平台在新会话开头自启注入的上下文」（runtime context 快照、
 * workspace instructions 块、CLAUDE.md 内容等）提供渲染面折叠判定锚——
 * t260905-04 的折叠件只认工单台 charter 注入的 CHARTER_MARKER，宿主 260906
 * 实报「还是显示了一堆，只折叠了开头一小部分」：真控制台新会话=平台自启
 * 上下文 N 条 + 工单台注入 1 条叠加，后者折了前者裸奔。本模块与
 * ../host/session-charter.ts 的 CHARTER_MARKER 同层：折叠触发器的另一路真源，
 * 渲染端（src/client/context-fold.ts）经常量消费，防两端漂移。
 *
 * ── 内容锚纪律（红线，同 context-fold.ts 头注取证结论）──
 * 平台自启上下文的注入源在宿主二进制（仓内 grep「Current runtime context」
 * 「Instructions from」零命中），气泡 DOM 结构不可实查（context-fold.ts 头注
 * 在案）——故锚算法取「内容推导式」：**只认平台生成的恒定文本特征，绝不赌
 * 平台 CSS 类名/结构属性**。锚取平台 wrapper 措辞（跨项目恒定）优先；仅一条
 * 项目侧内容锚（CLAUDE.md 头行），更名/改版=漂移信号人审。
 *
 * ── 误折面声明（设计内限制，防后人当缺陷修）──
 * 平台 wire 契约 PromptContentPart 无 metadata 字段（KI-046 取证实锤），渲染面
 * 原理上无法分辨「平台注入」与「用户粘贴恰好以锚行开头」：**前缀命中即折含
 * 用户粘贴形态**，属本机制的固有代价（折了也可点开看全文，信息不丢）。
 * 能兜住的误折面只到「中段提及锚字样绝不折」——匹配一律首行/前缀口径。
 *
 * ── 锚漂移看守 ──
 * 每锚注明出处；固定桩样本落 integration/t260905-09/fixtures/（逐字同步），
 * ro 冻结场景（sc_platform_context_anchor_contract.mjs）锚「本清单↔fixtures
 * 逐字一致 + 客户端常量引用在文」——平台改措辞=场景红→人审同步，不静默。
 */

/** 锚匹配口径：exact=整段以锚文本开头；first-line=首个非空行以锚开头。 */
interface PlatformAnchor {
  id: string
  match: 'exact' | 'first-line'
  /** 锚文本（前缀口径，大小写敏感）。 */
  text: string
  /** 出处与漂移责任声明。 */
  note: string
}

/**
 * 平台自启上下文锚清单（新增锚须带出处注 + fixtures 样本 + 场景同步）。
 * 出处口径：宿主 260906 实报（notes/queued-fold-platform-context-ticket.json）
 * + 真控制台新会话实文取证（本模块只收平台生成措辞，逐条见 note）。
 */
export const PLATFORM_CONTEXT_ANCHORS: PlatformAnchor[] = [
  {
    id: 'runtime-context-snapshot',
    match: 'exact',
    text: 'Current runtime context. This snapshot supersedes earlier runtime-context snapshots.',
    note: '平台运行时上下文快照的首句（宿主每轮注入的 wrapper 恒定措辞，跨项目恒定）。',
  },
  {
    id: 'runtime-context-preamble',
    match: 'exact',
    text: 'The following workspace instructions may be relevant to your work.',
    note: '平台 workspace instructions 块的开场句（宿主恒定措辞，紧随 runtime context 快照之后）。',
  },
  {
    id: 'dsh-file-policy',
    match: 'first-line',
    text: 'Current DSH file policy:',
    note: '平台文件沙箱策略行（宿主恒定措辞，独立段）。',
  },
  {
    id: 'instructions-from',
    match: 'first-line',
    text: 'Instructions from: ',
    note: '平台注入工作区指令文件的 wrapper 行（恒为「Instructions from: <路径>」形态）；命中即整条消息按注入物折叠。',
  },
  {
    id: 'claude-md-heading',
    match: 'first-line',
    text: '# sandbar — ',
    note: 'CLAUDE.md 头行（项目侧内容锚，工单点名；项目更名/头行改版=场景红人审，非静默）。唯一的项目侧锚，平台侧 wrapper 措辞锚齐备后可审删。',
  },
]

/**
 * 平台上下文折叠判定（纯函数，smoke 直测）：
 * - 容错口径与 classifyContextFold 同款：非字符串/空串 → false；
 * - exact 锚：trimStart 后以锚文本开头；
 * - first-line 锚：首个非空行以锚文本开头（允许锚行前有空白）；
 * - 中段提及锚字样 → false（误折面声明见头注）。
 */
export function classifyPlatformContext(text: unknown): boolean {
  if (typeof text !== 'string') return false
  const trimmed = text.trimStart()
  if (trimmed === '') return false
  for (const anchor of PLATFORM_CONTEXT_ANCHORS) {
    if (anchor.match === 'exact') {
      if (trimmed.startsWith(anchor.text)) return true
    } else {
      const firstLine = trimmed.split('\n', 1)[0] ?? ''
      if (firstLine.startsWith(anchor.text)) return true
    }
  }
  return false
}

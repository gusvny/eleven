# 工单排队计划（260910 定）

> 起因：260910 暂停功能一票全程暴露的结构性缺陷总清账。宿主拍板：能并发的
> 尽快开；同文件必须串行。本文=排队真源，票开掉一条划一条。

## 在飞（260910 已开，并发）

| 票 | 内容 | 写集 | epic |
| --- | --- | --- | --- |
| t260910-03 | 多仓落仓修复（P0，KI-066）：预派生病灶+双保险丝+逐仓物化+正规入口全链场景 | tools+engine+integration | engine-hardening |
| t260910-04 | 暂停功能补全（KI-068）：host 透传 paused/paused_phase+API 面场景 | workbench+integration | ticket-pause |
| t260910-05 | UI 证据质量（KI-069）：截图内容断言+证据路径新名迁移（不做签字界面嵌图，宿主拍板） | ui-check+workbench+integration | engine-hardening |

## 排队（t260910-03 收口即开，同文件 ticket.py/dev_lane 串行）

1. **入口收口**（KI-067）：ticket.py create/rework 静默失败修复 + client.py 无差别
   自审计 + 回执嵌「走正规入口」提醒（ticket.py 转发带自报家门标记，非安全语义）
   + sign/retry_qc 包进正规入口。epic=engine-hardening。
2. **KI-048 修复**：合并被脏工作区拒绝时正确分类（不冒充冲突）+ 人门展示原因
   + 合并前主动脏检查提示。epic=engine-hardening。

## 第二批（择机攒批）

- diff 面多仓汇总+过程产物过滤（dengzhufpv 报告 2a/2b，changes.ts）。
- 路由表失联显式告警（dengzhufpv 建议：项目无 paths.model_routes 声明且默认
  路径无表 → 票面/UI 提示，防静默回落）。
- 构建产物抖动：压缩器版本钉死（同源码重建逐字节稳定，diff 去噪）。
- 仓根 .suyou/ 四个 model_patch 残留清理（宿主未裁）。

## 尾巴

- t260910-02（暂停实测活体票）：t260910-04 验收用，验完撤。
- charter 修订：见 notes/discussions/260910-session-charter-revision.md
  （宿主令：本批问题搞完后落盘）。

## 补记（260910 巡检清场）

- `suyou-dispatcher-scan` 定时器已暂停（旧名+触发类型名错配 `dispatcher-scan`
  ≠真名 `DispatcherScanWorkflow`，曾产 3 个 RUNNING 僵尸已 terminate，
  留 Temporal 历史可溯）。随 inspection 票① 一并治理：定时器命名/类型对齐。
- 巡检 epic 现状：骨架模块在（inspection_* + DispatcherScanWorkflow），
  票①②③ 未开；排第二批，且作为本批缺陷修复后的全面验证手段。

## 补记（260910 详情 UI 重设计 gap，宿主纠错）

- 「工单详情 UI 重设计」mock（260904-ticket-detail-ui-mock.html，六屏）**无落地票**，
  驱动面=KI-019（泳道图失真，open）/KI-027（关闭后动态流消失，open）/KI-048（观测面）。
  已顺带落地片段：快照要点 t260905-07、并行分叉 t260901-05/t260903-04、执行规格卡
  t260904-06。未落地主体：①总布局（人话状态卡+泳道图+检查明细）②红灯文案对照
  ③真泳道双道与逐轮分格。排「工单详情观测面重设计」票进第二批（与 KI-019/027 同族，
  勿与 project-lifecycle 项目管理 UI mock v5 混淆——后者已落地）。

## 补记（260910 文档视图修复，宿主 mock 过稿）

- 票「文档视图修复」：①bug——docs tree/doc 按当前项目根解析（KI-070，修「只能看
  sandbar 文档」）；②UI——按 mock v1 重做（notes/discussions/260910-docs-view-mock.html，
  宿主过稿）：Project 切换 + Search + 左栏上「Docs/Notes 文件浏览器」下「On this page
  大纲」+ 右栏正文全宽 + 英文固定 UI 元素 + 正文 Verified 新鲜度 chip（doc-lifecycle
  面B verified 时间戳亮出）。写集=server/plugins/workbench/ + integration/；
  场景必含：项目锚 docs tree 断言（另一项目读到自己的 docs）+ 回落引擎仓断言。

## 宿主待办（260910 记）：退役「下一单建议」

- 宿主 260910 拍板：**suggest_next（合并签字后预跑「下一单建议」，spawn 一个
  integration agent 会话产建议）已无使用价值，后续去掉**。先记账不即做。
- 成本面（记录用）：每张票收口都会多跑一次 agent 会话（t260910-03 合并时实测
  触发：suggest_next/running → spawn），属纯开销。
- 退役口径建议（实现时定）：dev_lane 主链去掉 suggest_next 段 + 相关 activity
  （prepare_epic_next/suggest_next）+ 场景与 prompt 引用一并清；epic-next 状态
  目录（.suyou/epic-next，t260910 快照里仍在）是否随之退场需一并裁。
- 排期：独立小票，排第二批（与入口收口/文档视图同批，不插止血队）。

## 补记（260910 票号冲突教训）

- 巡检机制简化面票首次开票用号 t260910-07 = 与 dengzhufpv 侧验证票撞号（票号全局唯一，
  AlreadyStarted 拒建，见 t260910-07=T2b fpv-toolchain 落仓重验）；已换号重开 =
  **t260910-09**。教训：开票前先看全项目在飞清单取号，不假定本仓独占号段。

## 补记（260910 晚）

- 文档视图修复票**已开 = t260910-10**（bug KI-070 + mock v1 过稿 UI；宿主点名先开）。
  与 t260910-05（UI 证据质量）同文件面（node.ts + lib bundle 产物），规格内已写明按序合并、
  冲突按兜底规矩消解。
- 巡检机制简化面票已开 = t260910-09（首开 t260910-07 撞 dengzhufpv 票号被拒）。
- 当前在飞：04/05/06/08/09/10。

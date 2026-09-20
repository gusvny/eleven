# 项目术语表（terminology）

> **地位**：项目内文档、票据文本、agent 可见文字的用词规范。所有角色与 agent 按本表用词；表格由 integration 岗位维护，增删改走人审。
> **原则**：中文为主，特定行业术语可保留英文原词（如 intent、scenario）；每个术语给中英文对照与定义，三列对齐。

## 一、测试体系

| 中文 | English | 定义 |
|---|---|---|
| 测试用例 | test case | 可判定通过/失败的最小验证单元；必须声明意图与高层步骤 |
| 验证路径 | test path | 同一用例内一条可独立判定通过/失败的验证分支（如正例路径、反例路径）。**旧行话「腿」已废止，见「旧词废止」一节** |
| 正例路径 | positive path | 该成功的必须成功 |
| 反例路径 | negative path | 该拒绝的必须拒绝、该报错的必须报错 |
| 环境路径 | environment path | 需要特定外部条件（docker／真实台）才能执行的分支；条件缺件时该路径报「环境不可用」，不计产品红 |
| 移交命令 | handover command | 前段 agent 因执行面受限未能运行的验证命令，移交（handover）到集测段由 worker 代跑 |
| 意图 | intent | 本用例验证哪条契约或行为承诺 |
| 高层步骤 | high-level steps | 到达被测行为并完成断言的步骤序列 |
| 单元层 | unit layer (L1) | developer 随本票改动交付；白盒、随实现、廉价可弃 |
| 组件契约层 | component contract layer (L2) | integration 设计；灰盒、锚定 API 契约 |
| 系统场景层 | system scenario layer (L3) | integration 维护；全链路旅程+错误注入 |
| 场景集 | scenarios | L3 场景资产的集合；实际路径由项目声明给出 |
| 基准场景 | baseline scenario | 场景集中作为门槛的参考场景——基准不过，其余无需再测 |
| 灰盒 | gray-box | 理解要深（架构/机制/数据流用于设计）+ 绑定要浅（断言只认契约与可感知行为） |
| 白盒 | white-box | 断言面向实现内部结构；仅限 L1 使用 |
| 黑盒 | black-box | 完全不依赖内部知识的测试视角；仅作对照概念 |
| 对抗职责 | adversarial role | integration 从功能假设 developer 错误模式，主动构造暴露场景 |
| 用例设计 | test case design | 依据"用例设计依据"产出用例的过程 |
| 用例设计依据 | test design inputs | ①原始 user_request+验收口径 ②已知问题清单命中项 ③对外契约与行为规格 |
| 已知问题清单 | known issues (KI) | 系统已知缺陷登记，含故障模式与回归用例列 |
| 故障模式 | failure mode | 一类可复发的错误机理，跨票沉淀 |
| 回归用例 | regression case | 钉死已修复缺陷的用例；无回归用例的缺陷修复不予合入 |
| 意图级重复 | intent-level duplication | 同意图已有用例覆盖再另起——避免 |
| 步骤级重复 | step-level duplication | 前置/脚手架步骤的重复——允许，以共享步骤代码解决 |
| 共享步骤代码 | shared step code | 多用例复用的前置步骤代码模块 |
| 错误注入 | fault injection | 主动制造故障条件，验证防御与恢复行为 |
| 冻结快照 | frozen snapshot | 合入落盘时写进票据记录的最终交付数据 |
| 归档 | archival | 运行时数据在合入/运行时刻写入项目级持久存储 |

## 二、引擎与工单

| 中文 | English | 定义 |
|---|---|---|
| 工单 | ticket | 一张开发任务的完整流程单元 |
| 泳道 | lane | 工单专属的隔离工作空间；git worktree 只是当前实现方式 |
| 写集 | write set | 工单允许修改的路径白名单 |
| 打回 | rework | 审查不通过，退回上一工序重做 |
| 合入 | merge in | squash 合入 main，一单一提交 |
| 仲裁 | arbitration | 集成结果裁决：通过/测试_fault/代码_fault 三态 |
| 验收走查 | acceptance walkthrough | 按验收口径对交付做最终走查，合并前最后一道关 |
| 程序步 | programmatic step | 无 agent 参与的纯程序活动（如测试套件执行） |
| 返工循环 | rework loop | 测试/代码 fault 触发的有限次（≤5）自动重做 |
| 冲突消解 | conflict resolution | 泳道与 main 漂移后的自动（≤3 轮）/人工合并处理 |
| 合并签核 | merge sign-off | 合入前的人工签字关口 |
| 环境初始化 | lane bootstrap | 泳道内复制引擎家目录与凭据 |
| 软降级 | soft degrade | 数据不可得时置空并注明原因，不硬失败 |
| 实际路径 | actual path | 抽象条款在本项目落地的具体位置 |
| 旧档冒充 | stale-artifact substitution | 运行时阶段产物被误提交入库后，新工单泳道检出即自带旧结果文件，各阶段当作本阶段产出直接消费——阶段显示完成而实际未做任何工作（人审定名 2026-09-03，宿主） |

## 二·五、doc-lifecycle 词条（260904 随立项新增）

| 词条 | 释义 |
|---|---|
| 沉淀（sedimentation） | 验证过的事实从 notes 迁入 docs 的动作——由**验证事件**触发（宿主拍板／工单收口／测试在案），不是时间到了就搬 |
| 毕业（graduation） | 一份 notes 讨论稿经宿主过稿、按写作指南改写为定稿文档迁入 docs 的过程；notes 侧标「已转立项」，来源标签回桥（`> 来源立项：<代号>`） |
| 临时真源（interim source of truth） | 债条目在 docs 本体修订前充当的过渡权威面；后续工单读到旧 docs 条目以债为准——写集改革落地后此机制退役 |
| 两记忆（two memories） | notes=过程记忆（工作台，volatile，消费者是人）；docs=沉淀记忆（知识库，durable，消费者是 agent 的 context＋人） |
| verified（核对时间戳） | 「本篇文档的事实最近何时被对照代码现实核对过」——机器/agent 盖戳，区别于 `updated`（内容改过没，人维护）；存中央账本（index 扩展），不落文档文件 |
| 心跳（heartbeat） | 每日任务的活性证明（账本 generated_at 每日必更一行）——账本停更=巡检死了，所有 verified 打问号 |

## 三、禁用对照

| 中文（禁用） | 规范中文 | 规范 English |
|---|---|---|
| **腿**（含 正腿／负腿／回归腿／环境腿／三态腿／全腿 N/A／缺腿） | 验证路径／正例路径／反例路径／回归用例／环境路径／三态路径／全部路径不适用／漏一条路径 | test path（compounds as listed） |
| **交接腿** | 移交命令 | handover command |
| delta | 本票改动 / 泳道改动 | lane diff |
| 出题 / 题源 | 用例设计 / 用例设计依据 | test case design / test design inputs |
| 落点 | 实际路径 | actual path |
| 故障账 | 已知问题清单 | known issues (KI) |
| baselines（作资产集合名） | 场景集 | scenarios |
| 夹具 | 共享步骤代码 | shared step code |
| 出仓 | 归档 | archival |
| 收口 | 合入 | merge in |
| 机械步 | 程序步 | programmatic step |
| 回路 | 返工循环 | rework loop |
| 合并门 | 合并签核 | merge sign-off |
| 暂存（指凭据机制时） | 环境初始化 | lane bootstrap |

## 维护说明

- 谁写：integration 岗位（增删改均需人审）。
- 谁读：所有角色与 agent——写文档、票据文本、审批意见、UI 文案时的用词依据。
- 何时更新：新概念进入协作词汇，或既有术语经用户拍板修订时。
- **「腿」废止生效（宿主令 260920）**：自本日起，文档、票据、场景描述、注释与对外文字**一律不得新增**「腿」及其复合词，按上表映射改用规范词；存量（260920 实测 405 文件 / 3427 处）按票分批替换：批一 `docs/`＋`notes/` → 批二 `integration/` 场景描述与注释（等 t260920-01 合入后开动，避免撞它的改动面） → 批三 `server/` 注释；**机器可读标识符**（`legs`／`_handover_debt_legs` 等）暂不改名，但新增标识符不得再用 `leg`。机械看守（按文件出现次数基线，新增即红）随批一落地。

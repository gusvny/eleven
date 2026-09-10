---
title: "docs 索引"
category: reference
tags:
  - 索引
  - 知识库
status: active
updated: 2026-09-04
---

# docs 索引

> **260904 迁移注记**：本库自 suyou 仓迁入 sandbar（宿主令）。迁的是**引擎/插件/基建域**文档——
> 判定法则见 `notes/README.md` 毕业规则（新 agent 改 sandbar 代码需要读的进本库）。
> **产品/内容/项目域文档**（HLD、平台架构、图书馆、游戏激励、营造、掌握模型、阅读批注、
> agent 形象、古籍管线、reference 调研）留 suyou 冻结仓作历史参考（只读，不回写）。
> 机器索引已重跑（`docs/index.json`，11 篇）。
>
> 沿革：2026-08-21 docs 当知识库重构（四类目录 + frontmatter + index.json + suyou-knowledge
> 插件消费）；本页是给人看的总目录，给机器看的是 `docs/index.json`，目录结构与迁移映射见
> `design/知识库设计.md`（§2 / §6）。

## design（设计 —— 引擎/插件长什么样、为什么）

| 文件 | 内容 |
|---|---|
| `design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md` | **引擎机制主档**：DSH+Temporal 多 agent 工单引擎（引擎/插件域工单首读参考） |
| `design/工单工作流台设计.md` | 工单工作流台设计（多角色协作基础设施） |
| `design/右栏会话入口与hero定制设计.md` | workbench 右栏会话入口与 hero 定制（附录含【有效】/【已证伪】锚点结论） |
| `design/metrics-api契约v1.md` | workbench metrics API 契约 |
| `design/metrics面板ui规划.md` | metrics 面板 UI 规划 |
| `design/知识库设计.md` | 知识库设计定稿：四目录、markdown 规范、UI、迁移映射 |
| `design/dsh_seam需求书v1.md` | dsh 插件接缝需求书（插件族契约） |
| `design/杂务工单模版设计.md` | chore-lane 杂务工单模版（草案，待宿主审定稿） |
| `design/失败分类协议v1.md` | 失败分类协议 v1 与机械归属判定：一行 JSON 规范行 + 三态收紧 + 闸 main 基线差集决策表（t260910-13） |
| `design/设计文档写作指南.md` | 设计文档写作规范 |
| `design/sandbar项目接入契约v1.md` | sandbar 项目接入契约 v1（键表/接手面/append 式变更记录） |

## ops（运维 —— build / 部署 / 监控）

| 文件 | 内容 |
|---|---|
| `ops/admin-dsh-应用方案.md` | admin × DeepSeek Harness（dsh）应用方案 |

## 根级（横切规范）

| 文件 | 内容 |
|---|---|
| `terminology.md` | 项目术语表（integration 维护，人审增删；自 suyou 整表迁入，含少量项目域条目待清理） |
| `testing-guide.md` | 测试环境隔离指南（3099/7233 红线、Docker 隔离测试环境） |

## 维护约定

- 每篇头部 YAML frontmatter：`title`（首个 `#` 标题）/`category`（design|content|ops|reference）/`tags`/`status`（active|draft|deprecated）/`updated`（最近实质修改日）。
- 新增文档：放进对应分类目录 + 补 frontmatter，然后跑 `python3 docs/scripts/build_index.py` 刷新 `docs/index.json`。
- 关联文档之间**相互链接**（相对路径，三类关系：依赖/被依赖、取代/被取代、实践参考，见 `design/知识库设计.md` §3.2）。
- 仓库根 `CLAUDE.md` 为接力交接总入口，本目录是其细化知识库；过程性讨论与立项见 `notes/`（分工与毕业规则见 `notes/README.md`）。

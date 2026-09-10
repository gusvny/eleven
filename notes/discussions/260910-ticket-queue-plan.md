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

# sandbar

多项目工单引擎：模版即代码的 Temporal 流水线 + dsh 工作台插件族。从 suyou 仓
物理搬迁而来（2026-09-03，M2-B），干净基线起步，旧 git 历史留在 suyou 仓不丢。

## 版本

semver 从 v0.1.0 起（首版=搬迁快照）。依赖 dsh 发行包（@deepseek-ai/dsh，
版本区间声明见 M2-C 安装器交付）。

## 仓内地图（suyou 仓内路径 → 本仓同路径）

| suyou 路径 | 本仓 | 说明 |
| --- | --- | --- |
| server/dsh/temporal-poc/ | 同路径 | 引擎本体（base/dev_lane/六模版类/worker/client） |
| server/dsh/workbench/ 等 10 个插件目录 | 同路径 | dsh 插件（workbench/knowledge/providers/ui/ui-check/temporal-tools/headless-resume/profile×2/workflows） |
| server/tools/{verify_lane,ticket,workflow,dispatcher_loop}.py | 同路径 | 引擎工具（admin call 消费面） |
| server/dsh/{projects.yaml,suyou-projects.ts,suyou-tools.ts} | 同路径 | 注册表迁移种子+装载器+工具桥插件（改名/改造=M2-C） |

留 suyou 侧：roles/、model-routes.yaml、merge-checks.yaml（项目侧声明，契约①d/③）、
serve.py/admin.py 等 suyou 业务服务端。逐文件判定真源=suyoU 仓
notes/debts/sandbar-m2-migration-manifest.md。

## 目录名注记

`temporal-poc` 等旧名保留（改名涉及 dsh 插件发现/软链/引擎路径引用，须随
M2-C 安装器连引用重建一起做，不在搬迁步单独动——宿主 20260903 裁定）。

## 下一步

M2-C 安装器（console/Temporal/worker 生命周期管理+semver+dsh 版本区间+兼容矩阵）
→ M2-D suyou 切安装制零回归 → M3 摘除+dogfood。

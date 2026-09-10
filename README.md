# sandbar

多项目工单引擎：模版即代码的 Temporal 流水线 + dsh 工作台插件族。从 suyou 仓
物理搬迁而来（2026-09-03，M2-B），干净基线起步，旧 git 历史留在 suyou 仓不丢。

## 版本

semver 从 v0.1.0 起（首版=搬迁快照）。依赖 dsh 发行包（@deepseek-ai/dsh，
版本区间声明见 M2-C 安装器交付）。

## 仓内地图（suyou 仓内路径 → 本仓同路径）

| suyou 路径 | 本仓 | 说明 |
| --- | --- | --- |
| server/engine/ | v6 现路径 | 引擎本体（base/dev_lane/六模版类/worker/client） |
| server/plugins/{ui,workbench,knowledge,providers,temporal-tools} | v6 现路径 | dsh 插件五件（cordis 农场实挂）；profile×2/roles/ui-check/headless-resume/workflows 摊平在 server/ 直下 |
| server/tools/{verify_lane,ticket,workflow,dispatcher_loop}.py | 同路径 | 引擎工具（admin call 消费面） |
| server/{projects.yaml,suyou-projects.ts,sandbar-tools.ts} | v6 现路径 | 注册表迁移种子+装载器+工具桥插件（改名/改造=M2-C） |

留 suyou 侧：roles/、model-routes.yaml（t260910-14 起降级为迁移窗口的读侧兜底表——真源=各项目声明 paths.model_routes 指向的文件）、merge-checks.yaml（项目侧声明，契约①d/③）、
serve.py/admin.py 等 suyou 业务服务端。逐文件判定真源=suyoU 仓
notes/debts/sandbar-m2-migration-manifest.md。

## 目录名注记

引擎旧目录名与包装层均已退役（宿主令 v6，t260907-10 落地）：引擎住 server/engine/，
插件住 server/plugins/，装配配方/角色声明/路由表摊平在 server/ 直下。venv 旧路径
回落期一轮后摘除（摘除票收口，KI-057 登记）。

## 下一步

M2-C 安装器（console/Temporal/worker 生命周期管理+semver+dsh 版本区间+兼容矩阵）
→ M2-D suyou 切安装制零回归 → M3 摘除+dogfood。

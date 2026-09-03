# sandbar — 多项目工单引擎

从 suyou 仓物理搬迁而来（M2-B，v0.1.0 干净基线）。本仓=sandbar 引擎真源
（suyou 侧引擎已冻结，只改本仓）。逐文件判定真源与搬迁史见 suyou 仓
notes/debts/sandbar-m2-migration-manifest.md。

## 目录
- server/dsh/temporal-poc/：引擎本体（base/dev_lane/worker/client）
- server/dsh/workbench 等 11 个插件目录：dsh 工作台插件族
- server/tools/：verify_lane/ticket/workflow/dispatcher_loop
- server/dsh/roles、model-routes.yaml：项目侧声明（角色 persona/模型路由）

## 硬规则
1. console（3099）永属用户操作面：任何代码/测试/安装器不得重启/停止/占用。
2. 小步 commit；写集白名单内干活。
3. 文档注释用现代中文。
4. 本仓只读 ~/Documents/suyou 的历史文档作参考，不回写。

# dsh 升级 UI 兼容面 × 接缝矩阵（t260916-25）

> **用途**：dsh 引擎升级前后的 UI 兼容面核对矩阵。每行一个「UI 相关接缝」：
> 升级时逐行核对旧行为是否延续，配合 `server/tools/stage_console.sh`（一键 stage
> 台）与 `integration/lib_stage_ui_surface.mjs`（自动断言）使用。
> **毕业去向**：本文按 epic 文档正文规范写，待收口段搬入 `notes/epics/dsh-upgrade.md`
> （本票写集不含 notes/，勿在此票顺手改）。
> **警示**：stage 控制台连的是生产 Temporal 与项目注册表——人工核对时只读浏览，
> 写操作（建票/改配置）会打到生产。

## 实测口径

- 「0.1.1 行为」= 生产现役版（/opt/homebrew 全局安装 0.1.1-rc.2）；
- 「0.1.5 实测」= 本票实弹（`--version 0.1.5-rc.2` 隔离安装 @ /tmp/dsh-stage-t260916-25，
  端口 3201，2026-09-16~18，selfcheck 全绿），标注「票面手工」的行来自 integration
  在本票前的手工验证（0.1.5-rc.2 @ /tmp/dsh-stage，端口 3199）。

## 矩阵

| # | 接缝 | 出处锚 | 0.1.1 行为 | 0.1.5 实测 | 覆盖方式 | 升级时看什么 |
|---|------|--------|-----------|-----------|---------|-------------|
| 1 | web 端口补丁位 | server/profile/cordis.patch.yml:100（webserver port，3099→3199） | 同左 | 补丁字面锚生效，stage 台听 --port ✓ | 壳 prepare 端口 sed + 失配即红 | 上游改缩进/键名 → prepare 红（有提示不静默） |
| 2 | dsh CLI 入口 | /opt/homebrew/bin/dsh → lib/bin.js | 全局软链指 lib/bin.js | npm 包 `files:['lib/*.js']` **无 bin/ 目录**，入口=lib/bin.js（shebang 可执行）✓ | 壳两级解析（bin/dsh→lib/bin.js） | 入口 404=壳红；改 files 布局同 |
| 3 | web 认证 | 化石 console.log 首行带 token URL | 未深测（本票前生产匿名可开） | **token 兑换语义**：匿名 GET /=401；`/?token=X`→303+Set-Cookie（dsh-auth-*，30 天）；带 cookie→200 ✓ | lib cookie jar+token 兑换；壳自动提 token | 升级后 401 进不去=认证面 break（清单 M0） |
| 4 | 组合插件包 | 首页 `<link href>/plugins/??...`（**挂 link 非 script**，53 文件 combo，`&amp;` 需解码） | 票面手工实测：200，13.2MB，含三个 sandbar 插件代码 | 200 ✓，combo 列表含 **4 个 sandbar**：admin-ui/knowledge/providers/workbench 的 client.js（必过下限=此四名，lib 已回填）✓ | lib 逐名断言（R1 口径） | combo 语法/挂载点变化→bundle:scan 红；包名从 combo 消失=该插件 UI 半丢 |
| 5 | temporal-tools 浏览器半 | cordis.patch.yml 挂载名 | — | 不在 combo（纯模型工具插件，无浏览器半，与 profile 注释吻合） | info 记录+五软链在位 | 若它出现在 UI → 清单 M5 核对 |
| 6 | workbench 宿主 API | 票面手工实测三路径 | 票面手工：200 | /sandbar-workbench/api/build-info、/api/wf/projects、/api/wf/inspection/tickets **全 200 JSON** ✓ | lib workbench-api 断言（≥1 条） | 404=宿主挂载丢；200 非 JSON=契约破 |
| 7 | admin/knowledge API 前缀 | cordis.patch.yml 挂载名 | — | /sandbar-admin/api/routes→**400**、/sandbar-knowledge/api/index→**400**（挂载在、查询契约未探，非 404） | info 探测+清单 M5/M6 | 404=挂载丢；400=在但参数语义需人工 |
| 8 | 会话文件事件面 | 票面手工：0.1.5 不再写 assistant/chunk、reasoning-chunks | v0 会话含上述事件 | 本票未自动断言（FS 面只验拷入可读：10 会话/143 文件 ✓） | FS 自检+清单 M1/M2（重点） | 正文/推理流显示缺失=会话渲染 break |
| 9 | 用量字段 | 票面手工疑点：cacheRead 恒 0? | — | 未自动断言（页面级） | 清单 M3 | in/out 失真或 cacheRead 恒 0=用量页 break |
| 10 | 凭据 seam | KI-016（skip-if-exists 病族） | — | prepare **强制重拷**（fresh）+chmod 600 ✓ | 壳 prepare（R2 分档） | 老凭据假活会被误读成「升级 break」 |
| 11 | preset 目录 | cordis.patch.yml 注：$DSH_HOME/.agent-presets（软链不被扫描） | 同左 | 实体拷贝强制重拷 ✓ | 壳 prepare | 起不了新会话=查此 seam |
| 12 | 依赖树复用 | 化石 profiles/node_modules（逐包软链 189 项→dsh 安装） | 全局布局：包内 node_modules（186 顶层项） | prefix 布局 189 项/全局 434 项（scoped 展开口径）均定位成功 ✓ | 壳两布局取条目多者 | 上游第三种布局→依赖树定位红 |
| 13 | 进程与启动输出 | 化石 console.log：`dsh web: http://…/?token=…` | 同左 | 字面稳定 ✓；实测存在「台好了但 URL 行迟到」瞬态 | 壳字面锚+宽限 20s（R4c/gen17 收口：宽限耗尽=响亮红+收自起台+清 pidfile，「台没起成」终态同构，不留监听态无头台） | 上游改文案→URL 宽限红（台已自收，重跑 start 幂等重来） |

## 自检覆盖与人工清单的分工

- **自动断言**（selfcheck，升级前后各跑一次）：行 1/2/3/4/6/10/11/12/13；
- **人工清单**（checklist 子命令打印）：行 5/7/8/9 全部 + 全行抽验——自动断言
  只锚定「实测过的事实下限」，UI 观感级 break（排版/交互/主题/流式）必须人眼。

## 变更记录

- 20260916~18 t260916-25 初版：13 接缝入表，0.1.5-rc.2 实弹回填（行 4 名集
  票面「三个」修订为实测「四个」，temporal-tools 无浏览器半单列）。

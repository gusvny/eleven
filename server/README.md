# 溯游 admin × dsh（DeepSeek Harness）—— 路线 C 混合薄壳

admin 的第三种形态：把 `server/admin.py` 的工具面整体挂进 dsh 的 agent 运行时
（agent loop / WebUI / 审批 / 会话审计全由 dsh 提供），**python 工具层一行不动**。
方案论证见 `docs/ops/admin-dsh-application-plan.md`。

- 工具真源 = `server/tools/*.py`（schema 每次启动现取现注册，不存在双写漂移）；
- run-id 审计单一真源 = `server/admin.log`（run_id 随工具返回值进 dsh 会话日志，双层互查）；
- 每次工具调用 = spawn 一个 python 进程（~百毫秒级开销），无需 serve.py 在线。

## python 还是 TS —— 分界逻辑（260820 定）

判据一句话：**这段逻辑要被几个运行时消费？**

- **≥2 个运行时消费（dsh / CLI / launchd / serve.py API / 将来其他 harness）→ python**，落 `server/tools/*.py`。stdlib 零依赖，任何有 python3 的地方能跑；与内容管线同语言同数据习语。
- **只服务 dsh 运行时或浏览器 → TS/yaml**，落 `server/`。TS 刻意**无逻辑**（薄壳）：适配、传输、UI、cordis 组合层配置（工具多实例、schedule、persona 等只能在这里做）。
- 铁律：**逻辑 python 单写、适配 TS 薄壳、组合层用 yaml**——逻辑两边各写一份必漂移。

## 前置

- **Node ≥ 22.19**（或 24+；dsh 靠 Node 原生类型剥离直接加载 .ts 插件。开发机实测 v26.5.0）。
- npx（随 Node 自带）。pnpm 只在要往 profile 里装额外插件时才需要——sandbar 本体仍零 npm 依赖。
- dsh 与仓库同机（插件要 spawn 本机 python3 + 读写仓库文件）。

## 目录内容与一次性安装

```
server/
  sandbar-tools.ts            # 插件本体（唯一真身）；导出 runAdminCli 供 ui/node.ts 复用
  ui/                       # 管理台 UI 插件（包名 sandbar-admin-ui，dsh.client 双面包）
    package.json            #   exports["."]=node.ts（宿主半）/exports["./client"]=lib/client.js
    node.ts                 #   宿主半：在 dsh webServer 挂 /sandbar-admin/api/*（tools/call/audit）
    src/client/index.tsx    #   浏览器半源码：设置页「溯游」分区（工具直调+审计流水）
    lib/client.js           #   浏览器半产物（已提交；改 src/client 后才需重建，见下）
    tsdown.config.ts        #   构建配置（closure-factory 外衣，react/@deepseek-ai 外部化）
  workbench/                # 工单工作流台插件（包名 sandbar-workbench，设计 v0.3 M2；独立命名不寄生 admin 壳）
    package.json            #   exports["."]=node.ts（宿主半）/exports["./client"]=lib/client.js
    node.ts                 #   宿主半：在 dsh webServer 挂 /sandbar-workbench/api/wf/*（tickets/workflows/
                            #   详情/accept/advance/dispatch-next/rework/update；调 ticket/workflow M1 引擎）
    src/client/index.tsx    #   浏览器半源码：设置页「工单台」分区（三区：台面网格+筛选/详情抽屉/操作区）
    lib/client.js           #   浏览器半产物（已提交；改 src/client 后才需重建，见下）
    tsdown.config.ts        #   构建配置（closure-factory 外衣，react/@deepseek-ai 外部化）
  profile/                  # WebUI profile（bundles: dsh-base + dsh-web-app）
    package.json            #   profile 清单（dsh.profile.bundles）
    cordis.patch.yml        #   用户补丁层：挂 sandbar-tools + sandbar-admin-ui + sandbar-workbench + 钉 deepseek-official 路由
    cordis.yml              #   空根配置（dsh 每次启动原样重写，勿手改）
    sandbar-tools.ts          #   → ../sandbar-tools.ts（相对软链，loader 按 profile 目录解析相对名）
    node_modules/sandbar-admin-ui      # → ../../ui（裸包名解析锚；不入 git，见下方重建制式）
    node_modules/sandbar-workbench     # → ../../workbench（同款解析锚）
    node_modules/sandbar-knowledge     # → ../../knowledge（同款解析锚）
    node_modules/sandbar-providers     # → ../../providers（同款解析锚）
    node_modules/sandbar-temporal-tools # → ../../temporal-tools（同款解析锚）
  profile-headless/         # headless profile（bundles: dsh-base + dsh-headless）
    ...                     #   cordis.patch.yml / sandbar-tools.ts 均为指回上面的软链
                            #   node_modules/ 五条 sandbar-* 软链同款（headless 无 webServer，
                            #   两个宿主半均待机）
```

管理台面板：启动 WebUI → 设置（侧栏齿轮）→ 导航「溯游」（工具直调+审计流水）与「工单台」
（工单工作流台三区：台面卡片网格/详情抽屉/操作矩阵）。
工具直调卡走 `/sandbar-admin/api/call`（同源，不需 admin token，webServer 只绑回环）；
命中 needsApproval 名单的写操作须面板弹窗确认后带 `confirm:true` 重发。
工单台走 `/sandbar-workbench/api/wf/*`（ticket/workflow M1 引擎；写操作直接执行，run-id 审计
在 server/admin.log 同一真源）。审计流水读 `server/admin.log` 末 100 行。
headless profile 下两个宿主半等不到 webServer 服务、静默待机——这是设计行为。

UI 重建（只有改了 `ui/src/client/` 或 `workbench/src/client/` 才需要；sandbar 仓库零 npm
依赖，tsdown 从外部供给）：

```sh
cd server/plugins/ui        && npx -y tsdown@0.22.2 -c tsdown.config.ts
cd server/plugins/workbench && npx -y tsdown@0.22.2 -c tsdown.config.ts
```

dsh 的 `--profile` 只接受 `$DSH_HOME/profiles/` 下的 profile **名**（不接受路径），
所以把两个 profile 目录软链进去（`$DSH_HOME` 缺省 `~/.dsh`）：

```sh
mkdir -p ~/.dsh/profiles
ln -sfn /Users/xingu/Documents/sandbar/server/profile          ~/.dsh/profiles/suyou
ln -sfn /Users/xingu/Documents/sandbar/server/profile-headless ~/.dsh/profiles/suyou-headless
```

软链农场（`profile*/node_modules/sandbar-*` 五条＋`sandbar-tools.ts` 一条）**不入 git**
（.gitignore node_modules/），新 checkout 或改名后按下面制式重建（在仓库根执行）：

```sh
for p in server/profile server/profile-headless; do
  mkdir -p "$p/node_modules"
  ln -sfn ../sandbar-tools.ts                          "$p/sandbar-tools.ts"
  ln -sfn ../../ui             "$p/node_modules/sandbar-admin-ui"
  ln -sfn ../../workbench      "$p/node_modules/sandbar-workbench"
  ln -sfn ../../knowledge      "$p/node_modules/sandbar-knowledge"
  ln -sfn ../../providers      "$p/node_modules/sandbar-providers"
  ln -sfn ../../temporal-tools "$p/node_modules/sandbar-temporal-tools"
done
```

插件里 admin.py 的位置按「本文件上两级」自动推导（= 仓库根），正常无需任何配置；
非常规布局时设 `export SANDBAR_REPO=<仓库根>` 或改 patch 里 sandbar-tools 行的 `config.repo`。

## 配 key（凭据 seam，key 不进任何仓库文件）

二选一：

- **Web 设置页**（推荐）：启动 WebUI → 设置 → 模型 → 填 DeepSeek API key，
  写入 `~/.dsh/.credentials.yaml`，热生效无需重启；
- **环境变量**：`export DEEPSEEK_API_KEY=sk-...`（凭据解析顺序：进程环境 → 凭据文件 → .env）。

## 使用（所有命令钉版本号；升级 dsh 走提案制）

WebUI（agent 控制台：工具卡片 / 审批弹窗 / 会话回放）：

```sh
npx @deepseek-ai/dsh@0.1.0-rc.7 --profile suyou
# 浏览器开 http://127.0.0.1:3080（只绑回环；占用了就追加 --port 3099）；工作区选 sandbar 仓库
```

headless CLI（一次性无人值守，跑完打印结果退出，替代 `admin.py chat`）：

```sh
npx @deepseek-ai/dsh@0.1.0-rc.7 --profile suyou-headless "跑一遍全量 QC，红了列出来"
```

检查组装（不起服务不跑插件，直接打印插件树，排错先跑这个）：

```sh
npx @deepseek-ai/dsh@0.1.0-rc.7 --profile suyou --dump-config | grep -A4 sandbar-tools
```

## 审批（§12.2-③ 两阶段提交 v1）

插件内置 `tools/pre-execute` 门禁：命中 `needsApproval` 名单（默认 `params_set`）
的调用先转 dsh approval seam——WebUI 弹「允许/拒绝」，决定写入会话审计事件
（`approval/asked` / `approval/decided`），工具调用本体仍落 `server/admin.log`。
调整名单：改 `profile/cordis.patch.yml` 里 sandbar-tools 行的 `config.needsApproval`
（保存即热重载），例如把将来的发布/下架工具加进去。

**headless 下审批 fail-closed**：headless 没有审批应答者，`params_set` 这类工具会被
自动拒绝——无人值守时人不在场就不许批，这是设计行为。要在 headless 里跑写操作，
退回 `admin.py call` 直调（不推荐把 `needsApproval` 清空）。

## 与旧形态的关系（三形态并存）

| 形态 | 适用 | 状态 |
|---|---|---|
| `admin.py tools/call/chat`（纯 stdlib CLI） | 无 Node 环境的降级路径，功能等价 | 保留不动 |
| `serve.py` `/api/admin/*` + `/admin` 过渡页 | 远程 admin（将来服务器部署，HTTP 天然支持） | 保留不动 |
| **dsh（本目录）** | 本机 agent 控制台：WebUI/审批/会话回放 | 本形态 |

## 排错

- profile 起不来 → 先 `--dump-config` 看组装；`--dump-default-config` 可跳过用户层定位坏补丁。
- 插件行在树里但工具没注册 → 看启动日志 `sandbar-tools:` 前缀的行；多为 python3 不在 PATH
  或 repo 推导失败（设 `SANDBAR_REPO`）。
- cordis 的 `!!js` 表达式**只在 config/disabled 里求值**，插件 `name` 字段不支持——
  所以插件用 profile 目录内相对软链挂载，移动目录结构时保持软链有效即可。
- macOS 首跑可能弹「文稿目录」授权（TCC，与 app 热更层同款），手点 Allow 一次。
- dsh 是 Developer Preview：版本钉死 `0.1.0-rc.7`；会话日志格式不承诺跨版本兼容。

# dsh 升级复盘（0.1.1-rc.2 → 0.1.5-rc.2，260923）

> 用途：**下一次升级的检查清单 + 本次未记录问题的登记**。只写事实、判据与定位；
> 进度与票况不写在这里（查 Temporal / 立项单）。
> 落笔人＝integration（260923）；触发＝宿主令「复盘一下，把没有记录的问题记录下来」。

## 一、一句话结论

升级本身（版本、位钉、preset、服务面）**今天已经能跑**；但本轮暴露的问题全部是**同一类**：
**上游改了「平台面」（服务名 / 槽选项 / 配置键 / 依赖解析），我们这边既不会有编译错误、
也不会有测试红**——所以它们只能靠「升级前主动对账 + 升级后真环境验收」发现。
本轮这类问题**已发现 6 处，其中 1 处是静默失效（角色说明书）**，详见 §四。

## 二、今天实际发生过什么（时间线，全部有实证）

| # | 症状 | 真因 | 性质 |
|---|---|---|---|
| 1 | 3099 打不开/白屏 | `npm install -g` 装的 0.1.5-rc.2 与验证过的 tarball **不是同一套 bits**（当天 cordis 族解析到新车，`cordis-plugin-hmr@1.0.18` 删了 launcher 必调的 `registerConfig`） | 上游依赖解析漂移 |
| 2 | 旧 console 被隔空打挂 | dsh 的静态页/客户端模块**每请求现读磁盘、无缓存** → 原位换包即白屏 | 我们剧本里的错误假设 |
| 3 | 新建/续会话全废（GUI） | 机器级 preset 是 0.1.1 时代实体拷贝，`dsh-persona` 的 `text:` → `prefix:`（**required**）→ 挂载即抛 | 机器级资产没进兼容面 |
| 4 | 「新建会话」全项目报「请求异常」 | `workspaces.startSession` → 0.1.5 迁到 `uiWorkspace`（`ctx.workspaces` 成纯控制器） | 平台服务面迁移 |
| 5 | **整个 UI 消失、退回 dsh 默认界面** | 我的第 4 项修复用**属性形式**取未 inject 的服务 → cordis 抛 `cannot get property … without inject` → slot 条目渲染期崩 | 修法自身踩 cordis 纪律 |
| 6 | （静默，未报错）角色说明书没进 agent | roles patch 用 `dsh-system-prompt.persona`，0.1.5 改成 `personaPrefix/personaSuffix`（**有默认值 → 不报错、静默为空**） | 配置键改名（**静默**） |

前 5 项当天已修并有回归；第 6 项**待修**（见 §四）。

## 三、已验 / 未验（下次升级照这张表复核）

**已验（有实证口径）**
- 全局安装 bits：`npm install -g … --before=<验证日>` 复现已验证解析集；`start-console.sh --bits-check` 两套候选全绿。
- 控制台启动：裸跑自动挑可用 bits；显式坏套响亮拦下（`integration/tests/test_start_console_bits.py` 8 条）。
- GUI 会话面：真浏览器加载 → 我们的 UI 锚在位、崩溃错误 0、点「新建会话」出 tab（`tests/session-start-version-shim.mjs` 静态看守 23 条）。
- 工作区/依赖树/preset 目录：stage 台 selfcheck 全绿（组合包四插件在位、workbench API 全 200）。
- 平台包挂载：`server/profile*` 挂的 6 个包在 0.1.5 全存在；引擎生成的模型 patch 键（provider/model）与 0.1.5 schema 一致。
- 容器镜像：`sandbar-agent:dsh-0.1.1-rc.2-s1` 与 `dsh-0.1.5-rc.2-s1` **都已构建**（runbook §6 旧文说 0.1.5 未建＝过期，已改）。

**未验（下次升级前必须补）**
- runbook §1-T4 第 2/3/4 条：候选版场景全集隔离副本整跑、（巡检一轮）、版本面自检——**至今未跑**。
- 生产冒烟票（create_plan→…→closed 全链）本轮**没走**。
- **docker 形态 spawn 未实跑**（当前 lane agent 走 host 形态；镜像虽在,未验证过真 spawn）。
- **回退面未演练**：回 0.1.1 需要三件套同时回——① `npm i -g` 0.1.1 且**同样要钉 bits**（否则再吃一次依赖漂移）；
  ② GUI preset **换回 0.1.1 版**（现存 `~/.dsh/.agent-presets/sandbar-integration.bak-260923/` 正是它，
  但见 §四-4：备份放在扫描根内）；③ 容器 tag 切回 `…0.1.1-rc.2-s1`。
- 其它项目（nusuyou/dengzhufpv）**无 `paths.dsh_bin` 钉** → worker spawn 走裸 `dsh`，即全局那套是它们唯一的面；
  本轮全局坏时它们一起坏（worker 日志实证 `bin=dsh(→/opt/homebrew/bin/dsh) 来源=default`）。建议逐项目加钉。
- 一个完整巡检周期（次日 07:30 调度 + 巡检 agent）未观察。

## 四、本轮发现但**还没修**的问题（按严重度）

### 1（严重，静默）roles patch 的角色说明书在 0.1.5 下被丢弃
- 事实：`server/roles/{developer,integration,product-operation}.yml` 用
  `- id: system-prompt / name: '@deepseek-ai/dsh-system-prompt' / config: { persona: … }`；
  0.1.5 该包 `static Config = z.object({ includeHarnessIdentity, includeRuntimeContext, personaPrefix, personaSuffix, toolOrder })`
  ——**没有 `persona`**，且新的两个键都有 `.default("")`。
- 后果：schemastery 对未知键**不抛错**（实测：`z.object({a,b})({a:'x',oldkey:'y'})` → `{a:'x',b:'',oldkey:'y'}`）
  ⇒ 我们的 `persona` 原样保留但**没人读**，`personaPrefix` 取默认空串 ⇒ **headless agent 收不到岗位说明书**，
  且**没有任何报错**（引擎侧照常 spawn、票面照常跑）。
- 影响面：切换 0.1.5 之后的所有 agent 段（developer / integration / 产品运营角色），即所有项目的所有票。
- 修法（已核过细节，可直接落）：把 `persona:` 改名 `personaPrefix:`；占位符 `{{cwd}}` **是合法变量**
  （`dsh-agent-loop` 注册了 `provider`/`model`/`cwd`，system-prompt 在装配期会插值，未知变量才抛），
  所以不会撞「unknown prompt variable」。回退兼容：0.1.1 读的是 `persona`，可**两个键都写**（各自忽略对方的键），
  或按钉住的 dsh 版本选目录。
- 回归建议：`integration/tools/dsh_surface_check.py`（已落地，见 §五）＋一条「spawn 出来的 agent 确实带角色说明」的用例
  （真 spawn 一次、问它角色名，或从 prompt 装配面取证据）。

### 2（既有，静默降级）`sidebar.footer.action` 是 list 槽，注册必须带 `id`
- 事实：0.1.5 里该槽声明 `kind: "list"`（平台自己注册时带 `id: "cordis-panel"`）；我们的注册**没带 id**
  → 浏览器控制台警告 `list slot "sidebar.footer.action" requires options.id`，
  「度量入口软退化回工单台下栏」（功能在、位置错）。
- 已用**改动前的产物**复现 → **不是今天改出来的**，是既有缺口。
- 修法：注册时补 `id: 'sandbar-metrics'`（照平台先例）。

### 3（既有）插件 `package.json` 的 `dsh.client.inject` 仍点名 0.1.5 已移除的包
- 四个插件（ui/knowledge/providers/workbench）都写着
  `dsh.client.inject: ['@deepseek-ai/dsh-client-runtime', '@deepseek-ai/dsh-client-ui-settings']`，
  而 0.1.5 **整包移除**了 `dsh-client-runtime`。今天没阻塞（组合包与该字段的消费面已换），
  但这是「声明了不存在的包」，属同类陈旧声明，需核实语义后清理或加注。

### 4（卫生）备份目录放在会生效的扫描根里
- `~/.dsh/.agent-presets/` 下同时有 `sandbar-integration/` 与 `sandbar-integration.bak-260923/`，
  备份是**完整可识别的 preset**（含 `preset.yml`+`agent.cordis.yml`，且是 0.1.1 旧 schema）→
  会作为一个可选 preset 出现在名册里，误选即挂载失败。
- 建议：备份挪到扫描根之外（如 `~/.dsh/agent-presets.bak-<日期>/`），或升级流程里明确「备份+挪走」。

### 5（脚本/机器面）机器级依赖写进了仓内脚本
- `start-console.sh` 的候选链里硬编码了 `$HOME/.sandbar/dsh-015/bin/dsh`（本次为救命加入）。
  它让「裸跑就能起来」成立，但仓内脚本依赖了机器级路径 ⇒ 换机/清理 dsh-015 后行为变化。
  建议：做成 `SANDBAR_DSH_CANDIDATES`（或读 project.yaml 的 `paths.dsh_bin`）＋文档标注。

### 6（不属于升级，但今天暴露）引擎 spawn 面 `embedded null byte`
- nusuyou t260923-04（implement 段）连环失败真因：`ValueError: embedded null byte`
  （`server/engine/agent_runtime.py:353` 的 `subprocess.Popen(cmd, cwd, env)`），
  **不是** dsh bits 问题（日志实证）。这是引擎侧缺陷，会咬任何项目；建议单独立项。

## 五、把「平台面对账」做成机械检查（本次新增的工具）

`integration/tools/dsh_surface_check.py`（只读、零网络、不起 dsh）：给定目标 dsh 安装，机械对账五类——
- **A 服务面**：我们插件 `inject` 的服务名必须存在于目标版；
- **B 访问纪律**：插件里 `ctx.X` 属性访问必须已在 `inject` 里（防「without inject」崩槽条目）；
- **C 槽选项**：往 `kind: list` 的槽注册必须带 `id`；
- **D 配置键**：roles patch / profile patch / GUI preset 里对平台包用的 config 键必须在该包 schema 里
  （区分「有默认值＝静默丢弃」与「required＝挂载即抛」）；
- **E 客户端模块**：插件 `dsh.client.inject` 点名的包必须存在。

跑法：`python3 integration/tools/dsh_surface_check.py`（缺省目标＝`~/.sandbar/projects/sandbar/project.yaml` 的 `paths.dsh_bin`）；
退出码 0/1，`--json` 供场景消费。**今天六处里，除 bits 漂移外的五处，这个脚本都能在升级前报出来。**

## 六、下次升级的检查清单（建议写进 runbook 门槛）

**升级前**
1. `dsh_surface_check.py` 对**候选版**跑一遍（红项先处置/先定性，别等切了再发现）。
2. 位钉清单齐备：引擎 `paths.dsh_bin`（每项目）、容器 `SANDBAR_AGENT_IMAGE`、`start-console.sh` 候选链、
   其它项目是否也钉（无钉＝走全局，全局坏即全坏）。
3. bits 预案：目标版本记下**验证日**，安装时用 `--before=<该日>` 钉解析；装完 `--bits-check`。
4. 机器级资产清单（**不在仓库、不进任何测试网**）：`~/.dsh/.agent-presets/*`、`~/.dsh/profiles/*` 软链、
   `~/.dsh/storages/*`（workspace 注册）、`~/.dsh/.credentials.yaml`。逐项列出「升级后谁来重建」。
5. 回退三件套现成：旧版 npm 安装命令＋bits 钉、旧 preset（**挪到扫描根外**）、旧镜像 tag。

**升级中**
6. **先请宿主停 3099**（原位换包会打挂活着的 console），再换包；console 归宿主手动起停。
7. 装完两道对账：版本字段 + `--bits-check`。

**升级后（验收口径）**
8. **真浏览器**加载页面 + 点一次「新建会话」（「组合包命中」≠ 插件激活——今天因此漏判一次）。
9. 真 spawn 一次 agent，验证**角色说明书确实进了 prompt**（不是只看它跑起来了）。
10. 走一张全链冒烟票 + 观察一个完整巡检周期；docker 形态另跑一次 spawn。

## 七、可复用的判据（写给自己）

- 上游改的是**平台面**时，我们这边**不会有编译错误、不会有测试红**——必须靠对账与真环境验收。
- 「文件在」≠「功能在」：组合包命中 ≠ 条目激活；配置项写了 ≠ 被读（未知键会被静默保留而不生效）。
- 报错文案要点名「哪一版、哪个面」：`startSession 不可用：0.1.5 起在 uiWorkspace，workspaces 现为纯控制器`。
- 与平台打交道的新代码，先问三句：**这个服务在 inject 里吗？这个槽是 list 还是 single？这个配置键目标版还在吗？**

# dsh 升级流程（0.1.1-rc.2 → 0.1.5-rc.2）runbook 草案 v0

- 日期：260916
- 宿主 260916 原则：**升级要有流程，核心是不能影响现有生产使用，且可回退**。
- 本文档=流程草案（含回退），定稿后按步执行；每步执行前在本文档打勾并记时间。
- **260923 补记（integration 落笔，宿主当日指令「补」）**：①T4 探针门槛文本自
  `integration/t260916-24/RUNBOOK_GATE.md` **并入本 §1**（该文件交付时即写明「由 integration
  落笔」）；②已交付项补勾（T1/T4/T3 代码面，票号在案）；③三问状态更新（见 §4：Q3 已答并落地、
  Q1 属 T2 宿主操作窗口、Q2 仍无人拍板）；④新增 §6「当前就绪度快照」。本 §与 §6 只记录现状与
  判据，不代替执行。

## 0. 现状与升级收益

- 现版本 dsh 0.1.1-rc.2（宿主全局 npm）；评估对象 0.1.5-rc.2（tarball 已解包核对过接口面）。
- 会话格式：v0（`session.jsonl`）→ v3（`session.v3.jsonl.zstd`）；fsync/回滚/单写者 flock 机制不变，读取端对 torn record 的拒绝不变。
- 增益：会话持久化可靠性、headless 面更新、自研 headless-resume 插件兼容已核对。

## 1. 硬门槛（不满足不开工）

- [x] **T1 读侧先行**（已交付）：引擎 4 处按字面名消费会话文件的代码先改成「双名兼容 glob」（`session.jsonl` 与 `session.v3.jsonl.zstd` 都认）：
  - `server/engine/agent_activities.py:205`（坏会话隔离 rglob）
  - `server/engine/agent_activities.py:2826`（token 统计 glob）
  - `server/plugins/workbench/src/host/agent-usage.ts:140`
  - 相关报错文案里的字面文件名
  - → 这是一条 dev-lane 前置票（先于升级单独走闸，可独立回退）。
  - **260923 勾选依据**：t260916-23（双名兼容）＋ t260917-05（会话发现面零静默降级）均已合并关闭；
    另有 t260922-02（0.1.5 记录类型面三处消费面适配 ＋ 缺失显式标注）同族收口。
- [ ] **T2 队列排空**：sandbar 在飞工单=0；无 agent 会话在写。
  - **260923 现状＝不满足**：在飞 2 张（t260922-10 / t260922-18，均处仲裁·验收段）。切换前须等其收口。
- [ ] **T3 备份**：`cp -a ~/.dsh/sessions ~/.dsh/sessions.bak-<日期>`（回退兜底第一层）。
  - **260923 现状＝未做**（尚无执行窗口；属 T2 执行前置）。
- [ ] **T4 决策三点**（见 §4）。
  - **260923 现状**：Q3 已答并落地（镜像同升）；Q1 属 T2 宿主操作窗口；**Q2 仍无拍板**（唯一真缺口）。

#### T4 探针与回归全绿（并入自 `integration/t260916-24/RUNBOOK_GATE.md`；升级候选版本先在隔离面验，全绿才进 §2 执行）

1. **接缝探针 live 档**（`integration/t260916-24/probe_dsh_seam.py`）：
   `python3 integration/t260916-24/probe_dsh_seam.py --version <候选版本>`
   （版本必须显式钉；隔离前缀安装 + 隔离 DSH_HOME 一次性真会话 + 五断言：文件名口径／解析面必填／
   记录类型族清单／沙箱不变量／钉模型生效／resume 可用）。任一拦停级红 → 不开工，逐项点名即破法定位。
   环境缺（npm/网络/凭据/zstd）= exit 2，补环境重跑。离线自检 `--selftest` 已入场景
   `t260916-24-dsh-probe-selftest`（ro 池）防探针腐烂。
   **判据口径（t260922-07 收口）**：断言 a 只认会话**正文**（`session.jsonl[.zstd]`／
   `session.vN.jsonl[.zstd]`），0.1.5 侧车 `session.lock` 按显式名单单列 INVENTORY、不计入正文计数；
   断言 c 的越界写目标建在可写三根（workspaceRoot ∪ /tmp ∪ tmpdir）**之外**
   （`$HOME/.sandbar-probe-escape/<mkdtemp>/main-repo/.git`），台账印三根审计行，
   目标意外回根内＝探针 ENV 红不判（绝不退回根内目标）。
   **双版对照硬要求（t260922-07②，下一次门槛即须执行，含 0.1.5-rc.2 复评）**：
   在位已验证版 **0.1.1-rc.2** 与候选版**各跑一遍** live 档，各自留痕 `live-run-<date>.md`，
   两版同判据结果并排落账（侧车单列口径与「越界位三根之外被拒 ＋ 根内可写对照」不变量两版都要在案）。
   注意：`live-run-260922.md` 第 2 条「0.1.5 越界写可写」系目标建在 tmpdir∈可写根内的**假红**
   （原测无效，t260922-07 已改判），**改判后重判未跑**——以上述双版对照补判，不得视为已判绿。
   **260923 执行面补记（本轮实测，跑之前必读）**：①探针必须由**能写 `$HOME`** 的执行面运行
   （越界目标位在可写三根之外；受限沙箱内会诚实地判 ENV 红并拒绝退回根内）；②npm 安装若在**受限沙箱**里跑，
   会因写不了 `~/.npm` 而 EPERM——**注意 npm 的提示文案会写成「cache folder contains root-owned files」，
   该文案具误导性**：260923 实测 `~/.npm` 下**非当前用户属主条目为 0**，根因是沙箱而非文件属主。
   稳妥做法＝换独立缓存目录（`npm_config_cache`／`--cache`）或在宿主终端直接跑；registry 本身可达；
   ③该安装**偏慢**（依赖树大、要等全部 tarball 拉完才写 `node_modules`）——别把「prefix 尚为 0B」误读成卡死，须让 600s 预算跑满。
2. **场景全集**：升级候选就位后，在隔离泳道/隔离副本先跑 `python3 integration/run_scenarios.py`
   （registry 全集，条数以该文件实时为准）全绿；engine 池（docker 台）不得借
   `SANDBAR_SCENARIO_EXCLUDE_POOLS` 豁免本轮。
3. **巡检套件**：巡检一轮全绿（含次日 07:30 调度触发的完整周期观察，衔接 §2 步骤 7）。
4. **版本面自检**：重启 worker 后 `cat <worker pidfile>.meta` 的 `dsh` 键应报新版本
   （host=实证 `--version`；docker=镜像 tag 提取）；`SANDBAR_DSH_EXPECTED_VERSION=<候选版本>`
   置于 worker 环境可让「不符」每次 spawn 响亮（`SANDBAR_DSH_STRICT=1` 升格硬闸，回退演练时可用）。
   **260923 门槛清账（integration 落笔；宿主令「在 main 上修复」，不开票）**：候选版
   **未引入任何回归**——把当日候选版跑批的 17 条非 PASS 逐条归因后，全部落在「我自己的探针改动／
   早于本日的存量红／环境假红」三类里，无一条由 0.1.5 造成：
   - 探针族（t260922-03/-07）假红：探针改「首跑/续跑产出同形」后桩仍按「有无 DSH_HEADLESS_SESSION」
     判首次/续跑（引擎**每次 spawn 都注入**该 env+patch），首跑被误判成续跑 → 桩修 create-or-resume
     真判据，断言一条未放松（`287dad5`，三条场景 9/0、11/0、6/0）；
   - 存量红：`auto-rework-trace` 其实是**崩**在 NameError（引擎在常量里调用新模块而夹具桩命名空间
     没跟上，崩点前判不到任何契约）＋调用点计数 8→9（t260916-19 门内 `_consume_rework`；兄弟守卫
     注释早已写明这次过渡，两侧同批收敛）；no-skip 门与定稿协议撞字（6 处残留**无一是真 skip 用法**，
     沿用本门既有「合法残留类别」机制补 4 类并加白名单自证）；术语门红的是**我自己**写的被禁字（探针
     19 处＋留痕 10 处＋runbook 2 处，按术语表逐义替换）；命名门 2 处（一处证词引文去字面，一处读侧
     旧名面挂 `naming-compat` 标记）——均 `32bd27a`/`09ee614`/`fa51e1e`；
   - 环境假红：**夹具桩台进程泄漏占满夹具自用的 39 口池**（3511–3549 实测 39/39 全占）→ 整族 stage
     场景自报「高位口耗尽」，最易被误读成「候选版回归」；已按仓内 30 分钟孤儿阀清场，并在夹具侧加
     **桩台寿命自毁**（`679d25a`，池子自愈；KI-096 已流转为已修）。
   - **第 2 条判据的口径澄清**：跑批里 **env_fail 结构性存在**（如 t260916-26 B2 需共享供给台，
     缺席即按三态纪律报 ENV_FAIL——不是产品红、也不冒充绿）。故第 2 条按「**零产品红（FAIL）**、
     环境红逐条在册、相对在位版零新增红」执行；本条验证待当日两批在飞机检（t260923-06、t260922-18）
     收口后跑全量复跑落账。

#### 升级切流与回退（衔接 §2/§3）

- 引擎侧只动 worker 环境旋钮：host=`SANDBAR_AGENT_CMD`（显式二进制路径）、docker=`SANDBAR_AGENT_IMAGE`
  （镜像 tag）。**但「console(3099) 用的全局 dsh 不受影响」是错的——260923 实测推翻**：dsh 的 web
  静态页与客户端模块是**每个请求现读磁盘**（`dsh-host-frontend-static/lib/index.js:64` `await readFile(target)`；
  `dsh-client-modules/lib/index.js:545/753` 请求期 `readFileSync`），全程无缓存——**原位 `npm install -g`
  会在下一秒把活着的旧 console 打挂**（旧进程启动时组好的 config 引用的包已被新版删掉 → 客户端资源 404 → 白屏）。
  故切换前必须**由宿主先停 3099**（console 属用户操作面，引擎不代停，红线 #1 自动满足指的是「引擎不去碰它」，
  不是「它不会坏」）——这是一条硬前置，不是可选项。
- 回退＝旋钮切回旧路径/旧 tag ＋ `dsh --version` 复核；meta 的 `dsh` 键即时可查证。
- **「dsh 就绪」的判据不止版本号**（260923 事故）：同一个版本号的 npm 安装会因 semver 区间解析到不同的
  传递依赖——装完必须跑 `./start-console.sh --bits-check`（§2 步 2/3）。

## 2. 升级步骤（串行，每步可独立验证）

0. [ ] **安装源核实（260916 探针实测，必读）**：包名是 **`@deepseek-ai/dsh`**（scoped）——裸 `dsh` 是另一个无关包（registry 上只有 1.0.0/1.0.1），照裸名装必失败（ETARGET 实测）。registry 现状：`latest=0.1.5-rc.1`、`next=0.1.5-rc.2`、`alpha=0.1.6-alpha.1`；**版本必须显式钉**（`@deepseek-ai/dsh@0.1.5-rc.2`），裸装会得到 rc.1。隔离预演：`npm install --prefix /tmp/dshprobe @deepseek-ai/dsh@0.1.5-rc.2 --cache /tmp/npm-cache-probe`（不碰全局安装）。
1. [ ] 停各票专属 worker 与主 sandbox worker（优雅 SIGTERM，确认 pid 退出）；**并请宿主停 3099 console**
   （原位换包会当场打挂活着的旧 console——机制见上段；console 归宿主手动起停，引擎不代停）；
2. [ ] 钉版本安装，**同时钉住依赖解析**：`npm install -g @deepseek-ai/dsh@0.1.5-rc.2 --before=2026-09-22T00:00:00+08:00 --cache /tmp/npm-cache-upgrade`
   （前缀决策见 §4-Q2；`--cache` 绕开 `~/.npm` 属主问题）。`--before` 让 npm 按该时刻的 registry 状态解析依赖
   ——**这正是「版本号相同、bits 不同」的解法**（260923 事故即当日新发的 cordis 族依赖被解析进来）；
   已验证解析集＝`cordis 4.0.2 / cordis-plugin-loader 1.0.3 / cordis-plugin-hmr 1.0.17`（装完的三道对账见步 3）；
3. [ ] **装完三道对账（版本号对不代表可用；260923 六处事故里五处落在这三道之外）**：
   - ① 版本字段：`@deepseek-ai/dsh` 的 version == 0.1.5-rc.2（防 dist-tag 漂移）；
   - ② **bits 指纹**：`./start-console.sh --bits-check` 绿——校验 cordis 族解析集与
     「hmr 里是否真带 launcher 必调的 `registerConfig`」（260923 就是死在只校了 ①）；
   - ③ **平台面对账**：`python3 integration/tools/dsh_surface_check.py`（对**目标版**跑，升级前跑更好）绿——
     机械对账五类：A 我们 inject 的服务名在不在目标版／B 有没有「未 inject 就属性访问」的雷／
     C 往 list 槽注册带没带 id／D roles·profile·preset 里的 config 键在不在目标版 schema
     （**有默认值＝静默丢弃**，如 `dsh-system-prompt.persona` → `personaPrefix`）／
     E 插件 `dsh.client.inject` 点名的包还在不在。红项逐条定性后再切。
4. [ ] `dsh --version` == 0.1.5-rc.2；起一次 console 冒烟（宿主操作）：顶部不得出现
   「Failed to load plugins」横幅、token URL 能进页面；**真浏览器加载 + 点一次「新建会话」**
   （「组合包命中某插件」≠ 该插件激活——260923 因此漏判过一次）；`dsh` 起一个一次性会话，确认落盘
   `session.v3.jsonl.zstd` 且旧 `session.jsonl` 未被改动；
5. [ ] 容器面（若 Q3=同升）：`bash server/engine/build_agent_image.sh`（DV=0.1.5-rc.2）→ 镜像 `sandbar-agent:dsh-0.1.5-rc.2-s1`；同步改三处版本（`Dockerfile.agent` ARG、`build_agent_image.sh` DV、`agent_runtime.py DEFAULT_AGENT_IMAGE`——有测试 `test_镜像版本三处同步` 锁定）；
6. [ ] 重启全部 worker（先主 sandbox，后按需起票 worker）；
7. [ ] **生产冒烟**：开一张 sandbar 冒烟票走完 create_plan→…→closed 全链；确认 agent 会话可写可读、token 统计面正常、workbench 会话用量页正常；
   **并单独验一次「角色说明书真的进了 agent prompt」**（起一个 headless agent 问它角色名即可——
   260923 实证：配置键改名后 agent 照常跑、票面全绿，但岗位说明书整段没了）；
8. [ ] 观察一个完整巡检周期（次日 07:30 调度触发正常）后宣布完成。

## 3. 回退（任一步失败或冒烟不过即走）

0. **回退三件套齐备**（260923 复盘补）：① 旧版安装命令**同样要钉 bits**（`--before=<0.1.1 的验证日>`
   或 overrides），否则再吃一次依赖漂移；② GUI preset 换回 0.1.1 版（现存
   `~/.dsh/.agent-presets/sandbar-integration.bak-260923/`；注意它现在躺在**会生效的扫描根里**，见 KI-103）；
   ③ 容器 tag 切回 `sandbar-agent:dsh-0.1.1-rc.2-s1`（镜像在）。
1. `npm install -g dsh@0.1.1-rc.2`（同前缀；`--cache` 同上）；
2. 容器面若已重建：镜像 tag 切回 `sandbar-agent:dsh-0.1.1-rc.2-s1`（旧镜像不删）；
3. 重启全部 worker；
4. 会话数据：**v3 写的会话在 0.1.1 下不可读**——回退后新会话恢复旧格式文件名，v3 期间产生的会话文件保留不删（留待再次升级后读取）；这正是 T1 读侧双名兼容的价值：升级与回退两个方向都不丢已有会话；
5. 回退后开一张冒烟票复验全链。

## 4. 待宿主决策（就是之前说的「三问」，纳入流程）

- **Q1 窗口**：建议=队列为空的任意时点即可；若要严格无影响，选「无在飞票 + 无 agent 会话活跃」的窗口执行，全程预计 30~60 分钟（含冒烟）。
  - **260923 状态＝未开工（设计如此，非欠答）**：文档口径=宿主全局升级与切换**由宿主在 T2 执行时操作**
    （前置＝本票试验协议 `integration/t260921-14/TRIAL_RUNBOOK.md` 绿）。**当前前置不满足**：队列非空
    （在飞 2 张），且试验协议尚未执行。
- **Q2 npm 前缀**（~~方案 A=sudo 装回原位；方案 B=用户级前缀；二选一~~ ← **原表述已作废，见下**）：
  **宿主管 260923 裁定＝按 A 执行，且无需二选一**——
  - **裁定依据（260923 实测，原「二选一」的两条前提都不成立）**：
    ① `npm config get prefix` = `/opt/homebrew`，而 `/opt/homebrew/lib/node_modules` 与 `/opt/homebrew/bin`
    的**属主都是当前用户**（`user:admin`，均含写位），现装全局 dsh 也是 8/22 由该用户装的
    ——**「用户不可写、需批 sudo」不成立，A 案不需要 sudo**；
    ② `~/.npm` 下**非当前用户属主条目为 0**（代签人早前「root 属主缓存」的判断系受限沙箱下的误读，
    已同步改正 §1-T4 补记与 live-run-260923-015.md）。
  - **裁定口径**：Q2 实际只剩「敲裸 `dsh` 时命中哪一份」，取舍为 **A＝装回原位**
    （零路径改动、`ROLLBACK.md` 剧本现成、免 sudo）；**B 仅在将来想彻底摆脱 homebrew 前缀时才考虑**
    （届时须同批迁包 + 改回退剧本路径 + 理清 PATH 归属）。
  - **执行次序（与试验解耦）**：试验期**原位那份 0.1.1 不动**（＝回退面），引擎侧只走
    `paths.dsh_bin` 路径钉指向试验二进制（`~/.sandbar/dsh-015/bin/dsh`）；待试验与巡检全绿，
    再 `npm install -g @deepseek-ai/dsh@0.1.5-rc.2` 完成全局切换（回退＝装回 0.1.1，剧本现成）。
  - 引擎侧无论 A/B 都走 `paths.dsh_bin` 路径钉（t260921-14 交付），**试验与切换都不依赖本项位置选择**。
- **Q3 容器镜像**：同升（推荐，版本一致避免宿主/容器行为分叉）or 先只升宿主、容器明确留 0.1.1-rc.2（镜像 tag 不动）。
  - **260923 状态＝已答并已落地**：**同升 0.1.5-rc.2**——t260921-14 完成三处同步锁
    （`DEFAULT_AGENT_IMAGE`／`Dockerfile.agent` ARG／`build_agent_image.sh` 缺省），旧 tag
    `sandbar-agent:dsh-0.1.1-rc.2-s1` 保留为回退面（`ROLLBACK.md` 剧本）。
    **但镜像本体仍未构建**（见 §6 就绪度快照第 3 条）——切换前必办。

## 5. 风险清单

| 风险 | 缓解 |
|---|---|
| **同版本号 ≠ 同 bits**（260923 实弹，本手册最大盲区） | semver 区间会解析到上游当天新发的传递依赖：`cordis-plugin-hmr` 1.0.18 删掉了 launcher 在 `patchReload: live` 下必调的 `registerConfig` → 该安装**自不相容**（手动开 hmr 会撞更深的同类错，profile 侧改不动）。缓解＝装时 `--before` 钉解析（§2 步 2）+ `start-console.sh --bits-check` 当闸（§2 步 3）——**只校 `--version` 判不出可用** |
| **原位换包打挂活着的 console**（260923 实弹，同一次事故的白屏半边） | 客户端资源/静态页按请求现读磁盘、无缓存 → `npm install -g` 即把旧 console 打成白屏（旧 config 引的包被新版删）。缓解＝切换前宿主先停 3099（§2 步 1，硬前置）；`start-console.sh` 现会在启动时对账 bits，能起来的就是对的套 |
| **机器级 GUI preset 未纳入兼容面**（260923 实弹） | `~/.dsh/.agent-presets/<项目>-<角色>/agent.cordis.yml` 是 0.1.1 时代的**实体拷贝**：不在仓库、不在任何测试网、不在接缝矩阵里。0.1.5 把 dsh-persona 的配置 schema 由 `text:` 改成 `prefix:/suffix:`（`prefix` 必填）→ 旧拷贝**挂载即抛** → 新会话起不来、老会话续不上。缓解＝升级后重建 preset（备份原目录），流程见 §6 第 7 条；接缝矩阵已补该行（行 14） |
| v3 会话文件打坏引擎读侧 | T1 前置票先落（双名 glob），有场景看守 |
| npm 全局权限/属主 | `--cache` 绕 cache 目录；前缀按 Q2 决策 |
| 升级中宿主误用 dsh | 停 worker 后立即升级+重启，窗口短；或挑你不用 dsh 的时段 |
| 混代双写（升级后旧 worker 还活着） | 步骤 1/6 串行保证；worker.pid 检查进 checklist |
| **其它项目无 dsh 钉 → 裸 `dsh` 落坏套**（260923 查明） | 只有 sandbar 在 `~/.sandbar/projects/sandbar/project.yaml` 声明了 `paths.dsh_bin`；nusuyou/dengzhufpv 等处 worker spawn 走 `来源=default` 的裸 `dsh`（worker 日志实证），即**全局那套是它们唯一的面**——故全局 bits 出问题时坏的是所有项目的 agent 段，不只是 console。缓解＝全局安装保持指纹绿（本次已重装回已验证解析集） |
| 回退后 v3 会话不可读 | §3.4：保留文件不删；T1 双名读侧保证下次升级可续 |

## 6. 当前就绪度快照（260923，integration 落笔；只记事实与判据）

1. **代码/票据面：基本就绪**。epic dsh-upgrade 下 14 张票，13 张已关闭（T1／T4／T5／T6／T3 各票
   与今日 t260922-02（记录类型面）、-06（会话 id 寻址）、-07（侧车与探针判据精度）、-11（撕裂档
   点名自动隔离）均已合入 main）。唯一在飞的是 t260922-10「引擎 ops 记名清场入口」——挂在
   本 epic 下但**不是升级阻塞项**（其内容为通用 ops 缺口）。
2. **门槛面：文本已入册（§1）；接缝探针双版对照已于 260923 执行完毕、两版并排全绿**。
   探针离线自检全绿（`--selftest`：金样本 4 档 + 篡改 7 档逐项红＋prompt 守卫＋凭据归因）；
   **live 档双版对照结果**：在位 0.1.1-rc.2（`--inplace`）与候选 0.1.5-rc.2 各 **PASS=12 FAIL=0 ENV=0（RC=0）**，
   留痕见 `integration/t260916-24/live-run-260923-011.md` 与 `-015.md`（并排对账表在文内）。
   本轮同时修掉探针自身两处口径错（resume 两组生产同形、对照组 `--inplace`），修法与本轮三条执行面注意
   已写入 §1-T4 条目；探针版本体改动见 main 提交（260923）。
   ⇒ **§1-T4 第 1 条（接缝探针 live 档）已满足**；第 2/3/4 条（候选版场景全集隔离副本整跑、巡检一轮、
   版本面自检）**仍未执行**——本行未全部打勾前，不得视为「可以切」。
3. **容器镜像面：260923 已办结（本行原写「0.1.5 镜像不存在」，实测已失效，改事实）**——
   `docker images` 实测：`sandbar-agent:dsh-0.1.1-rc.2-s1` 与 **`sandbar-agent:dsh-0.1.5-rc.2-s1` 都在**，
   引擎缺省 `DEFAULT_AGENT_IMAGE` 已指 0.1.5。**但 docker 形态 spawn 至今未实跑过**（当前 lane 走 host 形态），
   下次升级前补一次。（原文如下，仅作沿革）
   - 现状：`server/engine/agent_runtime.py:46 DEFAULT_AGENT_IMAGE = "sandbar-agent:dsh-0.1.5-rc.2-s1"`
     （缺省已翻新），而 `docker images` 只有 `sandbar-agent:dsh-0.1.1-rc.2-s1`（9 天前）——
     **0.1.5 镜像不存在**，且全仓没有任何地方设 `SANDBAR_AGENT_IMAGE` 指回旧 tag。
   - 影响：**docker 形态 spawn 会因镜像缺席失败**（本部署当前 lane agent 走 host 形态
     ——`dsh_pin_<tag>.json` 实测 `mode=host`——故尚未咬到；一旦以 docker 形态起票即炸）。
   - 处置二选一：`sh server/engine/build_agent_image.sh`（缺省 DV=0.1.5-rc.2，联网窗口一次性），
     或在 worker 环境设 `SANDBAR_AGENT_IMAGE=sandbar-agent:dsh-0.1.1-rc.2-s1`。
4. **三问**：Q3 已答落地（镜像同升，镜像本体 260923 已建）；Q1 属 T2 宿主操作（前置未满足）；
   **Q2 已裁定＝按 A（原位、免 sudo），不必二选一**（宿主管 260923，依据见 §4）。
5. **可切性的最短路径（建议序，260923 晚更新）**：①等 t260922-18 收口（T2 队列排空；10 已关）→
   ②§1-T4 第 2/3/4 条（候选版场景全集隔离副本整跑、巡检一轮、版本面自检；第 1 条接缝探针双版对照
   **已于 260923 全绿**）→ ③按 §2 八步执行（**切换那一下必须由宿主先停 3099**——「只动 worker 侧旋钮、
   console 不重启」的旧口径已被 260923 白屏事故推翻，见下第 6 条）→ ④生产冒烟票＋观察一个完整巡检周期。
   ~~（旧序中的「明确 Q2」「建 0.1.5 镜像」「T3 备份」三项均已办结：Q2 裁定见 §4、
   镜像 260923 已建、备份 260923 已做。）~~
6. **260923 事故与修复（宿主报「在外头修了一下才能进 console」；宿主令「不开票，直接搞好」）**：
   - **事故链**：09-23 10:13 `npm install -g @deepseek-ai/dsh@0.1.5-rc.2` 装出的那套，与 09-21
     验证过的 tarball 解包**不是同一套 bits**（同版本号、240 个包中有 8 个版本不同：cordis 4.0.3／
     loader 1.0.4／**hmr 1.0.18**／group、include、timer、cosmokit、schemastery 各高一档）；
     `hmr@1.0.18` 删掉了 `registerConfig`，而 `dsh-app-boot/lib/index.js:1115` 的 `watchUserPatches`
     必调它、`lib/profile-boot-Dk-7KqJc.js:321` 在 `patchReload==="live"`（自定义 profile 缺省）下
     会动态挂 hmr 再调 → **该安装自不相容**；同时原位换包把当时活着的旧 console 静态资源打挂（白屏）。
   - **修复（main 侧，同日）**：
     ① 全局重装成已验证解析集——`npm install -g @deepseek-ai/dsh@0.1.5-rc.2 --before=2026-09-22T00:00:00+08:00`；
     现全局树与 `~/.sandbar/dsh-015` **240 个包零版本差异**；
     ② `start-console.sh` 加 bits 指纹对账（`--bits-check` 可单跑：不指定 `DSH_BIN` 时自动挑能用的那套，
     显式指定坏套则响亮拦下、不静默替换；默认取值不再裸信 PATH，机器钉优先）——治「裸跑 `./start-console.sh`
     必踩坏套」这个最可能复发的入口；
     ③ 回归用例 `integration/tests/test_start_console_bits.py`（8 条，全离线、不占端口、不起服务）；
     ④ 验证口径：用 stage 台（独立端口 3288 + 独立 `DSH_HOME`）实起修复后的全局那套 → **干净 boot +
     `selfcheck` 全绿（pass 7 / red 0）**；起完即停、临时 home 已清、3099 全程未动。
   - **附**：其它项目（nusuyou/dengzhufpv）未声明 `paths.dsh_bin`，worker spawn 走裸 `dsh`——
     全局 bits 坏掉时它们一起坏（见 §5 风险表末两行）。
7. **GUI preset（机器级）重建流程（260923 立，0.1.1→0.1.5 实案）**：
   ① 先备份：`cp -a ~/.dsh/.agent-presets/<项目>-<角色> ~/.dsh/.agent-presets/<项目>-<角色>.bak-<日期>`；
   ② 本体＝目标版**出厂 standard 组合**原样拷贝（保证可挂载），只改 persona 一处；
   ③ persona 按新 schema 承载（0.1.5 起 `dsh-persona` 的 `prefix` 必填、旧 `text:` 键挂载即抛），内容
   同步自角色真源 `server/roles/<角色>.yml` 的岗位说明书全文；
   ④ 用 dsh 自带 YAML 解析器校验（注意文件里有 `!!js` 标签，PyYAML 会拒——用 dsh 内 `yaml@2.9.1` +
   `tag:yaml.org,2002:js` 自定义标签解析，断言条目数与 `prefix` 非空）；
   ⑤ 校验「preset 的 persona 文本与 `server/roles/<角色>.yml` 逐字一致」——**逐个字符比对，不靠肉眼**。

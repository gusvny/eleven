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

#### 升级切流与回退（衔接 §2/§3）

- 引擎侧只动 worker 环境旋钮：host=`SANDBAR_AGENT_CMD`（显式二进制路径）、docker=`SANDBAR_AGENT_IMAGE`
  （镜像 tag）——console(3099) 用的全局 dsh 不受影响（红线 #1 自动满足）。
- 回退＝旋钮切回旧路径/旧 tag ＋ `dsh --version` 复核；meta 的 `dsh` 键即时可查证。

## 2. 升级步骤（串行，每步可独立验证）

0. [ ] **安装源核实（260916 探针实测，必读）**：包名是 **`@deepseek-ai/dsh`**（scoped）——裸 `dsh` 是另一个无关包（registry 上只有 1.0.0/1.0.1），照裸名装必失败（ETARGET 实测）。registry 现状：`latest=0.1.5-rc.1`、`next=0.1.5-rc.2`、`alpha=0.1.6-alpha.1`；**版本必须显式钉**（`@deepseek-ai/dsh@0.1.5-rc.2`），裸装会得到 rc.1。隔离预演：`npm install --prefix /tmp/dshprobe @deepseek-ai/dsh@0.1.5-rc.2 --cache /tmp/npm-cache-probe`（不碰全局安装）。
1. [ ] 停各票专属 worker 与主 sandbox worker（优雅 SIGTERM，确认 pid 退出）；
2. [ ] 钉版本安装：`npm install -g @deepseek-ai/dsh@0.1.5-rc.2`（前缀决策见 §4-Q2；`~/.npm` 属主问题用 `--cache /tmp/npm-cache-upgrade` 绕开）；装完确认 `@deepseek-ai/dsh` 的 version 字段 == 0.1.5-rc.2（防 dist-tag 漂移）；
3. [ ] `dsh --version` == 0.1.5-rc.2；冒烟：`dsh` 起一个一次性会话，确认落盘 `session.v3.jsonl.zstd` 且旧 `session.jsonl` 未被改动；
4. [ ] 容器面（若 Q3=同升）：`bash server/engine/build_agent_image.sh`（DV=0.1.5-rc.2）→ 镜像 `sandbar-agent:dsh-0.1.5-rc.2-s1`；同步改三处版本（`Dockerfile.agent` ARG、`build_agent_image.sh` DV、`agent_runtime.py DEFAULT_AGENT_IMAGE`——有测试 `test_镜像版本三处同步` 锁定）；
5. [ ] 重启全部 worker（先主 sandbox，后按需起票 worker）；
6. [ ] **生产冒烟**：开一张 sandbar 冒烟票走完 create_plan→…→closed 全链；确认 agent 会话可写可读、token 统计面正常、workbench 会话用量页正常；
7. [ ] 观察一个完整巡检周期（次日 07:30 调度触发正常）后宣布完成。

## 3. 回退（任一步失败或冒烟不过即走）

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
| v3 会话文件打坏引擎读侧 | T1 前置票先落（双名 glob），有场景看守 |
| npm 全局权限/属主 | `--cache` 绕 cache 目录；前缀按 Q2 决策 |
| 升级中宿主误用 dsh | 停 worker 后立即升级+重启，窗口短；或挑你不用 dsh 的时段 |
| 混代双写（升级后旧 worker 还活着） | 步骤 1/5 串行保证；worker.pid 检查进 checklist |
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
   本轮同时修掉探针自身两处口径错（resume 两腿生产同形、控制腿 `--inplace`），修法与本轮三条执行面注意
   已写入 §1-T4 条目；探针版本体改动见 main 提交（260923）。
   ⇒ **§1-T4 第 1 条（接缝探针 live 档）已满足**；第 2/3/4 条（候选版场景全集隔离副本整跑、巡检一轮、
   版本面自检）**仍未执行**——本行未全部打勾前，不得视为「可以切」。
3. **容器镜像面：存在一处既存不一致，切换前必办**（t260921-14 自己的 merge 关卡检查项①
   「建 0.1.5 镜像 或 worker env 指回旧 tag，两者必居其一」）：
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
   **已于 260923 全绿**）→ ③按 §2 七步执行（只动 worker 侧旋钮，console 3099 不重启；
   试验期原位 0.1.1 不动）→ ④生产冒烟票＋观察一个完整巡检周期。
   ~~（旧序中的「明确 Q2」「建 0.1.5 镜像」「T3 备份」三项均已办结：Q2 裁定见 §4、
   镜像 260923 已建、备份 260923 已做。）~~

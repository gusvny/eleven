# Temporal POC — workflow + schedule 模型验证（t260821-01）＋ 正式化步1（t260821-02）

**目的**：不迁移任何现有数据，只验证「用 Temporal 当工单/流水线引擎」这个模型成不成立。
四个要证明的点（工单原文）全部**跑通并留有输出存档**，见 §3。

**边界（已实测遵守）**：全部产物在本目录内；23 张现有工单、`server/tools/ticket.py`、
`app/public/data/`、`pipeline/output/` 一字未动（§6 有 git 证据）。POC 对仓库的唯一外部动作是
**只读**调用 `server/admin.py call qc_run` / `call ticket {"op":"list"}`
（admin.py 每次调用照例往 `server/admin.log` 追一条审计 JSONL——那是 admin 层既有设计，已 gitignore）。

---

## 1. 怎么起（三步，全在本目录）

```bash
cd server/engine
./setup.sh          # ① 装环境：下 temporal 单二进制 → bin/temporal；建 .venv 装 temporalio
./run_server.sh     # ② 另开一个 shell：temporal dev server（SQLite 落盘，免 docker/postgres）
                    #    gRPC 127.0.0.1:7233 / Web UI http://127.0.0.1:8233
./demo.sh           # ③ 一键跑四个 demo（自己起停 worker，输出同时落 out/）
```

只想手动玩：`./run_worker.sh`（另一个 shell 常驻）+ `.venv/bin/python demo_happy.py`。

**为什么不是 `brew install temporal`**：本机 `/opt/homebrew` 对执行 agent 的沙箱只读
（`touch /opt/homebrew/x` → Operation not permitted，且本会话审批被禁用无法升级权限）。
所以走官方**单二进制**路径：`https://temporal.download/cli/archive/latest?platform=darwin&arch=arm64`
→ 解到 `bin/temporal`。实测版本 **temporal CLI 1.8.2（Server 1.31.2, UI 2.50.1）**；
python 侧 `.venv`（系统 python 3.9.6）+ **temporalio 1.18.2**。
`bin/ .venv/ data/` 全部 gitignore，`./setup.sh` 幂等可重建。

## 2. 目录

| 文件 | 是什么 |
|---|---|
| `shared.py` | 配置与数据契约（七段 STAGES、人门集合、workflow id 约定、dataclass 载荷） |
| `workflows.py` | **状态机本体**：`ContentPipelineWorkflow`（七段）+ `DispatcherScanWorkflow`（巡检） |
| `activities.py` | 有副作用的动作：`machine_qc`（跑真 qc_run）/`ticket_scan`（只读 list）/加工·审校·发布占位 |
| `worker.py` | worker（注册 workflow+activity 到 task queue `sandbar`，LEGACY `suyou-poc` 双 poll 过渡） |
| `fixtures/qc_red_stub.py` | 红灯 fixture：印一份与 qc_run **同契约**的 green=false JSON（见 §4） |
| `demo_happy.py` / `demo_fail.py` / `demo_schedule.py` / `demo_durability.sh` | 四个 demo |
| `demo.sh` | 一键全跑 + 存档 |
| `out/` | **演示输出存档**（demo-A/B/C/D + demo-full.txt + git-baseline.txt） |

## 3. 四个证明点：各看哪里

| # | 要证明的 | 代码在 | 演示输出 |
|---|---|---|---|
| 1 | **状态机=代码推进、历史不可变**：七段顺序与门写死在 workflow 代码里，agent 只能 signal/activity，改不动状态 | `workflows.py` 的 `run()` + 唯一入口 `_enter()`；`force_stage` signal 一律拒绝 | `out/demo-A-happy.txt` ③（agent 要求直接跳 publish → stage 一动不动，被拒记录留痕）+ ⑧（全量事件历史，signal/activity 逐条有据） |
| 2 | **验收机械化**：machine-qc 是 activity 跑真实脚本，绿才推进 | `activities.py: machine_qc` 跑 `python3 server/admin.py call qc_run {"scope":"260627"}`；判绿只看 `green` 字段 | `out/demo-A-happy.txt` ④（四项红绿灯 green=true, red_count=0，exit_code=0）；红灯路径见 `out/demo-B-red-blocked.txt` |
| 3 | **人门=signal**：approve / final-review 无超时挂起，只有签字能解；终审只能是人 | `workflows.py`：`wait_condition(lambda: gate in self._sigs)`；`sign()` 只认 `approve`/`final-review` | `out/demo-A-happy.txt` ②（起来就停在 approve/awaiting-human）⑤（终审打回 → 自动回加工重跑机器门）⑥（再签才发布） |
| 4 | **单例 + 调度**：Schedule 定时触发巡检；workflow id 即锁 | `demo_schedule.py`（`ScheduleSpec` 15s + `overlap=SKIP`）；`shared.pipeline_wf_id()` | `out/demo-C-schedule-dedup.txt`：C-1 手动 trigger + 自然周期各一次（num_actions=2）、巡检读出真实工单分布 `{closed:27, dispatched:1, rework:1}`；C-2 同 id 二次 start → `WorkflowAlreadyStartedError` |

**失败路径（工单验收第 3 条）** `out/demo-B-red-blocked.txt`：
机器门红 2 项 → `stage=machine-qc/stage_state=blocked`，静置 6s 不动、execution 仍 RUNNING
（**红灯不是失败，是闸门关着**）；agent 喊「修好了」发 `retry_qc` 只是请求**重跑脚本**，
脚本还红就还是卡（跑了 2 次仍 red_count=2）；历史里 `ai_review_stub` / `publish_dry_run`
**一次都没被调度**（下游一步没走）。

**加送的第五个点** `out/demo-D-durability.txt`（worker 重启）：
杀掉 worker → 服务端里流水线仍 RUNNING；停机期间发的 signal 照收进不可变历史、排成待办
（`有待办workflowTask=True`）；worker 重启后攒下的活自动执行（机器门次数 +1）。
这条是「agent 会话结束/换人/崩了不丢状态」的模型基础——也是现在 md/json 工单最脆的地方。

## 4. 演示红灯为什么用 fixture（诚实说明）

现库 `qc_run(scope=260627)` 是**全绿**的（这也正是绿灯路径用真脚本的原因）。要演示「红灯卡住」
就不能去改真实内容数据（内容归编辑，POC 零碰）。所以只把 activity 要执行的**命令**换成
`fixtures/qc_red_stub.py`（输出与 qc_run 同 JSON 契约、green=false），
**activity 里判绿的代码一字不改**——避免「为了演示失败在业务代码里埋假分支」。
绿灯路径（Demo A）跑的是真脚本，红灯路径（Demo B）跑的是同契约 fixture，两条路一套判据。

同理诚实标注的占位：`process_stage`（加工只登记交接，不生产内容）、
`ai_review_stub`（**不调模型**）、`publish_dry_run`（**零写入**，真发布链应换成
`verify_lane content` + `build_shelf` 那套 activity）。

## 5. 对现有引擎的意味（迁移评估，供总管/用户判断，POC 不动手）

现有 `server/tools/ticket.py` + `docs/design/工单工作流台设计.md` §8/§9 的语义，对到 Temporal 上：

| 现在（json 工单 + 引擎校验） | Temporal 里对应物 | 白拿的好处 |
|---|---|---|
| `stages` yaml 模板 + `advance` 校验 | workflow 代码里的执行顺序 | 状态无法被绕过写（不是「引擎劝你别跳」，是**跳不了**） |
| `exit: human` + `stage_state=awaiting-human` | signal + `wait_condition` 无超时挂起 | 挂多久都不丢，进程可重启 |
| `log[]` / `handoffs[]` 手写数组 | 事件历史（服务端持久化） | 免维护、不可篡改、天然可追溯（防幻觉第五层） |
| `accept {evidence}` 脚本输出原文 | activity 返回值自动进历史 | 「我检查了」不算证据 → 变成结构化事实 |
| `revision_count ≤ 2` 硬校验 | workflow 里的循环计数（POC 已实现 `MAX_REVISIONS=2`） | 同 |
| 「一张提案一条流水线」靠人不撞 | workflow id 即锁（AlreadyStarted） | 重复派活自动被拒，不用写 lockfile |
| dsh-schedule / launchd 定时巡检 | Schedule（可 pause/trigger/查 num_actions） | 巡检本身有历史、可暂停、跑没跑一眼可见 |
| `dispatch-next` 生成派活指令 | activity 里调 dispatch + **async activity completion**（token 交给 agent，agent 干完回调完成） | agent 变成「长活 activity」，超时/重试/心跳是引擎的事 |

**要付的代价 / 必须先定的事**（迁移前的硬问题，POC 只列不拍）：
1. **模板从数据变代码**：yaml「丢文件即上线」的热插拔会丢。折中做法=把模板作为 workflow **input**
   传入（一条流水线一旦启动就钉死那份模板），仍可热改模板但不破坏确定性。
2. **workflow versioning**：改了流程代码，running 的老实例怎么办（`patched()`/版本分支）——
   这是 Temporal 的固有作业，迁移第一天就得立规矩，否则改一次代码卡死一批在跑的工单。
3. **常驻进程 +1（或 +2）**：temporal server + worker 都要常驻（本机 launchd；dev server 用 SQLite，
   将来上服务器要 Postgres）。现在的 ticket.py 是「无常驻进程、文件即真相」，这条是取舍不是优劣。
4. **依赖口径**：`temporalio` 不是 stdlib，与 `server/` 现在的「纯 stdlib」口径冲突（需用户点头）。
5. **UI 与工具面**：`sandbar-workbench` 要改读 Temporal（或让 activity 把状态**投影**回
   `tickets/*.json` 当只读视图，UI 不改——迁移期建议走投影，双写只读不双主）。
6. **工具面必须只暴露 signal/query**：给 agent 的 dsh 工具只能有
   `pipeline_status`(query) / `pipeline_sign`(签字，身份注入) / `pipeline_retry_qc` / `pipeline_start`；
   一旦暴露「设置 stage」，证明点 1 立刻失效。

## 6. 零改动证据

`out/git-baseline.txt` 是开工前 `git status --porcelain` 快照（当时已有 54 行改动，全部属其它并行泳道）。
完工核对方式（任何人可复跑）：

```bash
cd /Users/user/Documents/suyou
git status --porcelain -- server/tickets server/tools/ticket.py app/public/data pipeline/output \
  > /tmp/after.txt
grep -E "server/tickets|server/tools/ticket.py|app/public/data|pipeline/output" \
  server/engine/out/git-baseline.txt > /tmp/before.txt
diff /tmp/before.txt /tmp/after.txt && echo "现有工单/引擎/数据零改动 ✅"
```

`out/zero-touch-check.txt` 存了本次完工时的实跑结果。

## 7. 已知限制（未验证的，别当成已证）

- dev server = 单机 SQLite（`data/temporal.db`，gitignore），**无鉴权**（同 dsh web 回环口径）；
  生产形态（Postgres / Temporal Cloud / 反代鉴权）未评估。
- `ai-review` 未接模型、`publish` 未接真发布链、`process` 未接真派活（都是显式占位，见 §4）。
- 未做 workflow versioning 实验（§5 第 2 条），未压测，未验证 worker 常驻（launchd）与开机自启。
- 本会话沙箱下 `/bin/ps`、`pkill` 不可用（Operation not permitted），所以 Demo D 一律按自己记下的
  PID 发信号；脚本里没有进程枚举。
- 残留物：Demo B 故意把 `content-pipeline:p260821-red` 留在 running（UI 里看得见；
  260904 宿主令 content-pipeline 模板退役后此为历史残留实例，terminate 即清）；
  schedule（LEGACY 旧 id `suyou-dispatcher-scan`，现 `sandbar-dispatcher-scan`）跑完是 **paused** 状态。清场：
  `bin/temporal workflow terminate -w content-pipeline:p260821-red --address 127.0.0.1:7233 --reason 清场`、
  `bin/temporal schedule delete --schedule-id sandbar-dispatcher-scan --address 127.0.0.1:7233`（LEGACY 旧 id 由 scan_schedule 幂等删旧退役）；
  彻底重置=停 server 后删 `data/`。

---

## 8. 正式化步1（t260821-02）：client CLI + worker 定形 + dsh 插件壳

步1 只做**工具面**：client.py 五子命令 CLI、worker 前台/后台+优雅停、dsh 插件
`server/plugins/temporal-tools/`（模型可见工具）。七段状态机（§2 的 `workflows.py`）语义原样不动；
「把 ticket.py 的 stage 推进切到 Temporal + 现有工单 adopt」是**步2（t260821-03）**，不在此步。

### 8.1 client.py —— CLI 子命令（安全红线）

工具面**绝无 set-stage / force_stage / 改状态入口**（260904 宿主令后 start 只剩
dispatcher-scan，signal 已退役——sign/retry_qc 只服务 v1 content-pipeline 人门段，
模板删后保留子命令名做 fail-closed 退役报错；工单签字走 `ticket op=sign`）：

| 子命令 | 干什么 | 例 |
|---|---|---|
| `start` | 启动 workflow（260904 起仅 dispatcher-scan） | `python client.py start '{"type":"dispatcher-scan","id":"dispatcher-scan"}'` |
| `query` | 只读 workflow 快照（stage/stage_state/qc_runs/timeline） | `python client.py query '{"workflow_id":"t260822-01"}'` |
| `signal` | **已退役（260904）**：调用一律结构化报错 | — |
| `schedule-list` | 只读列 Schedule | `python client.py schedule-list` |
| `cancel` | terminate 一个 workflow（清场/撤销） | `python client.py cancel '{"workflow_id":"…","reason":"清场"}'` |

以上是步1 的五子命令壳；v2 时代另有 ticket / ticket-start / ticket-list / ticket-query /
ticket-prune / ticket-archive-legacy / running-tickets 等工单面子命令（`client.py` 无参
运行看 USAGE 全表）。

stdout 一律单行 JSON `{ok, result|error}`，供 node.ts 插件解析。审计=workflow 事件历史本身。

### 8.2 worker.py —— 前台 / 后台 + 优雅停

```bash
.venv/bin/python worker.py                                      # 前台（看日志）
.venv/bin/python worker.py --daemon --pidfile data/worker.pid \
                             --logfile data/worker.log          # 后台（常驻）
kill -TERM "$(cat data/worker.pid)"                             # 优雅停：停领新活 + 宽限期内跑完在飞 activity（§8.3.1）
SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC=600 .venv/bin/python worker.py …   # 宽限可调（缺省 1800s；显式 "0"=立即取消旧行为）
```

worker 是「肌肉」，服务端是「骨架与记忆」：worker 挂了/换新进程，服务端里的 workflow
状态与历史不丢，停机期间攒的活等重启后自动补跑（POC 证明点 D）。优雅停的宽限语义、
在飞点名与运维口径见 §8.3.1（t260916-29）。

### 8.3 server / worker / 插件 三者启动与生命周期

| 组件 | 启动 | 生命周期 | 挂了会怎样 |
|---|---|---|---|
| temporal dev server | `./run_server.sh` | 常驻；SQLite 落盘 `data/temporal.db`（gitignore） | workflow 状态/历史都在它这；不删 data/ 不丢 |
| worker | `worker.py [--daemon]` | 常驻；`kill -TERM` 优雅停（宽限期 §8.3.1） | 可随时换/重启；停机期间 workflow 仍 RUNNING，重启自动续 |
| dsh 插件 `sandbar-temporal-tools` | profile `cordis.patch.yml` 的 `- insert` 行 | 随 dsh 进程加载；每次工具调用 spawn `client.py` | 无状态；server/worker 不在线时工具调用结构化报错 |

插件加载：`server/profile/node_modules/sandbar-temporal-tools → ../../temporal-tools`
（与 sandbar-workbench 同款裸包名软链；profile-headless 有同款软链）。默认 python 取
`engine/.venv/bin/python`（temporalio SDK 装在仓库内 venv，不碰系统 python）。

### 8.3.1 运维口径：console(3099) 与票 worker 生命周期（t260916-29）

**核心事实：重启/重载 console（3099）会波及全部在飞 agent 阶段。** 票专属 worker 是
console 的子进程（console ensure 负责补拉，260824 宿主决策，设计如此）；console 退出
时对它们全数 SIGTERM。260916 两轮事故实证：修复前 `Worker(...)` 未设
`graceful_shutdown_timeout`（SDK 缺省 0=立即取消），在飞 agent 段（动辄 10~40 分钟）
被秒杀且票面只显无信息的「agent 活动故障」，与真实限流/传输故障不可辨。

**worker 收到 SIGTERM 后的语义（修复后）**：停领新活 → 宽限期
`SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC`（缺省 **1800s**；显式 `"0"`=旧「立即取消」
逃生门；畸形值回落缺省；无上限封顶——设多大=接受 worker 滞留多久）内等在飞 activity
收尾并回报；停机时日志**逐个点名在飞 agent 活动**（票/段/gen/attempt），收尾后打
终态清单。宽限耗尽仍被取消的：activity 侧转成 `type=worker_terminated` 的
ApplicationError → 票面 blocked 原因写作**「worker 被外部终止（停机/重载），活动已
取消（票 X 段 Y 第 N 次）」**，绝不与限流/传输/代码故障混淆；且 dev-lane/基类 agent 段
（`agent-stage-worker-shutdown-retry` patched 门内）**自动重跑一次**，无需人工逐票
retry_qc（再失败才 blocked 等人）。

**三路停机口径（谁能享受宽限）**：

| 路 | 触发 | 在飞 agent 段结局 |
|---|---|---|
| ① console 正常退出/插件重载 | dispose → 票 worker 全数 SIGTERM | 立即进宽限期：期内收尾（最常见路径） |
| ② console 崩溃/被 SIGKILL | 子 worker 被 launchd 收养（ppid=1），watch（缺省 30s 一轮）发现后自退 | ≤一个 watch 周期后**同样进宽限期**（ppid 守卫走的就是同一条优雅停路径） |
| ③ 宿主机断电/死机 | 什么都不跑 | 无宽限可言：服务端 heartbeat_timeout（3min）+ 重试是唯一兜底，票面呈 timeout 形文案 |

**生效窗口（KI-081 教训：代码落地≠行为生效）**：本修复**按 worker 进程生效**——已
在跑的存量票 worker 仍是旧码（grace=0、无归因），直到各自重启（console 重载 /
reap+spawn）才受益。在飞 workflow 收口后被新 worker 续跑时自动获得重跑门
（patched 门对老 history 恒 False：老实例重放走旧分支，行为一致、不歧变）。

**已知边界**：①在飞点名/归因只覆盖四个长活动汇聚点（AGENT_STAGE_IDS 全族 +
arbitrate + acceptance_walkthrough + run_integration_tests）——merge_check（20min）、
merge、巡检套件等非 agent 长活动停机取消仍走旧文案，通用化留专门票；②
`inspection_flow.py` 的「套件活动故障/teardown 活动故障」是巡检回执内部字样，不属票面
blocked 故障族；③SIGKILL 单个 worker 进程（绕过信号面）同③路：无宽限，靠心跳兜底。

**KI-093 纪律声明**：本票只做「记账 + 停机取消归因 + 重跑门」，**不触碰 spawn/reap
粒度与进程组逻辑**（`_run_agent_stage_impl` 内 KI-009 的 finally 全路径 reap 原样
保留）；「兄弟边被杀」是普通活动失败、无 worker_shutdown 取消细节，归因面绝不把它
洗成 worker 停机（UT 场景级负例锁定）。

**故障模式取舍清单**（借用实现逐项声明，C5）：

| 借用源 | 带过来什么 | 明确不带/例外 |
|---|---|---|
| selfcheck_ki061_wake_reset 台架 | start_local 本地测试 server（随机端口，零碰 3099/7233）、零模型零真 agent、exit-code 契约、无墙钟断言、async-with 全终态回收 | 本票场景 B 故意 grace=0 复现旧行为（台架多相 worker 切换改「停 worker 起新 worker」） |
| dev_lane PATCH_ID 家族（INTEG_LOOP_PATCH_ID 先例） | 重跑门走 `workflow.patched`：老 history 重放恒 False，控制流变更不歧变 | 文案变更不走门——只改文案不改控制流，replay 天然安全 |
| worker.watch_interval_sec 容错范式 | env 解析容错矩阵（缺省/畸形/NaN/Inf/负→缺省） | 不设上限封顶：宽限=运维自认的滞留上界，封顶会替运维做错决定（显式 "0" 保留逃生门） |
| agent_activities 取消清理先例（ui_evidence 段） | 「清理后 re-raise」保取消语义：非停机取消（工作流取消/心跳错）原样重抛 | 只对「SDK 细节=worker_shutdown」的取消改道；细节拿不到一律 fail-closed 走旧语义 |

### 8.4 端到端演示（步1，260904 起演示面已断——属预期）

`./demo_cli.sh`（输出落 `out/demo-step1-cli.txt`）：start content-pipeline → query 读 stage
（approve/awaiting-human）→ signal 签 approve → 真 qc_run(260627) 绿灯 → 停在 final-review →
signal 签 final-review → publish(dry-run) → COMPLETED；另跑 schedule-list + cancel，最后优雅停 worker。
**260904 宿主令 content-pipeline 模板退役、signal 子命令退役后，demo_happy/demo_fail/
demo_schedule/demo_cli.sh 等 v1 演示面的 start/signal 调用会被结构化拒收——属预期，
演示脚本按原样保留作历史参考，不再维护。**

零改动证据：`out/zero-touch-step1.txt`（现有工单 / server/tools/ticket.py / books 零改动）。

---

## 9. 正式化步2（t260821-03）：ticket stage 推进切 Temporal（JSON 变只读投影 + 现有工单 adopt）

**架构翻转**（与步1 的 POC / headstart 不同）：**Temporal 是真相，JSON 是投影**。
每张挂了 workflow 模板的工单 = 一个 `TicketWorkflow`（workflow id = 工单 id，单例）。
stage 机（advance/accept/rework/update/dispatch-next 的确定性推进）写死在 workflow 代码里；
人门（exit=human 段）= `sign` signal；脚本门（machine-qc/publish/verify）= `script_gate`
activity 跑真 `qc_run`/`verify_lane`，绿才推进。

> **260823 多项目化清理**：步2 的 JSON 投影层已整体退场——`server/tickets/` 目录、
> 老 `TicketWorkflow` 类、`adopt.py`/`verify_adopt.py`/`selfcheck_step2.py`/`demo_step2.sh`、
> `project_ticket` activity 全部删除。工单真源恒为 Temporal workflow（v2 模版即代码），
> 项目区分 = ProjectKey search attribute。下表为清理后的现状。

| 文件 | 是什么 |
|---|---|
| `workflows.py` | 保留步1 两 workflow（ContentPipeline / DispatcherScan） |
| `workflows_v2.py` + `base.py` + `dev_lane.py` | v2 模版即代码（工单真源）：base.py stage 机四模版 + dev-lane（activity 直编排） |
| `activities.py` | `admin_call` / `script_gate` / 巡检活动 |
| `shared.py` | `GateSpec`/`Signature` 等契约 + ProjectKey SA 打标助手 |
| `client.py` | `ticket-start`（必传 project，打 SA）/ `ticket-list`（--project 过滤）/ `ticket-query` / `ticket`（update/rework/sign/query） |
| `server/tools/ticket.py` | 纯 Temporal 薄壳：全部 op 转发 client.py，create 必传 project（projects.yaml 白名单） |

### 9.1 安全红线（延续步1）

- 工具面**无 set-stage / force_stage**：`client.py ticket` 只暴露
  advance/accept/rework/update/dispatch-next/sign/query 七个合法入口，前五个是
  workflow update（确定性推进，历史可查），sign 是人门 signal，query 只读。
- 工单 adopt 后 `ticket update` 的 `stage_state` 参数被拒绝——stage_state 由 workflow
  派生（running/awaiting/awaiting-human/blocked），外部不得设置。
- 人门只能 `sign` signal 解（approve/reject），`advance` 在人门段被拒（「请 sign 签字」）。

### 9.2 怎么跑

```bash
cd server/engine
./run_server.sh                                              # ① temporal dev server（常驻，带 ProjectKey SA 注册）
.venv/bin/python worker.py --daemon                          # ② worker（常驻，优雅停 kill -TERM $(cat data/worker.pid)）
```

### 9.3 已知边界（未验证的，别当成已证）

- **模板钉死在 workflow input**：adopt 时把 template stages 链快照进 input；改模板
  不影响已 adopt 的 running 实例（同 README §5.1 折中）。
- **workflow versioning 未做**：改 `TicketWorkflow` 流程代码时，已 adopt 的 running
  老实例仍按旧代码 replay（§5.2 硬问题，仍未立规矩）。
- **人门机械校验简化**：旧 `ticket advance` 出 approve/final-review 时读提案文件
  （`_check_human_gate`）；步2 改为 `sign` signal 即门，不再读提案文件（提案联动留 M3）。
- **常驻进程 +2**：temporal server + worker 都要常驻（§5.3）；工单 adopt 后 mutation
  依赖 worker 在线，worker 挂了 ticket advance/accept/update 会报「Temporal 转发失败」。
- **dsh 插件**：`sandbar-temporal-tools` 仍是步1 的 5 工具（start/query/signal/schedule-list/cancel；
  其中 signal 已于 260904 退役为结构化报错）；
  人门签字当前走 `client.py ticket '{"op":"sign",…}'`，插件加 `ticket_sign` 工具留待后续。
- **脚本门映射**（`shared.default_gate_for`；260904 宿主令 content-pipeline/proofread/
  regression/cleanup 模板退役后，下列映射仅 dev-lane 段在活，其余为留存数据）：
  content-pipeline machine-qc→`qc_run all`、
  publish→`verify_lane content auto`；dev-lane 的 verify 由 merge_check 在泳道内直跑、
  regression regress→`verify_lane code`。cleanup/proofread 无脚本门。

---

## 10. M6（t260821-m6-scan-expand）：自治巡检恢复与扩权

巡检从「工单分布统计」扩为「**待决工单检查报告**」——integration 角色的例行载体。
**红线：巡检只出建议不出决定，签字只能人（sign who=用户/总管）。**

### 10.1 巡检扩权（DispatcherScanWorkflow v2）

- 待决口径：未 closed 且（status=settled 或 stage_state=awaiting-human）。
- 每张待决工单出：stage/stage_state、停留时长（max(updated/log/pending) 起算）、
  验收勾选率（只数 item 在当前验收清单里的勾选，孤儿 check 不计）、脚本门最近一次
  红绿灯（Temporal snapshot.gate_runs 只读 query；不可达回退工单 log「脚本门」记录）、
  pending 数、**建议动作三档**：
  - 疑似卡死：停留 ≥ 阈值（默认 48h，`SANDBAR_SCAN_STUCK_HOURS` 可调）；
  - 待补：验收未勾齐 / 脚本门最近一次红；
  - 可签：人门待人签字，或 settled 且验收齐、门绿——材料齐备，人可签/推进。
- 确定性规约：读工单（admin list/show）、查脚本门、写文件全在 activity
  （`scan_tickets_report` / `write_scan_report`）；workflow 体零 IO，只消费返回值。
  版本分支 `SCAN_PATCH_ID="dispatcher-scan-v2"`：老实例 replay 走旧分支（分布统计）。
- 纯函数（`shared.py`：is_pending_decision/build_scan_item/gate_from_log/scan_summary）
  脱 Temporal 可测：`selfcheck_scan.py` 29 项离线自测。

### 10.2 报告落盘与台面展示

- 落盘 `out/scan/<YYYY-MM-DD>.json`（同日重跑覆盖当日文件，每日最多一个）。
- **入 git 与否的判断：不入**（`out/scan/` 已 gitignore）——报告是每 45min 刷新的
  运行产物，入库只会制造 git status 噪音；留档=文件本身 + 演示/结算 note 引用路径。
  out/ 下静态 demo 留档仍入库，两类分开。
- 工单台：sandbar-workbench 台面表格下方「巡检报告」区（只读 API
  `GET /sandbar-workbench/api/wf/scan-report` 取文件名序最新报告；无报告 reason 降级）。
  **node.ts 新端点需重启 3099 控制台生效；lib/client.js 刷新页面即生效。**

### 10.3 schedule 治理（scan_schedule.py，运维通道，不进模型工具面）

```bash
.venv/bin/python scan_schedule.py describe                    # 只读快照（num_actions 证据）
.venv/bin/python scan_schedule.py resume --minutes 45 --note "为什么恢复/什么频率"
.venv/bin/python scan_schedule.py pause --note "为什么暂停"   # note 强制，不留无解释暂停
.venv/bin/python scan_schedule.py trigger                     # 立即手动触发一轮
```

260822 已恢复 dispatcher scan（LEGACY 旧 id `suyou-dispatcher-scan`，t260907-04 起 `sandbar-dispatcher-scan`）：45min/轮、overlap=SKIP、note 落 schedule state，
num_actions 2→3 证据见 `out/demo-M6-scan-expand.txt`。
**注意**：schedule 触发的巡检由共享队列（LEGACY 旧队列 `suyou-poc`，现 `sandbar`）上的 worker 执行——本泳道合并进主树后，
需重启主 worker（`kill -TERM $(cat data/worker.pid)`，supervisor keepalive 自动拉起新代码）
才开始产出 v2 报告；在此之前定时轮仍走旧分支（只统计，无害）。

### 10.4 闭环验证（巡检→报告→可签建议）

`verify_m6.py`：专属 queue（`SANDBAR_TASK_QUEUE=suyou-m6-verify`）起新代码 worker，
跑一条 DispatcherScanWorkflow 并等结果，断言真实工单地形（t260820-hanshu-l0 人门→可签 /
t260821-11 settled 验收 0/5→待补）。留档 `out/demo-M6-scan-expand.txt`。
sign 动作不在验证脚本里——红线：签字只能人。


## 11. 跨项目写操作闸（t260915-12）：caller-project gate

写操作（盖章信号/授权/返工/裁决/暂停恢复/update/retry_qc/cancel/ticket-start）在动笔前
先校验**调用方项目归属**：身份与目标票不符=fail-closed 拒收，宁可拦住合法请求也不放行
越权写（260915 宿主实报立项；纪律层 charter 已补，本节是机器层契约）。

### 11.1 身份从哪来（出处链，优先级从高到低）

| 来源 | 形态 | identity_src |
|---|---|---|
| 显式参数 | `caller_project`（client args / ticket.py 参数） | `arg` |
| 注入链 env | `SANDBAR_CALLER_PROJECT`（dsh 会话/ticket.py `_poc` spawn 注入） | `env` |
| cwd 窄兜底 | 真人在注册项目工作区直跑时由 cwd×注册表推导 | `cwd` |
| 未声明 | 以上皆无 | `none`（identity_class=undeclared） |

规则：值必须过 `PROJECT_KEY_RE`（形状非法=结构化拒收 `kind=cross_project_refused`，
不静默当未声明）；形状合法但注册表查无=仍按 declared 判（误配显式暴露，回执附
`caller_project_registered=false`）；**cwd 落在引擎仓树内一律不推导**——dsh 工具链
spawn、console 插件的 cwd 指向引擎自身，标识「被调用的引擎」而非「调用方会话」
（review C1 行为红线：排除按整树祖先判定，不是仓根等值）。

### 11.2 判定矩阵（唯一真源 `shared.cross_project_judge`；client 侧薄封装）

| caller 身份 | 目标票 project | 越权旗 | 动作 |
|---|---|---|---|
| declared=同项目 | 任意 | — | 放行 |
| declared=异项目 | 有 | 无旗 | **拒收**（`kind=cross_project_refused`，文案点名双项目+目标票号） |
| declared=异项目 | 有 | `cross_project={by, reason 必填}` | 放行+记名（by/reason 原文入账） |
| undeclared（策略 B 现状） | 有 | — | 放行+强制记名（哨兵盖章，回执 `identity_class=undeclared`） |
| 无比对对象（目标无 ProjectKey SA / 读面） | — | — | 放行（cancel 打在引擎件上=identity_class=engine-internal 照记 admin.log） |

- 目标快照/SA **瞬时读取失败≠越权**（KI-025）：可重试的 `kind=transient` 结构化拒收，
  绝不 fail-open 放行 terminate；不存在=`kind=not_found`。
- **undeclared 策略翻 A（拒收）路径**：改 `shared.UNDECLARED_POLICY` 一处常量
  （`record`→`refuse`），并同步改两处场景（`t260915-12-cross-project-gate` 的策略锁腿、
  `t260915-12-gate-real-chain` 相七）与本节——**前提=跟进插件票把 dsh 会话/工作台的
  身份注入收口做完**（否则 console/工具链写面会从放行变硬拒，静默行为反转）。未收口前
  B 策略是现状契约，被场景钉住。

### 11.3 记名与对账（工单③：越权旗使用记录可查）

- **盖章 op**（sign/authorize/rework/ruling/pause/resume）：调用方身份随载荷下发
  （`caller_project`/`cross_project_note`，dataclass 带默认=老历史解码兼容），workflow
  侧第二道复核后写入 `meta['cross_project_uses']`（ts/op/by/caller_project/note 原文）
  ——`ticket.py op=show` 可对账，按笔累计。
- **不盖章 op 残留（方案 §8 已声明，非漏记）**：retry_qc（裸 who 契约）、update
  （`@workflow.update` 同步面）、cancel/ticket-start（无 workflow 侧落点）——Temporal
  历史无身份落点，记名仅在 admin.log；回执 `cross_project_notice` 按 op 说实话
  （「查询面 cross_project_uses 列不出」），不谎称可查。
- **admin.log 行**：每笔调用附 `caller_project/identity_src/identity_class/override`
  键；越权对账 grep：`override=true`（旗）或 `identity_class=undeclared`（B 策略记名）；
  拒收行 `override=false` 也是一笔记录。身份键同 source 口径：claimed 值、非身份鉴别。
- 两道闸的分工：client 侧闸=信号不出手（省一次无效投递）；workflow 侧第二道=复核盖章
  值（直发 SDK/老 client 兜底面，无盖章=兼容不校验）。拒收在 client 侧截住时
  snapshot.refused 零新增；直发越权章则落 workflow refused[]。

### 11.4 不进闸的面（明确豁免，防「漏记」误读）

| 面 | 豁免理由 |
|---|---|
| `query`/`ticket-list`/`ticket-query`/`running-tickets`/`schedule-list`/`start` | 读/扫描面，零写副作用 |
| `signal` 子命令（§8.1 权威表：已退役） | 调用一律结构化报错，本就不可达写面 |
| `ticket-prune`/`ticket-archive-legacy` | 只触 closed+已归档票，自带双 fail-closed（决策记录在案） |
| 旧模板（content-pipeline/inspection）sign handler | 统一接闸但目标无项目面→判定恒放行（行为零变化，源锁防分叉） |

场景：源码锁+重放=`integration/t260915-12/tests/sc_check_cross_project_gate.py`
（离线恒可跑）；真链路行为面=`sc_cross_project_gate_realchain.py`（docker 台）。
实现级单测：`server/engine/tests/test_t260915_12_t01_caller_gate.py`（纯函数矩阵）、
`t02_client_receipt.py`（client 接线桩测）。


## 12. 巡检分项目归属（t260915-20）：声明带项目身份 + 起票盖 ProjectKey SA + repo_root 按项目解析

巡检此前是**引擎级**的：声明实例无项目字段、起票不盖章 ProjectKey SA、repo_root
缺省空=扫在 worker 自己的仓（引擎仓）——多项目即断（dengzhufpv 零巡检覆盖）。
本票把「归属」建成巡检的一等身份，全部走声明面：

### 12.1 机制（四个面）

- **声明面**：`inspection.yaml` 实例必填 `project_key`（实例级项目身份=项目注册表
  key；enabled 与否都不豁免——无身份的占位实例=无主票预定席）。与
  `schedule.project_key`（every-n-tickets/race-first 的**计数源**键）是两个字段：
  实例级=归属、schedule 级=计数取数面，绝不互串。解析单点=inspection_decl.py，
  校验在实例字段链最后（既有负腿事由照旧先爆）；缺身份/形状畸形 → fail-closed
  点名实例 id，绝不静默回落引擎仓。
- **起票面（SA 盖章三路）**：手动 `trigger`、cron 调度（`schedule-up` 的 create 与
  update 两分支）、计数 watcher 开票 activity——三路起票一律
  `payload.project_key=实例身份` + `typed_search_attributes(ProjectKey=实例身份)`。
  工单板项目过滤（`AND ProjectKey=`）与巡检行 `project` 字段由此天然成立。
  cron 调度的 action 由 `_schedule_action` **单点 builder** 铸造，create/update
  共用——update 分支同样重铸 action（修复前重跑 schedule-up 刷不了已建调度的
  payload/SA，t260913-02 只修 create 侧的同族坑）。
- **扫描面（repo_root 解析链）**：`--repo-root` 显式旁路优先（隔离台/运维用）；
  否则按实例身份经 `shared.resolve_project_root` 解析注册条目主目录（契约
  「项目根=dirs[0]」，与 resolve_epics_dir 同注册表同取法，但**无空 key 回落腿**）。
  扫描与套件从此跑在归属项目的仓里。
- **workflow 面（无主守卫）**：新 patch 门 `PROJECT_PATCH_ID`——项目身份与
  repo_root **双空**的新票 → blocked 终态点名「无项目身份」+处置入口（重跑
  schedule-up），杀旁路起票的静默残窗；sign 闸 target=本票 SA ProjectKey（回退
  payload project_key，双空=老 history 恒放行），异项目 caller 签字即结构化拒收。

### 12.2 迁移四步（运维口径）

1. **cron 调度（现役三实例）**：部署本版后，对三实例各重跑
   `inspection_trigger.py schedule-up --instance <id> --note <谁/为何/频率>` →
   update 分支重铸 action（新 payload+SA）→ 自检
   `inspection_trigger.py describe --instance <id>`（回执 `schedule_action` 摘要带
   project_key/repo_root/sa_project_key）。**修复前的版本重跑无效**（update 不碰
   action）——先部署再重跑。
2. **在途票**：部署时刻在途的票 `patched()=False` 走旧路径跑完，守卫不追杀（重放安全）。
3. **历史闭环票**：行 project 恒空（SA 是起点真源，不造历史）——UI 侧按「未归属」显示。
4. **跨部署存量旧 watcher**：现役生产零计数实例（声明计数形态全是注释示例）无存量
   负担；若旧 watcher 跨部署存活并开票 → 票撞无主守卫=blocked（可见），处置=
   terminate 旧 watcher（id=`inspection-watcher-<id>` 确定单点）+ schedule-up 复活。

### 12.3 验证面

- 单测：`server/engine/tests/test_t260915_20_inspection_project.py`（声明必填/形状/
  事由次序、resolve_project_root 三态、resolve_repo_root 三腿、builder payload+SA、
  watcher 串键回归钉、守卫两腿、sign target 链）。
- 集成：`t260915-20-decl-project-identity`（离线声明门）+
  `t260915-20-project-identity-realchain`（docker 台：双项目各起一期票断言 SA/
  行/payload/扫对仓路径、update 重铸腿、未知项目键负腿、无主守卫腿）。


## 13. 巡检声明落位迁移A（t260916-02）：每项目仓内单文件 + 票号统一工单号形式

### 13.1 机制面（迁移后的世界）

- **声明落位**：每项目一份 `inspection.yaml`，缺省 `<项目主目录 dirs[0]>/inspection.yaml`
  （单文件，进 git；不做 `inspection.d/` 目录）；注册条目 `project.yaml` 的
  `paths.inspection_decl` 可指路别处（相对拼 dirs[0] / `~/` 展开 / 绝对，词法校验与
  `model_routes` 同源；`..` 逃逸 fail-closed）。**回落语义与 model_routes 刻意不同**：
  声明缺席=该项目无巡检面（absent，不冒充错误、不借用他项目、不回落样例）；
  坏形/不可读=项目级 error 点名声明路径。真源链：`inspection_decl.py`
  （`iter_project_decls` / `load_decl_for_instance` / `enabled_instance_whitelist`）。
- **引擎仓零声明**：`server/engine/inspection.yaml` 已删（迁移交付本体）；引擎只留
  机制 + `docs/inspection-sample.yaml` 样例模板（样例实例不进任何聚合）。sandbar 自己
  的五实例迁到**仓根 `inspection.yaml`**（字段逐项不变，只换文件头注）。
- **票号统一工单号形式**：巡检票号=`t<YYMMDD>-<NN>`（`ticket_id == workflow_id`），
  走既有票号分配面（`shared.next_ticket_seq_from_ids`，全类型前缀扫描——工单与巡检
  同天共享序号空间，`server/tools/ticket.py` 的 `_next_seq_v2` 只扫工单店的现成缺陷
  一并修复）。铸号函数 `inspection_ticket_id` 退役删除；实例/期号**不从票号反解**，
  改从票面（snapshot/payload）与 SA 读。落账文件名保留 `inspection-<实例>-<期>.json`
  （键名单点 `inspection_flow.inspection_ledger_name`，与票号是两个名）。
- **显式去重（每期一票）**：单点 `inspection_ticketing.open_period_ticket`，三路判定——
  ①SA 快路径（`InspectionInstance`+`InspectionPeriod` 查询，命中任意状态即 deduped，
  含历史 COMPLETED）；②原子指针三态（见 13.3）；③`AlreadyStarted` 归属判定（本
  （实例,期）=deduped 收尾清指针；外来撞号=NN+1 让位重试 ≤`MAX_ALLOC_RETRIES`=5）。
  同期多张票=点名报错（有第二写入方，人工处置），绝不猜。
- **聚合遍历**：板面白名单 / deadman 漏跑核查 / schedule-up 都遍历注册项目读各自声明；
  跨项目实例 id 重复=歧义实例剔除+点名两处（trigger 面多命中同样报错）。
- **spawner**：Temporal Schedule 铸不了 t 形号（建 schedule 时未知当日序号）——调度
  action 改指 `InspectionPeriodicSpawnWorkflow`（固定 id `inspection-spawn-<实例>`），
  到点由 activity 走 `open_period_ticket` 铸号开票。旧直发 action 的 schedule 会被
  `schedule-up` 拒绝点名重跑（`_schedule_action_summary` 认 spawner 才放行）。
- **板面双腿查询**（client.py `cmd_ticket_list` kind=inspection）：SA 腿
  （`InspectionInstance` OR 白名单串）+ legacy 腿（`WorkflowType=InspectionPeriodicWorkflow
  AND WorkflowId STARTS_WITH "inspection-"`）；按 id 去重合并、行带 `match_via`
  （sa / legacy_id）/ `legacy_unowned`（无 ProjectKey SA=「历史票·无项目身份」徽标，
  口径⑤显式降级可辨）。R8 闭合窗施加于合并后行集。

### 13.2 迁移步（在跑环境的一次性操作）

1. **重启 dev server**（下一次 `run_server.sh` 自带两个新 SA 启动参）。
2. 或对在跑 server 手工补注册 SA（见 13.4 三路径）。
3. **重跑 schedule-up**：`inspection_trigger.py schedule-up --note "t260916-02 迁移"`——
   旧直发 action 全部换绑 spawner；不重跑则旧调度仍按旧 payload 直发（票号旧形）。
4. 存量在途旧形票：无需处理——legacy 腿照常上板（`match_via=legacy_id`），
   resolve 查询面兼容（SA 查无 → legacy 只读探测）。

### 13.3 去重指针生命周期（`<INSPECTION_DIR>/inspection-<实例>-<期>.ticket`）

- 目录接 `SANDBAR_INSPECTION_DIR` 覆盖链（缺省 `server/engine/out/inspection`）；
  `.ticket` 后缀不进台账扫描（deadman 畸形清单同样豁免）。
- 语义=「本进程正为该（实例,期）飞行开票」的 O_EXCL 原子 claim；有效指针先
  `describe()` 验票（NotFound=确定结论，不依赖可见性索引）：
  - 票在且 SA==指针身份 → deduped（source=pointer）；票在但**无 SA 章**（迁移前旧票）
    → 可信 deduped（legacy 标记）；票在但 SA 与指针不一致 → **配置事故显式报错，
    不自动清指针**（防掩盖第二写入方）。
  - 票不在：年龄=`st_mtime` 基准（R4；单测注入统一 `os.utime`），>
    `CLAIM_GRACE_SEC`(120s)=陈旧自动清+回执 `stale_pointer_cleared` 留痕后照常开票
    （绝不永久楔死期号）；≤窗=并发飞行中显式报错（不误杀并发）。
  - 畸形（空/半截 JSON/缺 ticket_id）：同年龄规则——超窗自动清留痕，窗内显式报错。
- 失败路径收口：非 dedup 失败删**自建**指针（只删本次 O_EXCL 建的）；SA 未注册、
  重试耗尽、ES 瞬态都显式报错点名。

### 13.4 SA 注册三路径（InspectionInstance / InspectionPeriod = Keyword）

```bash
# ① dev server（run_server.sh 已带启动参，重启即注册）
server/engine/run_server.sh
# ② 手工对在跑 server（dev 7233 / 测试台 17233 皆此法，幂等容 already）
bin/temporal operator search-attribute create --address 127.0.0.1:7233 \
  --name InspectionInstance --type Keyword
bin/temporal operator search-attribute create --address 127.0.0.1:7233 \
  --name InspectionPeriod --type Keyword
# ③ docker 测试栈：integration/stage_docker.py precheck 幂等补建（含 ProjectKey/EpicCode 共四项）
```

**R3 归因指引**：SA 未注册时，dedup 快路径/板面 SA 腿的查询会显式失败，报错含
`unknown search attribute`（开票面）或 `InspectionInstance` 字样（查询面）——这是
**注册步未做**（配置），不是代码故障；先跑上面任一路径注册，再重试触发。

### 13.5 `STARTS_WITH` 算子降级注记（R2）

legacy 腿的 `WorkflowId STARTS_WITH` 是本仓首个该算子使用（此前零先例）。若后端
（Temporal 版本/ES 可见性配置）拒绝该算子，代码**自动降级**：类型单腿
（`WorkflowType=InspectionPeriodicWorkflow`）拉回 + 客户端按 id 前缀过滤——过滤仍
发生在快照查询之前（防僵尸收益不破），回执 `inspection_scan_mode=type_only_fallback`
可观测；铸号扫描面（`scan_prefix_ticket_ids`）同款降级。降级是**既定取舍非静默换实现**；
`scan_mode` 三值：`starts_with`（正型）/ `type_only_fallback`（降级）/ `skipped`
（白名单降级，查询都不发）。

### 13.6 两条命令（样例即文档）

```bash
# 起一期（每期一票；重复触发返回既有票号）
server/engine/.venv/bin/python server/engine/inspection_trigger.py trigger \
  --instance integration-tests --period 20260916
# 看聚合声明面（逐项目 ok/absent/error + 白名单并集 + 调度意图）
server/engine/.venv/bin/python server/engine/inspection_trigger.py decl
```

## 14. admin.log 文件生命周期（t260916-21）：按天轮转 + 保留窗 + 同日过大顺切 + 写失败点名

admin.log（`server/admin.log`，已 gitignore）此前纯 O_APPEND 单文件增长
（260916 实测 1.74GB/12.8 天，日均约 135MB，无任何轮转）。本票把文件生命周期
收口进 `server/engine/audit.py` 单点（写路径唯一收口=`_append_line`），其余
写者零改动——admin.log 全部已知写者共 4 个（review C1 普查）：
`audit.py`（client.py/ticket.py 行）、`tools_registry.py`、
workbench `node.ts`、knowledge `review_store.py`（后三个在 engine 写集外），
同语义=每次调用按路径 append、不持 fd，轮转后自然续写新文件，无分叉面。

### 14.1 轮转/顺切/保留窗契约（验收①-④）

- **按天轮转（惰性）**：本地日界（`time.localtime` 口径，勿混 UTC）首个跨日
  写入时把活跃文件原样改名 `admin.log.YYYYMMDD`（归档名=文件**关闭日**，取其
  mtime 日；存量多日大文件整体落单日名下属预期），后续写新文件。
- **恰好一次**：两步原子挪移——先 rename 到唯一私有名
  `<logname>.rolling.<pid>.<uuid6>`（赢家唯一，输家 FileNotFoundError=别人已
  轮转），赢家再经 `_publish`（硬链原子 no-clobber）发布归档名；目标名已存在
  自动去重后缀，**永不覆盖**。rename 前后做 inode 身份复核（防 stat→rename
  窗口内误抓别人重建的新文件——原样还原不算本进程轮转）。
- **存量迁移**：现存文件原样改名归档，不删不截断（跨两代 schema 行留考古）。
- **同日过大顺切**（宿主 260916 定稿措辞：无「熔断」语义——同日文件过大就顺切
  下一个文件，纯拆分无告警）：同日文件 ≥512MB（`admin_log.max_mb`；≤0=关顺切，
  值畸形=该键回落内置缺省）当日再切 `admin.log.YYYYMMDD-HHMMSS`。
- **保留窗**：默认保留 **14 天**（宿主 260916 定稿；`admin_log.keep_days` 可调；
  ≤0=永不删，值畸形=该键回落内置缺省），仅归档赢家进程跑一次清扫；删除面
  **仅限**归档命名面 `<logname>.<8位日>[-<6位时>[-<去重后缀>]]`（logname 从
  `SANDBAR_ADMIN_LOG` 派生——隔离语义不变），面外文件（.bak/非法日期）不碰。
  rolling 孤儿（轮转中途崩溃残）**先按其 mtime 日收编入归档面，不静默删**；
  收编失败才降级删除并 stderr 点名。清扫删除失败一律 stderr 留痕不 raise
  （不破坏写路径）。
- **配置面（宿主 260916 定稿：project metadata，不用环境变量）**：两个旋钮读
  「引擎所属项目」条目 `~/.sandbar/projects/<key>/project.yaml` 顶层
  `admin_log: {keep_days, max_mb}`（additive 字段；shared 装载器已同步容忍该块
  ——旧读取方零感知，先例=`paths.model_routes` 指路键）。引擎所属项目=条目
  dirs 覆盖引擎仓根（等值或祖先，主仓/worktree 两态命中）。内置缺省兜底
  14 天/512MB：注册表缺席/条目未命中/解析失败/值畸形一律回落（fail-open 显式
  口径：配置读不到不阻断审计写）；读取带缓存（键=注册表根+文件 mtime，每写一行
  只多两次 stat）。env 侧只保留既有的 `SANDBAR_ADMIN_LOG` 路径覆盖（测试隔离
  语义不变）；`SANDBAR_PROJECTS_DIR` 沿用 shared 注册表隔离面（测试桩同入口）。
- **KI-010 边界**：轮转是 containment（防失控+保考古），日均增长根因
  （workbench 轮询+读操作通胀，known-issues KI-010）未除。

### 14.2 写失败点名（验收⑤）

admin.log 不可写（权限/只读 fs/路径为目录等）时三通道留痕，绝不吞回执、绝不
raise：stderr（既有）+ `logging.getLogger('audit').warning`（已配 logging 的
宿主进程自动出 WARN）+ 回执 dict 就地点名 `audit_write_failed`。为此
`client.py _emit` 改为**审计先于打印**（t260916-21，范围偏差·有意：不改则
marker 结构上不可达 stdout 回执——nusuyou/dengzhufpv 实测「写失败回执正常」
病灶）；ticket.py 直 spawn 路径本就先审计后打印，零改动受益。

测试：`server/engine/tests/test_t260916_21_admin_log_rotation.py`（L1）；
场景：`integration/t260916-21/sc_admin_log_rotation.py`（灰盒 L3，
`t260916-21-admin-log-rotation`）。

## 15. 调度路自愈重定向 + 板面降级可见 + 台账留史（t260917-02）

260917 首次自动巡检实测暴露三缺口（票形双缺陷/板面吞在跑票/台账无归档覆盖），本节
是三修复 + 一复核的机制注记。

### 15.1 调度路径票形统一：非 t 形 fire 自愈重定向（修复①）

- **根因**：260916-02 的「重跑 schedule-up」在过渡窗没跑，旧代 schedule-up 铸的
  action 仍直发 `InspectionPeriodicWorkflow`（服务端给 fire id 追加 `-<fire时刻UTC>`
  后缀）——票面 ticket_id=workflow id 本身、无实例/期 SA。
- **机制**：workflow 侧守卫（`legacy_fire_redirect_reason`，纯函数）认出「非 t 形
  fire」→ 起票单点 `spawn_inspection_period` → `open_period_ticket` 铸 t 形票承接；
  壳即返（不扫描/不落账/不进人门——扫描与人门只属于承接票）。patch 门
  `REDIRECT_PATCH_ID`：老 in-flight 票零新命令（replay 安全，`replay_check.py
  --workflow <票 id>` 机械验证）。
- **身份回退链**（`activities._resolve_spawn_identity`）：旧 payload 缺 project_key
  → 按 plan 的 `instance_project_key`（decl 实例级身份）回退；repo_root 缺 → 注册表
  解析；都决议不出 → 显式失败（fail-closed，绝不静默回落引擎仓）。face 不采信旧
  payload（空传 → 按当前声明 scan_face 决议）。
- **运维边界**：重定向是**过渡窗自愈**，不是对「不重跑 schedule-up」的豁免——action
  不刷新，每期都要多走一次重定向；`schedule-up --note "..."` 重跑仍是一劳永逸解。

### 15.2 板面降级可见（修复②）：不可辨「在跑」不再静默吞

- 不可辨（无实例/期 SA 且 id 非旧形词法）**且在跑** → 显式降级行上板：行带
  `identity_note`（假设语气点名「疑似旧调度 action 直发或演练残留」+核查入口），
  回执 `kept_unresolved` 计数；**且已闭合** → 维持不上板（僵尸纪律半边不动），
  `dropped_unresolved` 计数——两个计数分账可辨。
- 同期并存：同 (实例,期) 的 open 行带 `same_period_closed=<闭合票号>` 注（不合并行、
  不隐藏任何一张——每期一票语义下的双行只注不并）。

### 15.3 台账留史（修复③）：跨票同名覆盖前归档

- `write_inspection_report` / 套件回执落盘前经 `_archive_if_other_run`：同
  `ticket_id` 重写不归档（每跑一份以票为界）；**跨票**同名 → 旧件先搬
  `archive/<stem>-<sanitize(票号)>-<HHMMSS>[-N].json`（exclusive create，同秒自撞
  -N 递增），原字节保留可读；畸形旧件按 corrupt 整体搬移；归档失败不拦新写
  （canonical 恒保最新）。`archive/` 不进 deadman 期号集合。
- **保留口径（宿主已裁决默认）**：archive/ **不自动清理**，无 TTL——磁盘面人工或
  工具处置；语义=每期一份 canonical + 每跨票覆盖留一份史。

### 15.4 跳火可观测（复核④）：OverlapPolicy=SKIP 与人门长挂解耦

- **口径更正（review C1）**：跳火**可直接观测**——`ScheduleInfo` 携带
  `num_actions_skipped_overlap` / `running_actions` / `num_actions_missed_catchup_window`
  （temporalio 1.18.2 字段实证）。「SDK 无 skip 观测字段」的旧断言只对
  `ScheduleActionResult` 成立，不得再引用。
- **结构解耦**：schedule action 指向 spawner（秒进秒出）后，人门长挂的是**真票**而
  非 action 的 Running 位——下一期 fire 不再被人门挡住。旧直发 action 形态下人门长挂
  仍会占 Running 位（重定向守卫是承接种，不是占位者）。
- **deadman 回执**（`inspection_trigger.py deadman`）：`skip_count` /
  `running_actions` 两键（None=未查）；finding 两腿——observed（skip>0 且
  Running>0 →「跳火实锤：skip 计数 N、上期 action 仍在 Running」high）优先，
  inferred（计数不可得 + missed 非空 + action 未指 spawner → med 兜底）可辨不混装；
  observed 命中即 `alarmed=true`（每天可见的告警，ops 退出码可踩）。

### 15.5 相关面索引

- 真值表/纯函数面单测：`server/engine/tests/test_t260917_02_inspection_redirect.py`
  （形状判别/身份回退/重定向判据/period 透传）、`test_t260913_02_inspection_deadman.py`
  （跳火两腿）、`test_t260917_02_inspection_ledger_archive.py`（归档真值表）、
  `test_t260915_08_inspection_board.py`（降级可见/同期同注/部分 SA 真值表）。
- 集成场景：`integration/t260917-02/`（legacy-fire-redirect / board-unresolved-running /
  ledger-archive-regression，登记于 run_scenarios.py）。
- N1 运维加急（合入后宿主/main 尽快执行）：`schedule-up` 重跑（action 指向 spawner）
  + terminate 挂门旧壳（id=inspection-integration-tests-period-2026-09-16T23:30:00Z）；
  deadman 落 15.4 后该风险每天自动点名。

## 退役账（t260907-04 命名清理①：7 条过渡兼容，撤任何一条前先对表）

t260907-04 把 SANDBAR_* env、suyou-poc 队列、.suyou/ 协调目录改成 sandbar 名。以下 7 条  # naming-compat
兼容路径逐条带退役条件，防「撤了半截」：

| # | 项（suyou 旧名面） | 退役条件 |
|---|---|---|
| 1 | 共享旧队列（退役账#1） `suyou-poc` 双 poll（shared.LEGACY_TASK_QUEUE） | 旧队列连续一个发布周期零任务且在飞 workflow 无旧队列起动 |
| 2 | ticket 旧前缀（退役账#2） `suyou-ticket-*` 双前缀 poll（shared.LEGACY_TICKET_QUEUE_PREFIX） | 旧前缀队列一发布周期零任务且在飞 workflow 无旧前缀 |
| 3 | schedule 幂等删旧行（退役账#3）（scan_schedule.retire_legacy_schedule，旧 id `suyou-dispatcher-scan`） | 删旧行保留一个发布周期（防旧代码引擎并存重建），超期整段删 |  # naming-compat
| 4 | dispatcher 旧锁回落（退役账#4）（server/tools/dispatcher_loop.py LEGACY_LOCK，旧锁 `suyou-dispatcher.lock` 只读） | 巡检观测旧锁零命中连续一个周期 |
| 5 | 目录镜像双写（退役账#5）（shared.mirror_to_legacy，旧名 `.suyou/` 只写不读） | 插件面票（workbench 旧名清理）收口 |  # naming-compat
| 6 | env 双向桥（退役账#6）（shared.apply_env_compat，SANDBAR_*↔SANDBAR_*） | 插件面票收口后降单向前向，再一版整函数删除 |
| 7 | WS_DIR_BASE 旧 base 粘滞（退役账#7）（LEGACY base `/tmp/suyou-ws`） | 旧 base 存量工单目录清零 |

另有目录粘滞回落（resolve_dot_dir 规则 2，老泳道 `.suyou/` 整生命周期旧名）不占上表：  # naming-compat
退役条件 = 旧名泳道存量清零，随规则 2 分支一并删除。

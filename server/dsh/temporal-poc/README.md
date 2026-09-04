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
cd server/dsh/temporal-poc
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
| `worker.py` | worker（注册 workflow+activity 到 task queue `suyou-poc`） |
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
5. **UI 与工具面**：`suyou-workbench` 要改读 Temporal（或让 activity 把状态**投影**回
   `tickets/*.json` 当只读视图，UI 不改——迁移期建议走投影，双写只读不双主）。
6. **工具面必须只暴露 signal/query**：给 agent 的 dsh 工具只能有
   `pipeline_status`(query) / `pipeline_sign`(签字，身份注入) / `pipeline_retry_qc` / `pipeline_start`；
   一旦暴露「设置 stage」，证明点 1 立刻失效。

## 6. 零改动证据

`out/git-baseline.txt` 是开工前 `git status --porcelain` 快照（当时已有 54 行改动，全部属其它并行泳道）。
完工核对方式（任何人可复跑）：

```bash
cd /Users/user/Documents/suyou
git status --porcelain -- server/dsh/tickets server/tools/ticket.py app/public/data pipeline/output \
  > /tmp/after.txt
grep -E "server/dsh/tickets|server/tools/ticket.py|app/public/data|pipeline/output" \
  server/dsh/temporal-poc/out/git-baseline.txt > /tmp/before.txt
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
  schedule `suyou-dispatcher-scan` 跑完是 **paused** 状态。清场：
  `bin/temporal workflow terminate -w content-pipeline:p260821-red --address 127.0.0.1:7233 --reason 清场`、
  `bin/temporal schedule delete --schedule-id suyou-dispatcher-scan --address 127.0.0.1:7233`；
  彻底重置=停 server 后删 `data/`。

---

## 8. 正式化步1（t260821-02）：client CLI + worker 定形 + dsh 插件壳

步1 只做**工具面**：client.py 五子命令 CLI、worker 前台/后台+优雅停、dsh 插件
`server/dsh/temporal-tools/`（模型可见工具）。七段状态机（§2 的 `workflows.py`）语义原样不动；
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
kill -TERM "$(cat data/worker.pid)"                             # 优雅停（在跑 activity 做完，停领新活）
```

worker 是「肌肉」，服务端是「骨架与记忆」：worker 挂了/换新进程，服务端里的 workflow
状态与历史不丢，停机期间攒的活等重启后自动补跑（POC 证明点 D）。

### 8.3 server / worker / 插件 三者启动与生命周期

| 组件 | 启动 | 生命周期 | 挂了会怎样 |
|---|---|---|---|
| temporal dev server | `./run_server.sh` | 常驻；SQLite 落盘 `data/temporal.db`（gitignore） | workflow 状态/历史都在它这；不删 data/ 不丢 |
| worker | `worker.py [--daemon]` | 常驻；`kill -TERM` 优雅停 | 可随时换/重启；停机期间 workflow 仍 RUNNING，重启自动续 |
| dsh 插件 `suyou-temporal-tools` | profile `cordis.patch.yml` 的 `- insert` 行 | 随 dsh 进程加载；每次工具调用 spawn `client.py` | 无状态；server/worker 不在线时工具调用结构化报错 |

插件加载：`server/dsh/profile/node_modules/suyou-temporal-tools → ../../temporal-tools`
（与 suyou-workbench 同款裸包名软链；profile-headless 有同款软链）。默认 python 取
`temporal-poc/.venv/bin/python`（temporalio SDK 装在仓库内 venv，不碰系统 python）。

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

> **260823 多项目化清理**：步2 的 JSON 投影层已整体退场——`server/dsh/tickets/` 目录、
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
cd server/dsh/temporal-poc
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
- **dsh 插件**：`suyou-temporal-tools` 仍是步1 的 5 工具（start/query/signal/schedule-list/cancel；
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
  - 疑似卡死：停留 ≥ 阈值（默认 48h，`SUYOU_SCAN_STUCK_HOURS` 可调）；
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
- 工单台：suyou-workbench 台面表格下方「巡检报告」区（只读 API
  `GET /suyou-workbench/api/wf/scan-report` 取文件名序最新报告；无报告 reason 降级）。
  **node.ts 新端点需重启 3099 控制台生效；lib/client.js 刷新页面即生效。**

### 10.3 schedule 治理（scan_schedule.py，运维通道，不进模型工具面）

```bash
.venv/bin/python scan_schedule.py describe                    # 只读快照（num_actions 证据）
.venv/bin/python scan_schedule.py resume --minutes 45 --note "为什么恢复/什么频率"
.venv/bin/python scan_schedule.py pause --note "为什么暂停"   # note 强制，不留无解释暂停
.venv/bin/python scan_schedule.py trigger                     # 立即手动触发一轮
```

260822 已恢复 `suyou-dispatcher-scan`：45min/轮、overlap=SKIP、note 落 schedule state，
num_actions 2→3 证据见 `out/demo-M6-scan-expand.txt`。
**注意**：schedule 触发的巡检由 suyou-poc 队列上的 worker 执行——本泳道合并进主树后，
需重启主 worker（`kill -TERM $(cat data/worker.pid)`，supervisor keepalive 自动拉起新代码）
才开始产出 v2 报告；在此之前定时轮仍走旧分支（只统计，无害）。

### 10.4 闭环验证（巡检→报告→可签建议）

`verify_m6.py`：专属 queue（`SUYOU_TASK_QUEUE=suyou-m6-verify`）起新代码 worker，
跑一条 DispatcherScanWorkflow 并等结果，断言真实工单地形（t260820-hanshu-l0 人门→可签 /
t260821-11 settled 验收 0/5→待补）。留档 `out/demo-M6-scan-expand.txt`。
sign 动作不在验证脚本里——红线：签字只能人。

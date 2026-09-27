# 260918 宿主 docker daemon 卡死（供给面停摆）——事故记录与处置

> 记录人：integration（守夜，sandbar 项目会话）｜时间：2026-09-18 17:5x（本地）
> 性质：**宿主级供给故障**（非本仓代码缺陷）。只定位+留证+停闸，不改宿主、不改他票。

## 一、结论（一句话）

宿主机 OrbStack 的 docker API 已**完全无应答**：socket 能连上、连上后一个字都不回
（`docker ps` 90s 无返回）；同期 Temporal(7233) 与 console(3099) 响应正常。
因此**凡是吃 docker 的段一律必红**——集测「供给装配超时（>900s）」、验收起台/拆台
`STAGE_ENV: docker 不可用`、合并检查 `verify_lane code` 5 红——都是同一个根因，
不是票的代码问题。**恢复动作在宿主侧，需人授权**（红线：integration 不重启用户 Docker/OrbStack）。

## 二、证据（2026-09-18 17:44–17:50 现测）

| 探针 | 结果 | 判读 |
|---|---|---|
| `python socket.connect_ex(~/.orbstack/run/docker.sock)` | rc=0，耗时 0.00s | 宿主侧 relay 活着，socket 在 |
| 同一连接发 `GET /_ping`，5s | **0 字节**（recv 超时） | 卡死在 socket 之后的那一层 |
| `curl -m 15 --unix-socket .../_ping` | `CURL_RC=000`，time 15.01s | 无 HTTP 响应 |
| `docker ps`（自建超时） | **>90s 无返回**（kill -9 收场） | 不是「慢」，是死 |
| `docker info` | >25s 无返回 | 同上 |
| `connect 127.0.0.1:7233`（Temporal） | rc=0，收到 15B | 宿主网络正常，排除沙箱/网络面 |
| `connect 127.0.0.1:3099`（console） | HTTP/1.1 404 | 用户操作面健康（未受牵连） |
| `orb status` | `Running` | VM 进程活着（≠ docker 服务活着） |
| 卡住的 docker 客户端 | 13 个 `docker (info\|ps\|rm\|inspect…)` + 2 个 `/bin/sh -c … docker info …`（测试台入口闸） | 它们各自在自己的超时/永久等待里 |

**排除「是我的沙箱挡住 docker」**：同一 shell 能连 Temporal/console；且引擎 worker（非 dsh
agent 进程）侧同样报 docker 不可用（下节）。→ 真因在宿主的 docker 服务，不在 dsh 沙箱。

## 三、引擎侧同源痕迹（worker 日志，非 dsh agent）

- `08:02:53` / `08:03:05` `[agent-gc] docker 不可用` —— `agent_runtime.py:140 _docker_present()`
  = `docker info` 15s 超时 → False。**即今晨 08:02 起 docker 就已不可用**（更早无日志证据，
  不排除更早）。
- `14:11:55` ×2（t260917-08 / t260916-25）`ui_capture_stage: [down_stage] 拆台 rc=2：
  STAGE_ENV: docker 不可用`——正在拆台时 daemon 已经不答。
- `docker rm 异常（容忍）：Command [docker rm -f sandbar-agent-utt05j] timed out`——
  拆容器 30s 超时，说明卡的不是一个调用面。
- `17:42:48` **t260917-08 merge_check 红灯**：`泳道内 verify_lane code 绿灯: red=1`，
  5 failed 全落在 `server/engine/tests/test_t260913_05_teardown_multirepo.py`
  （`docker rm -f` 超时被当 error），`5 failed, 1453 passed in 414.58s`。
  → 我此前记为「基线红 / flaky」的那 5 红，**真因就是本事故**。

## 四、影响面（为什么今夜没有产出）

1. **无票可收口**：`merge_check` 的 `verify_lane code` 跑全量套件，其中 teardown 用例要
   docker → 只要 daemon 卡着，**每张票都会在这里红**。今夜合并数 = 0 是供给决定的，
   不是 agent 或票的锅。
2. **集测段空转**：`run_integration_tests` 走「测试台供给」→ `docker info` 不通 →
   `供给装配超时（need=docker 测试台在位，>900s）`，每轮白等 15 分钟。
3. **仲裁/验收空转烧额度**：供给面红 → tests-fault → arb↔acc 循环。今日轮次：
   t260917-08 仲裁 21 轮（含 1 次「迭代超限转人工」）、t260916-25 仲裁 15 轮、
   t260917-09 仲裁 12 轮（2 次超限转人工）。**这些轮次里的绝大部分是环境红**。
4. 无关面：console(3099)、Temporal、agent 执行面（host 形态）都正常——所以票面的
   plan/implement/测试设计等**离线工作仍在推进且落盘**，不是全损。

## 五、我做了什么（不越界）

- **不动宿主**：未重启/未 stop OrbStack（用户长期红线），只做只读探测。
- **停闸省额度**：17:49 用正规入口 `ticket.py op=pause`（who=integration 守夜，note 写明原因）
  暂停 4 张吃供给的票，语义=**当前段自然跑完，停在段间门口**（不打断正在跑的实现/验收，
  不丢产物）：
  - t260916-25（插件 inject 契约票）、t260916-26（同族 stage 台票）、
  - t260917-05（dinD 复用票）、t260917-09（tests_rounds 上限语义票）。
- **-08 保持 blocked 不动**（blocked 不烧额度；且它是本事故的探针——恢复后第一张验它）。
- 记录本文件。

## 六、需要人做的一件事（恢复按钮）

择一（都在宿主侧，integration 不代按）：

1. 轻：`orb restart docker`（只重启 VM 内 docker 服务，不动 VM/容器外的其他东西）；
2. 重：退出并重开 OrbStack（若轻的不管用）。

恢复后我这边的动作顺序（已写进守夜提醒）：

1. **金丝雀**：`retry_qc` t260917-08 的 merge_check → 看 teardown 5 红是否转绿
   （绿=daemon 真回来了，且能顺带合并 -08）；
2. 绿则**逐张 resume**（间隔 ≥15 分钟，避免 4 张同时抢台再把 daemon 压死）：
   -25 → -26 → -05 → -09；
3. 若金丝雀仍红：不 resume，回读 daemon 状态并上报（避免又一轮空转）。

## 七、待办（票候选，等宿主恢复后评估）

1. **供给闸前置 docker 健康探测**：现在每个吃台的段各自等 900s 才红；应在段入口
   用短超时探一次，红就原子级 env_fail 点名（省掉 N×15 分钟空转）。
   ——与 t260917-08 刚落地的 `env_fail` 语义同族，待其合并后可直接复用口径。
2. **merge_check 的 docker 依赖用例单列**：`verify_lane code` 里 teardown 类用例在
   daemon 不可用时属 env_fail，不该计产品红（否则所有票被一个环境面钉死）。
3. **测试台并发与泄漏容器治理**：昨夜泄漏台/错血统 worker 已两次污染供给面；
   台并发上限与容器回收需要机器闸（当前只有租约/持有期软约束）。
4. **未证实、留观察**：daemon 为何卡死（候选：昨夜容器 churn/泄漏台残留把 VM 内
   docker 服务拖死）——本记录不做归因定论。

## 八、边界声明

- 本记录只定位、只留证、只停闸；**未修任何代码、未动任何他票、未重启宿主服务**。
- 恢复动作（重启 docker）属宿主操作，须人授权；授权后我按第六节顺序推进。

## 九、停摆期观察（18:00–20:35，补记）

1. **暂停语义是「段边界」，拦不住 activity 重试**：`ticket.py op=pause` 只让 workflow 在段间门口等
   resume（`base.py:195 _pause_gate`），**正在跑或被重试的段照跑**。t260916-26 的验收段即踩此缝：
   18:49 起 agent 因会话损坏（`seq gap`）在起跑即 rc=1 退出 → activity 重试 → 再起再死。
   实测每轮约 1 秒退出、**未产生模型调用**（额度零耗），故未干预；但这是一处值得记的缝：
   **想让「暂停」在环境故障期真正兜住额度，需要「段内重试也受暂停约束」**（与草稿⑥同族，可并入）。
2. **merge_check 会自行重试**：t260917-08 的合并检查自跑到第 4 次，每次都稳定复现同一 5 红
   （docker 依赖用例）→ 环境红判据可靠，可继续当金丝雀。
3. 停摆期宿主残留：13 个挂起 docker 客户端、2 个卡在台入口闸的 `docker info` 子进程、226+ 个
   bash 进程（含 dsh agent 的 shell）；daemon 恢复后应自然消化，未见内存/负载恶化（load ≈ 3）。
4. 无泄漏台：3199/3200/3201/3202/3300 全端口无服务在听（昨夜清理 + 宿主关闭 3199 生效）。

## 十、第一次停摆的收尾与「第二次卡死」（260918 21:20 / 260919 00:05）

**21:20 自愈**：`_ping` 恢复 `HTTP/1.1 200 OK`，`docker ps` 0 秒、`docker info` rc=0。**恢复非我所致**——
17:50 时那 13 个挂起客户端仍在（21:20 前未清理），说明是 OrbStack 侧自愈。恢复后按预案执行：
金丝雀 `retry_qc` 失败（Temporal 快照读取瞬时超时，未越权），但 t260917-08 的 `merge_check` **自己第 5 次
尝试 21:18 全绿 done**（六项全过），随即走人审授权收口 `0660667`；21:22 起逐张 resume
（-25 → -26 → -05 → -09，间隔 ≥15 分钟）；t260916-26 清坏会话后仍僵死，**杀进程触发失败路径**才复活（见下）。

**260919 00:05 第二次卡死**（本记录写作时进行中）：

| 项 | 观测 |
|---|---|
| 症状 | `docker ps` >15s 无返回；socket 连通、`GET /_ping` 5s 无应答（与第一次同形） |
| 宿主负载 | **3.5**（远低于第一次的 20–50）→ 排除「负载/并发压死」这一解释 |
| 挂起客户端 | 仅 2–3 个（`docker ps -q`、`docker ps -a --filter label=com.docker.compose.project=stage-console-c7204e3c`）→ 排除「客户端堆积」 |
| 影响 | t260916-25 验收段 00:06 `ActivityError: Activity task failed` → blocked；-26/-05 的下一步必红 |

**结论（升级后的判断）**：两次同形卡死、诱因各不相同（第一次高负载 + 13 客户端堆积；第二次低负载 + 无堆积）
→ 更像 **OrbStack docker 服务自身不稳定**（VM 内 dockerd 或宿主侧 relay 的看护进程失效），
而不是本项目 churn 造成的；自愈时机也不受我方可控（第一次熬了约 13 小时）。

**处置（第二次）**：按第一套预案——`pause` t260916-26（实现段）/ t260917-05（集测段）停在段间门口省额度；
t260916-25 保持 blocked（不烧额度）；守夜巡检改为 13 分钟一轮、**禁用裸 `docker ps`**（会挂死整条命令，
已踩坑一次），恢复后逐张放票并把「第一张到 merge_check 的 teardown 5 红是否转绿」当金丝雀。

**给宿主的建议（需要你决策，均在宿主侧）**：①两次卡死说明按钮级恢复不够，建议查 OrbStack 版本/日志
（`~/.orbstack/log/vmgr.log` 13:28 起只见容器侧噪声）或在白天做一次彻底重启；②若持续复发，
考虑给供给面加「docker 健康度前置闸 + 可降级到无 docker 的离线场景池」的工程方案（已并入草稿⑥）。

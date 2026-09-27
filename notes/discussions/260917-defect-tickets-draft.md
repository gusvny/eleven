# 结构性缺陷票草稿（6 条）

> 起草：integration 岗位（sandbar 项目会话）｜状态：**草稿待宿主定稿**（未开票）
> 来源：260917 单日实操（解「清越界+合 main」死结 7 次、3 张票撞仲裁迭代上限、多次 flaky 假红）
> 追加：260918 夜间事故（宿主 docker daemon 卡死 → 全体票空转，见 260918-docker-daemon-wedge.md）→ 草稿⑥
> 每条给出：现象与实证 → 建议 spec 要点 → 写集 → 验收。开票前请宿主核定标题与 epic。

---

## 草稿①：agent prompt 未点名「保护名单与共享测试资产不许改」→ 撞闸循环

**现象**：泳道内 agent 跑套件遇红时，反复去改**共享资产与保护名单**（`integration/baselines/*`、别的票的场景、workbench 运行产物），被阶段路径闸拒 → 票 blocked。单日复发 **5 次**（t260916-24 两次、t260916-21、t260916-23、t260917-05）。

**实证**：
- `t260916-24` 15:14 / 16:26：`段 arbitrate 不允许改 integration/baselines/ticket-lifecycle-scenes.mjs、integration/t260914-04/offline_ticket_pause_entry.py`（baselines=保护名单）
- `t260917-05` 13:xx：`段 arbitrate 不允许改 server/plugins/workbench/lib/client.cjs、client.js`（运行产物）
- `t260916-22` 12:05 / 12:36 / 13:03 / 13:26 / 13:43：同一形态 5 连撞

**建议 spec 要点**：agent 段 prompt（`dev_lane.build_stage_prompt`）在「红线」段显式点名：①保护名单路径（`integration/baselines/`、写集外共享资产）②不得改；③遇共享资产红 → **如实出 `verdict=tests-fault` 并点名路径转人工**（t260917-01 修向④已在 arbitrate 文案里落了一句，需推广到 implement/design 段 prompt）；④运行产物（`*.cjs/*.js` 编译产物）归属说明。

**写集**：`server/engine/dev_lane.py`（prompt 构建）、`server/engine/tests/`、`integration/`
**验收**：UT 断言 prompt 含保护名单条目；场景：构造「共享资产红」的桩泳道，断言 agent 走「点名转人工」而非改文件。

---

## 草稿②：`integration/run_scenarios.py` 共享登记表是并行冲突热点

**现象**：每张票都在同一个文件尾追加自己的场景登记 → **任何一票收口合入 main，其余在飞票立刻在该文件落后** → `merge_check` 的 merge 预演报冲突 → 票 blocked。单日 **4 次**（t260916-21/-22/-23/-02）。

**实证**：
- `t260917-02` 13:24：`merge 预演无冲突（merge-tree main × lane/t260917-02）: 冲突文件：integration/run_scenarios.py`（它 13:14 刚合过 main，13:15 -23 收口改了该文件）
- 其余三次为同类（合 main 时 `CONFLICT (content): integration/run_scenarios.py`）

**背景**：引擎 known-issues 已登记同类（KI-014「manifest 共享可变尾文件是并行泳道的结构性冲突热点」），但只治了 manifest。

**建议 spec 要点**（择一，方案段定）：①登记表按票分片（`integration/scenarios.d/<票号>.py` 或 JSON），main 侧只留装配逻辑；②或引擎在派段/收口时机械处理该文件的登记合并（保序并集 + 冲突自动解）；③最小解：`merge_check` 的 merge 预演把该文件列为「已知可并集」豁免，不因它单独 block。

**写集**：`integration/run_scenarios.py`、`integration/lint_tests.py`、`server/engine/`（若走引擎侧）、`integration/`
**验收**：两张票并行各自登记场景 → 先收口其一 → 另一票 merge 预演不再因该文件红。

---

## 草稿③：派段前不检查「泳道落后 main」→ 每个段落都撞已修好的红

**现象**：泳道 fork 落后于 main 时，agent 跑套件会遇到「main 早已修好、它却没有」的红，于是（按本能）去改共享资产 → 撞闸 → 死结。**单日解此结 7 次**（t260916-19/-20/-21/-22/-23/-24/-29），每次人工 3–5 步（备份 diff → 清越界 → 合 main → 解冲突 → 重跑）。

**实证**：`t260916-20`/`t260916-21`/`t260916-29` 的 `integration/t260916-02/lib_relocation.py` 缺 `engine-venv-compat` marker（main 已由 t260916-27 补，泳道落后）；合 main 后三票随即推进（-20 已收口落 main `baa9d5d`）。

**建议 spec 要点**：引擎在**派 agent 段前**检查泳道与 main 的关系（`git merge-base --is-ancestor main HEAD`）：
- 落后则 ①自动 rebase/merge（有冲突则转人工并点名冲突文件）；或 ②至少在 blocked 文案/票面点名「泳道落后 N 个提交，先同步」并给出命令；
- 不得静默放行（现状），因为静默会以「agent 越界改共享资产」的形式爆出来，掩盖真因。

**写集**：`server/engine/agent_activities.py` + `dev_lane.py`（派段前检查点）、`server/engine/tests/`、`integration/`
**验收**：UT/场景构造「泳道落后 main」→ 断言派段前被拦或自动同步；`rework`/`retry_qc` 文案含落后提示。

---

## 草稿④：flaky 测试造成「假红」→ 票无故 blocked（失败分类未覆盖）

**现象**：`server/engine/tests/test_t260901_25_t03_reap_process_group.py` 在**高负载并发跑全量**时红、单独跑恒绿；它导致 `merge_check` 假红 → 票无故 blocked。**单日两次**（t260916-23 12:57、t260917-02 13:17）。

**实证**：
- `t260916-23` 12:57：`FAILED ...test_t260901_25_t03_reap_process_group` `1 failed, 1374 passed`
- `t260917-02` 13:17：同一测试 `1 failed, 1382 passed`
- 复现对照：main 树单独跑 `1 passed`；-23/-02 泳道单独跑均 `1 passed`

**建议 spec 要点**：①该测试（进程组 reap，时序敏感）加确定性护栏（等待条件代替固定 sleep、或用桩时钟）；②失败分类协议（t260910-13 已立）增「疑似 flaky」判据：同用例在**单跑复现为绿**时不得直接判真败，应自动重跑一次并留痕；③`merge_check` 对该类红给出可辨文案（「单跑复现绿=疑似 flaky，已重跑」）。

**写集**：`integration/t260901-25/t03_reap_process_group.py`（或迁入的 UT）、`server/engine/failure_protocol.py`、`server/engine/agent_activities.py`、`integration/`
**验收**：场景构造「高负载下假红」→ 断言自动重跑且票不 blocked；真红仍 blocked。

---

## 开票建议（待宿主核定）

| 草稿 | 建议 epic | 优先级理由 |
|---|---|---|
| ① prompt 点名保护名单 | engine-hardening | 单日复发 5 次、直接造成死结 |
| ② run_scenarios 冲突热点 | engine-hardening | 并行度越高越痛（用户明确要多并行） |
| ③ 派段前查落后 | engine-hardening | 单日人工解结 7 次，全部可省 |
| ④ flaky 假红分类 | engine-hardening | 两次假红、掩盖真因 |
| ⑤ 会话损坏容错 | engine-hardening | 今日人工清会话约 10 次，头号 blocked 成因 |
| ⑥ 供给面 docker 健康闸 | engine-hardening（+工具面） | 260918 一夜全票空转；环境红被当产品红烧额度 |

---

## 草稿⑤：会话文件损坏必须容错（拒读 → 隔离 + 新建，不得让整段 agent 崩）

**现象**：agent 段因会话文件损坏以 `rc=1` 退出 → activity 判「agent 退出但未写结果文件」→ 票 blocked；**必须人工清掉坏会话才能重跑**。单日人工清会话 **约 10 次**（t260916-01/-22/-23/-26/-28、t260917-05/-08 等）。

**三种损坏形态**（本日实测）：

| 形态 | 报错 | 实证 |
|---|---|---|
| 帧撕裂 | `complete frame contains a torn JSONL record` | 多票（上午） |
| 进程僵死 | 不退不写、activity 心跳正常 → **永不超时** | t260917-01（需杀进程触发失败路径） |
| 结构错 | `corrupt session log: first line is not a session header` | t260917-08（00:14） |

**关键**：引擎侧已有「恢复失败 → 回落新建同 id 会话」的兜底（`server/headless-resume/`），但 dsh 在读到损坏会话时**直接 rc=1 退出**，兜底没机会生效。

**建议 spec 要点**：①会话读取层遇损坏即**隔离**（改名 `.torn-backup-<ts>`，沿用现成命名）并**新建会话继续**，不得整段崩；②引擎侧兜底：agent 退出码非零且日志含 `corrupt session log` 时，自动执行一次「隔离 + 重跑」（留痕，不无限重试）；③三形态全覆盖；④僵死形态另需「进程活性」判据（心跳正常但无 IO 超阈值即判死并走失败路径）。

**写集**：`server/headless-resume/`、`server/engine/agent_activities.py`、`server/engine/tests/`、`integration/`
**验收**：构造三种损坏会话夹具 → 断言 agent 仍能起跑（会话被隔离 + 新建）、票不 blocked；真失败仍 blocked。

---

## 草稿⑥：docker 供给面故障未被前置识别 → 全体票空转（260918 事故）

**现象**：宿主 OrbStack 的 docker API 卡死（socket 可连、连上无回包），引擎不认识这个状态：
①吃台的段各自**死等 900s** 才报「供给装配超时」；②报出来仍走 `tests-fault` → **计入「测试集迭代」轮次**，
于是 arb↔acc 空转烧模型额度（当日 t260917-08 仲裁 21 轮、t260916-25 15 轮、t260917-09 12 轮，含
3 次「超限转人工」）；③合并门的 `verify_lane code` 跑全量套件，其中 docker 依赖用例（`docker rm -f`
超时）计**产品面红** → **每张票都被钉死在合并门口**，一夜 0 收口。

**实证**（详见 `260918-docker-daemon-wedge.md`）：
- `python socket connect ~/.orbstack/run/docker.sock` rc=0 0.00s；同连接 `GET /_ping` 5s 内 **0 字节**；`docker ps` **>90s 无返回**；同期 Temporal(7233)/console(3099) 正常。
- 引擎侧（非 dsh agent）：`08:02 [agent-gc] docker 不可用`（`agent_runtime.py:140 _docker_present` = `docker info` 15s 超时）；
  `14:11 ui_capture_stage: [down_stage] STAGE_ENV: docker 不可用`×2；
  `17:42 t260917-08 merge_check 红＝verify_lane code 5 failed 全落在 tests/test_t260913_05_teardown_multirepo.py`。

**建议 spec 要点**：
1. **段入口前置供给探针**（短超时，如 5–10s）：docker 不可用即该段直接 `env_fail` 点名，
   文案含「宿主 docker 无应答 + 建议动作」——不占 900s、不进 tests-fault 轮次、不烧 agent 额度；
2. **环境红与产品红分账**：供给面红不参与「测试集迭代」计数（与 t260917-08 落地的 `env_fail` 语义同族，
   可直接复用其 `StageResult.env_fail` / `env_note_for` 口径）；
3. **docker 依赖用例单列**：`verify_lane code`（merge_check）把需要 docker 的用例标出来
   （先盘点：teardown 族等），daemon 不可用时它们记 `env_fail`，不把合并门钉死；
4. **供给面租约/并发闸**：台并发上限与卡死客户端回收（本次宿主残留 13 个挂起 docker 客户端 +
   2 个卡在台入口闸的 `docker info` 子进程），避免 churn 把 daemon 拖死（归因未定，先留观测点）。

**写集**：`server/engine/agent_activities.py`、`server/engine/dev_lane.py`、`server/engine/shared.py`、
`server/engine/verify_lane*`、`server/engine/tests/`、`integration/`
**验收**：用桩/旋钮伪造「docker 不可用」→ 断言 ①段入口秒级 env_fail；②仲裁轮次计数不增；
③merge_check 不因 docker 依赖用例记产品红；④daemon 恢复后同一票能正常跑（不留粘滞态）。

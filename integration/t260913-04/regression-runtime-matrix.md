# t260913-04 回归矩阵：agent 执行面容器化后，「依赖 agent 在本机执行命令」的能力逐个确认

> review_plan gen1 条件 **C3** 的落点（票面第 3 块「逐个确认」的清单化）。
> 口径：每行写「本票后它拿到哪个 runtime / 依据 / 要不要跟着改」。
> 「runtime」取值 = `host`（宿主直跑，存量语义）/ `docker`（每票一容器，本票新增）。
> 单点开关 = env `SANDBAR_AGENT_RUNTIME`（缺省 `host`；非法值 fail-closed 点名）。

## 0. 缺省值冻结（本清单同时是「host 语义逐字节不变」的证明）

- `agent_runtime.runtime_mode()`：未设 env → `host`；显式 `docker` → 容器；其它值 → `AgentRuntimeError`（不静默回落）。
- `host` 分支：`spawn_agent` 内的 `subprocess.Popen(cmd, cwd, env, stdout=logf, start_new_session=True)`
  与接线前**逐参数一致**；`_prepare_agent_spawn` 的 docker 专属段（profile 重置 + sandbox_pin 追加）
  带 `if runtime_mode() == "docker"` 前置，host 形态零新增文件、零新增 argv。
- 单测机械锚：`server/engine/tests/test_agent_runtime.py::test_spawn_host形态_旧语义零依赖fake`
  + `integration/t260913-04/sc_t26091304_wiring_contract.py`「host 缺省形态」轮
  （零 docker 调用 / 桩宿主直跑 / 结果文件形状不变 / 不写 sandbox_pin / 零容器残留）。

## 1. worker 启动点全族

| # | 启动点 | 本票后 runtime | 依据 | 要不要跟着改 |
|---|---|---|---|---|
| 1 | 生产 `server/engine/run_worker.sh` | **docker** | 本票显式 `export SANDBAR_AGENT_RUNTIME=docker`（一处接线、审计可见；D6） | 已改（本票交付） |
| 2 | `integration/` 自起 worker：`t260908-01/lib_ki061.py:118` 族 | host | 场景自造 env（`env_for` 剥 SANDBAR_* 后按需注入），未注入 runtime → 缺省 host | 不改（存量冻结） |
| 3 | `t260908-01/sc_ticket_pause_gate.py:222` | host | 同上（桩 agent `SANDBAR_AGENT_CMD`） | 不改 |
| 4 | `t260910-08/sc_t260910_08_lane_materialization.py:214` | host | 同上（桩 agent） | 不改 |
| 5 | `t260910-06/sc_ki067_entry_audit.py:350` | host | 同上 | 不改 |
| 6 | `t260905-02/lib_t26090502.py:43` | host | 同上 | 不改 |
| 7 | `t260905-03/lib_inspection.py:41` | host | 同上 | 不改 |
| 8 | D9 验收 lane worker（本票 Step 6 A 腿） | **docker** | `run_real_ticket_e2e.py --leg a` 显式注入 `SANDBAR_AGENT_RUNTIME=docker` | 新增（本票交付） |

**注**：`SANDBAR_AGENT_STUB=1` 在 `_prepare_agent_spawn` 之前 return（`agent_activities.py:1194` 一带）
→ 桩路径**根本不经过 spawn**，因此桩族场景（#2–#7）的绿**只是读侧零回归证据，不是容器执行面证据**（C2 措辞纪律）。
容器执行面的证据在 `integration/t260913-04/` 五条场景 + 本文件 §3。

## 2. 各段自检 / 引擎自带检查点

| # | 面 | 本票后 runtime | 依据 | 要不要跟着改 |
|---|---|---|---|---|
| 9 | `server/engine/selfcheck_*.py` | host | 纯宿主脚本，不经 spawn | 不改；`server/engine/tests` 732 项全绿（本票实测） |
| 10 | `integration/run_scenarios.py` 场景复跑 | host（缺省）/ docker（本票 engine 池四条） | 场景各自决定：本票 4 条 engine 池场景用真 docker 舞台与真镜像，但**不经 worker spawn 链**（③ 例外：直调引擎 spawn 链） | 本票新增 5 条已注册（ro×1 + engine×4） |
| 11 | 仲裁段 `agent_activities.py:3869`（`arbitrate`） | 跟随 runtime（host/docker 同源） | 三处 spawn 点统一走 `agent_runtime.spawn_agent`；reap 统一 `AgentProc.reap` | 已改（本票交付），语义 0 变化 |
| 12 | 验收走查段 `agent_activities.py:4182`（`acceptance_walkthrough`） | 同上 | 同上 | 已改（本票交付） |
| 13 | 通用段 `agent_activities.py:1246`（`_run_agent_stage_impl`） | 同上 | 同上 | 已改（本票交付） |

## 3. 本票新增的容器执行面证据（每条各自证明 A–G 的哪一条）

| 场景 | 池 | 证明面 | 实测结果（本机 docker 29.4.0 + `sandbar-agent:dsh-0.1.1-rc.2-s1`） |
|---|---|---|---|
| `sc_t26091304_wiring_contract.py` | ro（hermetic） | B/C/D/G + 红线 1/2/3/4（argv 契约：挂载面恰好泳道一项、env 白名单、user=uid:gid、无特权、pin 字面量、host 冻结、生产接线棒） | 27 pass / 0 fail / 0 env（设计段实跑 + 实现段复跑） |
| `sc_t26091304_image_supervisor.py` | engine | G + KI-009 收割前置（镜像内 dsh/node/py 依赖、非 root 可执行 supervisor、pgid 落盘→组 TERM→清档、坏参 fail-closed） | 16 pass / 0 fail；**本票实锤**：0711 权限导致所有容器内 spawn rc=2，`chmod 755` 修复后转绿 |
| `sc_t26091304_lifecycle_gc.py` | engine | D/G + 红线 3（spawn 即 ensure、容器内桩真跑、结果/日志落泳道原位、迟写按组收割、孤儿 gc 不误杀、收口零残留） | 19 pass / 0 fail |
| `sc_t26091304_multirepo.py` | engine | E + 红线 2 + D2（两棵成员仓树容器内可写、宿主可见、属主=worker uid、挂载源仅泳道根、git 降级形态、逐树代落盘） | 16 pass / 0 fail |
| `sc_t26091304_sandbox_neglock.py` | engine（门控 `SANDBAR_E2E_REAL=1`） | **B/C 核心 + 红线 2 + 宿主 260914 A 案**（真 dsh agent：正锁工作区内写成功、负锁宿主边界不可达（主树/他票路径不存在、/usr/local uid 权限拒）零落盘、正腿容器本地 /tmp 可写（容器内无沙箱拦截）、>65s 命令跑完、git 降级、证据面 mode=danger-full-access+真实拒绝；对抗轮 env 注入 workspace-write 与 profile 注入 disabled——pin 字面量都必须仍赢） | 13 pass / 0 fail / 2 na（设计段实跑：基线轮 6/6 绿；profilepatch 轮 5/5 绿=入口级 `disabled:false` 压制注入；envleak 轮 dsh **fail-closed 拒启**（rc=1）→ 正锁如实 N/A、负锁仍成立）。实现段独立探针轮复现：`sleep 65` 前台跑完并写盘 ✓、工作区内写 ✓、两处越界 `Permission denied` ✓ |
| `run_real_ticket_e2e.py --leg f` | 驱动（零模型成本） | F | 见 §4 |

## 4. F 成本腿实测（R6 判据两条臂各自出结论）

本机（OrbStack linux/arm64 29.4.0，镜像 `sandbar-agent:dsh-0.1.1-rc.2-s1`）：

```
基线 dsh --version        N=3 median=0.060s  ['0.051', '0.060', '0.063']
参考 dsh --dump-config    N=3 median=0.098s  ['0.091', '0.109', '0.098']
被测 ensure+首 exec       N=3 median=0.341s  ['0.521', '0.341', '0.312']
打点 ensure 段=['0.443', '0.270', '0.245'] 首 exec 段=['0.077', '0.072', '0.067']
比值臂：5.68x（判据 ≤3x）→ FAIL；绝对臂：0.341s（判据 ≤10s）→ PASS
```

- **绝对臂 PASS**：「起容器到 agent 可用」= 亚秒级（0.34s 中位），远优于判据上限 10s。
- **比值臂 FAIL（5.7–7.5×）**：基线 `dsh --version` 是 node CLI 打印版本（54–67ms，不装载 profile 栈），
  被测含 `docker run -d` + exec 往返的固定开销（~300ms）。**这不是「agent 就绪慢」**，是
  「容器创建固定成本」对「54ms CLI」的比值。忠实口径参考：`--dump-config`（真装载 profile 栈）0.098s
  → 比值 3.5×，仍在 3× 之上；容器冷起的固定成本（~250–450ms）就是这条臂的物理下限。
- **处置**：判据文本归 main 侧（红线 5），本段**不擅改**判据，只如实登记两条臂的结论与口径事实，
  交 integration 岗核定比值臂基线口径（建议基线改用「host 真起一段 agent 的就绪耗时」或直接以绝对臂为准）。

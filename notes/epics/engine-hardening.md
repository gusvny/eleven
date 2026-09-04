# 立项单：engine-hardening

| 字段 | 值 |
| --- | --- |
| 代号 | `engine-hardening` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-09-04 |
| 备注 | 起因=260904 t260904-01 首开脑裂事故链（KI-032×KI-033 叠加）；票①=硬闸+指纹+探测+隔离测试台 |

## 背景与问题

260904 实案链：裸 `client.py ticket-start` 不锚 `project_root` → 泳道存**相对路径**，落仓由「抢到 activity 的 worker 按自身 REPO_ROOT」决定 → suyou 侧遗留 headless（僵尸进程，带 supervisor 的 15s ticketEnsure）抢先伺服同一条专属队列 → worktree 建进冻结仓 suyou、agent 跑错仓（跨仓脑裂）。当日处置：cancel 作废 + 杀僵尸进程族 + 清两仓残骸 + 正规入口重开。本 epic 把处置上升为**机制**，并补上集成测试面「引擎行为零覆盖」的结构性空白（现套件纯替身层）。

## 目标（第 1 面）

1. **开票硬闸（KI-032 修复）**：`client.py ticket-start` 收到 `project` 即自查机器级注册表（`SANDBAR_PROJECTS_DIR` 覆盖语义保持）锚 `project_root`，与 `ticket.py:664-669` 同源（加载器收敛单一真源，不双份漂移）；未锚定即**拒收**——任何入口开票必得绝对路径泳道，落仓与执行 worker 解耦。
2. **worker 归属指纹（KI-033 修复）**：工单 worker 注册带引擎仓指纹；ensure 发现**异仓 worker** 伺服同票 → 告警/拒接，跨仓双 serve 不再静默。
3. **doctor 僵尸探测**：`sandbar doctor` 加「异仓引擎进程」扫描——cwd 指向非当前引擎仓的 node/python 引擎进程，红了报出来（迁移/切换后清场从纪律变命令）。
4. **隔离测试台（老仓模式迁回）**：boot 骨架（临时 DSH_HOME / 临时 profile / **port-0 内核分配**真启动 / teardown 三钩子幂等）收成 `integration/` 共享库；temporalite **槽位制**起停（`~/.sandbar/test-benches/slot-N`，flock 独占、崩溃自释、满槽排队不假红）；首个引擎行为场景=裸入口开票 → 断言 workspace 为绝对路径且锚项目主目录（未锚定形态修复后必须拒收）。

## 宿主红线（260904 钦点，验收一票否决）

- **隔离台互不冲突**：多票并行跑场景零假红、零串台（console 端口=内核分配；temporalite=槽位端口 + 槽专属 db + namespace 纵深）。
- **绝不影响生产 temporal**：隔离台不碰 7233/8233（temporalite 的 frontend/UI/metrics **全端口**隔离或禁用，UI 默认 8233 是暗雷必须显式覆盖）；不写生产库；生产 console 的 ensure 永远看不见隔离台里的票（可见域=各自连接的 Temporal）。`SUYOU_TARGET_HOST` 指向生产地址=拒跑（fail-closed）。
- **console 3099 红线照旧**：不重启不停不占用；temporal-tools（console 侧）改动上线后由宿主择机重启生效（staleness banner 提示，不自动）。

## 面/票拆解

- **票①（t260904-02，本面全量）**：目标 1–4。写集=引擎（temporal-poc：client/shared/worker + tests）、console 侧 supervisor（temporal-tools/node.ts）、安装器（installer/doctor 面）、`integration/`（bench 库+场景+登记）、KI 册与 epic 本档。**与在飞 t260904-01（workbench 面）写集零重叠，可并行。**
- 后续面（票①验收后再立，不在本面承诺）：引擎行为场景扩展（worker 生命周期/收口自退/多 console 防重）、裸入口面收敛。

## 验收标准（票①）

1. 裸 `client.py ticket-start` 带 project：产出 workspace 为**绝对路径**且锚 `<项目主目录>/.lane/`；无 project 且无显式锚=明确报错拒收（不是静默相对路径）。
2. 隔离场景里起异仓/异指纹 worker 伺服同票：ensure 侧可见告警或拒接记录（日志/回执可断言）。
3. `sandbar doctor`：fixture 注入假异仓进程 → 探测红；干净环境 → 绿（自证红绿，沿用套件纪律）。
4. 隔离台场景在**两路并发**下各跑各的 temporalite：零端口冲突、零数据串台、断言互不干扰；teardown 后槽位/db/临时家全清。
5. 场景断言**不出现**对生产 7233/8233 的任何连接尝试（含 UI/metrics 端口探测负向断言）。
6. KI-032/KI-033 在册子中转 closed（附票号）；epic 本档面状态更新。

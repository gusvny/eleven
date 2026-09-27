# 测试夹具临时物料 · 第二批整治报告（260927，不开票 / 未 commit）

> 范围=宿主授权的「三家生产者 + 全族清扫」。本文件是交付报告，不是工单；状态以工作区 diff 与本文数字为准。
> 所有路径相对仓库根 `/Users/user/Documents/sandbar`。**未 commit**（宿主先看后提交）。

---

## 1. 改动文件清单与每处意图

| 文件 | 状态 | 意图 |
|---|---|---|
| `integration/lib_tmp_reclaim.py` | 新增 | 集成侧回收 helper（**单源**）：注册表 + `atexit` 兜底 + **信号钩子（链式，不吞原处置）** + 幂等回收；目录与**文件**都管；单条失败不抛但点名 |
| `integration/run_scenarios.py` | 改 | ①`_run_lock_path` 产出的**同泳道单飞锁档**（文件）在抢到手后登记回收（抢不到绝不登记）；②同批装 SIGTERM/SIGINT 回收钩子；③两条 `os._exit` 收口路径（批台信号 / 预算耗尽）**显式**回收（`os._exit` 跳过 atexit）；④新增 `reclaim_tmp_artifacts()` / `_reclaimer()`（惰性装载，装不上只留痕不拦发车） |
| `integration/t260907-10/sc_engine_venv_compat.py` | 改 | `venv-compat-root-` / `venv-compat-home-` 两处裸 `mkdtemp` → `mkdtemp_reclaimed`（原表只覆盖 `-root`，`-home` 4,764 个从不在册） |
| `integration/t260910-13/sc_t260910_13_failure_protocol_{gate,pytest_source}.py` | 改 | **超出点名三家**的一处加修（理由见 §5.2）：当期最大活生产源 `t26091013-*`（8,594 条 <6h）两处裸 `mkdtemp` → `mkdtemp_reclaimed` |
| `integration/stage_docker.py` | 改 | 拆台失败（compose down `rc!=0` / 抛异常）时的「保留」从**静默 return** 改**具名点名** `STAGE_TMP_RECLAIM: kept admin_log, credentials, presets …`（三件物料都是容器 bind 的宿主机侧，不能删；但保留必须可见） |
| `integration/tools/sweep_tmp_fixtures.py` | 改 | ①第二批 28 个前缀**正式并入白名单**（原「未启用候选」半态退役，`CANDIDATE_PREFIXES_BATCH2` 常量删除）；②新增**文件族**判据（常规文件 `unlink`）与**在用即不动**（`flock` 抢得到才删）；③新增 `EXCLUDED_PREFIXES`（明确排除族，判据里排除优先）；④只读夹具（0555/0444）补写位后重删；⑤`--prefix ""` 剔除（空前缀=形同没有前缀闸）；⑥报告加 dirs/files 拆分 + `locks kept` |
| `server/engine/inspection_lane_watchdog.py` | 改 | 白名单**同源同步**（45 前缀逐字一致，漂移锁绿）；注释改正 `dsh-*` 族归因（非本仓）；水位段新增 `skipped_count`（名单有上界的全量计数） |
| `server/engine/activities.py` | 改 | `scan_tmp_fixture_dirs` 的 `skipped` 名单加**上界** `TMP_SCAN_SKIPPED_CAP=40` + 具名截断行 + `skipped_count` 全量（白名单里现在含文件族，上万条名字进回执会撞 Temporal 单 payload 2MB 上限；判据零改动：水位仍只数真目录） |
| `server/engine/tests/test_t260926_tmp_fixture_water.py` | 改 | **re-point 一条既有断言**（见 §6.1） |
| `server/engine/tests/test_t260927_tmp_fixture_family.py` | 新增 | 24 条定点回归（A helper / B 生产者三条终态 + 反证 / C 清扫器文件族与排除族 / D 拆台边界 / E 白名单覆盖面与水位上界） |

新增常量/函数：`sweep.FixtureEntry`、`sweep.BATCH2_MERGED_PREFIXES`（28）、`sweep.EXCLUDED_PREFIXES`（11 族）、`sweep.NAMED_CAP`、`sweep.match_prefix()`、`sweep.file_size()`、`sweep.lock_held()`、`sweep.make_tree_writable()`、`sweep._delete()`；`activities.TMP_SCAN_SKIPPED_CAP`；`run_scenarios.reclaim_tmp_artifacts()` / `_reclaimer()`；`stage_docker._report_stage_tmp_kept()`；`lib_tmp_reclaim.{register_tmp_path, mkdtemp_reclaimed, reclaim_registered, reclaim_count, live_tmp_paths, install_signal_reclaim}`。

---

## 2. 生产者终态矩阵（含不假装兜得住的两态）

| 终态 | run_scenarios 锁档 | 场景夹具（helper 注册的） |
|---|---|---|
| 正常结束 / 断言失败 / 异常 / `sys.exit()` | `atexit` ✔ | `atexit` ✔ |
| SIGTERM / SIGINT | 信号钩子：回收 → **链式交回原处置**（可调用→调它；否则 SIG_DFL+重发）✔ 实测退出码 143 | 同（若调用点装了钩子）✔ |
| `os._exit(130)` 批台信号收口 | 显式回收 ✔ 实测 rc=130 且零残留 | 同（helper 的显式调用点） |
| `os._exit(2)` 预算耗尽收口 | 显式回收 ✔ | 同上 |
| SIGKILL（执行器硬杀 / KI-138 宿主休眠后判死） | **抓不住，不假装兜得住** → 兜底=清扫器 + 巡检水位面 | 同 |

边界（如实）：`SIGTERM` 语义逐字不变（仍是被信号杀死，`wait` 得 143）；`SIGINT` 仍走 Python 的 `default_int_handler` → `KeyboardInterrupt`。

---

## 3. 全族清单（前缀 → 生产者 file:line → 是否已修 → 存量是否已清）

计数=260927 普查（`$TMPDIR` 顶层，一次遍历）。「已清」= 该族 ≥6h 存量已删净；残留只可能是 <6h 的新生条目。

### 第一批（260926 已启用，本轮复核）
| 前缀 | 存量 | 生产者 file:line | 已修 | 已清 |
|---|---|---|---|---|
| `integ-e2e-fixture-` | 7 | `integration/baselines/ticket-lifecycle-scenes.mjs:187`（JS 侧 `FIXTURE_PREFIX`） | ✔（260926：dispose `await` + 信号钩子 + 开跑即扫 reaper，回归 `integration/tests/test_fixture_reclaim.mjs`） | ✔ |
| `lint-pyc-` | 78 | `integration/lint_tests.py:46`（atexit 已加） | ✔ | ✔ |
| `fix10-/fix14-/fix17-` | 678 | `integration/t26*/*.mjs` 夹具族（散在） | – | ✔ |
| `pathgate-` | 130 | `integration/t260911-03/` 族 | – | ✔ |
| `t260907-06-ut-` | 384 | `server/engine/tests/test_multirepo_anchor.py:59/97/139` | ✔（260926） | ✔ |
| `t260907-12-ut` | 312 | 同上 `:276-362` | ✔（260926） | ✔ |
| `sandbar-agent-presets-` | 466 | `integration/stage_docker.py:1331`（物化）/ 拆台回收 | ✔（260926） | ✔ |
| `t26092212- / t260906- / lease-ut- / t260904-02- / t260901-21- / t02-lane / t26090704-lane / wb-` | 2,526 | 各票场景（file:line 见下批同族） | – | ✔ |
| `venv-compat-root`（本轮并入更宽的 `venv-compat-`） | 50 | 见下 | ✔ | ✔ |

### 第二批（本轮正式并入；28 个前缀）
| 前缀 | 存量 | 生产者 file:line | 已修 | 已清 |
|---|---|---|---|---|
| `t260907-12-act-` | 4,259 | `server/engine/tests/test_multirepo_root_activity.py:51` | ✔（260926，本轮**核实**） | ✔ |
| `t260907-12-ch` | 2,140 | 同上 `:125/:136`（`-ch-`/`-ch1-`） | ✔（260926） | ✔ |
| `sandbar-admin-log-` | 2,853（文件） | `integration/stage_docker.py:1332` | ✔（260926+本轮具名边界） | ✔ |
| `sandbar-credentials-` | 2,518（文件） | 同上 `:1333` | ✔ | ✔ |
| `sandbar-integ-run-` | 2,819（文件） | `integration/run_scenarios.py` `_run_lock_path`（file:line 3068↓） | **✔ 本轮修** | ✔ |
| `nusuyou-integ-run-` | 1,836（文件） | **姊妹项目** `~/Documents/nusuyou/integration/run_scenarios.py:182`（同款代码旧前缀） | ✘ 本仓修不到（跨仓） | ✔ |
| `venv-compat-` | 4,814 | `integration/t260907-10/sc_engine_venv_compat.py:56-58` | **✔ 本轮修** | ✔ |
| `t26092114-` | 8,115 | `integration/t260921-14/lib_t26092114.py:131,156` | ✘ | ✔ |
| `t26090704-lock` | 3,251 | `integration/t260907-04/sc_dispatcher_lock_fallback.py:35` | ✘ | ✔ |
| `t260904-18-mg` | 3,257 | `integration/t260904-18/lib_t260904_18.py:153` | ✘ | ✔ |
| `t260910-10-` | 5,785 | `integration/t260910-10/sc_docs_project_anchor.mjs:111`、`sc_docs_ui_mock_v1.mjs:121-122` | ✘ | ✔ |
| `t260908-02-ut` | 2,119 | `server/engine/tests/test_t260908_02_payload_roundtrip.py:55` | ✘ | ✔ |
| `t090506-` | 3,230 | `integration/t260905-06/sc_doc_read_through.mjs:52`、`sc_doc_entry_present.mjs:44-45` | ✘ | ✔ |
| `t260904-13-itest` | 1,900 | `integration/t260904-13/lib_ki044.py:47` | ✘ | ✔ |
| `sandbar-t26091202-` | 35（15 目录+20 文件） | `integration/t260912-02/lib_lifecycle_case.py:564`（`:76` 另写死 `/tmp/sandbar-t26091202-*`） | ✘ | ✔ |
| `detailred-e2e-` | 1,568 | `integration/t260915-01/tests/sc_detail_red_refusal_receipt.py:76` | ✘ | ✔ |
| `sandbar-reg-` | 1,529 | `server/plugins/workbench/tests/registry-loader.mjs:47` | ✘ | ✔ |
| `t260915-10-` | 2,204 | `integration/t260915-10/sc_docs_follow_project.mjs:87-88` | ✘ | ✔ |
| `t26092404-` | 2,123 | `integration/t260924-04/sc_project_template_ticket_journey.py:195`、`sc_project_template_gate.py:184,207` | ✘ | ✔ |
| `t260923-` | 168 | `integration/t260923-*` 族场景 | ✘ | 0 条 ≥6h（全是 <6h 新生，等龄） |
| `t260925-` | 1,053 | `integration/t260925-*` 族场景 | ✘ | ✔ |
| `t260916-` | 1,256 | `integration/t260916-15/sc_sidebar_merged_sort_ui.mjs:52` | ✘ | ✔ |
| `t260922- / t260921- / t260917- / t260918- / t260919- / t260920-` | 0 | 前瞻覆盖（本仓票号命名空间，无实命中） | – | – |

### 明确排除（永不参与，判据里排除优先；存量照留）
`com.google.Chrome.`(4,398) / `com.apple.`(131) / `BlobRegistryFiles`(73) / `playwright`(178) / `TemporaryItems` / `TemporaryDirectory.` / `vscode-git-` / `docker_cli_`(38 个 socket) / **`dsh-subprocess-`(2,030) / `dsh-spill-`(40)** / `tmp`(7,940 —— BSD `mktemp` 缺省模板，归因不到本仓)。

> **归因更正**：`dsh-subprocess-*` 上一轮被登记成「本仓 dsh 子进程探针族（server/ui-check、probe_*）」——**错的**（本仓 grep 零命中）。真生产者=`@deepseek-ai/dsh-subprocess-local` 的 `lib/runner-launch-*.js:683`（`defaultSpillDir ??= mkdtempSync(tmpdir(), "dsh-subprocess-")`），即 **dsh 运行时自己的 spill 目录**；删活会话的 spill 目录=弄坏在飞的 agent 子进程，故列入排除（不删）。

---

## 4. 清理前后计数与释放

| 项 | dry-run（清扫前） | apply 第 1 趟 | apply 第 2 趟（补只读族） | 合计 |
|---|---|---|---|---|
| swept | 53,069（43,022 目录 + 10,047 文件）**候选** | 53,048（43,001 + 10,047） | 21（目录） | **53,069** |
| kept live（<6h） | 10,490 | 10,490 | 10,491 | – |
| failed | 0 | **21** | **0** | 21（已定位并消除，见下） |
| locks kept（flock 在用） | 0 | 0 | 0 | 0 |
| freed | ≈1.9 GiB（采样估算） | ≈1.9 GiB | ≈651 B | **≈1.9 GiB（估算）** |

- 耗时：第 1 趟 81.8s，第 2 趟 0.6s（无挂起；`nohup` + 日志 `out/sweep-apply-260927.log`）。
- 失败 21 条全部同一形态：`t260925-15-inst-*` 的 `content/releases/v000001/` 是 `dr-xr-xr-x`（只读 fixture），`rmtree` 删其内文件需父目录可写 → `PermissionError: entries.json`。**已修**：`make_tree_writable()` 补写位后重试（只改 mode，不动内容），第 2 趟 0 失败；白名单外的只读目录连 mode 都没碰（有回归锁 `test_c5`）。
- 磁盘：`df` 421Gi → 416Gi used（≈5 GiB）。**不是净归因**——同一窗口有并行 agent 在同一台机器读写。
- 清扫后只读普查：顶层条目 **145,719 → 93,072**（目录 131,940→89,340、文件 13,738→3,691）。白名单族里**每族 total == <6h 新生数**，即 **≥6h 存量已清零**；残留 10,496 条全是 6h 内新生的（见 §5.1）。
- 复扫 dry-run：`DRY-RUN: swept 0 (dirs 0 / files 0) | kept 10496 live | failed 0 | locks kept 0 | freed≈0B`。

---

## 5. 归因结论（这轮真正解释现象的三件事）

### 5.1 存量已清，但「当期泄漏速率」仍在：活水有明确出处
- 新生的 10,496 条里，白名单族占大头：`t26090704-lock` 1,522、`t260904-18-mg` 1,520、`t260907-12-act-` 1,337、`t260910-10-` 978、`t090506-` 983、`t260904-13-itest` 982、`t260916-` 844、`t260907-12-ch` 672、`t260908-02-ut` 662、`t260915-10-` 493…
- **未覆盖族的活水更大**：`t26091013-*` 8,594（本轮已治本，存量 17,254 未清）、`sandbar-*` 1,977、`notes-gate-*` 1,968、`t260915-09-reg-*` 986、`t260905-dp-reg-*` 952、`t09-bump-*` 632、`sc-t26090510-*` 621、`q08-quad-reg-*` 499、`t08-guard-reg-*` 492、`stage-l1-*` 389、`t25-t03-*` 359…
- 时间形态（普查直方图）：09-27 03:46–08:00 之间**每 ~15.5 分钟**出现一次 1,000–2,000 条的爆发——与 KI-138 记的宿主 Sleep~15.5min → DarkWake 45s 同一节拍；即「进程只在唤醒窗口里推进，随后被硬杀 → `atexit` 跑不到 → 每个窗口漏一批」。**这不是脚本故障，是内核级终态**，兜底仍是清扫器 + 水位面。

### 5.2 生产者在 main 已修，但**泳道 worktree 跑的是修前的码**（本轮最重要的发现）
- 实况：`t260907-12-act-` 在 09-27 08:00 仍在新生（1,337 条 <6h），而 main 的生产者早已是 `mkdtemp_reclaimed`。
- 证据链：`.lane/t260926-05/server/engine/tests/test_multirepo_root_activity.py` 仍是**修前版本**（3 处裸 `tempfile.mkdtemp`、0 处 reclaim），且它的 pytest 缓存 `.lane/t260926-05/out/pycache/…test_multirepo_root_activity…pyc` 的 mtime = **09-27 09:06**（正在跑）。
- 含义：**「改 main」不等于「停止泄漏」**——每个在途泳道持有自己的码副本，直到该泳道 rebase/退休。故本轮把「前缀覆盖面」做成机械锁（`test_e1`：生产者字面前缀必须被白名单盖住），并建议泳道纪律补一条：*测试面共享 helper 的修复必须随泳道同步*。
- 同理：`nusuyou-integ-run-*` 的生产者在姊妹项目仓（`~/Documents/nusuyou/integration/run_scenarios.py:182`），本仓修不到——建议同款修改回灌那个仓。

### 5.3 文件族上一轮整族漏了
`silent` 的形态：`sandbar-integ-run-*.lock` / `sandbar-admin-log-*.log` / `sandbar-credentials-*.yaml` / `nusuyou-integ-run-*.lock` / `sandbar-t26091202-*` 里共 **10,047 个文件**在旧判据（只碰真目录）下**一条也删不到**；本轮补文件族 + 「在用即不动」后已全清。

---

## 6. re-point 的既有断言（逐条）

1. **`server/engine/tests/test_t260926_tmp_fixture_water.py::test_d3_whitelist_discipline_and_malformed_entries`**：样例条目 `nusuyou-integ-run-x.lock` → `nusuyou-scratch-x.lock`。原因：该锁族随第二批并入白名单，若保留原名，判据面 `dirs` 会从 3 变 4、`by_prefix` 多一槽。**intent 不变**（白名单外一律不计 + 畸形逐条点名）；已加注释说明改点。
2. **`server/engine/tests/test_t260926_lane_watchdog.py::test_c4_activity_registered_and_readonly_source_lock`**：该测试对 `inspection_lane_watchdog.py` 装配只读源码锁（禁字面 `subprocess`/`open(`/`Path(`/`os.environ`）。我最初的注释里写了 `dsh-subprocess-*` 字面 → **该锁转红**；**改注释措辞**（改用「dsh 运行时自己的临时 spill 目录 + 指向清扫器 `EXCLUDED_PREFIXES`」，零代码改动）后绿。这是一次「既有闸逼出的措辞修正」，非判据放宽。
3. **`integration/tools/sweep_tmp_fixtures.py` 内部形状（不是既有断言，但影响调用方）**：`scan()` 的 stale/live 元素由 `(name, mtime)` 变为 `FixtureEntry(name, mtime, kind)`；`estimate()` 行新增 `dirs/files/dir_avg_bytes`；摘要行加 `(dirs D / files F)` 与 `locks kept L`；`--prefix ""` 现在被剔除（空前缀=没有前缀闸，随后被空白名单闸拒收）。漂移锁 `test_f1` 的逐字断言（两份前缀元组相等、`DEFAULT_MAX_AGE_H` 同口径、源码含 `--apply`、`APPLY_MIN_AGE_H`、`not a real directory`）**全部仍绿**（实测）。
4. **白名单条目变更**：`venv-compat-root` → `venv-compat-`（超集，只多盖 `venv-compat-home-*`）。除漂移锁的「两处逐字相同」外无测试锚定该键，实测 26 条水位测试全绿。
5. **`server/engine/activities.py` 扫描回执新增 `skipped_count`**（水位判据面同名键，老回执缺键时回落成名单长度——有回归锁 `test_e3`）；`skipped` 名单现在有 40 条上界 + 具名截断行。既有断言（`test_d3`/`test_f3`）零改动且全绿。

---

## 7. 验证与结果（贴原始口径）

| 验证 | 命令 | 结果 |
|---|---|---|
| 引擎全量（我的面） | `server/engine/.venv/bin/python -m pytest server/engine/tests -q \| tail -3` | 一次干净时刻：**2537 passed / 0 failed**（166s）；最终一次：2542 passed / **6 failed**，6 条**全部**来自并行 agent 在飞的 `test_t260927_template_directory_face.py`（模板拓扑面，断言 `_template_topology_fallback`／`_topology_of`），该文件在运行中已被其作者删除，且 `client.py/template_topology.py/ticket.py/workflow.py` 当时是脏的（现已被其提交/revert）。**与本轮改动无关** |
| 我的引擎面定点 | 上面 9 个 import `activities` 的测试文件 + 两个新/改测试文件 | **202 passed** |
| 新回归 | `pytest server/engine/tests/test_t260927_tmp_fixture_family.py -q` | **24 passed** |
| 水位面既有 | `pytest server/engine/tests/test_t260926_tmp_fixture_water.py -q` | **26 passed**（含 re-point 后的 d3） |
| 机械闸 | `python3 integration/lint_tests.py` | **0 error / 0 warn**（09:26 曾出现 1 条 **外来** L7 红：`server/plugins/workbench/tests/project-template-lane-map.mjs` 两处被禁术语不在基线内，09:50 复核已消失；非我面，未触碰） |
| worker 启动面 | `SANDBAR_PROJECTS_DIR=<桩> server/engine/.venv/bin/python server/engine/worker_dryrun.py` | `{"ok": true, "activities": 61, "workflows": 7, "loader_rejections": 0}` |
| 同泳道单飞锁场景 | `python3 integration/t260913-02/sc_integ_run_singleflight.py` | **11 ok / 0 fail**（并发仍被挡住、持有者留痕可读、退出后零残留；`integ-singleflight-*` 目录零残留） |
| venv 兼容场景 | `TMPDIR=<私有> python3 integration/t260907-10/sc_engine_venv_compat.py` | **6 ok / 0 fail**，私有 `$TMPDIR` **零残留**（改前每跑留 10 个目录） |
| t260910-13 两场景 | `TMPDIR=<私有> python3 integration/t260910-13/sc_t260910_13_failure_protocol_{gate,pytest_source}.py` | **50 ok / 0 FAIL**、**15 ok / 0 FAIL**，私有 `$TMPDIR` **零残留** |
| 拆台闸（真 docker） | `integration/tests/test_stage_docker.py` | **ENV_FAIL（诚实环境红，未作产品判定）**：共享锁根内有新鲜外来工程 `stage-console-964fc799`（120s 内有起台活动）→ 与上一轮同因。拆台回收两路改由动态测试 `test_d1/d2/d3` 覆盖（monkeypatch compose + 静态接线锁） |
| 清扫器自证 | `test_c1..c5`（私有根：目录/文件/符号链接/排除族/只读族/活锁） | 全绿（含反证：把排除族挪进白名单后确实会删 → 排除判定真在起作用） |

---

## 8. 残留与建议（下一轮）

1. **删除面不再擅自扩大**：`t26091013-*`（17,254 条）/ `sandbar-*` / `notes-gate-*` / `t260915-09-*` / `t260905-dp-*` / `t09-bump-*` / `sc-t26090510-*` / `q08-*` / `t08-*` / `stage-l1-*` / `t25-t03-*` / `t260901-14-*` 等**未覆盖族**本轮**只归因、未清**（宿主给的白名单之外不碰，一条未删）。它们全在本仓票号命名空间内、生产者可见——建议下一轮授权，或改成**机械派生白名单**（从 `mkdtemp(prefix="…")` 字面自动生成 + 现成 `EXCLUDED_PREFIXES` 兜底），从根上消灭「手抄白名单必然漏变体」这类洞。
2. **L8 基线=泄漏发动机**：69 个文件 / 104 处「有 mkdtemp 零回收动词」仍在豁免名单里（本轮修掉 2 处），其中 `notes-gate-`、`q08-*`、`t08-*`、`sc-t26090510-*`、`stage-l1-*` 就是活水前列。建议按泄漏量排序分批改造（同款 3 行改法）。
3. **跨仓**：`nusuyou-integ-run-*` 的生产者在姊妹仓（本仓已清存量，但新产会在那边继续）。
4. **泳道同步纪律**：见 §5.2；否则任何「改 main 的测试面 helper」都会被在途泳道的旧副本抵消。
5. **水位面语义**：下一期巡检会因 10,496 个 <6h 目录越线（阈值 1000）出 med/high 发现——那是**真实当期水位**（活水速率），不是清扫失败；清扫后「≥6h 存量」这一支已归零，若仍报，报的就是活水。
6. **未做**：不 commit、不开票、未动 `console(3099)`、未删白名单外任何东西（`EXCLUDED_PREFIXES` 一族未删）；真 docker 拆台路径未实跑（ENV_FAIL），改用桩级动态 + 静态锚覆盖。

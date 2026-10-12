# integration/ —— 平台基线集成测试集

工单系统 + 立项单的基线集成测试，是 dev-lane 集成测试机制（t260829-07）的第一批常驻
测试集。**测试清单以 `integration/run_scenarios.py` 的 `SCENARIOS` 清单为准**（manifest
已退役；本文件其余处出现的 manifest 说法是历史残留，正在随票消化——t260904-10）。

## 怎么跑

```bash
# 跑单条
node integration/baselines/ticket-validate.mjs
# 跑全部（与引擎同款执行方式）
python3 integration/run_scenarios.py
```

引擎侧（`run_integration_tests` activity）→ `_run_scenarios` → `verify_lane lane=integ`
消费 `run_scenarios.py` 逐条以 `/bin/sh -c` 执行，cwd=仓根，逐条超时 900s
（`SANDBAR_INTEG_CMD_TIMEOUT_SEC` 可调），exit 0 计通过。

## 执行契约（每条测试一致，t260904-12 三态化——闸内无 SKIP）

- 场景级状态只有 PASS / FAIL / ENV_FAIL；退出码分家：**0=全过；1=有 FAIL（产品红，
  含全部子用例 N/A）；2=有 ENV_FAIL（环境红）**。旧「依赖缺失一律干净 SKIP（exit 0）」（退役）
  与 `SUMMARY pass/skip/fail` 语义**退役**（定稿=notes/discussions/
  260904-charter-injection-invalid-payload.md §7.3：没验成且原因归环境≠通过）。
- 环境缺失（依赖、隔离台、凭据、playwright 等）一律：打印 `ENV_FAIL: <缺什么>` 且
  exit 2——不假红也不假绿，依赖恢复后自动生效。
- N/A 仅给以**系统状态**为条件的子用例（不以测试环境为条件，如「该 feature flag 未开时
  该子用例无对象」），打印 `N/A: <原因>`；**全部子用例 N/A 的场景=产品红 exit 1**（无可验对象
  是场景设计/覆盖问题，修场景而非补环境）。python 侧共享助手=integration/lib_env.py；
  mjs 侧=t260904-05/lib_browser.mjs makeResults()（状态词表 pass/fail/env_fail/na）。
- 场景内部 SUMMARY 行格式 `SUMMARY pass=X fail=Y env_fail=Z na=W`（skip 计数退役）；
  执行器级末行 `SCENARIOS ran=N pass=N fail=N env_fail=N na=N`，汇总与明细**双向净
  才绿**（执行器自校验，谎报=产品红）。
- 池排除旋钮（t260913-03，机械判据=注册表自带的池名，缺省全跑）：每票集测段可声明
  `integration.exclude_pools`（如 `engine,exclusive`），被排除池的条目**不在本轮在册数**
  ——不计 ran/expected（`SCENARIOS ran=` 的 ran=本轮在册，`INTEG_SUMMARY.expected` 同步为
  本轮在册），执行器起跑前与汇总处**两次点名** `本轮跳过池=engine,exclusive（少 N 条）`
  （禁止静默少跑），过滤生效时 `INTEG_SUMMARY` 额外带 `excluded_pools`/`excluded_count`
  （缺省路径零新增行/键）。消费闸门=闸侧显式参数 `apply_skip_pools`（每票段由 dev-lane
  置 true；巡检/手动/缺省一律全跑）。等价 env/CLI 通路：
  `SANDBAR_SCENARIO_EXCLUDE_POOLS=engine,exclusive`、`--exclude-pools engine,exclusive`
  （CLI 优先）。执行器主路径对未知池只响亮点名（`EXCLUDE_POOLS_WARN`，rc 语义不变——
  不能与注入假场景表的既有电池冲突），未知池判红单点在
  `python3 integration/run_scenarios.py --print-pool-assets <池名>`（读真注册表、不跑
  套件，非零=红；池词汇表取模块导入期快照，与注入式 mini 注册表解耦）。
  **例外分支已撤除（宿主管 260914，起因＝KI-089）**：旧口径为「票面 write_set ∩（声明
  `exclude_pools_force_assets` ∪ 执行器机械派生面）非空 → 本票集测段强制全跑」。实测该子用例
  对**全部**在跑票恒命中——写集只要带目录形条目（如 `integration/`）即命中整个测试目录，
  四张在跑票逐票命中 77~78 项，排除声明一次都没生效。现口径：**apply=true（每票段）时
  声明即跳过，不设例外分支**；被跳池只由项目级全量轮（巡检/手动/回放——均不传 apply）覆盖。
  旧命中面仍在回执 `pool_exclude.former_force_assets` 里逐项点名（少跑必须可见），但不再
  据此放行。资产派生面（被排除条目 cmd token ∪ 其 import/require 传递闭包 ∪ `integration/`
  根共享基建面，sc_ 场景文件除外）保留，用于未知池/非法池名单点判红。已知缺口（动态导入、
  非 integration/ 且未声明的资产面、.sh 内容不遍历）登记在 t260913-03 结算，由定期全量轮兜底。
- **台账绿行复用**（t260930-01，治「41.5% 的执行是同一 (场景, 提交) 重复」）：一轮里
  某条场景**可不实跑**，当且仅当结果台账里已有一行**四键全等**的绿行——同 `scenario`
  名、同 `commit`（与被验证树 HEAD **精确相等**：祖先不算、「最近跑过」不算）、同
  `env_fp`、同 `conc_width`，且 `verdict=pass`。被跳过的条目叫**复用**：既不执行也**不
  计入 ran**，完整性不变式升级为 `ran + reused == expected`（复用单独一列，绝不冒充
  新鲜通过）；复用条目不落新账行（不刷新时间戳，绿行自行老化）。**绝不静默**：stdout
  专行 `INTEG_REUSE 复用台账绿行 N 条（同 commit 同环境指纹同宽，未实跑）：<名单>`
  （名单超 20 条截断加 `…（共 N 条）`）、`INTEG_SUMMARY` 的 `reused` 计数、报告 JSON 的
  `reused`/`reused_names`（**全名单**）与本轮三态（启用/禁用/零命中）、`SCENARIOS …`
  行尾追加 ` reused=N`；闸回执另有 `reuse{reused,names,expected,all_reused,accounted}`
  面与全复用轮的 `REUSE_FULL_ROUND` 专行（仲裁不必读执行器 stdout）。**fail-closed 关掉
  全轮复用并打一行具名理由（stderr）**：台账库装不上/读账抛错/主账不可读、工作树脏
  （HEAD 单独描述不了被验证的树）、HEAD 或环境指纹判不出、显式关闸。总开关
  `SANDBAR_LEDGER_REUSE`：`0`/`off`/`false`/`no`（大小写不敏感）=关，其余值（含缺席）=开。
  已知取舍：同提交上**抖动绿**会被如实复用（判据是账里那条绿行，不是运气复现）；换提交/
  脏树/换宽度即自动回退实跑。全复用轮（在册数全为复用）仍出正常绿回执——它说的是
  「这个确切的树已验证过」，不是「又验了一遍」。
- **变更面查询**（t260930-02，治「任何 `server/plugins/` 下的改动都被引擎当共享基座 ⇒
  每轮 438 条全量」）：只读查询面
  `python3 integration/run_scenarios.py --print-surface-plan <改动清单文件|逗号分隔串>`
  ——**不占同泳道单飞锁、不起任何场景、不写台账**，stdout 恰一行 JSON、退出码恒 0
  （判定全在 JSON 里）：`{"mode","reason","surfaces","names","expected","notes"}`。
  改动路径先要**有归属**：命中声明面 `integration/scenario-surfaces.json` 里某个 surface
  的 `paths`（按目录段前缀；每面必须显式声明 `artifacts` 构建产物前缀，无产物面写 `[]`，
  缺键=畸形），或落在 `ignored_paths`（运行产物域）里；两样都不是 ⇒ `mode=full` 并具名
  `reason=unclassified-path:<path>`。同样 full 的还有：改动清单为空、声明面缺席/畸形、
  选择器名不在册、算出的定点名单为空；`integration/**`（场景资产自身）改动一律 full。
  否则 `mode=targeted`，`names` = 四路并集（排序去重、每条都在册）：①命中面 `console=true`
  时**每一条会起产品控制台/舞台的在册场景**（机械派生：cmd 里的仓内文件 + 其 import/require
  静态闭包，路径或正文命中标记集 `lib_stage_console`/`stage_console`/`bench_console`/
  `with_stage.sh`/`stage_docker`；另加 `browser`/`browser-free` 两池整池）；②闭包/ cmd 正文
  引用改动路径、命中面 `paths` 或 `artifacts` 前缀的场景（**改 src 连带改构建产物**，
  只加载产物、不起控制台的场景族靠这半面才不漏）；③`always`（全仓不变量守卫）；④命中面
  `names`。方向恒为**过近似**：多跑允许，漏一条禁止。声明面路径可用
  `SANDBAR_SCENARIO_SURFACES` 覆盖（夹具/电池用；指向不存在的文件=具名 full，不回落默认面）。
- 舞台纪律（t260904-19 定稿：自搭进程舞台退役，双轨并一轨）：一切需要舞台的场景
  经 **integration/stage_docker.py** 单点搭台（同一 compose 文件
  server/docker-compose.test.yml；每场景独立 compose 工程名+端口档，flock 原子
  预留、禁区端口排除、teardown 零残留核验，故障模式取舍表见其头注）。docker 缺席/
  测试镜像缺席/起台不健康=ENV_FAIL（exit 2，文案点名缺什么），不假绿不静默回落
  自搭台（capture-lane 的 --boot-local 是 docker 缺席宿主的人工显式通路，闸内不用）。
  闸级统一入口=verify.yaml integration 段供给声明（supply，接入契约 ②a）——
  t260904-19 起简化为「确保测试台在位」一条：docker 在场+测试镜像在场+共享供给台
  （sandbar-test-integ）健康；该共享台是常驻基建例外（ensure 幂等、闸后不拆），
  「拆台零残留」口径适用对象是场景台。
  t260906-01 仲裁起，浏览器族测试控制台默认供给=**泳道限定台**
  `stage-console-<泳道仓指纹>`（lib_stage_console 自动 ensure/复用，注册表种子随台
  自愈）：每泳道各一台、注册表与 /repo 绑定只归本泳道——根除跨泳道共享台陈旧态
  （别泳道构建上红绿失真实录见 t260906-01 仲裁报告）；`SANDBAR_TEST_CONSOLE` 显式
  指台仍优先。旧 stage-console-shared 若仍在跑属历史遗留，归供给面清理。

  **舞台生命周期旋钮（t260912-02）**：
  - 残台清扫（按主人存在性：compose 工作目录已删 / 泳道不在 git worktree list /
    心跳陈旧超阈；booting 新鲜与在册泳道两阀不碰）：`SANDBAR_STAGE_SWEEP_STALE_S`
    （缺省 600）、`SANDBAR_STAGE_SWEEP_BUDGET_S`（缺省 30）；清理挂两处——全量闸
    开跑前 + 每台起台时（`SANDBAR_STAGE_SWEEP=off|0` 显式关闭，响亮
    STAGE_SWEEP_WARN 不静默）；手工入口 `python3 integration/stage_docker.py sweep
    [--dry-run]`（判拆点名，失败非零上抛）。
  - 起台保险丝：`SANDBAR_STAGE_MAX_STAGES` **缺省 100**（原 12 排队闸已退役——
    全机共用名额只制造假拥堵；保险丝只在失控循环刹停，触闸红不含「满员」字样，
    瞬态白名单不会重试放大）。
  - 受管网段：起台建网显式指定子网（`10.213.0.0/16` 切 /24，尾槽
    `10.213.255.0/24` 保留给手工直跑 compose 的缺省路径），爆发建网不再向 docker
    分配器申请库存（fully subnetted 病灶根治）。**手工并行注意**：两个手工台同起
    会撞保留槽——手工并行请各自显式传 `SANDBAR_TEST_SUBNET=10.213.x.0/24`
    （x 不取保留尾槽）；与宿主 VPN/局域网撞号时 `SANDBAR_STAGE_NET_BASE` 重指
    整张表（畸形=usage 红）。docs/testing-guide.md 的手工 compose 段落有同款
    漂移（docs/ 不在票写集），随本票 merge 一并核对。
  - 档位带基址：`SANDBAR_STAGE_BAND_BASE`（缺省 21000 语义不变）——多泳道共用
    一台宿主时兄弟泳道真台常驻 21000 窗，L1 电池（需要全净窗）可重指空闲窗跑；
    畸形或撞生产/缺省台窗=usage 红。

  **舞台生命周期旋钮（t260915-18 续）：锚身份 / 孤儿清扫半径 / 台面清点 / 引擎单所有者**：
  - 锚身份令牌（两段判活）：起台时 hold 分支在租约记 `anchor_token`（ps lstart
    逐字串）——「主人已亡但 hold 仍续心跳」的 pid 重用形态由 sweep crit_iv 判拆
    （当日 38h 老台疑似形态的判据面）；令牌探针不可得（无 ps 平台）=回落纯
    pid 判定，不引入新单点。
  - 孤儿容器清扫（「本管域容器而无租约文件」形态，KI-077 当日 37 只实证）：
    `SANDBAR_STAGE_SWEEP_ORPHANS`（`sweep` CLI 缺省开；**up/ensure 挂点缺省关**
    ——无半径清场=无授权真拆宿主存量，260915 实爆教训）、
    `SANDBAR_STAGE_ORPHAN_MIN_AGE_S`（缺省 1800s，第二道保守阀）、
    `SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX`（半径前缀：设置后 condemned 仅限命中
    前缀的工程名——孤儿是全机可见面，无半径即无授权清场）。判定窗内租约出现
    （新起台者进场）自动让位；域外容器（working_dir 出仓且非 `sandbar-baseline-`
    基线树）只列不判。
  - 台面清点（只读）：`python3 integration/stage_docker.py inventory`——回执
    JSON：capacity（containers/projects/leases/orphans/max_stages/
    out_of_domain_projects）+ stages 逐台（project/services/working_dir/age_s/
    holder_ticket=attempt 票号或 unknown/holder_pid/anchor_pid/heartbeat_age_s）。
    起台挂 `SANDBAR_STAGE_TICKET=<票号>/gen<n>` 即进租约（attempt→台名映射，
    排障不再猜哈希名）。巡检面 scan_face=stage（inspection.yaml
    `stage-capacity` 占位实例）复用同一回执开票。
  - 引擎单所有者（UI 截图台）：起/拆所有权归引擎（server/engine/
    ui_capture_stage.py `run_capture_stage`）——capture-lane 只当无拆权消费者
    （--stage-json）；起台/拆台/截图三段超时各自有帽：up
    `SANDBAR_CAPTURE_STAGE_UP_CAP_S`（缺省 180s）、down
    `SANDBAR_CAPTURE_STAGE_DOWN_CAP_S`（缺省 150s）、截图面由引擎
    UI_CAPTURE_TIMEOUT_SEC 帽。四条终态路径（成功/超时/取消/异常）全部显式
    down；拆台失败响亮（绝不静默）；capture 报「外部舞台已死」=拆死台冷重试
    一次再降级。C2 语义收紧：up 成功后 capture 失败（非死台）=直红不降级。

  **批级共享台（t260921-06，宿主令 260921「整机一个不行，顶多一次集成测试用一个
  temporal 容器」）**：共享粒度=**批**（一次跑批/一票集测段），批内按**命名空间**
  隔离——run_scenarios.main() 对含消费者的轮恰预起 1 个 `kind=batch` 台
  （工程名 `batch-<runid8>-<pwdhash8>`，+1 卷 +1 网），批终 down 全灭零残留
  （批间隔离不变，不得退化为整机共享：`--kind batch` 与 `--keep` 互斥=CLI 闸）。
  消费缝两条、env 键 `SANDBAR_STAGE_BATCH`（=批台工程名，仅注入给分类器命中的
  条目子进程）：
  - `lib_gate.require_stage/stage_down`（约 30 场景族唯一缝）：env 在场=ns-acquire
    申请本场景命名空间（零容器开销）/收尾 ns-drop，绝不 down 批台；env 缺席=
    逐场景独立台行为逐字保留。
  - `with_stage.sh`：env 在场=ns-acquire→跑→ns-drop（绝不 ensure/down）；env
    缺席=ensure→跑→down 现行逐字。
  分类器（候选 A）=`pool ∈ {engine, exclusive} ∧ entry ∉ 例外清单`
  （integration/batch_stage_exceptions.json，机器真源；每票集测段
  `exclude_pools=engine,exclusive` ⇒ 两族全不在册 ⇒ 零预起零注入=最高频路径零
  回归）。例外通道显式化（要求4）：清单行 `{entry, pool, project_pattern, reason,
  evidence}` 五键、entry/pool 机械取自注册表（生成器
  `integration/t260921-06/gen_batch_stage_exceptions.py` 落盘+自检，project_pattern
  语义=本泳道 compose 工程名前缀，含重试改名面）；新增消费缝使用者若落在清单/
  两池之外会被静态看守 `t260921-06-batch-manifest-contract`（ro，每票段必跑）
  点红。不假绿（要求5）：ns 注册失败/批台不在位=ENV_FAIL exit 2 点名（预起失败=
  整轮 exit 2 快速红，零场景开跑），绝不静默回落「没跑」；ns-drop 失败=响亮留痕+
  租约账面 `drop_failed` 打标（S3）不拦收口，批终 down -v 全灭兜底。窗口形态/
  隔离/反用例/信号收口四段由 `t260921-06-batch-runner-form`（engine）、
  `t260921-06-batch-ns-isolation`（engine）、`t260921-06-batch-seam-regression`
  （engine）执法。

## worker 旧码纪律（worker 启动时一次性载入代码）

worker 进程启动那一刻把引擎代码载入内存，此后泳道/main 再落新码**不会刷新在跑 worker**——
「代码落地」≠「行为生效」。症状画像（排障先对号）：①新信号送达不生效——回执 `ok /
delivered=true` 但票面字段不动、`refused` 也空；②旧进程 import 磁盘上新增的名字失败并**静默
降级**（KI-081 实录 `cannot import name 'AUTH_KINDS' from 'shared'`）。凡「一切都成功但没反应」，
先怀疑在跑 worker 持旧码。

实证两条：

- **260922**（dsh-upgrade epic，KI-081 同族）：dsh 0.1.5-rc.2 钉入本项目后，升级生效面
  以 worker 重启为准——在跑 worker 仍持旧码（KI-081 的 260913 对照坐实机理：同操作在
  当天新起 worker 的票上生效、旧 worker 票上送达不生效；重启后连排队中被丢的信号都补处理）。
- **260923**（本冒烟票 t260923-06）：在 0.1.5-rc.2 已钉入的窗口内全链走通，确认改 worker
  侧判定必须重启在跑 worker 方可见效。

操作纪律：改 worker 侧判定（信号载荷、判定位、import 面）**必须重启在跑 worker**；重启只走
**控制台 keepalive 补拉**（机理与处置锚=KI-081：`reap_ticket_worker`（SIGTERM）→
`spawn_ticket_worker`，或控制台 ensure 补拉）；**受限会话里手工 spawn 不可作为重启手段**——
手工起的进程继承当前会话沙箱（写不了主库 `.git` 等），不是引擎语义下的合法 worker。

## JSON registries: the canonical write path (t261009-51)

The shared JSON registries under `integration/` — `test_anchors.json`,
`known-red-baseline.json`, `batch_stage_exceptions.json` (the declared set lives in
`integration/lib_registry.py`) — have ONE canonical serialization: UTF-8,
`ensure_ascii=False`, `indent=2`, insertion key order, one trailing newline. Do not
append to them by hand-rolling `json.dumps`: import the single entry point
`integration/lib_registry.py` and call `write_registry(path, obj)`; it emits the
canonical bytes. The known failure modes of this style are declared in that module's
docstring (a lone-surrogate payload raises loudly — never silently downgrade to
`ensure_ascii=True`; family precedent `lib_emit_anchor.py`).

`lint_tests.py` L23 byte-compares each declared registry against its canonical
re-serialization and names the first differing line when the style drifts. It only
reports — it never rewrites; fix a red by running the canonical writer. Measured
fault behind this rule (KI-01M4HD396VNTTAY20CH0681N0Q): the anchors file flipped
1-space ↔ 2-space between writers, so a three-entry append produced a 9082-line diff
with zero semantic change.

## 环境前提

Node >=22.18（type-stripping 直跑，全部测试）；其余按条目按需探测：
python3（stdlib）、docker + 测试镜像 `test-temporal:cli-1.8.3`（舞台场景，
t260904-19 起必需；重建=`sh server/build-test-temporal.sh`）、temporalio SDK
（优先 `server/engine/.venv/bin/python`）、temporal CLI
（`server/engine/bin/temporal` 或 PATH，供给台 SA 注册与 temporal-only
消费面需要）、playwright-core（browser 族，t260912-01 起统一四路口径：
`SANDBAR_PLAYWRIGHT_PATH` → `SANDBAR_PLAYWRIGHT_MODULE`（旧名兜底同语义）→
裸导入 → 本树 `server/ui-check` → 主树 `server/ui-check`（主树经
`lib_pw_deps.mjs` mainRoot()=git rev-parse --git-common-dir 位置无关解析，
`SANDBAR_MAIN_ROOT` 可显式覆盖；泳道无 node_modules 时由主树供给）。
探测全空=ENV_FAIL，文案点名全部候选面实路径——不做「依赖缺失/布局算错」
式归因（t260912-01：旧 `../..` 位置算术在非 `<主仓>/.lane/<票>` 布局指错
目录却谎报依赖缺失，已随票退役，守卫=t260912-01-pw-path-resolution）。

## 安全红线（测试自己先遵守）

- `localhost:3099`（生产控制台）不碰；生产 Temporal 只读（仅 `operator namespace describe`），
  8233 Web UI 与一切写命令不碰。
- **建票类测试永远指向测试环境**：显式 `SANDBAR_TARGET_HOST=127.0.0.1:17233` +
  `SANDBAR_NAMESPACE=sandbar-test`；内置硬断言——该变量未显式设置或精确等于生产缺省
  `127.0.0.1:7233` 时拒绝执行（宁可 FAIL/ENV_FAIL 自家测试，绝不静默连生产）。

## 已知限制（覆盖诚实声明，非哑 guard）

- retention 条依赖 temporal CLI——`bin/temporal` 是未跟踪本机工件（worktree/新 clone 无），
  泳道内可能恒 ENV_FAIL（exit 2）；CLI 进 PATH 即恢复真实覆盖。
- ticket-validate 环境半依赖 temporalio SDK（随主 checkout `.venv` 走），worktree 内常 ENV_FAIL（exit 2）；
  纯函数半零依赖恒跑。
- ticket-empty-writeset-declare（t260901-01）与 ticket-validate 的分工：真实建票的
  **正路径**（空写集+声明 → 建票成功）归 ticket-validate env half，本条不重复；本条守
  **桥路四层**（工具 schema/payload、host 透传、弹层纯函数、预跑建议 write_set 透传）
  与 **负路径**（空写集无声明 → 连接前拒收、双出路文案）。SDK 探测在 worktree 泳道会
  回落到主 checkout `.venv`（经 `git rev-parse --git-common-dir` 解析），比 ticket-validate
  的探测多一档，泳道内 D 段可真实覆盖；E 段仍需显式 `SANDBAR_TARGET_HOST`（写护栏不变）。
- ticket-lifecycle（t260831-04 落地， stub 大脑端到端）：**t260904-12 起移出闸清单（SCENARIOS
  移册，非 SKIP 非豁免）**——worker 机械步内恒触发嵌套护栏（SANDBAR_TASK_QUEUE 特征检测，
  防无界自递归：净化半必 clone fixture/起 worker/起票，递归面无法否定），属设计性环境红、
  闸内不可达 PASS；移册依据=定稿 §7.3「真跑不进闸的（红线禁区/破坏性）不进闸清单」+宿主令
  exit=0 目标；真实覆盖承接=主库人工清单（t260903-09 主库跑生效）。**口径逆转链**（防历史
  反复无据可查）：t260831-03 曾以死条目为由不登记 → t260831-04 按工单要求翻回登记（见下） →
  本次三态化后依定稿条款再移册。原文记录保留如下：在引擎机械步内
  恒 ENV_FAIL（exit 2）：`_run_manifest` 继承 worker 环境，条目检测到 `SANDBAR_TASK_QUEUE` /
  `SANDBAR_WATCH_WORKFLOW`（工单专属 worker 特征）即判「泳道内机械跑」报 ENV_FAIL——否则会
  clone fixture、再起 worker、再起 integ-e2e- 票，无界自递归。这是嵌套安全护栏的正确行为，
  不是死条目：真实覆盖在顶层人工跑（两变量皆无时执行五场景）。t260831-03 壳文件曾以
  「避免恒 SKIP 死条目」为由不登记，t260831-04 按工单要求取登记并在此显性记录取舍。
- ticket-lifecycle 的场景 D 与工单正文的偏差在案：正文要「多次 merge reject 构造超限」，
  引擎 merge 人门 reject 无轮次计数（dev_lane.py merge 段），构不出超限；场景改覆盖真实
  存在的同类上限（stub 仲裁 summary 缺 `verdict=`，3 次格式纠正轮 → blocked）并复活收口。
  merge reject 无计数属引擎发现，另开票处理。
- ~~lane-parallel-dom（t260901-09，泳道图并行分叉 DOM 级双边同亮断言）~~ **261001 已删**
  （宿主令：删场景与注册表条目）。删除理由与代价在案：功能断言 P1–P5 长期绿、红只在
  P6 卫生面（页面资源 `ERR_INCOMPLETE_CHUNKED_ENCODING`，与台供给/负载面同签名），
  判定力已由 `t260903-04-parallel-ui-truth`（真源优先契约，含双显真值表）与其
  `t260903-04-client-bundle-sync`（S0 构建契约同面）分担；**代价=真浏览器渲染层的
  双边同亮断言此后无场景，算法/真值层仍被覆盖**。同类 S0/S1 两层结构的先例仍见
  `sc_evidence_lightbox_dom.mjs` / `sc_multi_tab_coexistence.mjs`。
- capture-chat-e2e / capture-chat-active（t260901-03）自 t260901-09 起补泳道 worker 递归
  护栏（与 ticket-lifecycle 同款 SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW 探测）：两条的
  真实覆盖靠 boot 隔离台 + 真模型种子链路 + capture-lane 只拍**本次重建**的 bundle
  （陈旧 build 拒跑是防证据造假的设计行为）——非 UI 票的泳道不重建 bundle，此前提在
  泳道机械跑环境天然不满足，故一律 ENV_FAIL（exit 2，不再 exit 0 假绿；e2e 整 entry 8 场景环境红；active 只环境红
  C1 重链，U1-U3/C2 纯函数半照跑）；顶层人工/隔离台跑不受影响，携带真实覆盖。
  t260901-09 前缺口实证：非 UI 票泳道机械跑 2 败均源于 capture-lane 陈旧拒跑（exit 2），
  与本票 diff 无关（失败文件本票零改动，git diff 为空）。
- capture-chat-e2e（t260901-03）依赖**真模型凭据**（capture-lane 从用户 DSH_HOME 拷
  `.credentials.yaml`，种子消息走真模型链路）：凭据缺失的机器上整条 ENV_FAIL（exit 2，
  原因打 stdout），有凭据无网络/模型不可达时才 FAIL——与 capture 的「loud 非零、不静默
  降级」设计同源。每条隔离台 2 次真模型调用，有成本，勿高频机械重跑。
- capture-redline-gate（t260901-03）全 hermetic（本地 mock 控制台，零 Docker 零真台）；
  R2（造数端点回空 cwd 须快速显式失败）是**随本票修复才存在的行为**，修复前跑本条
  R2 恒 FAIL——这是验收棒，不是坏条目。
- capture-chat-active（t260901-03，developer 自产基线）与 capture-chat-e2e 的分工：
  前者 U1-U3 纯函数防呆任何环境恒跑 + C1 全链与 C2 红线；后者黑盒断言更严
  （7 视图逐张非空白、逐视图零失败、隔离台端口退出后拒连的孤儿进程检查）且
  真模型凭据缺失时整条约 ENV_FAIL（exit 2）。两条 C1 都跑真模型，勿高频机械重跑。
- t260901-03 gen3 对齐 main 后，capture-chat-e2e 追加两条验收棒：A4 锚断言按
  main 版隔离台路径（「+ 新建会话」+ 种子消息）判读、chat 截图不得被准入模态
  遮挡；A7 全程不得有裸 TypeError 冒泡（种子链异常必须过报错包装）——对齐前
  的泳道实现曾 run-to-run 违反后者，此条即其回归闸。
- ui-evidence-failure-retention（t260901-02）依赖 temporalio SDK（import agent_activities
  直调 activity），SDK 不可用的环境恒 ENV_FAIL（exit 2）——与 ticket-validate 的环境半依赖同款取舍；
  两条 capture-lane 基线（capture-lane-preset / ui-evidence-failure-retention）均不 boot
  控制台、不装浏览器，3099 全程零接触（后者显式把 SANDBAR_CONSOLE_URL 钉死死端口并内置
  红线自检断言）。隔离台端到端实拍（boot 控制台+浏览器出图）是重环境路径，不进 manifest：
  依赖真机凭据与 `$HOME/.dsh` preset 实体，泛化跑只会恒 ENV_FAIL，该口径由
  `node server/ui-check/capture-lane.mjs --selftest` 与 implement 段端到端验收步骤承担。
- t260915-12 的场景登记是「同票双场景不同层」的参照样：`t260915-12-cross-project-gate`
  （离线源码锁+纯函数重放，无 docker/网络依赖恒可跑）与 `t260915-12-gate-real-chain`
  （真链路行为面，docker 台）——同一契约的两半，intent 分工写在各自登记行与场景 docstring，
  后续票照此分半时先读这两条。

## 基线设计红线（审查标准，integration 岗位维护）

- **写集判定不归基线管。** 任何基线不得用 `git status` 之类的全仓库状态去断言「某工单
  只改了它声明的文件」。写集白名单由 `verify_lane code` 按**当前工单的 write_set** 语境
  判定，语境天然正确；而基线跑在泳道根，看到的是一个可能被多个活动工单共享的 worktree，
  无法把脏文件归因给哪个工单——worker 代落盘机制下别的工单合法写集本来就处于未提交态。
  在这种视角下，全局写集断言只有两种下场：误伤邻居（假性 FAIL 阻塞仲裁），或者降级成
  「有 offender 即 SKIP」的恒不判定（连自家泳道也不再 FAIL，检查名存实亡）。
- **新增/修改基线时的自检**：这条断言在「泳道被别的活动工单复用」时还成立吗？不成立
  就改到按正确语境判定的层（如 verify_lane），或者删掉，禁止用 SKIP 降级把矛盾糊过去。
- **判例**：t260831-06（全局写集断言把邻票合法写集判成 offender，假性 FAIL 阻塞仲裁）与
  t260831-08（把同一断言降级为 offenders 非空即 SKIP，自家泳道也不再判定）是同一类错误的
  两个反面。两案一致的打回口径：基线只保留 repo 只读的内容断言（文档结构、契约条款等），
  纪律类判定一律下沉 verify_lane。
- **判例补充（t260901-19 仲裁修复）**：t260901-10/t260901-17 的 t06_write_set.sh 曾漏网——
  在本票（t260901-19）泳道机械跑时把本票写集内的 shared.py 合法改动判成「越界」致 2 败。
  已按 t260901-07/check.sh t05 同款泳道守卫修复（非本票泳道目录名即 SKIP），main 侧断言体
  保留。同类写集纪律检查新增时必须自带泳道守卫，不再事后补。
- **判例（t260901-15 仲裁，第三案）**：`t07-t260901-07-no-code-touched` 与
  `t10-t260901-10-write-set` 两条全局 git 状态断言（`git status --porcelain` /
  `git ls-files --others` / 对 HEAD 的 diff）在共享泳道把在飞工单 t260901-15 的合法写集
  （写集明含 `server/plugins/workbench/`，且已过 verify_lane 白名单）判成越界，2 败阻塞仲裁。
  t260901-11 对前者的「代码目录否定清单」修订仍残留同一病灶（工作区/提交全局视角无法把
  改动归因给哪个工单）。按既定打回口径整段移除（check.sh 留碑注，t06 脚本删除，manifest
  除名 2 条，53→51）：写集纪律由 verify_lane 按当前工单 write_set 精判承接
  （merge_check payload 带 write_set，见 verify-lane-config 基线），基线侧零净损失。

## 后续工单的 design 步如何增补测试

1. 新建 `integration/baselines/<name>.mjs`（Node >=22.18 直跑，头部注释写清 intent 与
   high-level steps，代码与注释用英文）；环境依赖按上文执行契约做 precheck，桩用
   `SANDBAR_EPIC_NEXT_STUB` / `SANDBAR_AGENT_STUB` / `SANDBAR_SUGGEST_STUB`（零真模型）；
   会写 Temporal 的测试必须过「安全红线」写护栏。
2. `manifest.json` 追加 `{"name": "<name>", "cmd": "node integration/baselines/<name>.mjs"}`。
   注：逐条 cmd 是引擎消费契约的硬性字段（shared.py:203，缺 cmd 的条目直接判败），
   无法省成纯清单；格式统一为 `node integration/baselines/<name>.mjs` 即是本测试集的
   通用执行入口。

## 第 5 组（ticket-lifecycle）—— t260831-04 已落地

本组不再是空壳：`baselines/sc_ticket_lifecycle.mjs`（总入口，内部分场景；文件名勘误
t260917-07——旧文档写 `ticket-lifecycle.mjs` 系笔误，树上从未存在该文件）+
`baselines/ticket-lifecycle-scenes.mjs`（脚手架与场景库）。链路全真：Docker 测试 Temporal
（17233/sandbar-test，不可达则幂等 `docker compose up -d`，仍不可用 ENV_FAIL exit 2）+ 每票专属
worker（`SANDBAR_TASK_QUEUE`/`SANDBAR_WATCH_WORKFLOW`，WATCH 收口自退 + 看门狗 kill）+ 真实
引擎链（prepare_workspace→create_plan⇄review_plan→implement∥design_integration_tests→
run_integration_tests→arbitrate→acceptance_walkthrough→merge_check→merge 人门→suggest_next
→closed）。桩的只有 agent 大脑：worker 置 `SANDBAR_AGENT_STUB=1` + `SANDBAR_SUGGEST_STUB=ok`。

隔离要点（引擎 merge 落账目标是 worker 侧 REPO_ROOT 当前分支、无视 base_ref）：
每轮运行先 `git clone --branch main --single-branch` 本地主库到临时 fixture 仓，worker 从
fixture 内的 engine 启动（REPO_ROOT=fixture）——泳道 worktree、settle、merge、拆树
清理全部发生在 fixture 内，真仓零接触。fixture 内 app/node_modules 与 engine/.venv
软链回主 checkout，泳道内 verify_lane 才可绿。

确定性机制：stub 大脑的 arbitrate summary 天然缺 `verdict=`（3 次格式轮即 blocked，场景 D
的上限来源）；场景 A/B/C/E 在票机械跑 run_integration_tests 期间向泳道预置
`.suyou/stage_arbitrate_gen<N>.json`（summary 含 verdict=pass），走引擎结果文件幂等缓存  # naming-compat
确定性放行。gen 取「泳道已有文件最大 N+1」，不静态推算。

## verify-lane-config（t260901-08）—— verify 道配置驱动回归闸

`baselines/verify-lane-config.mjs`，全 hermetic（git + python3 stdlib，fixture 全在平台
临时目录，零 Docker 零网络零真台）。守的是 sandbar 契约②/②a 的三态关闭语义在 verify_lane
code 道的落地：缺失=道关闭（green 可见非静默）、畸形/版本不支持=fail-closed 红、合法配置
下白名单按 write_allow（或工单 write_set 精判）装配、合并闸口径（require_base=true）空 base
判红、检查项只随声明出现。**合并闸判据口径（t260901-08 收口定稿）**：精判=工单
write_set 逐文件上限（merge_check payload 接线 `write_set: list(args.write_set)`，D6/D6b
fixture 锁定；该 fixture 同时守 verify_lane `has_ws` 精判分支不退化——payload 带
write_set 而 verify_lane 丢了分支会静默退化回粗判据）；verify.yaml write_allow **仅兜
手动/未带写集调用**，不再是合并闸判据（07/08 越界事故在粗判据下漏网的判例）。
**写集判定不归本基线管**（见上文基线设计红线）——所有 fixture
都是自建临时仓，不对真实泳道做任何全局写集断言。

已知限制（诚实声明，非哑 guard）：

- F2/F3（merge_check 调 verify_lane 必须带 base + require_base 的静态回归棒）曾为
  **PENDING 有声跳过**（改动点 `agent_activities.py` 当时不在派单写集内，补丁落在
  `integration/patches/merge-check-verify-base.patch` 待扩写集）——t260901-08 收口轮
  扩写集经总管拍板、补丁已真落盘（merge_check payload 带 `{lane, path, base,
  require_base:True, write_set}`），本条**已转硬断言**，基线内不许再有 SKIP 分支：payload
  回归（丢 base/require_base/write_set）直接 FAIL。判据本身（require_base × 空 base 判红）
  由 E 组在 verify_lane 侧真实覆盖。
- **合并闸判据口径（收口轮定稿）**：精判=工单 write_set 逐文件上限（merge_check payload
  接线 `write_set`，verify_lane `'write_set' in args` 优先）；`verify.yaml write_allow`
  **仅兜手动/未带写集调用**，不是合并闸判据——粗判据下 `server/` 前缀全放行，t260901-07/08
  两起越界事故在该口径下依然漏网，精判接线才是本票题眼（D6/D6b fixture 锁定）。

## multi-tab-coexistence（t260901-15）—— 工单台多页签共存黑盒基线

> **已退役（261002 宿主令）**：场景文件已删，留痕与四问（守什么/为什么退/
> 移交/认赔）见 `integration/retired-scenarios.md`。以下正文仅存档供复活参考。

`baselines/multi-tab-coexistence.mjs`。用户场景驱动：管理台常开多页签，三缺陷修复
（①页签互见在看提示；②写操作交叉失效；③不可见页签暂停轮询）+「点 13 详情跳回 11」
竞态收口。两层结构（同 sc_evidence_lightbox_dom 先例）：S0 build-contract 纯 node 恒跑
（lib 双产物同步 + 多页签接线锚点在产物内；implement 前按设计恒红——验收棒）；
S1 真浏览器双（多）页签场景（T1 互见/T2 写交叉失效+写守门 confirm/T3 隐藏零轮询/
T4 过期在途响应不得覆盖抽屉/T5 恶意页签流量与 BC 缺席兜底/T6 关页签 viewer 摘除/
T7 零 pageerror），数据在 `/sandbar-workbench/api/wf/tickets*` 边界 page.route() 打桩，
fixture detail 全页签共享（D 页签写、B 页签下一次拉取即见新数据），请求计数器按页签
归属（T3 归属断言的前提）。不建票、不 boot 控制台、3099 零接触，泳道机械跑无递归风险。

已知限制（诚实声明，非哑 guard）：

- T3 依赖浏览器对后台页签真实报 `visibilityState=hidden`：headless 环境若不报，先尝
  试 CDP `Page.setWebLifecycleState`，仍不可达则该场景**ENV_FAIL（exit 2）**（其余场景照跑）。
- 33s 零请求窗口覆盖 5s/5s/8s/30s 全部轮询周期；窗口内任何一次泄漏即 FAIL，不抽样。
- S1 覆盖的是**测试控制台（3199）所服务的 bundle**：隔离台若未随泳道产物重建，T1–T6
  会对陈旧 bundle 报 FAIL（有声暴露，非静默）；泳道产物正确性由 S0 锚点先行把守。
- T5b 的 localStorage 污染限定 presence 相关窄键名，避免波及控制台自身偏好键误伤
  T7 卫生闸；若实现选了键名以外的命名，该子断言退化为只验广播畸形流量（计数打 stdout，
  人审可见）。

## lane-done-terminal-states（t260901-08 追加范围）—— 终态留痕优先于计数启发式回归闸

`baselines/lane-done-terminal-states.mjs`，黑盒消费 `lane-states.ts` 纯模块（同
lane-parallel-states 形态），以 t260901-07 真实时间线形态（merge-conflict-loop：
仲裁内部重跑复用结果文件不增 gen、merge_check 脚本门三进段只落 checks 不落
results）作案底。守的契约：引擎 `dev_lane._finish` 落 done 终态条目后，重验循环
后的 run_integration_tests/merge_check 不得再误亮「进行中」（T1）；存量 closed
票短路不破（T2）；旧票无 done 条目回落现有 inRun 启发式、原行为锁定（T3，存量
数据不追改的拍板口径）；rework 重进步回 running（T4）；畸形 timeline 条目防呆
（T5）。消费方审计结论（review 第 3 轮代做）：UI STATE_LABEL 已含 done
（index.tsx:862），其余 timeline 消费方（rework 横幅/blocked 查找/enters 计数/
host agent-usage）均按具体 state 过滤或只数 running，不受新增 done 条目影响。

## 第 7 组（t260901-19）—— token 节流三刀的回归闸（cap 作用域 / arb 尾保 / precache 短路 / cache_probe）

`integration/t260901-19/` 四条，方案=create_plan v3（三轮审读后通过）。纯 python3（stdlib），
`PY` 回落链见 manifest（t03 需 temporalio SDK，缺失 ENV_FAIL exit 2，真覆盖在有 venv 的顶层环境）。

- **t19-cap-previous-context**（t01）：`shared.cap_previous_context` 作用域契约——六类
  「- 上次*」历史行整行（含前缀）截 800+「…（截断）」、「- 打回原因：」行与一切未识别行
  逐字透传（含 arb_ctx 单行 JSON）、未识别行 2 万硬顶、封顶类合计 4000 尾部丢弃+尾注、
  畸形输入（None/非字符串/bytes/空白）归一空串；`build_stage_prompt` 接线后打回块与
  机器负载在 prompt 里逐字可查。这是 review 第 2 轮打回项 1（cap 作用域过宽会掏空仲裁
  输入/截断打回意见）的常驻防回归闸。
- **t19-arb-ctx-tail-budget**（t02）：dev_lane arb_ctx 组装的静态回归棒——预算 6000→4000
  且必须尾保（`[-4000:]`，失败明细 details 在 JSON 尾部，头切会挤掉）。verify-lane-config
  F2/F3 同款「验收棒」判例：改回头切即 FAIL。
- **t19-suggest-precache-shortcut**（t03）：`suggest_next` precache 命中短路全套——
  次序 rfile→stub→短路→spawn、ok/done 双形态命中零 spawn 且 evidence 带 `precache-hit`、
  state_key 不匹配/缓存损坏/缺字段/模板幻觉/failed 形态/空 epic 一律落回 spawn、stub 通道
  最优先、rfile 幂等回归、测试卫生（合成 epic code `t-itest19-*` + teardown，仓库
  `.suyou/epic-next/` 无残留）。spawn 面用 monkeypatch 哨兵封死——实现有洞时表现为  # naming-compat
  「记录到 spawn 尝试」，绝不会真拉起 agent 进程。
- **t19-cache-probe**（t04）：`integration/cache_probe.py` 工具契约——zstd 缺失可读报错
  exit(2)、位置参数注入扫描根、空根 exit 0、畸形/半截行跳过且计数、命中率
  cache_read/(input+cache_read) 口径（fixture 900/1000=90.0%）、只读不落盘。
  fixture 半区依赖系统 zstd，缺失 ENV_FAIL exit 2。

已知限制：t03 泳道机械跑恒 ENV_FAIL（exit 2；temporalio SDK 不在泳道，走 venv 回落链声明），真实覆盖
在带 `.venv` 的顶层/主 checkout 环境跑——与 ui-evidence-failure-retention 同款环境取舍。

## 第 8 组（t260901-20）—— metrics M1a 读侧聚合（门面/缓存/双前门）

`integration/t260901-20/` 五用例 + 聚合入口，manifest 单条目
`t260901-20-metrics-m1a` → `t06_all.mjs`（与 t14 同款聚合执行形制）。全 hermetic
（mkdtemp fixture + env 钩子 SANDBAR_METRICS_DIR/SANDBAR_PROJECTS_DIR/SANDBAR_EPICS_DIR，
零 Docker 零真台零 3099），泳道机械跑可执行。黑盒面：HTTP 进程内 handler
（t260901-14/t06 同款 mock harness，type-stripping import node.ts）+ CLI 子进程。

- **t01_gate_shape**：exact 路由在位；4xx 防穿矩阵（view 缺省/非法、window 非法、
  同名重复参数、epic 非法字符/超长、project 未知、隔离条目带「隔离」定位）；
  200 信封逐字段对契约块 2（kpis 恒冻结四字段、cache.status 枚举、ChartSpec 形状、
  四枚举 view 全绿）；并发 3 路同请求形状一致。
- **t02_cache_lifecycle**：缓存目录不可写→200 直算不 5xx（root 下为系统态条件子用例，N/A 口径）；
  legacy SANDBAR_PROJECTS_YAML 模式缓存禁用零落盘；缓存目录整体 rm 后惰性重建 200；
  缓存记录 block-3 键集全等 + 二次请求 hit（无票环境为系统态条件子用例，N/A 口径）。
- **t03_health_degrade**：view=health 回冻结信封不设视图变体键；本机独立探测
  7233，不可达时 200+reason 人话必带（不可达=ENV_FAIL 口径）；health 请求零缓存写入。
- **t04_cli_door**：argv 畸形（缺参/坏 JSON/非对象/非法值）exit 2+stderr 人话；
  合法请求 exit 0 出契约信封。
- **t05_dual_door**：同请求 HTTP vs CLI，剔 generated_at/cache.computed_at 后
  UTF-8 字节全量比对（契约块 2 比较面，M3 基线锁先行落地）。

已知限制（诚实声明，非哑 guard）：

- **数字级正确性不在本集**：泳道无 Temporal，聚合数字（窗口/token/LOC）只能以
  降级形状覆盖；数字对账=developer 单测（方案步 1/2）+ M3 三票人工核对。t02 末段
  与 t05 在有票环境（Docker 测试台/真票）自动升级为数据级断言，无票时为系统态条件子用例（N/A 口径）。
- **双前门一致基线带预热约定（acceptance P1 定稿）**：cache.status 按契约块 2 字面
  语义（惰性生成=computed / 命中=hit，实现 gen1 已回归字面），冷缓存下两门天然
  一 computed 一 hit——那是契约语义本身。双门比对基线在两门前预热缓存（同请求先跑
  一次），两门同缓存状态下剔两时钟字段后字节全量比对；status 不进剔除清单，比较面
  不削。M3 基线按同约定执行。
- **双前门一致基线在降级数据上锁定形状一致性**：真实数字双门一致由 M3 基线按同
  口径复验；本集保证的是比较面机制（剔两时钟字段后字节全量）先行在案。
- **单元层五用例（implement 补齐，t01_params_cache / t02_aggregate / t03_views_e2e /
  t04_cli / t05_dual_door，走 SANDBAR_METRICS_STUB 缝全离线秒级）**：聚合口径数字级
  锁（窗口切分/末窗封口/human_wait/by_round、chunk 镜像不翻倍/cacheRead 单列/
  模型归因/多角色加总、numstat 分列 binary 行、git 失败软降级）、缓存语义（坏 JSON
  作废/engine_version 失配重算/frozen 跳 delivery/legacy 禁用/不可写直算）、
  归窗口径（closed 按闭单时刻、未结按创建时刻，KPI 与 charts 同口径）、纳票分母、
  响应冻结形状跨视图不变、cache.status 契约字面语义（首查惰性生成=computed、
  命中=hit；单元层 t05_dual_door_stub 锁定）与预热后双前门字节级一致。黑盒五用例与单元层五用例
  由 t06_all 全量聚合执行。

- 本组设计基线=方案 gen2（stage_create_plan_gen2.json）+ review 三轮意见；缓存
  路径取 sandbar 契约 ①a（`projects/<key>/data/metrics/`），契约块 3 L189 目录
  表述矛盾已上报用户裁决（见该方案遗留项）。
- **t07_acceptance_walkthrough.mjs**（验收走查脚本，18 子项）当前**未接入
  t06_all**：其中「首查惰性生成 → cache.status=computed/miss」按契约块 2 字面断言，
  与实现成文口径（写出即 hit，metrics.ts L589-594）冲突——该冲突的根因是契约
  自身张力（字面语义下冷缓存双前门字节比对必红，因比较面不含 cache.status），
  属用户裁决项（修约块 2 status 语义，或扩比较面）。裁决落地前接进机械门会恒红。

## t260902-03 — host 陈旧全局提醒（重启 console 横幅）基线

`integration/t260902-03/` 三条 + 聚合入口，manifest 单条目
`t260902-03-stale-host-watchdog` → `i_all.mjs`。全 hermetic（fixture 仓 + 进程内 mock
webServer 直调 handler + 静态锚点，零端口零 Docker 零 3099），泳道机械跑可执行。
implement 前按设计**恒红（验收棒）**：i01 找不到 /build-info 路由、i02 import 不到
staleness.ts、i03 bundle 无横幅锚点。

- **i01_stale_watchdog_e2e**：黑盒消费 node.ts apply + mock webServer（agent-live 形态）。
  T1 新鲜 boot→stale:false 且 boot===disk 指纹；T2 只摸 watched 文件 mtime→仍 false
  （内容 hash 非 mtime，checkout 触碰不误报）；T3 改 watched 文件内容→stale:true
  （模拟合并落账不重启，一日三咬场景）；T4 同进程二次 apply 不得重置 boot 指纹
  （stale 保持 true）；T5 全缺失→200 {stale:false,error} 人话（无法判定=不误报）；
  T6 五路并发轮询裁决/指纹一致；T0 POST→405 只读看守。信封契约钉死（屋风 {ok,result}）：
  200 → {ok:true, result:{stale, bootFingerprint?, diskFingerprint, missing, error?}}。
  fixture 只保证 watched 清单必含的 node.ts 在场，其余 watched 文件名缺席落 missing[]
  不影响裁决。
- **i02_client_classifier**：分类纯函数落 `src/client/stale-check.ts`（React-free，
  hero.mjs 先例：import react 的模块裸 node 跑不了）——钉契约
  `classifyBuildInfoResponse(status, bodyText) → {stale, error?}`：仅 2xx + 可解析 +
  result 信封 + 无 error + `{stale:true}` 时 stale=true；非 2xx/畸形 JSON/缺字段/
  非布尔/裸顶层 stale（无 result 信封，钉端点-分类器信封一致性）/NaN 等
  15 矩阵 + 8 畸形 fuzz 全 false/error 透传且不抛（看守自身不得成为新报错源）。
- **i03_build_contract**：lib/client.cjs 与 lib/client.js 双产物同带横幅文案与轮询路径
  （抓漏 tsdown 重建）；sidebar.tsx 挂 useStaleHost 单例 + wb-stale-banner JSX 位于
  `.wb-right-content` 容器之上（四视图共享壳，切视图横幅常驻）；index.tsx（Board 视图）
  不得出现横幅/hook（防回退成单视图提醒，review R1 回归闸）。
- **manual_browser_checklist.md**：F1-F7 浏览器走查（隔离台 3199，严禁 3099）——
  新鲜无横幅/落账≤30s 出横幅/四视图常驻/消音仅本页签/重启归零/隐藏页签零轮询/
  畸形响应零报错。机械基线不 boot 控制台，浏览器面由隔离台人工/验收段承担。

已知限制：i03 的「JSX 在容器之上」是源码序静态锚点，真实跨视图常驻由浏览器走查
F3 承担。设计阶段基线曾按扁平信封/钉名 staleness.ts 初钉，calibration 时对齐屋风
{ok,result} 信封与 stale-check.ts 落点（分类逻辑 React-free 的验收面不变，矩阵只增不减）。

## 第 9 组（t260916-24）—— dsh 升级接缝探针 + 版本钉路径三场景（epic dsh-upgrade T4）

`integration/t260916-24/` 一探针两场景一夹具（契约=主检出 notes/epics/dsh-upgrade.md
§接缝矩阵 + 方案 gen1）：把「dsh 升级会不会 break」变成可重跑的可判定判据。

- **probe_dsh_seam.py**（探针本体，无 sc_ 前缀=不入 registry）：
  - `--selftest`：离线正负双自检（金样本 3 档绿——vN 无 cacheReadTokens 档必须恰出
    WARN，锁「可选键缺席告警不拦停」语义；篡改 7 档逐项按预期断言名红，含坏 JSON 行/
    截断半行/zstd 坏帧=KI-059 撕裂族）。已包装为场景 t260916-24-dsh-probe-selftest（ro 池）。
  - `--version <候选版本>`：**live 档不入默认跑分面（验收④）**，升级门槛时显式调用——
    隔离前缀 npm 显式钉版安装（装后核 package.json 防 dist-tag 漂移）+ 隔离 DSH_HOME
    一次性真会话 → 断言 a 文件名口径（必录实际文件名→匹配代际，两代均不匹配才红）/
    b 解析面必填（provider/model+in/out 整型；cacheReadTokens 缺席=WARN 不拦停，矩阵 #2
    开放问号）/ b+ 记录类型族清单（矩阵 #10 底册交 T5）/ c 沙箱不变量（泳道内写成功+
    主库 .git 模拟位越界写被拒）/ d 钉模型生效 / e resume 同 id 续写。退出码 0/1/2 三态
    （lib_env 同款，环境缺=2 点名不假绿）。
  - `--rounds N`：延伸子用例，同 home 连跑 N 轮汇总 cacheRead 观测（非门槛判据）。
  - zstd 依赖=CLI（引擎读侧同款硬依赖）；zstd v1.5.7+ 缺省压缩产物后缀是 `.zst` 而非
    `.zstd`——fixtures 一律 `-o` 显式钉名（坑已填，重造夹具时注意）。
- **t260916-24-dsh-face-meta**（engine 池）：真 worker 起跑链上归属 meta 的 `dsh` 版本面
  四子用例（缺省=宿主实测/钉路径=桩自报/预期不符可查/探测失败不挡启动）——验收②③的记录面。
- **t260916-24-dsh-expected-loud**（engine 池）：真工单链上「版本与预期不符→响亮」两子用例
  （缺省=带病跑但日志点名两版本；STRICT=1=宁可停不悄悄跑错版本）——验收③的执行面。
- **lib_t26091624.py**：版本桩（--version/agent 双形态记账）+ 舞台装配 + worker 拉起收尾。
- **RUNBOOK_GATE.md**：升级回归门槛文本（写集外交接件，integration 粘贴进 runbook §1）。

引擎侧配套（server/engine/）：`dsh_pin.py` 版本面解析器 + worker meta 增 `dsh` 键 +
spawn 落票面 `dsh_pin_<tag>.json` + 四旋钮（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）。

## 第 10 组（t260922-06）—— 会话 id 寻址口径 / resume 专项收口（seam 矩阵 #5，插件半边）

`integration/t260922-06/` 两场景（灰盒 L2，fake-dsh 桩缝，零 live 零凭据零网络秒级，池=ro）。
票面根因经 create_plan 源码实证修正：0.1.5 原生支持自定义 id 寻址（单点真源=自定义 id 本身，
无需映射表），真崩点=插件 summarize 消费 0.1.5 已移除的 `Session.events` 形状
（`events is not iterable`，每次 spawn 跑完 exit 1）。本组守**插件半边**（写/续侧行为 +
装载/物化缝）；读侧半边归 developer 引擎 UT（test_t260922_06_resume_addressing.py）与
t260916-23 dualname 族；0.1.1/0.1.5 live 双版对照（验收④）归升级门槛机械段
（RUNBOOK_GATE + probe --version；其 cold-start 缺口归 t260922-03/判据票收口）。

- **t260922-06-resume-seam-plugin-faces**（ro）：以临时桩包树（@deepseek-ai/* 包名即接缝
  契约面）驱动真实 node.ts 公共入口 apply()，八面收割 stderr/stdout/退出码/桩账本——
  legacy(0.1.1) 与 v3(0.1.5) 双形状 resume 成功且装配级输出全等、自定义 id 原样进
  agents.resume（不造 uuid）、形状不识别/返回缺 .agent（四处调用点全覆盖）/seq 缺口
  一律响亮点名 exit 1、回落链（KI-059 撕裂链形状）逐级显式宣告「回落新建同 id 会话」
  「改用全新会话 id（上下文不可恢复）」、全局判据=stderr 全行词汇表形状零裸栈。
- **t260922-06-resume-seam-plugin-wiring**（ro）：装载/物化缝（方案 §5.1「TS loader
  sibling 导入」遗留风险的机械代理 + t260913-04 物化缝同族）——整目录拷贝副本内按
  node.ts 同款 URL 形状导入 summarize.js 自足可装载且双形状 golden 不变、node.ts 的
  URL sibling 引用逐个闭合、summarize.js 零依赖契约静态守卫（破约=纯函数单测网静默
  死亡在此响亮）、副本含全部插件文件。

与 developer L1（server/headless-resume/test/summarize.test.mjs 纯函数语义）intent 分工：
彼守 summarize.js 语义 golden/畸形族，本组守装配面（守卫接线/回落链次序/退出码）与
物化装载面——纯函数单测过≠守卫接线在、真源单测过≠副本可装载。

## t261011-26 — line round live face + retained evidence (`lib_round_face.py`)

The line round used to be invisible while it ran: its suite log lived in a
per-round system temp dir and was deleted at round end, and nothing answered
"how is the round doing" (host question 261011). The runner
(`line_round_runner.py`) now publishes, via `lib_round_face.py`:

- `<develop_dir>/rounds/current.json` — the LIVE face, exists ONLY while a
  round runs (ABSENCE = idle, the rule workbench `certification-model.ts`'s
  `roundState` input already declares). One writer = the runner. Written
  atomically, refreshed by a log-watching thread every ~2s from the suite
  log's own vocabulary (PASS/FAIL/ENV_FAIL blocks, pool banners,
  INTEG_SUMMARY); unknown lines are ignored, never counted.
- `<develop_dir>/rounds/<run_id>/` — retained evidence per round:
  `face.json` (terminal record: state done/failed + outcome green/red/named
  could-not-run reason) and `suite.log`, kept rolling for the last
  `FACE_RETAIN_ROUNDS` (10) rounds.

Face shape (the contract; `lib_round_face.py` module docstring is the truth
source): `run_id` (relabeled to the ledger run id at round end), `line`,
`revision` map, `started_at`/`updated_at`, `state` (running/done/failed),
`pool` (`unknown` until a banner is seen), `counts`
(ran/pass/fail/env_fail), `last_scenario` (name + verdict), terminal-only
`outcome` (verdict + reason). Consumer faces (adapters) are a separate
ticket — until one lands, publishing is not panel-visible.

Unresolved develop dir (no project declares the candidate repos) is a named
stderr degrade: the round runs exactly as before, only the face is absent.
Unit battery: `integration/tests/test_t261011_26_round_face.py`.

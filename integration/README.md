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
  含全腿 N/A）；2=有 ENV_FAIL（环境红）**。旧「依赖缺失一律干净 SKIP（exit 0）」（退役）
  与 `SUMMARY pass/skip/fail` 语义**退役**（定稿=notes/discussions/
  260904-charter-injection-invalid-payload.md §7.3：没验成且原因归环境≠通过）。
- 环境缺失（依赖、隔离台、凭据、playwright 等）一律：打印 `ENV_FAIL: <缺什么>` 且
  exit 2——不假红也不假绿，依赖恢复后自动生效。
- N/A 仅给以**系统状态**为条件的腿（不以测试环境为条件，如「该 feature flag 未开时
  该腿无对象」），打印 `N/A: <原因>`；**全腿 N/A 的场景=产品红 exit 1**（无可验对象
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
  **例外腿已撤除（宿主管 260914，起因＝KI-089）**：旧口径为「票面 write_set ∩（声明
  `exclude_pools_force_assets` ∪ 执行器机械派生面）非空 → 本票集测段强制全跑」。实测该腿
  对**全部**在跑票恒命中——写集只要带目录形条目（如 `integration/`）即命中整个测试目录，
  四张在跑票逐票命中 77~78 项，排除声明一次都没生效。现口径：**apply=true（每票段）时
  声明即跳过，不设例外腿**；被跳池只由项目级全量轮（巡检/手动/回放——均不传 apply）覆盖。
  旧命中面仍在回执 `pool_exclude.former_force_assets` 里逐项点名（少跑必须可见），但不再
  据此放行。资产派生面（被排除条目 cmd token ∪ 其 import/require 传递闭包 ∪ `integration/`
  根共享基建面，sc_ 场景文件除外）保留，用于未知池/非法池名单点判红。已知缺口（动态导入、
  非 integration/ 且未声明的资产面、.sh 内容不遍历）登记在 t260913-03 结算，由定期全量轮兜底。
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
  `SANDBAR_NAMESPACE=suyou-test`；内置硬断言——该变量未显式设置或精确等于生产缺省  # naming-compat
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
- lane-parallel-dom（t260901-09，泳道图并行分叉 DOM 级双边同亮断言）：S0 build-contract
  纯 node 恒跑；S1 浏览器半依赖测试控制台（`SANDBAR_TEST_CONSOLE` 显式指台；缺省
  泳道限定台自动 ensure，见舞台纪律段）+
  playwright-core + 本机 chromium，缺任一 ENV_FAIL（exit 2）——与 session-tab-interactions 同款环境
  取舍。S1 造数用 playwright `page.route()` 在 `/sandbar-workbench/api/wf/tickets` API 边界
  打桩 fixture 快照（不进 Temporal、不写真工单）；泳道 worker 环境因 SANDBAR_TASK_QUEUE
  特征机械 ENV_FAIL 属既有正确行为，真实覆盖在隔离台环境（3199 台 + 浏览器在场）跑。
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

本组不再是空壳：`baselines/ticket-lifecycle.mjs`（总入口，内部分场景）+
`baselines/ticket-lifecycle-scenes.mjs`（脚手架与场景库）。链路全真：Docker 测试 Temporal
（17233/suyou-test，不可达则幂等 `docker compose up -d`，仍不可用 ENV_FAIL exit 2）+ 每票专属  # naming-compat
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

`baselines/multi-tab-coexistence.mjs`。用户场景驱动：管理台常开多页签，三缺陷修复
（①页签互见在看提示；②写操作交叉失效；③不可见页签暂停轮询）+「点 13 详情跳回 11」
竞态收口。两层结构（同 lane-parallel-dom 先例）：S0 build-contract 纯 node 恒跑
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
- **t02_cache_lifecycle**：缓存目录不可写→200 直算不 5xx（root 下为系统态条件腿，N/A 口径）；
  legacy SANDBAR_PROJECTS_YAML 模式缓存禁用零落盘；缓存目录整体 rm 后惰性重建 200；
  缓存记录 block-3 键集全等 + 二次请求 hit（无票环境为系统态条件腿，N/A 口径）。
- **t03_health_degrade**：view=health 回冻结信封不设视图变体键；本机独立探测
  7233，不可达时 200+reason 人话必带（不可达=ENV_FAIL 口径）；health 请求零缓存写入。
- **t04_cli_door**：argv 畸形（缺参/坏 JSON/非对象/非法值）exit 2+stderr 人话；
  合法请求 exit 0 出契约信封。
- **t05_dual_door**：同请求 HTTP vs CLI，剔 generated_at/cache.computed_at 后
  UTF-8 字节全量比对（契约块 2 比较面，M3 基线锁先行落地）。

已知限制（诚实声明，非哑 guard）：

- **数字级正确性不在本集**：泳道无 Temporal，聚合数字（窗口/token/LOC）只能以
  降级形状覆盖；数字对账=developer 单测（方案步 1/2）+ M3 三票人工核对。t02 末段
  与 t05 在有票环境（Docker 测试台/真票）自动升级为数据级断言，无票时为系统态条件腿（N/A 口径）。
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

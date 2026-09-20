# t260916-22 设计留档——巡检 agent 化（设计定稿 v1 落地）

- 票：t260916-22（scan 段退役、新增 inspect 段 role=inspection @ kimi-coding/k3 + 发现级裁定）
- 设计定稿：notes/discussions/260916-inspection-agent-design.md（宿主五问裁定全含）
- 本档=工单方案全文留档（create_plan gen2，review_plan gen1 附条件放行）+ 集成测试集设计说明。
- 状态行：方案=定稿（review conditional）；实现=并行段进行中；本文「实测回填」节由实现段补。

## 第一部分：方案全文（gen2）


# t260916-22 巡检 agent 化（设计定稿 v1 落地方案，gen2）

## 0. 现状锚点
- workflow=inspection_flow.py InspectionPeriodicWorkflow，现段序 setup(套件档)→scan→suite(套件档)→report→close；scan 段=活动 run_inspection_scan（activities.py，按 scan_face 分派 S1~S4/doc/stage 静态扫描器）。版本门范式 SUITE_PATCH_ID/PROJECT_PATCH_ID 在位。
- 双真源族（R1）：引擎 STAGES↔workbench host/inspection-face.ts INSPECTION_TOPOLOGY 由 tests/t260916-05-inspection-topology-lock.mjs 源级锁逐位比对（id 序+name 一致+变异自证），闸内由 integration/t260916-05/sc_inspection_dual_source_lock.mjs 真实执行——STAGES 改（增删改名换序）不改宿主表，锁必红。workbench 侧另有 tests/t260915-08-inspection-face.mjs 断言 scan 在场与短名。
- UI 票判定：shared.py:2548 UI_WRITE_PREFIXES 按**声明条目**前缀匹配（KI-044 现行语义；根治方向未落地）——本票申报件无命中（见 report）。
- 声明=inspection_decl.py 零依赖 YAML 子集解析器（unknown 键 fail-closed）；生产声明=仓根 inspection.yaml。运维通道=inspection_trigger.py（子命令表挂 verdict）；期票解析=inspection_ticketing.resolve_period_ticket_id。台账=out/inspection/inspection-<实例>-<期>.json + -suite.json（deadman ledger_periods 排除表已含 -suite.json）。
- agent spawn=_prepare_agent_spawn（本地 .dsh 三拷/torn 检疫/role patch 缺席软跳过/model_route 查表钉模型+双 warning 点名/会话延续/docker sandbox pin）+agent_runtime.spawn_agent（host/docker、进程组 reap）。dsh 权限预设含 read-only（--dump-default-config 实证）。headless runner（server/headless-resume/node.ts:150）只把最终消息打 stdout、不写结果文件 ⇒ 只读 agent 产出必须走 stdout 围栏 JSON。
- UT harness=纯逻辑 pytest（server/engine/tests/，无真 Temporal/网络）；场景=run_scenarios.py 登记制（未登记 sc_=lint 红）。

## 1. 总体形态（新票，INSPECT_PATCH_ID="t260916-22-inspection-inspect-stage" 门内）
schedule（不动）→ InspectionPeriodicWorkflow：setup（不动，套件档）→ suite（不动，套件档）→ deadman 漏跑核查（不占段位，挂 suite 块）→ **inspect【新】** spawn 只读 agent（role=inspection、kimi-coding/k3；输入=审查基座（suite 期=当期泳道 worktree；非 suite 期=repo_root）+当期 suite 回执+上期发现摘要（只给 id+subject 防照抄）+预算；输出=stdout 末块围栏 JSON 强 schema）→ **report【扩】** 机械复核链（id 铸造→证据复核→跨期去重/假报压制→预算截断→汇总/心跳→票面→落账）→ close 人门（不动）。
老在途票（patched=False）逐字走现路径；legacy 路径外提为 inspection_flow 模块级函数（类块外，保拓扑源码锁「类块内 _enter 字面量全集==STAGES∪PRE_FLOW」纯度）。
STAGES（编码真源）改为 setup→suite→inspect→report→close（setup/suite 仍 suite_only；仍 5 段、setup 起 close 收——锁形状自检不动）；inspect name="巡检审查"。**双真源同步责任（R1）**：template_topology._INSPECTION_NODES、workbench INSPECTION_TOPOLOGY（name 同值+short="审查"）、topology-lock.mjs 变异子用例字面、inspection-face.mjs 断言四处同票改齐；闸内 dual-source-lock 场景即机械验收。

## 2. 关键设计点
### 2.1 role 与模型
role=inspection；persona 不新增 server/roles/ 文件（写集外），由 inspect 活动生成一次性 cordis patch（真源=inspection_inspect.py PERSONA 常量：「只读审查员，宁可少报不可虚报；绝不改码；证据契约；输出契约」）。模型=查表 roles.inspection（仓外运维步骤：~/.sandbar/projects/sandbar/model-routes.yaml 加 inspection: provider kimi-coding / model k3）；表未加=现有可见降级（profile 默认+warning 点名），活动 meta 记录本轮实际路由。agent spawn 强制 host（agent_runtime.spawn_agent 加 force_host 参数）。
### 2.2 只读红线（机械三层）+ 写面解耦（R4 自查修正）
1) 工具面：spawn 追加一次性 patch 钉 sandbox-policy.mode:'read-only'+permission defaultPreset:'read-only'（晚于既有 pin 追加覆盖生效；docker danger-full-access pin 因 force host 不生效）。
2) 落点：审查基座 suite 期=当期泳道快照（收口即拆永无合并路径）；非 suite 期=repo_root（meta 记 base_dir+git rev-parse HEAD）。
3) **DSH_HOME 与基座解耦**：_prepare_agent_spawn 加可选参数 agent_home（缺省 None=cwd/.dsh，现行为逐字节不变零回归）；inspect 传 agent_home=<INSPECTION_DIR>/agent-home/<实例>-<期>/（该子目录名不以 inspection-<实例>- 前缀开头，deadman ledger_periods 词法天然忽略，零干扰）——非 suite 期 cwd=repo_root 时 .dsh 写面不落真仓。agent-home 不主动清（体量 MB 级；会话延续同票重试需要），名单进 design.md 记账，清理策略观察期后定。
4) 判定化：inspect contract 场景对被审查树逐字节校验和断言（t260905-03 场景②同款）。
### 2.3 输出契约（强 schema）
agent 最终消息末尾恰一块 ```json 围栏 {"findings":[…]}；条目=subject（含 file:line）/severity(high|med|low)/evidence(非空列表，项={path,line,quote≤200字})/why/suggestion/confidence(0~1)；id 不由 agent 提供（机械铸）。解析纪律（parse_arbitration_summary 同族）：围栏块 0 或 ≥2、坏 JSON、findings 非列表、条目缺键/越域 → ParseError 点名条目序号不猜；活动 ok=False→workflow blocked("inspect") 终态点名。id=sha256(规范化(subject|why|evidence 排序逐项 path+line+空白折叠quote))[:8]，同内容跨期稳定。
### 2.4 report 段机械复核链（新模块 inspection_inspect.py 纯函数；活动壳只 IO）
1 mint_finding_id；2 recheck_evidence(base_dir)：逐条逐证据——path 相对且不越 base_dir（绝对/.. 越界=不过）、文件存在、行号∈[1,行数]、quote 空白容差匹配（两侧连续空白折叠后包含判定）；全过=verified，任一不过=unverified+逐项 reason（票面点名不静默丢）；3 dedupe_and_suppress：id∈上期台账发现 id 集→recurring:true（不进 summary/建议）；id∈历史 false-positive 集→压制（同排除，票面点名）；上期台账读不出（坏 JSON/缺 findings/非列表）→prev_ledger_error 点名进 meta+去重降级「无上期」（可见不静默，R7②）；4 apply_budget：新发现按 (severity 降序,confidence 降序) 截上限（缺省 40），meta.truncated:N；5 汇总/心跳：summary 只计新发现，heartbeat=新发现==0 且套件绿（recurring/压制可见不破心跳——裁定④口径，review 异议改一行+用例）；6 建议门：scan=="agent" 须 verified && confidence≥0.6（常量） && severity≥med 才进 suggested_fix_tickets；deadman/suite 机械发现口径逐字不变。
### 2.5 预算 + 分面选择机制（R5）
- 预算：声明实例段可选键 max_findings（正整数，缺省 40）/inspect_timeout_min（正整数分钟，缺省 30），词法外 fail-closed；链路 decl parser 白名单+InstanceSpec→_plan_from_decl plan["inspect"]→workflow start_to_close=timeout→活动预算。活动内 deadline=timeout−60s（常量 margin，UT 锁不等式）；到点杀进程组 reap→ok=False「agent 未完成（超时）」→blocked("inspect")+落账（台账可见、heartbeat=false 不假绿）。inspect 活动 RetryPolicy maximum_attempts=1（烧配额不重试）；复核活动 RETRY(3)。
- 分面：声明新可选键 **inspect_profile**（设计稿 §5.2 明文名），词表=WIRED_FACES 同表（test/doc/stage/mechanism/simplify），缺省回落 scan_face 值（老声明零改动照跑）；scan_face 保留（legacy replay=扫描器选择键语义不变；新票=分面缺省来源）。prompt 构建=通用骨架（persona+红线+证据契约+输出契约+预算）+按 profile 选分面清单（五份）+suite 回执+上期摘要。
### 2.6 发现级裁定（verdict）
词表 false-positive(假报)/to-fix(待修)/doubt(存疑)（CLI 收英文 token+中文别名）。新 signal finding_verdict(finding_id,verdict,who,note)：who 非空、非 agent 角色名、≤64（复用 sign 语义）；过校验→face.findings 对应条目写 verdict+timeline 留痕，不调活动不拦闸（回放安全零新命令）。CLI：inspection_trigger.py verdict --instance --period --finding-id --verdict … [--who --note]：票在途→resolve_period_ticket_id→signal；已收口/查无→直改台账 JSON 票面+verdicts 文件。台账真源=out/inspection/inspection-<实例>-<期>-verdicts.json（append entries：finding_id/verdict/who/note/at；重复裁定 face 取最新 entries 全留痕）。deadman ledger_periods 排除表加 -verdicts.json。跨期消费：verify 活动读本实例全部更早期 verdicts 文件收 false-positive id 集（假报跨期不重复计数）；to-fix/doubt 留档供查准率统计。
### 2.7 静态扫描退役
inspection_scan*.py+selfcheck_scan.py 头注退役条（宿主令引文+票号、「留档考古、生产路径已摘除（INSPECT_PATCH_ID）、新代码禁接线」），逻辑零改动；activities.run_inspection_scan 保留注册（老票 replay 需要）+退役注记（新票不可达）；274 条旧发现不迁移（裁定④）；deadman/suite 逐字不动。
### 2.8 段名改法与 UI 闸预判（R1/R2）
见 §1 双真源同步责任。UI 闸：本票 workbench 申报件（src/host/、tests/）不命中 UI_WRITE_PREFIXES 五前缀，现行声明前缀匹配与 KI-044 根治方向的 diff×前缀匹配两语义下都不触发 ui_evidence 截图闸。
### 2.9 借鉴取舍清单（R4）
1 _prepare_agent_spawn：带 torn session 检疫/profile 三拷/creds merge（KI-016 残留=同名 leaf 不重写；本期每期新 agent-home 从零拷贝，同票重试复用 home 走 merge——key 集在票生命周期内不变，取舍可接受并声明）/model route 非 ok 与无命中双 warning（KI-030 收窄面）+meta 记录/会话延续（DSH_HEADLESS_SESSION=ticket-role，worker 重启续会话）；新增 agent_home 参数（缺省不变）；不带 docker sandbox pin（force host）。2 spawn_agent+_reap_agent_proc：带进程组 reap（正常/报错/超时/取消四路 finally，岗位纪律）、start_new_session、pgid 读取失败降级；force_host=显式选择。3 parse_arbitration_summary：带「恰一命中否则格式失败不猜」纪律到围栏 JSON 解析。4 sign 的 who 校验语义（非空/非 agent/≤64）带到 finding_verdict。5 SUITE_TO>内部 deadline+UT 锁（test_suite_timeout_outlives_internal_deadline 同款）带到预算双闸。6 RETRY_SUITE maximum_attempts=1 理由（烧钱不重试）带到 inspect 活动。7 t260905-03 场景②被扫树逐字节校验带到 contract 场景（红线判定化）。8 KI-002：被借面 max_polls=0 超时保护不生效——不带 max_polls，inspect 自带 deadline=timeout−60s+finally reap 替代（替代关系声明在案）。9 build_ticket_face 扩展向后兼容（新字段全缺省，老 finding/deadman/suite 条目零变化）。

## 3. 改动清单
见本结果文件 files_changed 结构化字段（49 件=本票申报写集全集；engine 21+workbench 3+integration 25；其中 workbench 三件与 docs 两件=写集外申报扩入，理由 R1/R6）。各件内容：
- engine 新件：inspection_inspect.py（§2.3/2.4 纯函数+PERSONA+五分面清单+verdict 纯面）；UT 四件 test_t260916_22_inspect_{core,activity,flow,verdict}.py。
- engine 改件：agent_activities.py（run_inspection_inspect：桩 SANDBAR_INSPECT_STUB=1+SANDBAR_INSPECT_STUB_FILE / 真 spawn 双态、stdout 捕获、轮询心跳、全终态 reap、超时；_prepare_agent_spawn 加 agent_home）；activities.py（verify_inspection_findings 壳：读上期台账+verdicts→纯函数链；run_inspection_scan 退役注记；ALL_ACTIVITIES 注册）；inspection_flow.py（INSPECT_PATCH_ID 门+新段序+legacy 外提+STAGES+build_ticket_face 扩展+finding_verdict signal）；agent_runtime.py（force_host）；inspection_decl.py（max_findings/inspect_timeout_min/inspect_profile 三可选键）；inspection_trigger.py（verdict 子命令）；inspection_deadman.py（排除 -verdicts.json）；template_topology.py（scan→inspect 同步）；inspection_scan{,_doc,_ms,_stage}.py+selfcheck_scan.py（头注退役条）。
- engine UT 改件：test_t260916_05_inspection_topology.py（新段名/段序）；test_t260910_09_inspection_flow_face.py、test_t260913_02_inspection_deadman.py（若锁面受影响则连带，申报在册防越界）。
- workbench 三件：inspection-face.ts（INSPECTION_TOPOLOGY scan→inspect，name=巡检审查，short=审查）；topology-lock.mjs（变异子用例字面改 inspect 且按 id 动态取，防再改名）；inspection-face.mjs（some(id==='inspect')+short('inspect')==='审查'）。
- integration：新四件（lib_inspect.py 场景共享夹具：inspect 桩 helper+真实仓形树+围栏 JSON 伪造器；sc_inspection_inspect_contract.py 桩链横向契约+红线字节不变+畸形点名；sc_inspection_inspect_journey.py 端到端；sc_inspection_verdict_cli.py 裁定落账+跨期压制）+run_scenarios.py 登记/摘除+既有 12 件按 §8 处置表。
- docs 两件：inspection-sample.yaml（三新键样例+scan_face 语义注记改为「分面缺省来源」）+index.json（build_index.py 重跑产物）。

## 4. 实施步骤（每步带验证；实现段每变更一 commit）
1 契约纯函数层（inspection_inspect.py+test_core）：畸形输入全覆盖（0/2 围栏块、坏 JSON、缺/空 evidence、severity/confidence 越域、subject 空、quote>200、../ 越界、绝对路径、行号 0/负/超行数、引文不符、空白差异应过、id 跨期稳定+内容变即变、41→40 截断+truncated 记账、recurring/压制不占预算、心跳合成、建议门边界、**上期台账坏 JSON/缺 findings/非列表→prev_ledger_error 点名（R7②）**）。
2 活动层（run_inspection_inspect+verify 壳+force_host+agent_home+test_activity）：桩合法/畸形两子用例；SANDBAR_INSPECT_CMD 假脚本走真进程链；假脚本超时子用例断言「agent 未完成」+reap 干净（pgrep 零残留）；路由 miss 点名进 meta（夹具表传参不依赖机器表）；agent_home 落点断言（真仓/泳道零 .dsh 残留）。
3 workflow 接线（flow+decl+template_topology+workbench 三件+test_flow+test_t260916_05 更新）：INSPECT_TO≥deadline+margin 不等式锁；patched 两子用例路径选择纯面；build_ticket_face 新字段+建议门；decl 三新键正/反用例+plan 透传（含 inspect_profile 缺省回落 scan_face）；**node server/plugins/workbench/tests/t260916-05-inspection-topology-lock.mjs 绿（双真源改齐的机械证明）+inspection-face.mjs 绿**；test_t260905_03_inspection_flow/test_t260913_02_inspection_suite 零回归。
4 裁定面（trigger+deadman+signal+test_verdict）：词表/别名、who 闸、apply_verdict 纯面、verdicts 文件读写畸形输入、deadman 词法排除 -verdicts.json、压制消费。
5 退役面：头注退役条+misreport_calibration 删登记；grep 断言 workflow 新路径零 run_inspection_scan 调用点；run_scenarios lint 无孤儿。
6 场景面（三新+§8 表更新件+registry）：三新场景绿；更新场景绿；python3 integration/run_scenarios.py 全量基点照常（288 基点净 -1+3 显式说明）；lint/hex-clean 照常。
7 留档+运维：integration/t260916-22/design.md 落盘本方案全文+回填实测（read-only 探针结论、路由生效证据、agent-home 名单）；docs 两件落盘+build_index 重跑。

## 5. 验收口径（工单六条↔落点）
1 端到端 → sc_inspection_inspect_journey：真实仓快照（仓形真树+真实文件锚）上桩 agent 产出发现（evidence 锚快照内真实文件行，R7①）→证据复核（含一条坏行号→unverified 点名子用例，R7①）→人门 sign→落账→建议门→预算截断面全链绿。CI 桩链（确定性零配额）；真模型按观察期（§6）。
2 证据复核 UT → test_core（坏路径/坏行号/引文不符逐项降级 unverified+reason 点名；空白容差正用例）。
3 预算 UT → test_core 41→40 截断；test_activity 超时子用例 heartbeat「agent 未完成」不假绿。
4 裁定 UT → test_verdict+sc_inspection_verdict_cli（落账+假报跨期压制）。
5 既有巡检场景 → **显式更新**：test face（workbench inspection-face.mjs）、topology 锁（workbench topology-lock.mjs+闸内 dual-source-lock 场景+引擎 test_t260916_05）、detail_lane_map_dom、topology_receipt、suite_journey、board_ui、sidebar 两件、period_journey、doc_face、trigger_kinds、project_identity、decl_relocation（真链子用例桩注入）；**显式删除**：misreport_calibration；**零更新仍绿**（逐件理由见 §8）：ticketing/decl 词表/deadman/suite 机械/扫描器 CLI 契约四件。
6 288 场景基点 lint/hex-clean 照常 → 步骤 6。

## 6. 仓外运维步骤（不静默）
- 生效表加条目：~/.sandbar/projects/sandbar/model-routes.yaml roles 段 inspection: {provider: kimi-coding, model: k3}（宿主已定，本票=人审依据）；未加=可见降级。
- 观察期：连续 2 期人工核对查准率（设计稿 §5.4）；真模型首跑由宿主手动 trigger 一期核。

## 7. 遗留风险
见 report「遗留与风险」五条（files_changed 通道唯一性、read-only 预设实测、非 suite 期基座、路由表仓外待办、备选切法三条）。

## 8. 全族逐文件处置表（R3；分类依据=逐行 grep 取证）
【显式更新 12】
1 integration/t260916-05/sc_inspection_topology_receipt.py——:152/:159/:163/:174/:194/:248 节点/边/ID 集/stage/timeline/边序硬编码旧段名段序→按新段序改。
2 integration/t260916-05/sc_inspection_detail_lane_map_dom.mjs——:84/:89/:92/:93/:100/:116/:126/:132/:137/:143/:334/:342 节点/标签/边/stage/timeline/循环 id 集→新段名段序。
3 integration/t260913-02/sc_inspection_suite_journey.py——:239-243 阶段机序断言 setup/scan/suite→新序；journey 真链子用例注入 inspect 桩。
4 integration/t260915-08/sc_inspection_board_ui.mjs——:107 tle('scan','done')、:340 /scan|report|close/ 正则→段名+正则补 inspect。
5 integration/t260915-19/sc_sidebar_inspection_ui.mjs——:107/:130 stage:'scan'、:156 tle('scan',…)→'inspect'（宿主短名表改后 scan 走未命中截断，UI 字样断言会红）。
6 integration/t260915-19/capture_sidebar_ui.mjs——:42/:56 stage:'scan'→'inspect'。
7 integration/t260905-03/sc_inspection_period_journey.py（+lib_inspection.py 加桩 helper）——真链 journey：inspect 桩注入+夹具发现断言+段名。
8 integration/t260911-02/sc_inspection_doc_face.py——头注自述「报告断言一律走 trigger→flow→scan→落账真链」→真链子用例改桩注入 inspect；离线 doc 扫描器 CLI 子用例零改动保留。
9 integration/t260911-02/sc_inspection_trigger_kinds.py——计数触发真链子用例（票会进 inspect 段）→桩注入；触发/去重断言本体零改动。
10 integration/t260915-20/sc_inspection_project_identity.py——J1b「发现落面（worker 扫描完成）」真链子用例→桩注入；声明/SA 查询路径零改动。
11 integration/t260916-02/sc_inspection_decl_relocation.py——T4 t4_scan_own_repo 真链子用例（断言发现锚各自仓根）→桩注入+桩发现锚各仓真实夹具文件（R7① 同法）；lib_relocation.py 仅 scan_face 声明样例行零改动（连带申报在册）。
12 integration/t260916-05/sc_inspection_dual_source_lock.mjs——执行面零改动预期（锁文件改齐自动绿）；申报在册防实现段需调执行断言。
【删除+登记摘除 1】
13 integration/t260910-11/sc_inspection_scan_misreport_calibration.py——intent=静态扫描假报校准，随扫描退役整体消亡；该关切由验收②UT（证据复核降级）+新 contract 场景承接。run_scenarios.py 同步摘条目。
【零更新仍绿 11（逐件理由）】
14 t260905-03/sc_inspection_scan_contract.py——锁 inspection_scan.py CLI 契约；扫描器文件留档保留、活动 legacy replay 保留 → CLI 面零改动（R7③：理由在案非沉默）。
15 t260905-03/lib_inspection.py——扫描器 CLI helper；留档 CLI 在 → 绿（本票仅追加 inspect 桩 helper=连带改动已列更新件 7）。
16 t260905-03/sc_inspection_ki051_anchor_replay.py——黑盒 CLI 消费扫描器四子用例 → 留档 CLI 在 → 绿。
17 t260910-09/lib_inspection_ms.py+sc_inspection_ms_scan_contract.py——ms 扫描器 CLI 契约 → 留档在 → 绿。
18 t260910-09/sc_inspection_ms_decl_gate.py——scan_face=simplify 声明词表断言；scan_face 词表保留 → 绿。
19 t260913-02/sc_inspection_schedule_daily.py——scanner_result 是 lib 通用 CLI 解析助手（此处解析 deadman 输出）；段名无关 → 绿。
20 t260913-02/lib_lane_journey.py+sc_inspection_lane_lifecycle.py——「扫描」字面=夹具守卫文本/头注（KI-051 形态扫描对象），非段名 → 绿。
21 t260915-08/sc_inspection_board_rows.py——findings fixture 的 scan:"test" 是 finding 来源标记值（非段名），行渲染不消费该值语义 → 绿（实现段跑绿确认）。
22 t260915-20/sc_inspection_project_identity.py 声明子用例——scan_face 词表保留 → 声明/SA 查询路径绿（真链子用例已列更新件 10）。
23 t260916-02/lib_relocation.py——scan_face 声明样例行 → 词表保留 → 绿。
24 engine 侧 scanner UT 四件（test_t260905_03_inspection_scan/test_t260910_09_inspection_scan_ms/test_t260911_02_scan_doc/test_t260911_02_ticket_count）——锁留档文件本体 → 零改动照跑。

## 第二部分：全族处置表补档（review C1/C2，integration 落档）

C1 补档（全族 grep 查漏，两件原漏档归零更新仍绿）：
- integration/t260916-15/sc_sidebar_merged_sort_ui.mjs（:120/:156 stage:'scan' 夹具字面）——断言面不消费 stage 值（断言=updated_ts 全序/分组/黄调/title，零段名断言）→ 零更新仍绿；实现段可顺手把夹具 stage 改 'inspect' 保持夹具与真源一致（该件在其写集内）。
- integration/t260916-15/capture_sidebar_ui.mjs（:47/:70 stage:'scan' 夹具字面）——同上，零更新仍绿。

C2 注解：schedule_daily、board_rows 两件在 files_changed 申报内而 §8 记「零更新仍绿」——**预防式申报**（实现段跑绿确认时若需出零改动的确认性调整，不越界），与 item 11/12、两件引擎 UT「连带申报在册防越界」同款，非矛盾。

## 第三部分：集成测试集设计（integration 本段交付）

三依据对照（工单原文验收①-⑥ / KI 未闭合项 / 对外契约承诺）与本场景集 intent 分工见
integration/t260916-22/ 三场景文件头注；登记见 integration/run_scenarios.py
（t260916-22-inspect-contract / t260916-22-inspect-journey / t260916-22-verdict-cli）。
既有场景处置=方案 §8 表 24 件 + 本档第二部分补档 2 件（全族 26 件逐一在案）。

场景集（新增三件，全部落 integration/t260916-22/）：
1. sc_inspection_inspect_contract.py（L2 离线，stub temporalio）：inspect 产物的横向
   契约——围栏 JSON 解析纪律（畸形 0/≥2 块、坏 JSON、缺键越域=ParseError 点名）、
   证据机械复核（坏路径/越界/坏行号/引文不符→unverified 逐项点名；空白差异→过）、
   id 内容哈希跨期稳定、跨期去重 recurring/假报压制不占预算、预算 41→40 截断记账、
   心跳合成（新发现==0 且套件绿）、建议门 verified&&conf≥0.6&&severity≥med、
   上期台账/verdicts 文件畸形→prev_ledger_error 点名不崩。
2. sc_inspection_inspect_journey.py（L3 真台真票 exclusive）：全链用户旅程——trigger
   起票→inspect 段（桩 agent，SANDBAR_INSPECT_STUB=1+STUB_FILE 注入）产出发现锚
   真实仓形夹具的真实文件行→证据复核 verified/unverified 两子用例落面→人门两拍
   （未签不终态/签后收口）→落账 findings 留存→建议门只收合门发现→零发现心跳子用例
   （空桩）→用户可见段名=inspect（timeline 无 scan，段名退役旅程面）+发现来源标记
   scan==agent→被审查树逐字节不变（红线判定化）→仓根零 .dsh 残留（agent_home 解耦）；
   真进程链超时子用例（独立 StageWorker，SANDBAR_INSPECT_CMD=挂起脚本+decl
   inspect_timeout_min=2）：票到 blocked 点名「agent 未完成」不假绿、落账在且
   heartbeat 非真、agent-home 落台账目录、进程 reap 干净（pgrep 零残留）。
3. sc_inspection_verdict_cli.py（L3 真台真票 exclusive）：发现级裁定——verdict 子命令
   词表/中文别名/who 闸（非空、非 agent 名、超长拒）；在途票 signal 落 face+timeline；
   已收口票直改台账+verdicts 文件留痕；同 finding 重复裁定取最新 entries 全留；
   假报跨期压制（P1 裁假报→P2 同 id 发现被压制点名、不进 summary、不占预算）；
   -verdicts.json 不进 deadman 漏跑畸形清单。

既有场景退役一处：integration/t260910-11/sc_inspection_scan_misreport_calibration.py
随静态扫描退役整体摘除（登记+文件；S1 校准语义不再有可执行面），检测半
（ki051-anchor-replay / scan-contract）留守——旧票重放链仍在。真链场景更新口径：
发现注入一律走桩缝（t260916-22/lib_inspect 单点伪造器），被更新文件=period_journey
（桩按子用例切换混桩/空桩+unverified 点名断言）、doc_face 在线子用例（改守桩发现链，doc 扫描
器语义面由离线 CLI 子用例+developer UT 守）、trigger_kinds（空桩）、project_identity/
decl_relocation（A/B 锚桩时序切换+复核 verified 态=引擎 base_dir 正确性的内容级证明）、
六件段名字面件（scan→inspect 段名/「扫描」→「巡检审查」标签；finding 标记值
scan:"test" 全保留；t260916-15 两件按 C1 零更新仍绿，且不在本票写集内不动）。

桩注入契约（场景与实现的接缝，方案 §3 明文）：SANDBAR_INSPECT_STUB=1 +
SANDBAR_INSPECT_STUB_FILE=<最终消息文本文件>——桩文件内容=agent 最终消息全文，
末尾恰一块 ```json 围栏 {"findings":[…]}（走真解析纪律，不旁路）。真进程链子用例用
SANDBAR_INSPECT_CMD=<假脚本>。场景对「实现段的桩缝名」以此为准；落地名若有出入，
在 run_integration_tests 红灯归因后由仲裁段对齐（接口缝属方案明文承诺面）。

## 第四部分：实测回填（实现段落地位，占位）

本段（design_integration_tests）交付实测：场景集 3 新增 + 1 退役摘除 + 12 处显式更新
落盘；登记 292 条（lint L4）；`python3 integration/lint_tests.py` 全绿
（L1 语法 py 281/mjs 215、L2 pytest、L3 import、L4/L5 清单、L6 三态纪律，
0 error / 0 warn）。**本段实测（实现段并行落码后，同工作树真跑）**：
- t260916-22-inspect-contract（离线）→ **PASS 51/0**（解析纪律 7 态、复核 8 态、id 铸号、
  recurring/压制/预算截断/心跳、红线+agent-home，缝名全对齐）；
- t260916-22-inspect-journey（真台真票）→ **PASS**（混合桩五类发现/段名 inspect/零发现
  心跳/人门两拍/落账留存/超时子用例 blocked「agent 未完成」不假绿+agent-home+reap 干净/
  树不变+零 .dsh）；
- t260916-22-verdict-cli（真台真票）→ **PASS**（who 闸五拒收、在途 signal 回执带票号、
  收口直改+verdicts append 取最新、P1 假报→P2 同 id 压制不计数不破心跳、deadman 词法）；
- 既有 12 件更新件与退役件静态面全绿（lint L1-L6）；全量真跑归 arbitrate/merge 闸。

本段实测中发现并处置两件测试资产级故障（归因见 gen2 结果文件 evidence）：
1. **共享 lib 落账 reader 文件名漂移（已修）**：引擎落账文件名 t260916-02 起改为
   inspection-<实例>-<期>.json（票号 t 形化配套），lib_inspection.inspection_ledger
   仍按 <票号>.json 直读 → 永远 miss。已改为旧名直读兼容 + 扫描目录按
   face.ticket_id 匹配兜底（face 内票号字段=票↔账承诺关联面）。period_journey 等
   既有场景在 arbitrate/merge 期同样受益。
2. **泳道队列 ambient 泄漏风险（留档纪律）**：stage-admin 环境向场景 shell 泄漏
   SANDBAR_TASK_QUEUE=sandbar-ticket-<本票号>——不显式钉私有队列的场景，票会被路由到
   无人消费的泳道队列挂死（探针实证：workflow 积压零 poller）。既有钉队列场景
   （period_journey/project_identity/decl_relocation/trigger_kinds/doc_face）与本票
   journey/verdict 均显式 os.environ 钉私有队列，免役；后续新真链场景必须照抄该纪律。

- [x] dsh read-only 预设 headless 语义探针结论（实现段 gen3 回填，**源级探针**，不烧模型配额）：
      **approval=ask 在 headless one-shot 下=拒绝而非挂起**。证据=dsh 安装体内置插件源码
      （dsh-permission-presets 预设表 dump：read-only={sandbox: read-only, approval: ask}；
      dsh-user-approval lib/index.js:25「answerers fail closed」、:40 ASK 语义句
      「without an available answerer, the request fails closed」、:188 策略分支——never 直拒，
      ask 走 answerer 链、无应答面=统一 rejected）。⇒ headless 无应答面下任何需批准的写操作
      **即时被拒**（返回 agent 循环，不悬停烧超时），叠加 sandbox:read-only 的文件系统级硬闸，
      只读红线第 1/2 层成立；第 3 层（场景对被审查树逐字节校验）已判定化。**无需改钉合成预设**
      （approval never + read-only 方案弃用——ask 语义已够且保留可审计的拒绝留痕）。
      观察期首期真跑仍照旧复核端到端（本结论只覆盖语义面，不替代真跑验证）。
- [x] 路由生效证据（实现段 gen3 回填现状）：生效表 ~/.sandbar/projects/sandbar/model-routes.yaml
      **尚无 roles.inspection 条目**（260916 亲读；roles=developer/ops/artist/integration/
      product-operation/default）——宿主裁定 kimi-coding/k3 的人审依据=本工单，运维按方案 §6
      落表后下个 spawn 即生效。未落表期间=**可见降级不假绿**：spawn 侧双 warning 点名
      （表非 ok / 无命中）+ 活动回执 meta.model_route 记录本轮实际路由
      （命中={provider,model}；无表/无命中/复算失败={defaulted:true, reason:人读}，UT 两子用例覆盖）。
      观察期查准率核对以 meta.model_route 对账。
- [ ] agent-home 名单与清理策略：out/inspection/agent-home/<实例>-<期>/ 体量观测，
      清理策略观察期（连续 2 期人工核对查准率）后定。（名单机制已落实：路径=活动侧派生、
      deadman ledger_periods 词法天然不识别该子目录、.gitignore out/ 兜底零仓内污染。）
- [ ] 274 条旧发现整体作废（宿主裁定④）不迁移；t260916-13=静态扫描终点，deadman/suite
      机械发现留档跟踪不随退役。

## 第五部分：实现段回填（developer gen3 交付）

本段在前两棒实现（gen0/gen1 已落引擎与测试主体）之上收尾，改动四件：

1. **spawn 接线守卫普查更新**（integration/t260901-21/i02_spawn_wiring.py，连带必改）：
   inspect 段 run_inspection_inspect 新增第 4 个 _prepare_agent_spawn 调用点，守卫的
   调用点普查断言 4→5（1 定义 + 4 调用；同款先例=test_agent_runtime 接线守卫随
   spawn_agent 3→4、proc.reap 6→8 同步），并新增 inspect 调用点专属接线断言
   （project 源=args.project_key 巡检票身份语义 + spawn 必传 project=project）。
   守卫意图（每个 spawn 调用点都拿到本票项目凭据源）不变且覆盖面扩容。
2. **meta.model_route 落地**（方案 §2.1 承诺补齐）：run_inspection_inspect 真链回执 meta
   记录本轮实际模型路由（只读复算生效表，零副作用；复算异常=meta 点名降级绝不弄挂
   spawn 主链），UT 两子用例（形态断言 + 复算炸降级）在 test_t260916_22_inspect_activity。
3. **docs/inspection-sample.yaml**：inspect 段三键样例（max_findings/inspect_timeout_min/
   inspect_profile，注释带词表与缺省）+ scan_face 语义注记改「分面缺省来源」（R6）。
4. **docs/index.json**：重跑 build_index.py 实证**内容零漂移**（仅 generated_at 时间戳
   变化；inspection-sample.yaml 不在索引目录 docs/{design,content,ops,reference} 扫描面内，
   本票未增删任何 .md）——已还原原文件免时间戳噪声，索引无需变更即为诚实结论。
5. **方案 §2.7 退役名单纠偏一处**：selfcheck_scan.py **不退役不注记**——亲读定性=工单台
   扫描自检（M6 t260821：is_pending_decision/build_scan_item/gate_from_log，巡检票人门
   待办在工单台的可视面），与静态扫描器家族**同名词不同族**（t260910-14 已在案注释同判）；
   方案 §2.7 把它列进退役注记名单系误列，按实况定档（活体自检，加退役条=造假）。
   另 inspection_flow 模块头注的 activity 例举已随手刷新（run_inspection_scan 例举
   →inspect/verify/verdicts 四件+legacy 注记）。

另有测试面归因两件（本段实测）：
- **i02 守卫红=本票连带**（新调用点普查过期待更新），已修（见上 1）；
- **t260901_25_t03 reap 幂等子用例**在全量套件并发负载下偶发红（单跑 3/3 绿、
  _reap_agent_proc 本票零改动）——归因=既有时序敏感测试的负载 flake，非本票回归；
  留观，若闸内复现按超预留时重跑处置。

# 线轮欠账分诊清单（261012 integration 岗，全量轮 8x_40e1y/pyd5pbro 两轮普查 + main 单验）

> 口径：全量轮（线树，克隆环境）fail/not-checked 去重 ~38 → 在册豁免 13 → 剩余红面 25。
> 本表给每条的：main 单验结果（过=轮环境、挂=存量欠账）、根因（已诊/未诊）、修向。
> 轮环境条目**不入册**（册政：抖动绿不入册）；存量欠账按族开票。

## A 类：轮环境/噪音（main 单验过）——非产品欠账，处置=隔离或标注，不修代码
| 场景 | 单验 | 机制 |
|---|---|---|
| t260907-10-engine-layout | 过 | 克隆面/git ref 差异敏感 |
| t260928-13-registry-additive-keys | 过 | 真机面读全局注册（并发敏感） |
| t261009-51-registry-style-drift-bite | 过 | 同上 |
| t260920-03-terminology-baseline-floor | 过 | 基线面基线漂移敏感 |
| t261009-11-run-record-drivers | 过 | 台账面 |
| t261011-22-wait-bound-brakes | 过 | 墙钟面（负载敏感） |
| t260910-13-executor-fail-closed | 过 | 供给面 |
| t261008-36-panel-settings-faces-merge 族（browser） | 外部拒连 | 台装配在克隆/并发下（环境红=诚实分类） |

## B 类：main 存量真欠账（单验挂）——真修，按族开票
| 场景 | 根因（状态） | 修向 |
|---|---|---|
| ~~t260920-03-terminology-l7-gate~~ | 夹具只拷 lint_tests.py，同族导入无人随行（ModuleNotFoundError） | ✅ 已修（动态随行拷贝，`b3033112`） |
| ~~t02-t260902-02-archive-legacy-e2e~~ | 锚中文词「不可恢复」，文案英文化后永红 | ✅ 已修（锚 token，`2bbe0ab3`） |
| t260929-22-executor-entry-console | E4 五视图图标回归/断言漂移；E5 端点 spawn 引擎 CLI、夹具工程 entryproj 无并发声明→400/502 | 面板面回归排查（产品 or 断言）+ bench 夹具播种并发声明 |
| t260907-07-epic-cli-ticket-start | 未诊 | 分诊（CLI 面） |
| t260910-06-ki067-entry-audit | **sign 拒收面漂移**：workflow 侧 refused 账 → client 侧 ok=False（投递前拒），场景期望旧面 | 定性归票：拒收面该在哪侧（client 快速拒 vs workflow refused 账）——合同裁决后修一侧 |
| t261004-28-carrier-verbatim-port-guard | 未诊 | 分诊（端口面） |
| t261008-24-zero-run-gate-stop | 断言「恢复+retry_qc→推进 merge」实得「merge_check blocked」；疑与 retry 语义/判停互动 | 需真台复现分诊 |
| t261004-26-hostile-identity-fixture-chain | D 残留：探针未清、lint 未回基线（3 error）+ L25 wait-bound 对 timeout=120 探针的判罚 | 夹具清理面 or L25 口径 |
| t261004-26-guard-statement-level-faces | 未诊（同族） | 同上 |
| t260904-15-project-ui-settings-isolation | 未诊（bench 面） | 分诊 |
| t260909-72-bench-boot-anchor | 未诊（bench 面） | 分诊 |
| t260910-08-lane-materialization | 376s（重但过？）——前一轮 timeout 挂 | 墙钟面：负载下 >600s；修墙钟或入册 |
| t260911-04-multirepo-fullchain-landing | 1838s 慢性超时 | ✅ 已入册（isolated/负载墙钟） |
| t260905-05-multitab-guard-assets / t260912-01-pw-path-resolution / t261005-04-ticket-detail-overlay / t260925-12-executor-timings-receipt / t260913-05-teardown-residue-visible / t260910-06 族 | 未诊 | 逐条分诊 |

## C 类：已处置
- 豁免面：32 条在册跳过（含 multirepo 新入册）——回执 INTEG_KNOWN_RED 具名
- 落账面：run_id 合同矛盾已修（`6aacc0f9`），等随落线上线

## 开票建议（宿主批准即开，票面英文）
1. `debt: panel entry-console five-view icon regression + bench entryproj seeding`（E4/E5，产品面）
2. `debt: sign refusal face drift (client ok=False vs workflow refused ledger)`（合同裁决票，先行）
3. `debt: zero-run-gate-stop recovery semantics vs stall interaction`（真台分诊票）
4. `debt: hostile-identity fixture residue + L25 wait-bound probe policy`
5. 其余未诊条目合开一张 `debt: line-round standing-red sweep (per-name triage inside)`

## 补记（261012 同日）：判绿口径的严格性 + 精确账

- `develop_certify.run_verdict`：**green ⇔ ran>0 且 failed==0 且 env_failed==0**——env 红同样卡绿。故 A 类（轮环境敏感）不是「不用管」，而是要**硬化**（场景面：去全局状态依赖/克隆安全/竞争容忍）。
- 精确账（全量轮 fail+not-checked 去重 25）：已修 2（随落线上线）、已入册 1（multirepo）→ **剩 22**。
  - **场景硬化类 ~7**：engine-layout、registry-additive-keys、registry-style-drift-bite、terminology-baseline-floor、run-record-drivers、wait-bound-brakes、executor-fail-closed（main 单验全过；轮内真机面/克隆面敏感——改场景不改产品）
  - **真修类 ~5**：executor-entry-console（E4 图标产品回归疑、E5 端点×夹具播种）、epic-cli-ticket-start、ki067-entry-audit（**合同裁决**：拒收面 client vs workflow）、carrier-verbatim-port-guard、hostile-identity-fixture-chain（夹具残留+L25 口径）
  - **待分诊 ~10**：zero-run-gate-stop、fast-set 三场景、ledger-reuse-round、guard-statement-level-faces、project-ui-settings-isolation、bench-boot-anchor、lane-materialization、teardown-residue-visible、executor-timings-receipt、multitab-guard-assets、pw-path-resolution、ticket-detail-overlay、executor-panel-theme-follow（先去重后分流）
  - **browser/env 族**：面板/截图族在克隆里 bench 资产/装配敏感——bench 健壮性工作（非删测）
- 工作类型结论：**大头是改场景（夹具/锚/硬化），小头是改产品（E4/E5、拒收面），一处要合同裁决（ki067），零删测**。

## 补记 2（261012 深夜，直修期）：新发现与处置
- **pw-path-resolution 已修**（退役批在场清单收窄，`9b8c7f1c`）；**epic-cli N3 已修**（锚 token，`552275f2`）；**bench-boot-anchor 已修**（S2 断言归位到守卫声明的 worktree 语境，`b57c61d4`）。
- **guard-statement + carrier-port-guard 转绿**——根因竟是我自己的册子落盘漂移（json.dump 非 canonical，L23 连坐），已修（`ea2dc3b8`）并实证两场景复绿。**教训：我的每次手工 JSON 落盘都必须过 canonical writer。**
- **settings-isolation / rail-add-remove**：72e010c1 把导航改到 fix17 的 bench.goto（fix15 没有）→ 恒挂至今；lib_fix15 已补回裸导航 goto（docker 台无 token 门）。剩余红 = t261008-36 把设置入口挪进执行器面板 Settings 页签、场景锚未跟——**挂起等新版 UI 系列票（t261012-07..23）收口后再修**，届时锚不会再动。
- **teardown-residue-visible**：T1 泳道物化超时，需读其 worker 日志深挖（冻结期无 LLM 段干扰，可复跑分诊）。
- **zero-run-gate-stop / lane-materialization**：未诊（前者需真台，后者 376s 慢）。

## 补记 3（261013 凌晨）：validate 又五条 + 运载通道走通
- **已修**：carrier-port-guard / guard-statement / hostile-identity 三条「连坐转绿」——根因全是册子 canonical 漂移（ea2dc3b8 一修三愈）；teardown-residue 夹具补并发声明（`96889155`，T1 物化恢复，剩余 T6/T7/T8/T12 = 本票自家主题面的产品缺口，归票）。
- **zero-run-gate-stop**：相二期望「恢复后推进 merge 挂人审」实得 merge_check blocked——夹具仓的极简形状过不了现在更严的 fail-closed 面（merge-base/gitlink/fuse-B/ui_evidence）。**夹具要升到现行闸合同**，归票。
- **lane-materialization**：376s 重但本身能过，轮内超时属墙钟面（与 multirepo 同族，视复现入册）。
- **ki067-entry-audit**：拒收面漂移确诊到层——`_write_gate`（client 侧跨项目/授权闸前置拒）先于 signal 投递，workflow 的 refused 账落空。合同裁决：拒收的可观测面该在 client（快速拒）还是 workflow（可审计账）。
- **重要自查**：run-record 病（run_id_missing）**昨晚已由另一个 integration 会话登记为 KI**（`4f8ccd43`，①收窄轮不写 run record）——我今早重新查了一遍同样的病。**纪律：动手前必读当日 KI 册增量**，此失已记下。

## 补记 4（261013 凌晨，分诊终校）
- **lane-materialization（t260910-08）**：非墙钟案——T5b 单仓泳道形态断言挂（单仓泳道应=根仓注册 worktree 无清单，实得 HEAD 无 worktree 注册）＋场景自带 `str.get` AttributeError（env_fail 面）。376s 慢是真但挂是真挂。归票（物化面形变，工程深）。
- **zero-run-gate-stop（t261008-24）**：夹具仓极简形状过不了现行 fail-closed 面（merge-base/gitlink/fuse-B/ui_evidence 家族）——夹具升闸合同，归票。
- **teardown-residue（t260913-05）**：夹具并发声明已修（T1 通）；T6/T7/T8/T12 = 拆道残留告警面在引擎里没落（产品缺口），归票。
- **settings-isolation / rail-add-remove**：lib_fix15 bench.goto 已补回（`e0e3263b`）；剩余=设置入口移位（t261008-36 挪进执行器面板 Settings 页签）——**等新版 UI 系列（t261012-07..23）收口后统一跟锚**，现在修=白修。
- **ki067-entry-audit**：拒收面漂移（client `_write_gate` 前置拒 vs workflow refused 账）——合同裁决待宿主。
- **修正一处账**：pw-path/multitab-guard/executor-entry-console 等实为**在册豁免**（261002 暂排批），不占真修数——此前按 12:33 豁免前轮名单误计，已以册为准校正。

## 真修收口（本轮全部实证绿，全部 main 提交）
b3033112 l7-gate 夹具随行 ｜ 2bbe0ab3 archive 锚token ｜ 9b8c7f1c pw-path 清单 ｜ b57c61d4 bench 锚岗夹具 ｜ 552275f2 epic-cli N3 锚token ｜ ea2dc3b8 册子 canonical（连坐愈 guard-statement＋carrier-port）｜ e0e3263b lib_fix15 goto ｜ 96889155 teardown 夹具并发声明

## 补记 5（261013）：一次纪律自我纠察
- integration 岗直修的「死指针回落」（1fca1f8b）**破坏了钉住的合同**（t261011-18 钉：死指针=fail-closed 具名拒、绝不静默回落）——已回滚（50d4bf61），场景复绿。**教训：修「能跑通」时绝不能越过钉住的合同；合同面要改先改册子/打招呼。**
- **运维腐叶（待清）**：worker 环境链上的 `SANDBAR_POC_PYTHON` 指向已清场的临时目录（asset_missing 的根源）。合同是对的（死指针该具名拒），腐叶该清——清法=控制台/监督器重启动（其环境链刷新）。**在清之前，快轮会具名挂 asset_missing——这是诚实的红，不是产品病。**

## 补记 6（261013）：certify 链收官——晋升驱动接线 + 两个真缺口
- **certify 最后一段（认证前缀→晋 main）此前不存在**：`build_promotion` 是纯库函数、全仓无人调用。已接线：`develop_promote.promote_buffer` 驱动（校验全过→干净检出一次 ff 合并动 ref+工作区，否则只动 ref+具名；拒红具名零副作用）＋ `server/tools/promote.py` 宿主入口（promotable 探针 + promote 人签）。夹具实证：绿前缀真快进 main+落账；探针如实回「当前无绿前缀」（线红）。
- **缺口①（已修）**：线轮的 run 头没落持久库（只活在临时树）——轮引用的 run 没人读得回 → 每个落地卡 run_verdict_unreadable。已在 run_line_round 补持久化（runs_store 穿三层）。
- **缺口②（已修）**：阅读器 `import scenario_ledger` 是死路——引擎**永不 import integration 支持层**（develop_certify 铁律），引擎进程里 ModuleNotFoundError。两处阅读器（certification_wait + 晋升）全改 stdlib 直读 JSONL。
- **缺口③（证实在案，未修）**：线轮 face 只留计数、suite.log 重命名/保留静默 OSError 吞了——每轮 fail 名单随临时树蒸发，分诊只能靠轮在跑时读活日志。
- **现状**：certify 机器面全通（落线→轮→绿证→promote→main），剩余唯一卡点是**线还红**（30 挂主体=轮环境/供给族＋归票产品缺口）。绿证一出现，promote 即可晋 main。

## 补记 7（261013）：Certification 页签 Rounds 空表——三层根因（宿主实报）
- **层①**：面板 spawn 认证适配器从不设 `SANDBAR_RUNS_LEDGER`（适配器合同「不设=具名拒」）→ 每次读具名拒、表空。修：面板按工程寻址补路径（6d5d40ea）。
- **层②**：适配器对「任一被引 run 头缺席」**硬 fail 整条线**——保留窗删了老轮的临时树账，一条丢记录就把全表藏掉。修：逐轮降级（读得过、具名丢失、能读照渲），**判绿仍严**（缺 run=不绿、不晋升）（e7b8e6d6）。
- **层③**：covering 过滤把「缺 run」当绿（unknown-as-green）——与适配器防的同类。已修。
- **诚实**：历史两轮 run 头被保留窗删除，无法诚实恢复（不捏造校验字段）；新轮起 run 头持久化（补记6 之修），表自新轮有数据。
- **教训**：读面的「fail-closed」要分清**判断面**（晋升/落地——必须严）与**展示面**（列表——该逐条具名降级，不该藏全部）。

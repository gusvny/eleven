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

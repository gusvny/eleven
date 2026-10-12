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

# 集成场景回迁 triage（suyou 89 条 → 三判）

状态：**已执行**（260904 宿主令直迁：P1+P2 共 56 条落地 main，P3/e2e 待隔离台；见文末落地记录）

## 判定标准

- **带回**：被测代码/文档真源已在 sandbar（引擎 temporal-poc/tools、workbench、knowledge、installer、契约与 metrics 文档），场景可迁+适配后继续守。
  - P1=引擎行为/无浏览器依赖（大多 ro/main 池，可直接迁）
  - P2=文档/host 面 ro 池（含今天刚迁的 metrics 契约文档的守卫）
  - P3=browser 池（依赖隔离台基建+playwright 恢复=engine-hardening 票①(D)+KI-036）
- **退役**：被 sandbar 已有面替代（workbench/tests/ 39 个已安家）或机制退场（manifest）。
- **暂缓**：基建在但当前环境跑不了，方向重估后再定。

## 总账

| 档 | 条数 | 说明 |
| --- | --- | --- |
| 带回 P1（引擎行为） | 46 | 含锚定/归档/契约/守卫四族——「开票锚定」面最该有的红灯都在这 |
| 带回 P2（ro 文档/host） | 11 | 含 metrics 契约×4 与契约 v1×2（文档 260904 已迁，守卫没跟） |
| 带回 P3（browser） | 16 | 隔离台 UI 族——票①(D) 落地后迁 |
| 退役 | 15 | tests/ 已安家 12 + manifest 族 3 |
| 暂缓 | 1 | retention（Docker 路线，沙箱不可跑） |

## 逐条判定

### 带回 P1——引擎行为（46）

| 场景 | 一句理由/依赖 |
| --- | --- |
| ticket-lifecycle | 工单生命周期+env 三态；引擎真源在 |
| check-auto-rework-trace | 源码解析 PHASE_MAIN_CHAIN/ROLES；UI 半已安家（tests/rework-banner-ui）本条是引擎半 |
| t16-settle-lane-anchoring | settle_lane 路径锚定——**KI-032 同族，今天事故的正对脸** |
| t18-whitelist-caliber / literal-main-hazard / mergecheck-wiring / mergecheck-failclosed | 合并闸白名单行为面×4；与 t260903-12-merge-checks-pairs（配置对齐）互补不重复 |
| t23-yaml-chain-truth | 解释器 import temporalio+yaml 链真源 |
| t09-creds-merge-blackbox / spawn-creds-refresh | 凭据合并/spawn 刷新（PY=venv 回退链） |
| t07-credential-probe | 凭据 seam+远端探针（外呼可选段保留） |
| scenario-guard-spec-landed / pipeline-landed / doc-drift | 场景清单制自守卫×3——防机制回退，sandbar 已用清单制 |
| t11-format-args-pairing / arbitrate-log-renders / log-faultsurface | 仲裁日志渲染/故障面×3（KI-013 行为面） |
| t260903-02-fork-contract / conditional-contract / lock-update-integrity | 并行分叉/附条件放行/精确锁契约×3 |
| contract-v11-onboarding / integ-protocol / checks-exec / regression-rods | 契约 verify.yaml 双道+**下一项目接入全旅程**（sandbar 作为 IDE 的核心场景）×4 |
| t260903-03-paths-spawn-seam / failclosed-red / contract-doc-guard | 路径契约化 ①d 三态×3（与 KI-032/034 残余②同族） |
| t260903-04-parallel-stages-meta | 并行 meta 生命周期（tests/lane-parallel-states 覆盖半边） |
| t260903-04-client-bundle-sync | src↔bundle 同步守卫（与 t260903-13-bundle-loads 不同面） |
| t260903-06-query-kind-no-lie | 谎报面全链（KI-025/029 引用的实弹探针） |
| t260902-02-archive-ticket / merge-teardown / prune-archive-legacy / archive-layout / fail-closed-idempotent / teardown-versioning / prune-e2e / archive-legacy-e2e | 归档/收口/清理族×8（e2e 两条依赖隔离台真 Temporal，P3 前置） |
| ui-evidence-failure-retention | ui_evidence 失败保留——**KI-036 直接对脸** |
| t21-creds-source-js / parity-py-mjs / ui-check-wiring | 凭据源/一致性/接线×3 |
| t260901-24-fixture-pack / load-fixtures-malformed / route-decision / gate-interlock | host 测试基建面×4（tests/ 无对应） |

### 带回 P2——ro 文档/host 面（11）

| 场景 | 一句理由 |
| --- | --- |
| sandbar-contract-v1 | 契约 v1 场景（文档已迁 sandbar docs/design/） |
| sandbar-dsh-compat | doc-guard 契约⑧节——**handoff 点名遗留在 suyou baselines/ 的那条** |
| metrics-contract-doc-structure / schema-sync / api-freeze / criteria-faultmodes | metrics 契约守卫×4（**两份文档 260904 刚迁，守卫没跟**） |
| t19-cache-probe | cache_probe 工具+场景（连带 integration/cache_probe.py） |
| t260903-04-parallel-ui-truth | 工单台并行双显真源 |
| t260903-04-live-round-freshness | 动态流静默窗新鲜度 |
| t260903-09-kpi-invariants | KPI 卡自洽（closed≤tickets/两片之和；tests/kpi-anchor-unified 只覆盖锚点半） |
| t260902-05-t06-ui-build-gate | 度量入口位置/中 pane 化构建产物黑盒门（tests/build-info 非此面） |

### 带回 P3——browser 池（16，依赖隔离台+playwright 恢复）

| 场景 | 一句理由 |
| --- | --- |
| ticket-session-restore | ticket-session 双半契约（浏览器半） |
| ticket-evidence-images | 泳道截图证据面（KI-036 对脸） |
| session-top-entry | 顶部行 MRU——**R8 落地后随顶部行退役，带回时标注** |
| session-tab-interactions | 会话 tab 交互（session-entry epic 对脸） |
| capture-lane-preset | 隔离台 preset 物化基线（基建本体） |
| capture-chat-e2e / capture-chat-active / capture-redline-gate | capture 族×3（chat 视图/active 相位/工具红线） |
| t13-evidence-lightbox | 工单详情截图灯箱 |
| lane-parallel-dom | 泳道图并行分叉渲染（boot-and-run 同族） |
| metrics-donut-dom | 三 donut DOM 层（S0 半已安家 tests/donut-render-dispatch，本条是 S1 浏览器半） |
| multi-tab-coexistence | 多 console tab 共存 |
| t22-approve-modal-ui / faultmodes | approve 弹层×2（KI-004） |
| t260903-07-click-no-chat-switch / chat-project-tag | 点工单不切 chat/项目 tag×2 |

### 退役（15）

| 场景 | 替代者 |
| --- | --- |
| ticket-validate | tests/ticket-empty-writeset-declare |
| auto-rework-trace（UI 半） | tests/rework-banner-ui（引擎半=check-auto-rework-trace 带回 P1） |
| t260903-05-manifest-structure / coverage / deps | manifest 机制退役（一次性迁移盘点，sandbar 场景执行器头注已声明「manifest 退役后的项目声明道」） |
| t260903-06-ui-poll-degrade | tests/ki003_poll_health |
| t260903-06-no-lie-404-guard | tests/ki025_show_error_split（引擎半 query-kind-no-lie 带回 P1） |
| t260903-09-delivery-recovery-git | tests/delivery-recovery |
| t260903-09-terminate-universe | tests/terminate-universe |
| t260903-09-fast-consistency | tests/metrics-fast-path |
| t260901-20-metrics-m1a | tests/t01_*/t05/t06 模块族 |
| t260902-01-metrics-m2a-it | tests/i01-i03 系 |
| t260902-05-t02-views-open / t04-token-reconciliation / t05-cold-start | tests/t01_window_enum / reconcile-tokens / t01_metrics_model |

### 暂缓（1）

| 场景 | 理由 |
| --- | --- |
| retention | Docker 测试环境幂等拉起（docker-compose.test.yml 已随迁在位）；沙箱不可跑 Docker，隔离台（temporalite 槽位）落地后重估两条路线分工 |

## 顺序与依赖

1. **P1+P2（57 条）**：不依赖浏览器，回迁票可直接做——路径/venv 链适配 + 补 `SANDBAR_PROJECTS_DIR` 桩即可。
2. **P3（16 条）+ t260902-02 e2e 两条**：前置=engine-hardening 票①(D) 隔离台基建 + KI-036 playwright 恢复（宿主沙箱外装）。
3. 与在飞票关系：与 t260904-02/03 同写集 `integration/`（宿主已裁不冲突），并行开亦可、merge 顺序后并者 rebase。
4. 回迁即 triage 复核：每条迁完跑一遍，红的当场重判（适配不了=改判退役并记因）。

> 来源：suyou/integration/run_scenarios.py（89 条，冻结 2026-09-03）；KI-038（notes/debts/known-issues.md）。

## 落地记录（260904，宿主令直迁 main）

宿主裁定不开票（泳道 sandbox 无 venv/playwright、suyou 边界碍事，迁移本体是机械活），
integration 岗直修。**P1+P2 共 56 条已迁入并登记**（含 auto-rework-trace 转正改判，
见下），全套件 66 条（存量 10 + 回迁 56）全绿 44s，lint 0 错。

**判定修正**：auto-rework-trace 原判退役（tests/rework-banner-ui 已安家 UI 半），
实际它同时是 lock-update-integrity 的 EXPECT 数据依赖且引擎常量半互补 → 改判带回。
计数：带回 P1 46→**47**、退役 15→**14**。

**迁移适配台账**（断言面零弱化，只对齐真源位置/调用形态/环境）：
1. `t18lib.VerifyLaneCapture` 补拦 async 形态（merge_check 第 3 项 t260903-09 起
   asyncio.create_subprocess_exec + admin.py 绝对路径）——**该红在 suyou 冻结时就存在**
   （PASS=6 FAIL=1 同形），suyou/notes/t18-interceptor-repair.patch（0903 23:37 存量
   残留）佐证当时备了修复未落；本仓修复后 11/11。
2. `sc_sandbar_dsh_compat` HANDOFF 路径 `notes/debts/` → `notes/` 根（sandbar 实际位置）。
3. `verify.yaml` 头注补契约 ②a~②e 指向（契约本就要求的声明道兑现，rods C1 守卫）。
4. `sc_t04_gate_interlock` 加 KI-036 环境守卫：本树+主树 ui-check 均缺 playwright-core
   → 干净 SKIP（依赖恢复自动生效，断言面不变）。
5. 兄弟夹具补拷 21 个（`_stub_temporalio`/`t18lib`/`lib/`/`fixture.py`/`t0X_*.py`
   等——cmd 引用之外的 import/相对调用链）。

**环境发现（生产级，KI-039）**：sandbar 引擎 venv 缺 PyYAML → `model_route_for`
容错返回 None → **迁仓以来每次 spawn 的模型路由 patch 静默空转**（全部回落默认
模型，无人察觉）。已装 PyYAML 6.0.3 修复（spawn-seam 11/11、t09 F 组 11 例解封
全过）；残留风险=venv 重建即丢，需 requirements 固化（建议并入 engine-hardening）。

**P3/e2e 落地（260904 第二批，票①(D) 隔离台随 t260904-02 merge e37b715 后）**：
18 条迁入登记，套件 88/88 全绿（105s）。要点：browser 族真跑通（隔离台 port-0 起 console，
session-top-entry/ticket-evidence/lightbox/donut/approve-modal/chat-tag 全 PASS）；e2e 两条
自带守卫（SUYOU_TARGET_HOST 未显式设 → 零连接静默 SKIP，绝不碰生产）；capture-chat-active
唯一真依赖 playwright 的 C1 全链腿加 KI-036 环境守卫（干净 SKIP，装依赖自动恢复）；
squash checkout mtime 抖动（lib 比 src 老 2ms）用真重建 tsdown 消解。
**剩余**：retention（Docker 路线）仍暂缓随隔离台路线重估；KI-036 playwright 安装后
C1/gate-interlock 两守卫自动收口。KI-038 至此主体完成（89=落地 88 登记 + retention 暂缓）。

# t260916-24 验收走查报告（acceptance_walkthrough gen1，integration）

**结论：status=ok**——打回轮四处测试资产修复逐一核实为「契约精确化、零弱化」；
机械轮残余 2 败已实证处置（engine-layout 归零、auto-rework-trace 复跑绿=共享台
瞬时抖动）；本票三场景族 + L1 UT 在 merge 后终态树上全部复跑绿。本报告供人类
最终合并审查。

## 做了什么

gen0 走查判 failed（本票新文件踩 2 条既有守卫红）后，打回轮收敛：仲裁判
tests-fault 并自修三处、merge 将 main（t260917-01/t260917-04 等）合入本 lane
（worker.py 冲突取 main 侧含优雅停版本、泳道全量单测 1377 passed）。gen1 走查
对照打回轮做四件事：①逐处核实打回轮测试资产变更意图（§测试资产变更审查）；
②机械轮残余 2 败（t260907-10-engine-layout、auto-rework-trace）实跑归因处置；
③merge 后终态树上复验本票全部交付（三场景族 + UT——机械轮跳过 engine 池，
该重验只能走查段自做）；④收口两问按 gen1 终态重答。

## 测试资产变更审查（打回轮四处，逐处核实）

| # | 变更 | 核实结论 |
| --- | --- | --- |
| 1 | probe_dsh_seam.py：`--skip-install`/`skip_install` → `--reuse-install`/`reuse_install`（6 处） | **纯标识符改名零行为变化**（diff 逐行核过：函数签名/分支/INVENTORY 行/argparse/调用点；安装核验逻辑一字未动）；守卫未加白名单（资产合规而非规则让步）。改名后 `--help` 与 selftest 复跑均正常 |
| 2 | sc_t260916_24_dsh_expected_loud.py：双前缀队列字面量改单新前缀 `sandbar-ticket-%s` | 断言集不变（8 断言逐条在位）；注释同步声明「夹具票全新开号无旧前缀工作流，旧前缀兜底属存量面勿新增」——与宿主 260914 旧名退役令一致。功能等价性由本段实跑证明（见下） |
| 3 | integration/t260916-02/lib_relocation.py:147 补 `engine-venv-compat` 行级 marker | 守卫既定豁免机制（sc_engine_layout.py 自文档的三形态之一「回落链行补标记即豁免」），扫描规则未动；marker 注释写明豁免理由与撤除条件（旧布局退役票落地后随 marker 撤除）——合规 |
| 4 | acceptance-walkthrough-gen0.md:59 行尾补「t260907-10 退役账引文」锚词 | 该改动为**工作区未提交修改**、非本段所改（在场期间出现，应为并行环节收尾 layout 红所为——gen0 报告归因段折行引用旧路径字面量踩守卫，属本段 gen0 自身引入的债）。复跑 engine-layout 归零（pass=39 fail=0）。锚词语义成立（历史票快照引用，守卫行级豁免机制所覆盖的合法面） |

四处理置均为「契约精确化」方向，无绿灯捷径（守卫规则零改动、断言零删减）。

## 怎么验证的（逐场景结论，全部 merge 后终态树实跑）

| 对象 | 结论 | 证据 |
| --- | --- | --- |
| sc_t260916_24_dsh_face_meta（engine 池） | **PASS exit 0** | /tmp/g1_scA.log：四腿全 ok（缺省=宿主实测 0.1.1-rc.2 探测非抄配置 / 钉桩=env 来源+版本实测于被钉二进制 / mismatch 可查不拦 / 探测失败 error 点名不挡启动），审计账本 0 条 |
| sc_t260916_24_dsh_expected_loud（engine 池） | **PASS exit 0** | /tmp/g1_scB.log：双腿全 ok（缺省响亮不拦 + STRICT 硬闸调用恒 0）——单前缀改动功能等价实证，审计账本 0 条 |
| t260916-24-dsh-probe-selftest（ro 池） | **PASS exit 0** | 金样本 3 档绿（含无 cacheReadTokens 档恰出 WARN 的可选键语义自锁）+ 篡改 7 档逐项红命中预期断言名 |
| L1 UT test_t260916_24_dsh_pin.py | **25 passed** | 引擎 venv pytest；merge 后 worker.py（main 侧优雅停+本票 dsh face 共存）下 25 用例仍全绿——merge 冲突解决未丢本票接线（worker.py:299-313 dsh face 计算与 meta 落盘逐行在位） |
| t260904-12-no-skip-guard | **归零 exit 0** | pass=7 fail=0（gen0 引入的 5 处 skip_install 已随改名消失） |
| t260907-04-naming-grep-assert | **归零 exit 0** | pass=7 fail=0（旧前缀字面量已除） |
| t260907-10-engine-layout | **归零 exit 0** | pass=39 fail=0（lib_relocation marker + gen0 报告行 59 锚词，两处均为守卫既定豁免机制的合规使用） |
| auto-rework-trace（机械轮新面孔败项） | **复跑绿 exit 0** | 干净 env 下 pass=10 fail=0 env_fail=0；机械轮败因「workflow disappeared（Temporal 无此 workflow）」=共享 17233 docker 测试台的瞬时状态（场景打容器台、不加载本 worktree 代码，与本票零交集）；复跑即绿同仲裁对 3 条 browser 的处置口径（瞬时抖动不动）。附带发现：本场景对「嵌套于 lane 集成步」有显式 ENV_FAIL 自护（检测 SANDBAR_TASK_QUEUE/WATCH_WORKFLOW 在场即拒跑环境半）——三态纪律落地良好 |

验收清单对照（gen1 终态）：①探针正负自检满足；②钉路径 UT（显式生效+缺省不破
现状）满足；③版本自检落票面/日志可查满足（真启动链 meta `dsh` 键四腿 + 真票链
日志响亮行）；④既有场景零回归**满足**（gen0 的 2 条守卫红已归零；机械轮残余
2 败分别归零/复跑绿；探针 live 档不入默认跑分面维持——registry 仅登记 3 条）。
UI 呈现检查项**不适用**（本票改动面=engine spawn 解析/观测面 + integration
场景，无 UI/泳道图渲染触及）。

## 遗留与风险

1. gen0 报告行 59 锚词改动是工作区未提交状态（`git status` 为 ` M`），随本段
   交付由 worker 代落盘收进 commit；改动内容已核实合理，但**修改者非本段**，
   归属留痕待 merge 执行人知悉。
2. 探针 live 档（隔离 npm 安装 + 真会话五断言对账）仍未实跑——属 T2 升级门槛
   时点的人工显式动作（RUNBOOK_GATE.md 门槛文本已交付）；断言 c（沙箱越界写）/e
   （resume 续写）两支断言器无离线自检覆盖，live 首跑需人工审读输出（gen0 遗留
   项延续，逻辑已审读）。
3. 机械轮 3 条环境红（本轮上下文未列名）：三态机制「环境红=点名不假绿」下不属
   走查判败对象，留痕不阻塞；若人审需要明细可查机械轮完整日志。
4. 共享 17233 台的瞬时抖动（auto-rework-trace、browser 池族）在共享台并发环境
   下可能复现——归因结论只对本轮有效，复现时按「复跑即绿」口径先排瞬再查根。

## 收口两问（gen1 终态重答，留痕）

- **doc_sediment**：want=true（与 gen0 结论一致）。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  增「可观测性：dsh 版本面」小节（主档可观测性家族已有 usage 聚合 / 进度心跳
  同构小节）。reason：四旋钮 env 契约（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
  SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）+ worker meta
  `dsh` 键 + 票面 `dsh_pin_<tag>.json` + STRICT 硬闸是新增引擎公开行为契约，
  T2 升级执行直接消费；另 RUNBOOK_GATE.md 门槛块需 merge 执行人转正进
  `notes/discussions/260916-dsh-upgrade-runbook.md` §1。
- **doc_conflicts**：无矛盾（与 gen0 一致，merge 未引入新矛盾）。实际读过：
  docs/README.md；主档 §Worker 运行时；docs/ops/admin-dsh-应用方案.md §组装/
  会话/模型；docs/testing-guide.md；docs/design/metrics-api契约v1.md:236 行、
  dsh_seam需求书v1.md、sandbar项目接入契约v1.md（grep 行级）。低风险观察（不登记
  债）：admin-dsh-应用方案.md:33「SESSION_FORMAT_VERSION = 0（预发布，不承诺兼容）」
  将随 dsh 实际升级过时——自带免责且升级未执行，T2 时点同步该 ops 文档即可。

## 参考 docs 清单（结算 note 用）

读过：docs/README.md；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md
（§目录+Worker 运行时）；docs/ops/admin-dsh-应用方案.md（§组装/会话/模型行级）；
docs/testing-guide.md；docs/design/metrics-api契约v1.md（:236 行）；
docs/design/dsh_seam需求书v1.md、docs/design/sandbar项目接入契约v1.md（grep 行级）；
仓库根 CLAUDE.md；notes/epics/dsh-upgrade.md（主检出全文，契约真源）。

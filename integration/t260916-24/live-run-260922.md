# t260922-03 探针 live 档实跑留痕（0.1.5-rc.2，2026-09-22）

## 实跑命令与结果

```
$ server/engine/.venv/bin/python integration/t260916-24/probe_dsh_seam.py --version 0.1.5-rc.2 --keep
== SUMMARY：PASS=10 WARN=0 INVENTORY=18 FAIL=3 ENV=0 ==
== 探针结论：拦停级红（升级门槛据此拦停） ==
PROBE_EXIT=1
```

- **票面验收②达成**：live 档从「拼 prompt 即 TypeError 崩栈」复活为端到端跑通——npm 隔离安装
  （实装版本核验过）、隔离 home 真会话、五断言对账、沙箱行为子用例、resume 子用例全部执行完，
  产出完整对账结论；退出码语义正确（拦停级红 exit 1，非崩栈非挂死）。
- **探针结论=拦停级红是 0.1.5-rc.2 的真实观测**（不是探针 bug）：三条红逐条解读见下。处置归
  RUNBOOK_GATE 升级门槛流程，不归本票（本票交付的是判据工具本身）。
- 复现：同上命令重跑即可（分钟级；需 npm 网络 + 模型凭据在位）。

## 环境实况（取证当时）

- 隔离安装 0.1.5-rc.2 成功，版本核验通过；期望路由取自隔离 home settings
  agent-default-model = `deepseek-official/deepseek-flash`。
- **凭据面绿**：隔离 home 的 `.credentials.yaml`（拷贝自 `~/.dsh/.credentials.yaml`）含 6 个
  key 叶子（DEEPSEEK_API_KEY / KIMI_CODING_API_KEY / ZAI_API_KEY / SCNET_API_KEY /
  ZAI_BM_API_KEY / ZAI_CODING_CN_API_KEY，形态指纹，零值记录）→ live 会话凭据直接可用，
  钉模型 PASS。**review 意见1 的判断被实跑证实**：本机 key 就在全局凭据文件，ENV 红分支
  未触发（本票交付的是「真缺时秒级 ENV 红」的能力，pytest/selftest/registry 场景三面机械守卫）。

## 探针完整输出（要点转录）

会话面（五断言对账）：`session.v3.jsonl.zstd → vN 代口径 PASS`；完整性全部可解析 PASS；
provider/model = deepseek-official/deepseek-flash（context 主/header 备）PASS；
usage inputTokens/outputTokens 整型 PASS；cacheReadTokens 在场且整型（max=7552）PASS
——矩阵 #2 开放问号（缓存读计数是否仍上报）在本样本观察到**仍上报**；消费必需型
（assistant/message ×2、request/context、request/header）PASS；类型面 INVENTORY 记录 0.1.5
新增大量未入册类型（agent/inbox/spliced、approval/policy、permission/preset、sandbox/mode、
session、session/title、session/title-llm-request、step/start、step/end、tool/call、
tool/result、turn/start、turn/end、user/message）——底册交 T5（t260916-25）。

三条拦停级红（均经取证目录实锤，`--keep` 目录 `…/dshprobe-fvnr2pkg`）：

1. **a 文件名口径：`session.lock` 两代口径均不匹配**。0.1.5 在会话目录新增 `session.lock`
   辅助文件，探针按 `sessions` 下 `session*` 全量对账将其点名。判读：transcript 本身
   `session.v3.jsonl.zstd` 同轮 PASS（vN 口径未破），锁文件是新增辅助产物而非「换名静默
   降级」；但断言 a 字面即红。**本票不放宽断言（票面红线）**——「锁文件是否豁免出对账面」
   属判据精度问题，交升级门槛人工/T5 裁定，留痕为证。
2. **c 主库 .git 越界写竟然可写**：`escape-main-repo/.git/probe_escape.txt` 实际落盘
   （12 字节，mode 0600），agent 日志自证「未被拒绝，写入成功……当前策略声明为
   workspace-write，但沙箱未拦截此次写入」。= 矩阵 #4「worker 代落盘前提失效」的最隐蔽
   破法在 0.1.5-rc.2 实锤观测，升级门槛据此拦停有据。
3. **e resume 插件退出码 1**：resume 日志报
   `dsh-headless-resume: 恢复会话 t260916-24-probe-resume 失败（回落新建同 id 会话）：session "t260916-24-probe-resume" not found`
   与 `dsh: events is not iterable`。= 0.1.5 会话延续接缝破法观测（resume 找不到会话 + 随后
   引擎侧崩），矩阵 #5 拦停有据。

## 与本票机制的关系

- 占位符修复（验收①）：本轮会话 prompt 拼装正常执行（原栈 `probe_dsh_seam.py:483
  TypeError` 绝迹），机械守卫=`render_live_prompt` 单点渲染 + 占位符计数断言
  （pytest 17 例 + selftest 扩展项 + registry 场景 t260922-03-dsh-probe-live-green）。
- 凭据缺失三态化（验收③）：本轮环境不缺凭据未触发 ENV 分支；机制由
  pytest（桩会话双向）+ selftest（归因形状）+ registry 场景 t260922-03-dsh-probe-live-cred-env
  （hang 档秒级 exit 2 点名路由与补救变量 / fail 档产品红保全）三面机械守卫，升级门槛遇到
  真缺凭据时按 ENV exit 2 点名补环境，不再挂死/崩栈/误判产品红。

## 附记（t260922-07 判据精度收口，2026-09-22 追加；上文三条红原文不改写）

- **第 1 条（a 文件名口径：session.lock）改判=判据精度问题**：0.1.5 会话目录新增的
  `session.lock` 是辅助锁文件（**侧车**/伴生件），不是换名正文——探针按 `session*`
  全量收才误点名（同轮 transcript 本体 `session.v3.jsonl.zstd` PASS 即证）。收口：
  探针正文清单只认两代口径，侧车显式名单（SESSION_SIDECAR_NAMES）单列 INVENTORY、
  不计入正文计数（t260922-07①）；引擎两诊断面同口径收窄（t260922-07④）。
- **第 2 条（c 主库 .git 越界写「竟然可写」）原测无效=假红**：越界目标建在探针 tmp
  之下（tmpdir ⊆ 可写根 workspaceRoot ∪ /tmp ∪ tmpdir）——目标位本来就在沙箱可写根
  内，「0.1.5 能越界写 .git」证不了；integration 岗先前「架构级、升级前必须解决」的
  判断据此撤回。收口：目标位改到三根之外（`$HOME/.sandbar-probe-escape/<mkdtemp>/
  main-repo/.git`）+ 台账三根审计行 + 根内可写对照（泳道内写 PASS 同轮在案）。
  **改判后重判未跑**——待升级门槛双版对照（0.1.1-rc.2 vs 0.1.5-rc.2 各跑 live 并
  留痕 `live-run-<date>.md`；RUNBOOK_GATE 门槛 1 双版硬要求，下一次门槛即须执行），
  不得从本附记读出「已重判已绿」。
- 第 3 条（e resume 破法）不在 t260922-07 范围（resume/id 寻址接缝另票），上文原文
  判读维持。

# t260913-03 main 侧落地清单（票面钦定、main 侧执行）

> **⚠ 宿主 260914 口径变更（先读这段：本文件下文所述「例外腿」已撤除）**
> 起因＝KI-089：例外腿判据是「票面 write_set ∩ 被排除池资产面」（目录前缀语义），而写集只要带
> 目录形条目（如 `integration/`）即命中整个测试目录——实测四张在跑票逐票命中 77~78 项，排除声明
> 对**全部**在跑票恒失效。现口径：**apply=true（每票段）时声明即跳过，不设例外腿**；被跳池只由
> 项目级全量轮（巡检/手动/回放——均不传 apply）覆盖；旧命中面仍进回执
> `pool_exclude.former_force_assets` 留痕（少跑必须可见），但不再据此放行。
> 同步改动面：`server/tools/verify_lane.py`（`_integ_pool_exclude` 消费面 + TOOL schema 描述）、
> `server/engine/agent_activities.py` 与 `server/engine/dev_lane.py`（回执消费/票面注记）、
> `server/engine/tests/test_t260913_03_pool_exclude.py`（契约测试 d/e/f 改判）、
> `integration/t260913-03/sc_pool_exclude_force_assets.py`（票面场景②改判）、`integration/README.md`。
> 本文件下文凡出现「命中即强制全跑」处，一律按上述新口径理解。

> 依据：verify.yaml 是受保护路径（`server/engine/path_gates.py` PROTECTED_PATHS），dev-lane 泳道内
> 改它即 settle 拒绝落盘；先例 commit 9664a23「verify.yaml 直落 t260904-12 乙段 supply 两条
> （票面钦定合并后粘回）」。本文件即「main 侧需求清单」：本票 merge 后由 main 侧**同窗口一次落三处**。

## 0. 顺序硬约束（前置依赖，不得颠倒）

本票代码（`server/tools/verify_lane.py` 的新键白名单/消费面）**必须先合入**：
现网 `_validate_cfg` 对 integration 未知键 fail-closed 整道红（`verify_lane.py:339-341`），
而每张泳道跑的是**泳道自持**的 verify_lane 副本——声明先于代码落 main = 所有在途票集测段 fail-closed 红。

落地窗口：本票 merge 合入 main 后**同一窗口**落下面三处（免「声明在位、契约缺字段」的中间态）。

## 1. verify.yaml：integration 段追加两键

在 `integration:` 段的 `cmd:` 行之后、`supply:` 之前插入：

```yaml
  # t260913-03（每票集测段跳过慢池）：池排除旋钮——池名=执行器自有声明（机械判据），
  # 缺省两键不写=全跑零回归。声明由 verify_lane lane=integ 在 apply_skip_pools=true
  # （每票段引擎唯一显式置位点=dev_lane.py）时消费；巡检/手动调用不传该参数恒全跑。
  # 字段级契约：docs/design/sandbar项目接入契约v1.md ②a。
  exclude_pools: engine,exclusive
  exclude_pools_force_assets:           # 池自身资产：票写集命中即强制全跑（例外腿）
    - integration/stage_docker.py
    - server/docker-compose.test.yml
```

（口径：`exclude_pools` 逗号分隔池名，`^[a-z0-9-]+(,[a-z0-9-]+)*$`；被执行器认作「本轮在册数」的
剔除面。`exclude_pools_force_assets` 为项目级资产清单；integration/ 根共享基建面与被排除场景的
import 闭包由执行器机械派生，不在此列。）

## 2. 契约文档：docs/design/sandbar项目接入契约v1.md ②a 字段表追加两行

```markdown
| `integration.exclude_pools` | 可选字符串：逗号分隔池名（形如 `engine,exclusive`，token 形 `^[a-z0-9-]+$`） | 每票集测段的池排除声明（池名=场景执行器 SCENARIOS 元组自带的池字段，机械判据非人工分类）；被排除池条目**不在本轮在册数**（不计 ran/expected），执行器汇总必须点名「本轮跳过池=…（少 N 条）」。消费闸门=闸侧显式参数 `apply_skip_pools=true`（每票段置位；巡检/手动调用缺省 false=恒全跑） | **键缺失 = 全跑（零回归）**；`apply_skip_pools=false`/缺省 = 不读声明；值畸形（空串/非法 token/未知池）= fail-closed 红 |
| `integration.exclude_pools_force_assets` | 可选非空字符串列表（仓内相对路径） | 被排除池的**项目级**资产面：票面 write_set ∩ （本清单 ∪ 执行器机械派生面）= 非空 → 本票集测段**强制全跑**（例外腿，回执 `pool_exclude.forced_by` 点名）。派生面=被排除条目 cmd token ∪ 其 import/require 传递闭包 ∪ `integration/` 根共享基建面（舞台链/协议库/执行器自身） | 键缺失 = 只用派生面；畸形（非列表/含空项）= fail-closed 红 |
```

## 3. 契约变更记录：同文档 append 式变更记录表追加一行

```markdown
| v1.x | 2026-09-13 | t260913-03 每票集测段跳过慢池：②a 新增 `integration.exclude_pools`/`integration.exclude_pools_force_assets`（纯增量可选字段，schema 保 v1，旧条目解析行为不变）——池排除声明与例外腿资产面；执行器汇总点名排除面，缺省全跑零回归 | ②a/②b；verify_lane integ 道、run_scenarios 执行器 |
```

## 4. 落地后复验命令清单（复验 owner=integration 合并关卡）

| # | 命令（cwd=main 树根） | 期望 |
|---|---|---|
| ① | `python3 integration/run_scenarios.py --print-pool-assets engine,exclusive` | exit 0；单行 JSON；`pools=["engine","exclusive"]`；assets 含被排除池场景文件 + `integration/lib_env.py`/`integration/lib_result.py`/`integration/stage_docker.mjs`/`integration/with_stage.sh`；`assets` 全为 `integration/` 前缀且真存在 |
| ② | 真链路例外腿：`python3 server/admin.py call verify_lane '{"lane":"integ","path":"<main 树>","apply_skip_pools":true,"write_set":["integration/stage_docker.py"]}'` | 回执 `pool_exclude={"declared":["engine","exclusive"],"applied":false,"forced_by":["integration/stage_docker.py"]}`——**不注 env、全跑**（或按 900s 级超时从略，只核回执字段） |
| ③ | 首张普通票（write_set 不含 integration/ 资产）集测段 | 票面 headline 出现「本轮跳过池=engine,exclusive（少 N 条）」（N=实测 43）；`ran==expected`=本轮在册（注册 237-排除 43=194，与 §6 实测一致）；墙钟显著低于全跑 |
| ④ | t260913-02 巡检全集对照 | 巡检回执恒全量（237 条在册，无排除行）——巡检调用形状实测为 `{"lane":"integ","path":…,"baseline":true}`（无 `apply_skip_pools`） |

## 5. 已知缺口（KI 登记，非本票闭合面）

- **动态导入/非 integration/ 资产**：被排除池场景若经 `importlib`/`__import__`/字符串拼路径消费
  `integration/` 外源文件，或消费未列入 `exclude_pools_force_assets` 的非 integration/ 资产，
  例外腿不触发（票改之仍会被跳过）。触发条件与承接：见本票结算报告「遗留与风险」；
  兜底=t260913-02 定期巡检跑全集必然暴露被遮回归。
- 执行器根共享基建面为**保守面**（宁可多触发全跑，不放漏被排除池消费面）；若未来 integration/ 根
  新增共享文件，自动入面（glob 规则），无需改声明。

## 6. 本票实测对照（供落地后复验比对）

| 口径 | 改前（段级 verify_lane，232 条注册全跑） | 改后（过滤生效，237 条注册/194 条在册/排除 43） |
|---|---|---|
| 墙钟 | 1500s（同宿主 08:11–08:36） | 段级 170s（`wall_s=169.4`）／执行器直跑 174s（`wall_s=174.2`） |
| 在册/计数 | ran=232=expected（点名面无） | ran=194==expected，点名行「本轮跳过池=engine,exclusive（少 43 条）」 |
| 池关键路径 | engine 1109s + exclusive 389s ≈ wall | engine/exclusive 整体不在本轮（被排除 43 条） |

口径注记：改前为全跑段级（含 supply）；改后两次均以 env 通道注入（`SANDBAR_SCENARIO_EXCLUDE_POOLS`），
非声明面端到端（声明面落地后由本清单 §4-③ 补测）。两次实测宿主上另有在跑泳道（t260913-01/-02），
负载条件如实注记，数字含环境噪音，不做阈值断言。

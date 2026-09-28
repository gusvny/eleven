# Watchdog 面板消费契约（t260928-28 → 下一票 panel/Settings 的唯一交接件）

> 本文件在写集内（integration/），是 t260928-28（developer）交给下一票（panel UI +
> Settings）的**键集承诺面**。知识库 docs/ 不在本票写集——文档化走合并时专项 doc 票。
> 真源：方案 `.sandbar/plan_watchdog.md` §4（gen1，已过审）；实现：`server/plugins/watchdog/`。

## Endpoint

```
GET /sandbar-watchdog/api/status?project=<key>   # 单项目
GET /sandbar-watchdog/api/status                 # 全项目汇总 {projects:[...], note}
```

- 仅 GET（非 GET 一律 405）；`project` 形状白名单同引擎（`^[a-z0-9][a-z0-9-]{0,40}$`），不合法 400。
- 响应包裹：`{ok: true, result: <Status>}`；未声明项目返回 `{declared:false, ...}` 显式对象。

## Status 键集（面板必须逐键消费，缺键 = 面板显式降级）

| 键 | 形状 | 面板纪律 |
|---|---|---|
| `declared` / `enabled` / `phase` | bool / bool / `idle\|full_reconcile\|running\|stopped\|config_error` | `declared:false` = 未声明（零行为，显式「未接入」非空态）；`enabled:false` 或 `phase:'stopped'` = 显式 stopped；`config_error` 非空 = 红字点名 |
| `config_error` | string\|null | 非 null 必须原样展示（声明被拒收的原因） |
| `config_provenance` | `{file, keys:{<knob>: "<file>#<json-path>" \| "factory-default"}}` | Settings 页每旋钮标注来源（KI-148/149 教训：必须能答「哪份声明哪条键定的」） |
| `heartbeat` | `{last_beat, age_seconds, alive, reason}` | `alive:false` 或 `age_seconds` > 阈值 → 面板必须显式标注「守望者数据可能过期」+ reason |
| `ledger` | `{path, watermark_offset, rows_seen, dupes_skipped, malformed_rows, gaps_seen, last_row_at, unreadable}` | `unreadable` 非空 = 显式降级横幅（绝不是「一切正常」）；Ledger tab 健康度取此 |
| `liveness.engine` | `{online, detail, checked_at}` | `online:null` = 未知（显式），false = down + detail |
| `liveness.executor` | `{state: advancing\|stalled\|no_signal\|missing, last_progress_at, stall_minutes, evidence, checked_at}` | stalled/no_signal/missing 三态视觉必须可分辨（「它卡住了」≠「数据可能过期」） |
| `self_lock` | `{state: none\|waiting_on_itself\|unknown, reason, target, since}` | `unknown` 必须显示 reason（绝不渲染成「无自锁」） |
| `reconcile` | `{state: ok\|mismatch\|degraded\|never_run, reason, since, mismatches:[{ticket, board_state, ledger_state}]}` | degraded ≠ ok；mismatch 表格以看板列为准（board 是真源） |
| `startup` | `{missing_rows, replayed_rows, dedupe_keys}` | 「曾缺 N 行」的留痕读数（Overview 卡） |
| `presumed_self_rows` | int（t260929-04 新增，additive） | 自喂循环排除的响亮计数：简报点名后被判定为 executor 自身动作而压下的迁移数；>0 时 Overview 可标注「N 次自身动作未重复唤醒」，不是故障 |
| `presumed_self_detail` | string\|null（t260929-04 新增，additive） | 最近一次疑似自排除的人类可读证据（票+迁移），审计用 |
| `queue_mirror` | string\|null（t260929-04 新增，additive） | 队列镜像/投递通路状态串；`unreadable` 或非 `live` 开头 = 唤醒面在 no-signal 模式（照发但无消化判定），面板应显式标注 |
| `wakes` | `[{at, ticket, dedupe_key, mode, accepted}]` | 唤醒流水（Flow 卡的唤醒计数源） |
| `alerts` | `[{at, key, rule, target, level, title, detail, night_muted}]` | Alerts tab 数据源；`night_muted:true` 的行标「夜间已静音」；**没有 answered/auto_action 位**——未答复的 alert 永不自动变决定 |
| `notify` | `{beep: bool, unseen_redline: int}` | **beep 语义**：仅在出现新 dedupe key 的未读 alert 时为 true；反复轮询不重置、不翻倍；面板响一声后经（下一票的）已读接口按 key 清除 |
| `last_error` | string\|null | 非空 = 显式故障条 |

## 面板半必须显式降级的三种不可达

1. 路由 404 / 连不上（webServer 不在——headless 形态）；
2. 响应 `declared:false`（项目未声明守望者）；
3. `heartbeat.alive:false`（守望者死了/从没起过）。

三者都渲染为**显式「守望者不可达/过期（原因）」状态**，绝不静默渲染为空态或正常态。

## 声音（「一声就够」）

dsh 无任何发声能力（epic 实证零命中）——beep 由**控制台页面**产出：面板消费
`notify.beep=true` 时响一声。开关 = `watchdog.json` 的 `alerts.sound`（状态面 notify 位已含该
开关与夜间静音的与）；夜间口径 `alerts.night.policy ∈ silent|redline-only|normal`，
红线例外名单 `alerts.redline`。

## 配置文件（Settings tab 的编辑面）

`~/.sandbar/projects/<key>/watchdog.json`（env `SANDBAR_WATCHDOG_DIR` 覆盖根）；**文件存在 = 声明**，
未声明项目零行为。形状与出厂默认见方案 §2；新增键 fail-closed 拒收（未知键点名，KI-149 防呆）。
写入面（Settings 保存）属下一票；写后建议自校验（正面先例：安装器 project add 的装载器自检）。

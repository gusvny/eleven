"""inspection_ticketing — 巡检期票铸号与显式去重单点（t260916-02 声明落位迁移A）。

为什么存在：票号统一成工单号形式 `t<YYMMDD>-<NN>` 后，id 不再编码（实例,期号），
「每期一票」的机械保证（id 撞 AlreadyStarted）失效，必须补显式去重且行为等价：

  去重主判定 = SA 查询（InspectionInstance + InspectionPeriod，口径②「建议」的
  搜索属性）；并发窗兜底 = 原子指针文件（O_CREAT|O_EXCL，`<INSPECTION_DIR>/
  inspection-<实例>-<期>.ticket`，目录接 SANDBAR_INSPECTION_DIR 覆盖链——与台账
  同源单点，隔离台/临时目录天然互不污染）；最后一道 = 服务端 workflow id 唯一性
  （同日两个触发扫到同一个 NN → 同 id → AlreadyStarted → 验持有者 → deduped）。

指针三态纪律（review F2 修正，绝不谎报去重）：
  - 有效态（合法 JSON 带 ticket_id）：先 `handle(tid).describe()` 验票存在（RPC 打
    workflow 状态本身，不依赖可见性索引，NotFoundFailure=确定结论）；票在且 SA 与
    指针一致 → deduped；票在但 SA 不一致 → 配置事故显式报错（不自动清除——有第二
    写入方，删指针会掩盖）；票不在 = 陈旧指针（claim 与 start 之间 crash）：年龄
    > CLAIM_GRACE_SEC → 自动清除+回执留痕后重走 claim；窗内 → 显式报错不改动
    （不误杀并发者的 claim）。
  - 畸形态（空文件/半截 JSON/O_EXCL 与写内容之间被杀）：不可读 → 不可判定 → 显式
    点名；超龄同陈旧规则清、窗内报错。
  - 年龄基准 = 文件 st_mtime（有效态可再用 `at` 字段双核对——R4：两处口径必须一致，
    单测注入过期指针统一按 mtime 操作）。
  - 自动清除的理由（可审计）：指针是引擎内部锁痕，唯一语义=「一次开票在飞行」；
    超出 start 窗口的 claim 被证明是残屑，保留它=该（实例,期）永久楔死。显式报错
    而非假成功是底线，自动清是恢复手段；每次清除都在回执 `stale_pointer_cleared`
    留痕，绝不静默。

三路起票收敛：手动 trigger（CLI）/ cron 调度（InspectionPeriodSpawnWorkflow 的
spawn_inspection_period activity）/ 计数 watcher（trigger_inspection_period activity）
全部走本模块 `open_period_ticket`——铸号、去重、SA 盖章、启动只有一份实现。

`STARTS_WITH` 算子说明（R2）：铸号扫描用 `WorkflowId STARTS_WITH "<prefix>-"`——本仓
零先例，测试台首跑子用例先证；后端拒绝时回落「WorkflowType=巡检 + 客户端前缀过滤」
（漏 dev-lane 工单号，由 AlreadyStarted 归属判定+NN+1 重试兜住跨族撞号；回执带
scan_mode 可辨），取舍与原因记录进 README §13，绝不静默换实现。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 指针文件后缀：刻意**不带 .json**——deadman 台账扫描只收 `.json`（LEDGER_NAME_RE），
# 指针既不进台账也不进畸形桶（inspection_deadman.py 前缀过滤即跳过，实测）。
POINTER_SUFFIX = ".ticket"
# 指针飞行窗（秒）：claim 到 start 的正常耗时是毫秒级；窗内的「指针在票不在」按
# 并发飞行对待（显式报错不改动），窗外按崩溃残屑对待（自动清+留痕）。测试可注入。
CLAIM_GRACE_SEC = 120.0
# 撞号重试上限（NN+1 语义承接 ticket.py _uniq_v2 的逐号递增；_uniq_v2 无上限是 CLI
# 单次语境可接受，开票单点有循环框架故加上限防意外长转）。耗尽显式报错点名候选与撞主。
MAX_ALLOC_RETRIES = 5

SA_INSTANCE_NAME = "InspectionInstance"
SA_PERIOD_NAME = "InspectionPeriod"
# KI-191（t261002-11）：夹具标记 + 期槽占用时刻（与 shared.py 同名常量；本模块自带
# 一份沿用 SA_INSTANCE_NAME/SA_PERIOD_NAME 的本地常量先例——查询串与 describe 解析共用）。
SA_FIXTURE_NAME = "InspectionFixture"
SA_SLOT_TAKEN_NAME = "InspectionSlotTakenAt"


class TicketingError(ValueError):
    """开票面的显式失败（单行 JSON error 的素材；绝不静默）。"""


# ========================================================================================
# 期号/票号纯面
# ========================================================================================

def ticket_prefix_from_period(period: str) -> str:
    """期号 → 当日铸号前缀：`t<YYMMDD>`（期号 YYYYMMDD 取后六位；桶段期取日期段）。
    形状非法即 TicketingError（期号是去重键，形态必须先闭式）。"""
    p = str(period or "").strip()
    if not re.match(r"^\d{8}(-[1-9]\d*)?$", p):
        raise TicketingError("期号形状非法：%r（须 YYYYMMDD 或 YYYYMMDD-<bucket>）" % period)
    return "t" + p[2:8]


def ticket_id_from_seq(prefix: str, seq: int) -> str:
    """`t<YYMMDD>-<NN>`（%02d；≥100 自然进三位——词法 \\d{2,}，与 ticket.py 同形）。"""
    return "%s-%02d" % (prefix, seq)


# t 形工单号形状（全工单票共形：dev-lane 工单与巡检票同一词法）
TICKET_ID_SHAPE_RE = re.compile(r"^t\d{6}-\d{2,}$")


def has_ticket_id_shape(ticket_id: str) -> bool:
    """t 形**形状**判别单点（t260917-02：workflow 侧重定向守卫用它认「非 t 形 fire」）。

    ⚠ 语义圈死：这是**形状判别**，不是**巡检票身份判别**——本词法全工单票共形
    （dev-lane 工单票号同样匹配，本票自己的票号也匹配）；巡检票身份判别的唯一真源
    =SA (InspectionInstance, InspectionPeriod)（find_period_ticket_ids /
    resolve_period_ticket_id 链），绝不许拿本函数当「是不是巡检票」用。"""
    return bool(TICKET_ID_SHAPE_RE.match(str(ticket_id or "").strip()))


# ========================================================================================
# 指针文件（并发窗兜底；目录接 SANDBAR_INSPECTION_DIR 覆盖链）
# ========================================================================================

def pointer_path(ledger_dir: Any, instance_id: str, period: str) -> Path:
    """`<台账目录>/inspection-<实例>-<期>.ticket`——目录与台账同源（shared.INSPECTION_DIR，
    env SANDBAR_INSPECTION_DIR 覆盖），隔离台注入即整体隔离。"""
    return Path(str(ledger_dir)) / ("inspection-%s-%s%s" % (instance_id, period, POINTER_SUFFIX))


def pointer_age(path: Path, now_fn=time.time) -> float:
    """指针年龄（秒）。基准=文件 st_mtime（R4：畸形指针没有 `at` 字段可读，年龄判定
    必须统一落在 mtime 上；有效态的 `at` 字段只作双核对，不作基准）。读不到 mtime
    （文件刚被并发者清掉）→ 0.0（按「新鲜」对待——不误清并发者的 claim）。"""
    try:
        return max(0.0, float(now_fn()) - float(Path(path).stat().st_mtime))
    except OSError:
        return 0.0


def claim_pointer(path: Path, instance_id: str, period: str, ticket_id: str,
                  project_key: str, now_fn=time.time,
                  supersedes_ticket_id: str = "", fixture_mark: str = "") -> Tuple[str, Path]:
    """原子抢占：O_CREAT|O_EXCL 写指针。返回 ("claimed", path) 抢到 / ("exists", path)
    已有人 claim。写失败（目录不可写等）→ OSError 上抛（开票面显式报错）。
    supersedes_ticket_id 非空 = 本次开票是终止票重开（KI-114），指针链路留审计痕。
    fixture_mark 非空 = 本次 claim 是夹具开票（KI-191），指针 payload 留 `fixture` 痕
    （并发窗内后来者在 describe 之前即可读到夹具身份；空=不加该键，行形状不变）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ticket_id": ticket_id, "instance_id": instance_id,
               "period": period, "project_key": project_key,
               "supersedes_ticket_id": str(supersedes_ticket_id or ""),
               "at": float(now_fn())}
    if str(fixture_mark or "").strip():
        payload["fixture"] = str(fixture_mark).strip()
    body = json.dumps(payload, ensure_ascii=False)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return "exists", path            # 已有人 claim——三态判定归调用方（绝不绕过）
    try:
        os.write(fd, body.encode("utf-8"))
    finally:
        os.close(fd)
    return "claimed", path


def read_pointer_state(path: Path) -> Tuple[str, Dict[str, Any]]:
    """指针读取：("valid", 内容) / ("corrupt", {"reason": …})。空文件/坏 JSON/非映射/
    缺 ticket_id 都算 corrupt（O_EXCL 与写内容之间被杀的残痕）。"""
    try:
        raw = Path(path).read_text("utf-8")
    except OSError as e:
        return "corrupt", {"reason": "指针不可读：%s: %s" % (type(e).__name__, e)}
    try:
        data = json.loads(raw)
    except ValueError as e:
        return "corrupt", {"reason": "指针内容不是合法 JSON（写窗中断残痕）：%s" % str(e)[:80]}
    if not isinstance(data, dict) or not str(data.get("ticket_id") or ""):
        return "corrupt", {"reason": "指针内容形状非法（缺 ticket_id）"}
    return "valid", data


def clear_pointer(path: Path) -> bool:
    """清指针（自动清或清理路径用）；文件已不在=False（幂等）。"""
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise


#: 重开审计日志（KI-114）：追加一行 JSON——at/instance/period/terminated_ticket_id/
#: new_ticket_id。后缀刻意 .jsonl（不带 .json 结尾）：deadman 台账扫描只收 `.json`
#: 台账件，审计日志不进期号集合也不进畸形桶（不参与 deadman/ledger 会计）。
REOPEN_JOURNAL_NAME = "inspection-reopen.jsonl"


def append_reopen_journal(ledger_dir: Any, instance_id: str, period: str,
                          terminated_ticket_id: str, new_ticket_id: str,
                          now_fn=time.time, reason: str = "") -> None:
    """重开票的审计链接落盘（append-only JSONL）。既有文件哪怕内容畸形（半截行/
    坏 JSON）也不阻断追加——本函数只写不读，畸形行留给未来消费方按行容错；写失败
    OSError 上抛，由调用方显式报错（审计缺失绝不静默）。
    reason（260926）：人工具名重跑时的理由；空串＝不加该键（终止票自动重开的既有
    行形状逐字不变，老消费方零感知）。"""
    p = Path(str(ledger_dir)) / REOPEN_JOURNAL_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": float(now_fn()), "instance": str(instance_id),
               "period": str(period),
               "terminated_ticket_id": str(terminated_ticket_id or ""),
               "new_ticket_id": str(new_ticket_id or "")}
    if str(reason or "").strip():
        payload["reason"] = str(reason).strip()   # 人工具名重跑：理由进审计行
    entry = json.dumps(payload, ensure_ascii=False)
    with open(p, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


# ========================================================================================
# 起票裁决的可观测面（KI-129 修法② / KI-131「仍未修」块；260929 直修）
# ========================================================================================
#
# 为什么需要：自动班（cron → schedule → InspectionPeriodicSpawnWorkflow → activity
# spawn_inspection_period）**去重命中时只有 50ms 的返回值**——无新票、无报告、无告警。
# `triggered:false` 只活在 workflow 历史的返回值里，没有任何人能看见，于是「每日一班」
# 静默失效可以连续多天不被发现（KI-129 实案：20260926 期被非终态票占住 → 换期处置又
# 提前消费了 09-27…10-02 六期 → 09-27 起每天自动班全被去重挡掉，宿主 260929 只感到
# 「巡检没有了」；deadman 也看不见——它只认台账文件，而台账恰恰是提前服务留下的）。
#
# 本条只做**可观测面**，不改去重判据（改判据=行为变更，另议）：
#   ①台账目录 append-only 写 `inspection-spawn.jsonl` 一行（后缀刻意 .jsonl：deadman
#     台账扫描只收 `.json`，**写下「本期没跑」绝不能被读成「本期跑过」**）；
#   ②admin.log 一行（audit_call 单一收口，写失败在回执点名，绝不静默）。
#
# 告警口径（alarm=True ⇔「本期该跑而没跑」，都会被点名）：
#   - 起票失败（无票）；期槽被**非终态**票占住（KI-129 真丢期）；期槽被判已服务但
#     **台账缺失**（＝跑过却没出报告，KI-131 的「served 但判决非 ok」）。
#   已服务且台账在场的去重**不告警**（合法：提前服务/人工重开过），但同样落两行，
#   并在 note 里记明「本班不是本期第一次服务」+ 服务时间（这就是「巡检怎么没动」的答案）。

#: 起票裁决日志名（同 REOPEN_JOURNAL_NAME 理由：不进期号集合、不参与 deadman 会计）。
SPAWN_JOURNAL_NAME = "inspection-spawn.jsonl"


def ledger_file_name(instance_id: str, period: str) -> str:
    """期刊台账文件名（`inspection-<实例>-<期>.json`）。

    编码真源=inspection_flow.inspection_ledger_name（deadman 的 LEDGER_NAME_RE 按同一
    形状反解）；本模块刻意不 import inspection_flow（会牵出 workflow 依赖），改由单测
    锁两处逐字一致（同 inspection_trigger._default_ledger_dir 的「同口径由单测锁」先例）。"""
    return "inspection-%s-%s.json" % (instance_id, period)


def spawn_journal_rows(ledger_dir: Any) -> List[Dict[str, Any]]:
    """读起票裁决日志（只读；容错：文件缺席=空、坏行跳过——本面只写不读的既有纪律
    在读取侧补齐，畸形行绝不炸整次核查）。"""
    try:
        text = (Path(str(ledger_dir)) / SPAWN_JOURNAL_NAME).read_text("utf-8")
    except (FileNotFoundError, OSError):
        return []
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def spawn_skip_periods(ledger_dir: Any, instance_id: str) -> set:
    """「按声明空转」已解释的期号集合（decision=skipped-no-change）。

    漏跑核查据它把**「该跑而没跑」与「按声明判定无事可做」分开**——否则引入
    skip_when_unchanged 之后，每天都会多出一条假漏跑告警（审计面既不能说谎，
    也不能报警报成噪声，KI-129 同族纪律）。"""
    inst = str(instance_id or "")
    out = set()
    for row in spawn_journal_rows(ledger_dir):
        if str(row.get("instance") or "") != inst:
            continue
        if row.get("decision") == "skipped-no-change" and row.get("period"):
            out.add(str(row["period"]))
    return out


def last_run_base(ledger_dir: Any, instance_id: str) -> Dict[str, str]:
    """最近一次**真跑过**的期号与其基点 sha（lane.base_ref → suite.base_ref →
    scan_meta.inspect.base_head 三处任一）。读不出=空串（调用方据此不跳，绝不假跳）。

    期号解析复用 inspection_deadman.ledger_periods（单一真源，惰性 import 免环）。"""
    try:
        from inspection_deadman import ledger_periods
        info = ledger_periods(ledger_dir, instance_id)
    except Exception:  # noqa: BLE001——读面任何故障都只是「读不出」，不阻断起票
        return {"period": "", "base_ref": ""}
    for period in sorted(info.get("periods") or [], reverse=True):
        p = Path(str(ledger_dir)) / ledger_file_name(instance_id, period)
        try:
            doc = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        base = ""
        for key in ("lane", "suite"):
            src = doc.get(key)
            if isinstance(src, dict) and src.get("base_ref"):
                base = str(src["base_ref"])
                break
        if not base:
            sm = doc.get("scan_meta")
            ins = sm.get("inspect") if isinstance(sm, dict) else None
            if isinstance(ins, dict):
                base = str(ins.get("base_head") or "")
        if base:
            return {"period": period, "base_ref": base}
    return {"period": "", "base_ref": ""}


#: sha 形态（短/全长十六进制）：任一侧不像 sha ⇒ 判据不成立（判不准**不跳**）。
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def no_change_skip(last_base: str, head: str, last_period: str = "") -> Dict[str, Any]:
    """「无新变更则空转」判据（纯函数）。

    上次运行基点 == 当前 HEAD ⇒ 空转（不铸票、不跑套件、不占期槽资源），但仍**落一行
    裁决记录**（决策=skipped-no-change，漏跑核查据此不误报）。任一侧缺失/非 sha 形态 ⇒
    不跳——宁可多跑一次，绝不假跳（假跳=静默漏跑，比浪费一次更贵）。"""
    a, b = str(last_base or "").strip(), str(head or "").strip()
    if not (_SHA_RE.match(a) and _SHA_RE.match(b)) or a != b:
        return {"unchanged": False, "why": ""}
    return {"unchanged": True,
            "why": "main 无新变更（HEAD 仍为 %s，与上次运行%s的基点相同）——按声明 "
                   "skip_when_unchanged 空转不干活" %
                   (b[:7], ("（期 %s）" % last_period) if last_period else "")}


def spawn_decision_of(res: Any, ledger_dir: Any = None,
                      instance_id: str = "", period: str = "") -> Dict[str, Any]:
    """起票回执 + 台账在场性 → 裁决摘要（纯函数，无 side effect；畸形输入降级不抛）。

    返回 {decision: triggered|deduped|failed, period_state, ticket_id, alarm, note}。
    alarm/note 的口径见本节头注释（note 是给人读的一句话，中文＝文档面语言）。
    instance_id/period 优先取显式入参，缺省回落到回执里的同键（回执可能早于调用方
    补写这两键——判不准就不做台账在场性判定，只给通用文案）。"""
    out = {"decision": "failed", "period_state": "", "ticket_id": "",
           "alarm": True, "note": ""}
    if not isinstance(res, dict):
        out["note"] = "起票回执畸形（%r）——按失败处置" % (res,)
        return out
    if not res.get("ok"):
        out["note"] = "起票失败：%s" % str(res.get("error") or "无事由")[:240]
        return out
    r = res.get("result")
    r = r if isinstance(r, dict) else {}
    out["period_state"] = str(r.get("period_state") or "")
    out["ticket_id"] = str(r.get("ticket_id") or "")
    if r.get("skipped"):
        # 声明式空转（260929 宿主令：simplify-face 每天跑一次，没有新 change 就不干活）：
        # 不告警——按声明该跑而**判定无事可做**，与「该跑而没跑」是两件事。
        out["decision"] = "skipped-no-change"
        out["alarm"] = False
        out["note"] = str(r.get("skipped_because") or "按声明空转（无新变更）")
        return out
    if r.get("triggered"):
        out["decision"] = "triggered"
        out["alarm"] = False
        out["note"] = "本期已开票（%s）——按常规链路跑" % (out["ticket_id"] or "?")
        return out
    out["decision"] = "deduped"
    inst = str(r.get("instance") or instance_id or "")
    per = str(r.get("period") or period or "")
    if out["period_state"] == "live":
        out["alarm"] = True
        out["note"] = ("期槽被**非终态**票 %s 占住：本期不再开票、不跑套件、不出报告"
                       "（KI-129 形态）——人工换期，或记名 cancel 后再触发"
                       % (out["ticket_id"] or "?"))
        return out
    # 已服务槽位：台账在场＝正常（提前服务/人工重开）；不在场＝跑过却没出报告（欠账）。
    if ledger_dir is not None and inst and per:
        ledger = Path(str(ledger_dir)) / ledger_file_name(inst, per)
        if ledger.is_file():
            age = max(0.0, time.time() - ledger.stat().st_mtime)
            out["alarm"] = False      # 合法去重：本期确已被服务过（不是「该跑而没跑」）
            out["note"] = ("该期已由 %s 服务过（台账 %s，%.1f 天前）——本次自动班不再开票；"
                           "要重跑请带 reopen_reason 具名重开"
                           % (out["ticket_id"] or "?", ledger.name, age / 86400.0))
            return out
        out["alarm"] = True
        out["note"] = ("期槽被判已服务（%s）但台账不在场：该期跑过却没出报告"
                       "（KI-131「served 但判决非 ok」形态）——本班不会重跑它"
                       % (out["ticket_id"] or "?"))
        return out
    out["note"] = ("该期已被 %s 服务过——本班不再开票（period_state=%s）；"
                   "要重跑请带 reopen_reason 具名重开"
                   % (out["ticket_id"] or "?", out["period_state"] or "unknown"))
    return out


def note_spawn_decision(ledger_dir: Any, instance_id: str, period: str, res: Any,
                        face: str = "cron", now_fn=time.time) -> Dict[str, Any]:
    """把一次起票裁决落到两个可观测面（journal + admin.log），返回裁决摘要。

    调用点是**起票三路**（cron activity / watcher activity / 手动 CLI）——刻意不放进
    `open_period_ticket`；放在库函数里会让所有单测顺手往真 admin.log 写字（KI-161 教训：
    测试面不得写生产数据目录）。写失败一律**不抛**：起票本身的回执优先，缺失在返回的
    `journal_error` / `audit_write_failed` 键上点名（审计缺失绝不静默）。"""
    note = spawn_decision_of(res, ledger_dir=ledger_dir,
                             instance_id=instance_id, period=period)
    at = float(now_fn())
    payload = {"at": at, "instance": str(instance_id or ""), "period": str(period or ""),
               "face": str(face or ""), "decision": note["decision"],
               "period_state": note["period_state"], "ticket_id": note["ticket_id"],
               "alarm": bool(note["alarm"]), "note": note["note"]}
    out = dict(note)
    try:
        p = Path(str(ledger_dir)) / SPAWN_JOURNAL_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        out["journal_path"] = str(p)
    except OSError as e:      # 审计缺失绝不静默：点名进回执，起票结果照常返回
        out["journal_error"] = "%s: %s" % (type(e).__name__, e)
    try:
        import audit          # 同目录模块；局部 import 保持本模块「零重型依赖」的既有纪律
        receipt = {"ok": note["decision"] != "failed", "sub": "inspection-spawn",
                   "instance": payload["instance"], "period": payload["period"],
                   "face": payload["face"], "decision": payload["decision"],
                   "period_state": payload["period_state"],
                   "ticket_id": payload["ticket_id"], "alarm": payload["alarm"]}
        out["audit_call_id"] = audit.audit_call("inspection-spawn", receipt) or ""
        if receipt.get("audit_write_failed"):
            out["audit_write_failed"] = receipt["audit_write_failed"]
    except Exception as e:    # noqa: BLE001——审计面任何异常都不许吞掉起票回执
        out["audit_write_failed"] = "%s: %s" % (type(e).__name__, e)
    return out


# ========================================================================================
# Temporal 查询面（FakeClient 单测注入面：只用 list_workflows/get_workflow_handle/start_workflow）
# ========================================================================================

async def _list_ids(client: Any, query: str) -> List[str]:
    """list_workflows → id 清单（唯一扫描面；FakeClient 实现 async 迭代器即可）。"""
    ids: List[str] = []
    async for wf in client.list_workflows(query):
        ids.append(str(getattr(wf, "id", "") or ""))
    return ids


async def scan_prefix_ticket_ids(client: Any, prefix: str) -> Tuple[List[str], str]:
    """铸号扫描：同日全前缀（**全部** workflow 类型——工单店与巡检票必须互见，否则跨族
    撞号；t260916-02 修 `_next_seq_v2` 只扫工单店的现成缺陷）。
    返回 (ids, scan_mode)："starts_with"=可见性算子直查；"type_only_fallback"=后端拒绝
    STARTS_WITH 时回落「WorkflowType=巡检 + 客户端前缀过滤」（漏工单号，由 AlreadyStarted
    归属判定+NN+1 重试兜住；R2 取舍，README §13 记录）。"""
    try:
        ids = await _list_ids(client, 'WorkflowId STARTS_WITH "%s-"' % prefix)
        return ids, "starts_with"
    except TicketingError:
        raise
    except Exception as e:  # noqa: BLE001——算子不可用回落（可辨、可观测）
        try:
            ids = [i for i in await _list_ids(
                client, 'WorkflowType="InspectionPeriodicWorkflow"')
                if i.startswith(prefix + "-")]
        except Exception as e2:  # noqa: BLE001
            raise TicketingError("铸号扫描失败（两种扫描面都不可用）：%s / %s"
                                 % (type(e).__name__, type(e2).__name__)) from e2
        return ids, "type_only_fallback"


async def find_period_ticket_ids(client: Any, instance_id: str, period: str) -> List[str]:
    """同期票 SA 查询（去重主判定；返回全部命中 id——正常至多一个，多个=异常点名）。"""
    q = ('WorkflowType="InspectionPeriodicWorkflow" AND %s="%s" AND %s="%s"'
         % (SA_INSTANCE_NAME, instance_id, SA_PERIOD_NAME, period))
    try:
        return await _list_ids(client, q)
    except TicketingError:
        raise
    except Exception as e:  # noqa: BLE001——R3：SA 未注册要归因到注册步，不谎报「查无此票」
        txt = str(e).lower()
        if "unknown search attribute" in txt or "invalid" in txt and "attribute" in txt:
            raise TicketingError(
                "同期票查询失败（%s: %s）——InspectionInstance/InspectionPeriod 搜索属性"
                "未注册？先跑注册步（run_server.sh 自动 / 在跑 server：bin/temporal operator "
                "search-attribute create --name InspectionInstance --type Keyword，"
                "InspectionPeriod 同）再触发" % (type(e).__name__, e)) from e
        raise TicketingError("同期票查询失败：%s: %s" % (type(e).__name__, e)) from e


def _sa_pairs(sa: Any) -> List[Tuple[str, str]]:
    """SA 容器 → [(键名, 值)]（tolerant：TypedSearchAttributes 可迭代 pair / 旧 dict-of-lists）。"""
    out: List[Tuple[str, str]] = []
    if sa is None:
        return out
    if isinstance(sa, dict):
        for k, v in sa.items():
            vals = v if isinstance(v, (list, tuple)) else [v]
            for one in (vals or [""]):
                out.append((str(k), str(one or "")))
        return out
    try:
        iterator = list(sa)
    except TypeError:
        return out
    for pair in iterator:
        name = str(getattr(getattr(pair, "key", None), "name", "") or "")
        if name:
            out.append((name, str(getattr(pair, "value", "") or "")))
    return out


def _describe_not_found(exc: BaseException) -> Optional[bool]:
    """describe 异常 → True=确定不存在 / False=确定可读（不该到这）/ None=瞬态不可判。"""
    name = type(exc).__name__
    if name in ("NotFoundFailure", "WorkflowNotFoundError"):
        return True
    txt = str(exc).lower()
    if "not found" in txt or "not exist" in txt:
        return True
    if name in ("RPCError", "ServiceError") or "unavailable" in txt or "timeout" in txt:
        return None
    return None


# ---- 执行状态 → 期槽位裁决（KI-114/t260925-09：终止票不得永久吞掉期槽位）----
#: 活票（防并发去重语义不变）。CONTINUED_AS_NEW 作枚举兜底——真机 describe 对 continued
#: 票通常返回 RUNNING（新 run），两个名字都归「活」，不猜。
PERIOD_LIVE_STATUSES = frozenset({"RUNNING", "CONTINUED_AS_NEW"})
#: 已服务（该期已收口落账；重开=台账双计，必须挡）。
PERIOD_SERVED_STATUSES = frozenset({"COMPLETED"})
#: 已终止（槽位释放：清指针→铸新号重开，审计链接终止票与新票）。
#: 注意 FAILED/TIMED_OUT **不算**终止释放——失败票可能已写部分台账，是否重开属人工
#: 裁量，机器绝不猜（fail-closed）。
PERIOD_FREED_STATUSES = frozenset({"CANCELED", "TERMINATED"})


def period_slot_verdict(status_name: Any) -> str:
    """describe 状态名 → 期槽位裁决："live" | "served" | "freed" | "ambiguous"。
    空串/未知枚举名一律 ambiguous（fail-closed 的分类基石：绝不把不认识的态当释放）。"""
    s = str(status_name or "").strip().upper()
    if s in PERIOD_LIVE_STATUSES:
        return "live"
    if s in PERIOD_SERVED_STATUSES:
        return "served"
    if s in PERIOD_FREED_STATUSES:
        return "freed"
    return "ambiguous"


async def describe_period_run(client: Any, ticket_id: str) -> Tuple[Optional[bool], str, str, str, str, str]:
    """验票存在 + 读执行状态 + (实例,期) 身份（KI-114：去重判定升级为状态感知）
    + 夹具标记/占坑时刻（KI-191）。返回 (exists, status_name, instance, period,
    fixture_mark, slot_taken_at)：exists 三态同 describe_period_identity
    （True/False=确定结论，None=瞬态不可判，绝不猜）；status_name 取 describe 返回的
    执行状态名（真 SDK WorkflowExecutionStatus 与 FakeClient 桩均读 .name），不可读=空串；
    fixture_mark/slot_taken_at 从 SA 章照实读——老票/真班无章=空串（诚实降级面，
    绝不伪造缺省值；slot_taken_at 消费方把空串呈报为 unknown）。"""
    try:
        handle = client.get_workflow_handle(ticket_id)
        desc = await handle.describe()
    except Exception as e:  # noqa: BLE001——三态翻译见 _describe_not_found
        verdict = _describe_not_found(e)
        return ((False, "", "", "", "", "") if verdict is True else (None, "", "", "", "", ""))
    status_name = getattr(getattr(desc, "status", None), "name", "")
    # tolerant：有的桩/形态把状态对象再包一层（status.name 仍是对象）——逐层取 .name
    for _ in range(3):
        if not hasattr(status_name, "name"):
            break
        status_name = status_name.name
    status_name = str(status_name or "")
    instance = period = fixture_mark = slot_taken_at = ""
    for name, val in _sa_pairs(getattr(desc, "typed_search_attributes", None)
                               or getattr(desc, "search_attributes", None)):
        if name == SA_INSTANCE_NAME:
            instance = val
        elif name == SA_PERIOD_NAME:
            period = val
        elif name == SA_FIXTURE_NAME:
            fixture_mark = val
        elif name == SA_SLOT_TAKEN_NAME:
            slot_taken_at = val
    return True, status_name, instance, period, fixture_mark, slot_taken_at


async def describe_period_identity(client: Any, ticket_id: str) -> Tuple[Optional[bool], str, str]:
    """验票存在 + 读本票 (实例,期) 身份。返回 (exists, instance, period)：
    exists=True/False=确定结论（describe 的 RPC 打 workflow 状态本身，不依赖可见性索引，
    NotFoundFailure=确定 not found）；None=瞬态不可判（调用方按不可判处理，绝不猜）。
    （KI-114 起为 describe_period_run 的投影薄壳；去重主判定请用带状态的后者。）"""
    exists, _status, instance, period, _fx, _taken = await describe_period_run(client, ticket_id)
    return exists, instance, period


# ========================================================================================
# 开票单点（三路起票唯一实现）
# ========================================================================================

async def open_period_ticket(client: Any, *, instance_id: str, period: str,
                             project_key: str, repo_root: str = "",
                             scan_face: str = "test", decl_path: str = "",
                             task_queue: str = "",
                             per_ticket_queue: bool = False,
                             workflow_cls: Any = None, input_cls: Any = None,
                             reopen_reason: str = "",
                             fixture_mark: str = "",
                             grace_sec: Optional[float] = None,
                             now_fn=time.time) -> Dict[str, Any]:
    """铸号 → 显式去重 → 盖 SA → 起真票（t260916-02 三路起票单点）。

    回执（ok=True）result 键：
      triggered / deduped / ticket_id / first_run_id（triggered 时）
      dedup_source：sa_query | pointer | already_started
      stale_pointer_cleared：[路径…]（自动清残痕留痕，可观测；无=缺省）
      scan_mode：starts_with | type_only_fallback
      period_state：live | completed（deduped 时如实报命中票状态；KI-114）
      superseded_ticket_id：终止票重开时=被替代的终止票号（审计链接之一，另两处=
        新指针 payload supersedes_ticket_id + inspection-reopen.jsonl；无重开=""）
    失败（ok=False）：error 单行可读，点名路径/候选号/事由；绝不静默。
      KI-114 状态语义：活票/已服务票（COMPLETED）照旧 deduped（重开=台账双计）；
      终止票（CANCELED/TERMINATED）槽位释放自动重开；FAILED/TIMED_OUT/未知状态/
      describe 瞬态不可判 → fail-closed 显式报错，绝不静默开第二张。

    reopen_reason（非空＝人工/运维**具名重跑**；260926 宿主令「手动 trigger 一次巡检
    应该支持」）：对「已服务（COMPLETED）」与「FAILED/TIMED_OUT/未知」两类槽位，带具名
    理由即与终止票同路重开（清残指针 → 铸新号 → 审计链接三处，journal 落 reason）；
    **在飞期（live）不接受重开**（重跑=双跑同一期；先等收口，或记名 cancel 后再来）。
    空串＝既有语义逐字不变。

    fixture_mark（KI-191，t261002-11）：非空＝**夹具开票**——新票盖 InspectionFixture
    SA 章 + InspectionSlotTakenAt（起票时刻 ISO-8601 UTC）+ 指针 payload `fixture` 痕，
    回执带 `fixture=True`。去重认标记：真班（mark 空）视夹具票为**非去重对象**
    （跳过并照常铸真票——夹具占坑不再吞真班）；夹具开票遇真票/异标票 = 具名报错
    （夹具必须用自己的标记空间，绝不静默去重到真身上）。
    空串＝既有语义逐字不变（真班回执也新增 `slot_taken_at`（起票时刻；deduped 时=被
    去重票的占坑章，无章=空串由呈报层显式 "unknown"）与 `fixture=False`）。

    workflow_cls/input_cls 缺省=懒 import inspection_flow（CLI/worker 进程；单测注 fake
    免 temporalio 依赖）。grace_sec 缺省=CLAIM_GRACE_SEC（测试注入用）。"""
    from shared import (inspection_search_attributes, next_ticket_seq_from_ids,
                        ticket_task_queue)
    if workflow_cls is None or input_cls is None:
        from inspection_flow import InspectionPeriodicInput, InspectionPeriodicWorkflow
        workflow_cls = workflow_cls or InspectionPeriodicWorkflow
        input_cls = input_cls or InspectionPeriodicInput
    iid = str(instance_id or "").strip()
    if not iid:
        return {"ok": False, "error": "开票缺 instance_id（期=%r）" % (period,)}
    try:
        prefix = ticket_prefix_from_period(period)
    except TicketingError as e:
        return {"ok": False, "error": str(e)}
    grace = CLAIM_GRACE_SEC if grace_sec is None else float(grace_sec)
    ledger_dir = os.environ.get("SANDBAR_INSPECTION_DIR") or ""
    if not ledger_dir:
        # 与 shared.INSPECTION_DIR 同口径（stdlib 读法，零 temporalio 依赖）
        ledger_dir = str(Path(__file__).resolve().parent / "out" / "inspection")
    ppath = pointer_path(ledger_dir, iid, period)
    cleared: List[str] = []
    reason = str(reopen_reason or "").strip()   # 非空＝人工具名重跑（见 docstring）
    mark = str(fixture_mark or "").strip()      # 非空＝夹具开票（KI-191，见 docstring）

    def _err(msg: str) -> Dict[str, Any]:
        return {"ok": False,
                "error": "%s（实例 %s 期 %s）" % (msg, iid, period)}

    def _slot_taken_str(v: Any) -> str:
        # SA 章缺席（老票/真班旧票）→ 显式 "unknown"：诚实降级，绝不伪造时刻
        return str(v or "").strip() or "unknown"

    # ---- ① dedup 主判定：SA 查询（KI-114：命中后必须 describe 验状态——SA 章在
    #      ≠ 活票；终止票放行重开，活/已服务照旧 dedup，含糊态 fail-closed。
    #      KI-191：夹具票对真班**不是去重对象**——逐张读夹具章过滤后再裁决）----
    superseded_ticket_id = ""
    skipped_fixture_tickets: List[str] = []
    try:
        existing = await find_period_ticket_ids(client, iid, period)
    except TicketingError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "同期票查询异常：%s: %s" % (type(e).__name__, e)}
    if existing:
        # KI-114：逐张 describe 验状态再裁决（SA 章在≠活票）。重开合法化后同期可存
        # 「终止旧票 + 活新票」多张——收敛到活票裁决，绝不再见多张就一刀切报错。
        live_ids: List[str] = []
        freed_ids: List[str] = []
        served_ids: List[str] = []
        ambiguous_ids: List[str] = []
        taken_by_tid: Dict[str, str] = {}
        for tid in existing:
            exists, estatus, _einst, _eper, emark, etaken = \
                await describe_period_run(client, tid)
            if exists is None:
                return _err("同期票 %s 验票暂不可判（瞬态）——稍后重试，不猜状态" % tid)
            if not exists:
                # SA 说在、RPC 说不在：可见性与权威面矛盾，fail-closed 不猜
                return _err("同期票 %s SA 命中但 describe 不存在——可见性/权威面矛盾，"
                            "人工处置" % tid)
            # KI-191 夹具标记过滤（在槽位裁决之前）：
            if emark and not mark:
                # 真班遇夹具票：非去重对象——记录留痕后跳过（不进任何裁决集），
                # 照常铸真票。这正是 t261002-01 占坑事故的回归锚。
                skipped_fixture_tickets.append(tid)
                continue
            if mark and emark != mark:
                # 夹具开票遇真票/异标票：夹具必须用自己的标记空间，绝不静默去重到
                # 真身上（具名报错点名双方标记，检查名=fixture mark ownership check）
                return _err(
                    "fixture mark ownership check failed：本开票带夹具标记 %r，但同期票 %s "
                    "的标记=%r（空=真票）——夹具不得去重到非本标记的期票，请改用本夹具"
                    "专属标记或隔离 instance" % (mark, tid, emark or "空"))
            taken_by_tid[tid] = _slot_taken_str(etaken)
            slot = period_slot_verdict(estatus)
            if slot == "live":
                live_ids.append(tid)
            elif slot == "served":
                served_ids.append(tid)
            elif slot == "freed":
                freed_ids.append(tid)
            else:
                # FAILED/TIMED_OUT/未知状态名：默认绝不静默开第二张（fail-closed；失败票
                # 可能已写部分台账）。带 reopen_reason（人工具名）时才改判为可重开。
                if not reason:
                    return _err("同期票 %s 状态=%s（%s）——非活非终止非已服务，是否重开需"
                                "人工判定；本面 fail-closed 不自动开票"
                                "（要重跑请带 reopen_reason 具名）" % (tid, estatus, slot))
                ambiguous_ids.append(tid)
        if len(live_ids) > 1:
            # 不该发生（SA 是起票时刻唯一盖章）；发生=有第二写入方，点名不猜
            return _err("同期**活**票出现多张：%s——每期一票被破坏，人工处置"
                        % "、".join(sorted(live_ids)))
        if live_ids:
            if reason:
                # 在飞期不接受重开：重跑＝双跑同一期（并发两套 suite），先等收口。
                return _err("同期已有**在飞**巡检 %s（RUNNING）——重跑会双跑同一期，在飞期"
                            "不接受重开；等它收口，或先记名 cancel 后再重跑"
                            % "、".join(sorted(live_ids)))
            return {"ok": True, "result": {"triggered": False, "deduped": True,
                                           "ticket_id": live_ids[0],
                                           "dedup_source": "sa_query",
                                           "period_state": "live",
                                           # KI-191：回执点名占坑时刻（无章=unknown）
                                           "slot_taken_at": taken_by_tid.get(
                                               live_ids[0], "unknown"),
                                           "fixture": bool(mark),
                                           **({"skipped_fixture_tickets":
                                               sorted(skipped_fixture_tickets)}
                                              if skipped_fixture_tickets else {}),
                                           "stale_pointer_cleared": cleared}}
        if freed_ids or ambiguous_ids or (served_ids and reason):
            # 重开三源：①终止票（KI-114 自动放行）；②FAILED/TIMED_OUT/未知 + 人工具名；
            # ③已服务（COMPLETED）+ 人工具名（260926 宿主令：手动重跑同期必须支持）。
            # 清残指针（留痕带旧票号）→ 放行进铸号循环开新票；审计链接在 ④ 启动成功后
            # 落 reopen journal + 回执。已服务票而**无**具名＝「服务过又终止/含糊」复杂史，
            # 仍旧 fail-closed 人工判定（防台账双计）。
            if served_ids and not reason:
                return _err("同期既存已服务票 %s 又存终止票 %s——复杂史，是否重开需人工"
                            "判定；要重跑请带 reopen_reason 具名"
                            "（本面 fail-closed 不自动开票）"
                            % ("、".join(sorted(served_ids)), "、".join(sorted(freed_ids))))
            if len(served_ids) > 1:
                return _err("同期已服务票出现多张：%s——每期一票被破坏，人工处置"
                            % "、".join(sorted(served_ids)))
            superseded_ticket_id = ",".join(
                sorted(freed_ids + served_ids + ambiguous_ids))
            if clear_pointer(ppath):
                cleared.append("%s（重开：清旧指针 %s）"
                               % (ppath, superseded_ticket_id))
            # 落到 ② 铸号循环——不 return
        elif served_ids:
            if len(served_ids) > 1:
                return _err("同期已服务票出现多张：%s——每期一票被破坏，人工处置"
                            % "、".join(sorted(served_ids)))
            # 该期已收口落账：dedup 照旧（重开=台账双计），回执如实报 period_state，
            # 并给出重跑入口提示（260926 宿主令：手动 trigger 应支持）。
            return {"ok": True, "result": {"triggered": False, "deduped": True,
                                           "ticket_id": served_ids[0],
                                           "dedup_source": "sa_query",
                                           "period_state": "completed",
                                           "slot_taken_at": taken_by_tid.get(
                                               served_ids[0], "unknown"),
                                           "fixture": bool(mark),
                                           **({"skipped_fixture_tickets":
                                               sorted(skipped_fixture_tickets)}
                                              if skipped_fixture_tickets else {}),
                                           "reopen_hint": "该期已服务；要重跑请带"
                                                          " reopen_reason 具名重开",
                                           "stale_pointer_cleared": cleared}}

    # ---- ② 铸号 + ③ 指针三态 + ④ 启动（撞号重试循环）----
    ids, scan_mode = await scan_prefix_ticket_ids(client, prefix)
    seq = next_ticket_seq_from_ids(prefix, ids)
    for attempt in range(1, MAX_ALLOC_RETRIES + 1):
        ticket_id = ticket_id_from_seq(prefix, seq)
        state, cpath = claim_pointer(ppath, iid, period, ticket_id, str(project_key or ""),
                                     now_fn=now_fn,
                                     supersedes_ticket_id=superseded_ticket_id,
                                     fixture_mark=mark)
        if state == "exists":
            kind, data = read_pointer_state(ppath)
            age = pointer_age(ppath, now_fn=now_fn)
            if kind == "corrupt":
                if age > grace:
                    clear_pointer(ppath)
                    cleared.append("%s（畸形指针，年龄 %.0fs>%ss：%s）"
                                   % (ppath, age, grace, (data or {}).get("reason")))
                    continue
                return _err("去重指针畸形且在飞行窗内（%s：%s）——开票写窗中断嫌疑，"
                            "稍后重试；确认无并发可删该指针" % (ppath, (data or {}).get("reason")))
            ptid = str(data.get("ticket_id") or "")
            pmark = str(data.get("fixture") or "")
            # KI-191 指针层夹具归属检查（先于 describe——检查名=fixture mark ownership
            # check，与 SA 层同名同义）：夹具指针不是真班的飞行锁。
            if pmark and not mark:
                exists_pfx, _s_pfx, _i_pfx, _per_pfx, sa_mark_pfx, _t_pfx = \
                    await describe_period_run(client, ptid)
                if exists_pfx is False:
                    pass          # 票已不在：落下方陈旧指针路径处置（照旧）
                elif sa_mark_pfx or exists_pfx is None:
                    # 指针是夹具的飞行锁：真班不认——清痕重走铸号（票本体已由 SA 层
                    # 过滤，绝不 dedup 到它）。瞬态不可判也放行清痕：指针属夹具，
                    # 留着只会楔死真班；夹具票 SA 章仍在，幂等账不受影响。
                    clear_pointer(ppath)
                    cleared.append("%s（夹具指针归属检查：指针带 fixture=%r、本开票无"
                                   "标记——清夹具飞行锁后重走铸号）" % (ppath, pmark))
                    continue
                # exists_pfx True 且 SA 无章：指针 payload 与票面矛盾（罕见）——按
                # fail-closed 点名，不猜
                if exists_pfx and not sa_mark_pfx:
                    return _err("fixture mark ownership check failed：指针 %s 带 "
                                "fixture=%r 但指向票 %s 无夹具 SA 章——指针/票面矛盾，"
                                "人工处置" % (ppath, pmark, ptid))
            if mark and pmark != mark:
                return _err("fixture mark ownership check failed：本开票带夹具标记 %r，"
                            "但飞行指针 %s 的标记=%r（空=真班 claim）——夹具不得复用"
                            "非本标记的期槽空间" % (mark, ppath, pmark or "空"))
            exists, pstatus, pinst, pper, pmark_sa, ptaken = \
                await describe_period_run(client, ptid)
            if exists is None:
                return _err("去重指针指向 %s 但验票暂不可判（瞬态）——稍后重试" % ptid)
            if not exists:
                if age > grace:
                    clear_pointer(ppath)
                    cleared.append("%s（陈旧指针：指向的票 %s 不存在，年龄 %.0fs>%ss）"
                                   % (ppath, ptid, age, grace))
                    continue
                return _err("去重指针在飞行窗内且票不可见（%s → %s，年龄 %.0fs≤%ss）——"
                            "并发开票中或刚崩溃，稍后重试；确认无并发可删该指针"
                            % (ppath, ptid, age, grace))
            identity_match = (pinst == iid and pper == str(period))
            legacy_match = not pinst and not pper   # 无 SA 章的历史票（可信分支，见下）
            if not (identity_match or legacy_match):
                return _err("去重指针与票身份不一致（指针 %s → %s；票 %s 的 SA=(%s,%s)）——"
                            "配置事故，人工处置（不自动清除防掩盖第二写入方）"
                            % (ppath, ptid, ptid, pinst or "空", pper or "空"))
            # 身份相符（或 legacy 可信）→ 按执行状态裁决期槽位（KI-114）：
            slot = period_slot_verdict(pstatus)
            if reason and slot == "live":
                # 在飞期不接受重开（重跑＝双跑同一期）
                return _err("去重指针指向**在飞**巡检 %s（%s）——重跑会双跑同一期，在飞期"
                            "不接受重开；等它收口，或先记名 cancel 后再重跑"
                            % (ptid, pstatus))
            if reason and slot == "served":
                # 260926 宿主令：已服务期的人工具名重跑（与终止票同路：清指针→铸新号重开）
                clear_pointer(ppath)
                cleared.append("%s（已服务期 %s 状态=%s——人工具名重开：清旧指针）"
                               % (ppath, ptid, pstatus))
                superseded_ticket_id = ptid
                continue
            if slot == "live" or slot == "served":
                if legacy_match:
                    return {"ok": True, "result": {"triggered": False, "deduped": True,
                                                   "ticket_id": ptid, "dedup_source": "pointer",
                                                   "slot_taken_at": "unknown",
                                                   "fixture": bool(mark),
                                                   "stale_pointer_cleared": cleared,
                                                   "scan_mode": scan_mode,
                                                   "legacy": True}}
                return {"ok": True, "result": {"triggered": False, "deduped": True,
                                               "ticket_id": ptid, "dedup_source": "pointer",
                                               "period_state": "live" if slot == "live"
                                               else "completed",
                                               # KI-191：占坑时刻=被去重票的 SA 章，
                                               # 无章=unknown（诚实，不伪造）
                                               "slot_taken_at": _slot_taken_str(ptaken),
                                               "fixture": bool(mark),
                                               **({"skipped_fixture_tickets":
                                                   sorted(skipped_fixture_tickets)}
                                                  if skipped_fixture_tickets else {}),
                                               "reopen_hint": "" if slot == "live" else
                                               "该期已服务；要重跑请带 reopen_reason 具名重开",
                                               "stale_pointer_cleared": cleared,
                                               "scan_mode": scan_mode}}
            if slot == "freed":
                # 指针指向终止票：飞行窗语义已死（终止票绝不会再 start），立即清+留痕，
                # 重走铸号（KI-114：终止票不得永久吞掉期槽位）。
                clear_pointer(ppath)
                cleared.append("%s（指针指向终止票 %s，状态=%s——清旧指针重开）"
                               % (ppath, ptid, pstatus))
                superseded_ticket_id = ptid
                continue
            if reason:
                # 含糊态 + 人工具名：与终止票同路重开（260926 宿主令）
                clear_pointer(ppath)
                cleared.append("%s（%s 状态=%s——人工具名重开：清旧指针）"
                               % (ppath, ptid, pstatus))
                superseded_ticket_id = ptid
                continue
            # FAILED/TIMED_OUT/未知：fail-closed，不猜不重开（可能已写部分台账）。
            return _err("去重指针指向 %s 状态=%s（%s）——非活非终止非已服务，是否重开"
                        "需人工判定；本面 fail-closed 不自动开票"
                        "（要重跑请带 reopen_reason 具名）" % (ptid, pstatus, slot))
        # claimed——本进程持有指针，启动真票
        input_kwargs: Dict[str, Any] = {}
        if superseded_ticket_id:
            # KI-114：重开票 input 带被替代终止票号（票内审计链接；旧 input 类不认
            # 此键则走下方 TypeError 兼容面，链接仍由指针+reopen journal 承载）
            input_kwargs["supersedes_ticket_id"] = superseded_ticket_id
        try:
            payload = input_cls(instance_id=iid, period=period, repo_root=str(repo_root or ""),
                                face=str(scan_face or "test"), decl_path=str(decl_path or ""),
                                project_key=str(project_key or ""), **input_kwargs)
        except TypeError:
            # 兼容面：fake/旧 input 类形（缺 decl_path/project_key 等新键）——按已知键收敛
            payload = input_cls(instance_id=iid, period=period, repo_root=str(repo_root or ""),
                                face=str(scan_face or "test"))
        try:
            from datetime import datetime, timezone
            slot_taken_iso = datetime.fromtimestamp(
                float(now_fn()), tz=timezone.utc).isoformat()
            handle = await client.start_workflow(
                workflow_cls, payload,
                id=ticket_id,
                task_queue=(ticket_task_queue(ticket_id) if per_ticket_queue
                            else task_queue),
                search_attributes=inspection_search_attributes(
                    str(project_key or ""), iid, str(period),
                    fixture_mark=mark, slot_taken_at=slot_taken_iso))
            if superseded_ticket_id:
                # 审计链接第三处：reopen journal（append-only JSONL）。写失败=审计缺失
                # 显式报错（票已起，报错点名双事实，绝不静默吞掉审计缺失）。
                try:
                    append_reopen_journal(ledger_dir, iid, period,
                                          superseded_ticket_id, ticket_id,
                                          now_fn=now_fn, reason=reason)
                except OSError as e:
                    return {"ok": False,
                            "error": "新票 %s 已启动但 reopen journal 追加失败（%s: %s）——"
                                     "审计链接缺失，人工补记（被替代票 %s → 新票 %s）"
                                     % (ticket_id, type(e).__name__, e,
                                        superseded_ticket_id, ticket_id)}
            return {"ok": True, "result": {
                "triggered": True, "deduped": False, "ticket_id": ticket_id,
                "first_run_id": getattr(handle, "first_execution_run_id", ""),
                # KI-191：本票占坑时刻 + 夹具标记 + 被跳过的夹具占坑票（真班回执可见
                # 「谁曾占着这期」；空=无夹具占坑，不加键，既有形状不变）
                "slot_taken_at": slot_taken_iso, "fixture": bool(mark),
                **({"skipped_fixture_tickets": sorted(skipped_fixture_tickets)}
                   if skipped_fixture_tickets else {}),
                "dedup_source": "", "stale_pointer_cleared": cleared, "scan_mode": scan_mode,
                "superseded_ticket_id": superseded_ticket_id,
                # 人工具名重跑：理由随回执回显（对账锚；空串=不加该键，既有形状不变）
                **({"reopen_reason": reason} if reason else {})}}
        except Exception as e:  # noqa: BLE001——三路：deduped/外来撞号/其他失败
            already = type(e).__name__ == "WorkflowAlreadyStartedError" or \
                "already started" in str(e).lower()
            if not already:
                clear_pointer(ppath)          # 只删自己本次 claim 的（清理路径终点）
                return {"ok": False,
                        "error": "workflow %s 启动失败：%s: %s（已清自建指针 %s）"
                                 % (ticket_id, type(e).__name__, e, ppath)}
            exists, hinst, hper = await describe_period_identity(client, ticket_id)
            if exists and (hinst == iid and hper == str(period)
                           or (not hinst and not hper)):
                # 本（实例,期）已被并发者开出（deduped）——或撞上无 SA 章的旧票（可信，
                # 同指针三态分支口径）。收尾清自建指针：票已在，指针飞行语义终结。
                clear_pointer(ppath)
                return {"ok": True, "result": {
                    "triggered": False, "deduped": True, "ticket_id": ticket_id,
                    "dedup_source": "already_started",
                    # KI-191：并发窗内拿不到占坑 SA 章（票非本进程所起）——诚实 unknown
                    "slot_taken_at": "unknown", "fixture": bool(mark),
                    "stale_pointer_cleared": cleared,
                    "scan_mode": scan_mode}}
            clear_pointer(ppath)              # 撞了他人的号/验票不可判：删自建指针再让位
            if exists:
                seq += 1                      # 外来撞号 → NN+1 让位（_uniq_v2 语义等价）
                continue
            return {"ok": False,
                    "error": "workflow %s 已被占用且验票暂不可判（%s: %s）——已清自建指针，"
                             "稍后重试" % (ticket_id, type(e).__name__, e)}
    return _err("铸号重试耗尽（%d 轮，候选 %s-%02d…%s-%02d）：同日序号被持续占用，"
                "人工处置" % (MAX_ALLOC_RETRIES, prefix, seq - MAX_ALLOC_RETRIES + 1,
                              prefix, seq))


async def resolve_period_ticket_id(client: Any, instance_id: str, period: str) -> Dict[str, Any]:
    """（实例,期）→ 现存票号（sign/ticket/describe 查询面）：
    SA 查询优先；查无 → **legacy 只读探测**（旧形 id describe——过渡窗在途票/迁移前的
    历史票仍可管理；只读、绝不铸造旧形新票，R1 口径的合法保留面）。
    返回 {"ok": True, "ticket_id": …, "source": "sa"|"legacy_id"} / {"ok": False, "error": …}。"""
    try:
        ids = await find_period_ticket_ids(client, instance_id, period)
    except TicketingError as e:
        return {"ok": False, "error": str(e)}
    if len(ids) > 1:
        # KI-114：终止票重开后同期可 legitimately 存「终止旧票 + 活新票」两张——
        # 按执行状态收敛到活票；活票>1 才是每期一票被破坏（fail-closed 不猜）。
        live: List[str] = []
        dead: List[str] = []
        for tid in ids:
            exists, status, inst, per, _fx, _taken = await describe_period_run(client, tid)
            if exists is None:
                return {"ok": False, "error": "（实例 %s 期 %s）同期票 %s 验票暂不可判"
                        "（瞬态）——稍后重试" % (instance_id, period, tid)}
            if exists and period_slot_verdict(status) == "live":
                live.append(tid)
            else:
                dead.append(tid)
        if len(live) > 1:
            return {"ok": False, "error": "（实例 %s 期 %s）出现多张**活**同期票：%s——"
                    "每期一票被破坏，人工处置" % (instance_id, period, "、".join(sorted(live)))}
        if len(live) == 1:
            return {"ok": True, "ticket_id": live[0], "source": "sa",
                    "superseded": sorted(dead)}
        return {"ok": False, "error": "（实例 %s 期 %s）仅存非活同期票：%s——已终止/已服务"
                "票不承接在途操作；终止票重开走 trigger（自动放行），已服务票该期已收口"
                % (instance_id, period, "、".join(sorted(ids)))}
    if ids:
        # 单命中也如实报 live 标（KI-114：终止/已服务票存在≠活票；消费方自行裁量）
        exists, status, _i, _p, _fx, _taken = await describe_period_run(client, ids[0])
        return {"ok": True, "ticket_id": ids[0], "source": "sa",
                "live": bool(exists) and period_slot_verdict(status) == "live"}
    legacy = "inspection-%s-%s" % (instance_id, period)   # legacy 只读探测（历史票兼容）
    exists, _inst, _per = await describe_period_identity(client, legacy)
    if exists:
        return {"ok": True, "ticket_id": legacy, "source": "legacy_id"}
    if exists is None:
        return {"ok": False, "error": "（实例 %s 期 %s）同期票 SA 查无，legacy 探测暂不可判"
                "（瞬态）——稍后重试" % (instance_id, period)}
    return {"ok": False, "error": "（实例 %s 期 %s）查无同期巡检票（SA 查无 + 旧形票不存在）"
            "——查无此票≠连不上；起票走 inspection_trigger.py trigger" % (instance_id, period)}


async def open_produce_period_ticket(client: Any, **kw) -> Dict[str, Any]:
    """produce 期票起票路由（t260925-01 产出型巡检）：open_period_ticket 的
    produce 定形薄壳——per-ticket 队列（KI-113 口径，produce 不落共享队列）+
    InspectionProduceWorkflow/Input。kw 其余键（instance_id/period/project_key/…）
    语义与 open_period_ticket 一致。"""
    from inspection_flow import InspectionProduceInput, InspectionProduceWorkflow
    kw.setdefault("per_ticket_queue", True)
    kw.setdefault("workflow_cls", InspectionProduceWorkflow)
    kw.setdefault("input_cls", InspectionProduceInput)
    return await open_period_ticket(client, **kw)


# ========================================================================================
# 期槽诚实面（KI-191，t261002-11）：「谁占着这期」可查询 + 夹具清坑单点
# ========================================================================================

async def describe_period_slot(client: Any, instance_id: str, period: str) -> Dict[str, Any]:
    """（实例,期）→ 期槽占用人诚实面（KI-191：queryable, not just a boolean）。

    返回 {"ok": True, slot_state: live|served|freed|empty, ticket_id, status,
          fixture_mark, slot_taken_at, all_tickets}：
      - slot_taken_at 无 SA 章（老票/事故票 t261002-01 形态）= "unknown"——**照实呈报，
        绝不伪造时刻**（review_plan 意见 2 的落地）；
      - fixture_mark 空 = 真班占坑（或无章老票——由 slot_taken_at=unknown 伴生可辨）；
      - all_tickets = 全部同期票（含被替代终止票）的 {ticket_id,status,fixture_mark,
        slot_taken_at} 列表（重开史的完整诚实面）；
      - 活票收敛同 resolve_period_ticket_id：活票恰一张；>1 = 具名报错（每期一票被破坏）。
    失败（ok=False）：error 具名（检查名点名——期号形状 / 瞬态不可判 / 多活票）。"""
    iid = str(instance_id or "").strip()
    if not iid:
        return {"ok": False, "error": "期槽查询缺 instance_id（期=%r）" % (period,)}
    try:
        ticket_prefix_from_period(period)     # 期号形状闭式检查（具名 TicketingError）
    except TicketingError as e:
        return {"ok": False, "error": "期槽查询：%s" % e}
    try:
        ids = await find_period_ticket_ids(client, iid, period)
    except TicketingError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "期槽查询异常：%s: %s" % (type(e).__name__, e)}
    if not ids:
        return {"ok": True, "slot_state": "empty", "ticket_id": "", "status": "",
                "fixture_mark": "", "slot_taken_at": "", "all_tickets": []}
    rows: List[Dict[str, Any]] = []
    for tid in ids:
        exists, status, _i, _p, fx, taken = await describe_period_run(client, tid)
        if exists is None:
            return {"ok": False, "error": "期槽查询：同期票 %s 验票暂不可判（瞬态）——"
                    "稍后重试，不猜状态" % tid}
        if not exists:
            return {"ok": False, "error": "期槽查询：同期票 %s SA 命中但 describe 不存在"
                    "——可见性/权威面矛盾，人工处置" % tid}
        rows.append({"ticket_id": tid, "status": status,
                     "slot_state": period_slot_verdict(status),
                     "fixture_mark": fx,
                     "slot_taken_at": str(taken or "").strip() or "unknown"})
    lives = [r for r in rows if r["slot_state"] == "live"]
    if len(lives) > 1:
        return {"ok": False, "error": "期槽查询：（实例 %s 期 %s）出现多张**活**同期票："
                "%s——每期一票被破坏，人工处置"
                % (iid, period, "、".join(sorted(r["ticket_id"] for r in lives)))}
    occ = lives[0] if lives else rows[0]
    return {"ok": True, "slot_state": occ["slot_state"], "ticket_id": occ["ticket_id"],
            "status": occ["status"], "fixture_mark": occ["fixture_mark"],
            "slot_taken_at": occ["slot_taken_at"], "all_tickets": rows}


async def release_period_slot(client: Any, *, instance_id: str, period: str,
                              fixture_mark: str, now_fn=time.time) -> Dict[str, Any]:
    """夹具清坑单点（KI-191 验收②：终态=期槽释放，不留占坑残骸）。

    只放行**带本 fixture_mark 章**的活票：cancel 到终态（槽位裁决即 freed）+ 清该期
    飞行指针（留痕）。返回 {"ok": True, released: [票号…], pointer_cleared: bool}。

    具名失败（检查名逐条点名，绝不裸布尔，绝不静默）：
      - fixture mark missing check：mark 空/纯空白 → 拒绝（无记名清坑=谁都能清真班）；
      - period shape check：期号形状非法（复用 ticket_prefix_from_period）；
      - double-clean check：该期无任何同期票（已清过）→ 点名「已释放」不谎报二次成功；
      - ownership check：在场活票的夹具章≠本标记（含空章=真班票）→ 拒绝（真班占坑
        绝不可被夹具清坑面释放）；
      - cancel 失败（网络/权限）→ 点名异常类型，票保持原状。"""
    iid = str(instance_id or "").strip()
    mark = str(fixture_mark or "").strip()
    if not mark:
        return {"ok": False,
                "error": "release: fixture mark missing check failed——清坑必须具名夹具"
                         "标记（空标记=无记名清坑，拒绝；实例 %r 期 %r）" % (iid, period)}
    if not iid:
        return {"ok": False,
                "error": "release: instance check failed——清坑缺 instance_id（期=%r）"
                         % (period,)}
    try:
        ticket_prefix_from_period(period)
    except TicketingError as e:
        return {"ok": False, "error": "release: period shape check failed——%s" % e}
    try:
        ids = await find_period_ticket_ids(client, iid, period)
    except TicketingError as e:
        return {"ok": False, "error": "release: %s" % e}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "release: 同期票查询异常：%s: %s"
                % (type(e).__name__, e)}
    if not ids:
        return {"ok": False,
                "error": "release: double-clean check failed——（实例 %s 期 %s）无任何同期"
                         "票，期槽已释放过（重复清坑）；如需核对请走 describe_period_slot"
                         % (iid, period)}
    released: List[str] = []
    others: List[str] = []
    for tid in ids:
        exists, status, _i, _p, fx, _taken = await describe_period_run(client, tid)
        if exists is None:
            return {"ok": False, "error": "release: 同期票 %s 验票暂不可判（瞬态）——"
                    "稍后重试，不猜状态" % tid}
        if not exists or period_slot_verdict(status) != "live":
            continue              # 已终态/已服务票：槽位已释放，无需也不能再 cancel
        if fx != mark:
            others.append("%s(标记=%s)" % (tid, fx or "空"))
            continue
        try:
            await client.get_workflow_handle(tid).cancel()
        except Exception as e:  # noqa: BLE001——cancel 失败点名，票保持原状
            return {"ok": False, "error": "release: cancel 票 %s 失败（%s: %s）——"
                    "期槽保持原状，人工处置" % (tid, type(e).__name__, e)}
        released.append(tid)
    if not released:
        # 无带本标记的活票可放：或已清过（double-clean），或全是他人的坑——都具名点名，
        # 绝不谎报二次成功（KI-191：清坑面的「终态=已释放」必须可辨）
        if others:
            return {"ok": False, "error": "release: mark ownership mismatch check "
                    "failed——（实例 %s 期 %s）在场活票非本夹具标记（mark 不匹配）：%s——"
                    "夹具不得释放真班/异标占坑，人工处置"
                    % (iid, period, "、".join(sorted(others)))}
        return {"ok": False, "error": "release: double-clean check failed——（实例 %s 期 %s）"
                "无带本标记的活占坑票，期槽已释放过（重复清坑）；如需核对请走 "
                "describe_period_slot" % (iid, period)}
    # 清该期飞行指针（终态=槽位释放的一部分；幂等，不在=False）
    ledger_dir = os.environ.get("SANDBAR_INSPECTION_DIR") or ""
    if not ledger_dir:
        ledger_dir = str(Path(__file__).resolve().parent / "out" / "inspection")
    pointer_cleared = clear_pointer(pointer_path(ledger_dir, iid, period))
    return {"ok": True, "released": sorted(released),
            "others_refused": sorted(others), "pointer_cleared": pointer_cleared}

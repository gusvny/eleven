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
                  supersedes_ticket_id: str = "") -> Tuple[str, Path]:
    """原子抢占：O_CREAT|O_EXCL 写指针。返回 ("claimed", path) 抢到 / ("exists", path)
    已有人 claim。写失败（目录不可写等）→ OSError 上抛（开票面显式报错）。
    supersedes_ticket_id 非空 = 本次开票是终止票重开（KI-114），指针链路留审计痕。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"ticket_id": ticket_id, "instance_id": instance_id,
                          "period": period, "project_key": project_key,
                          "supersedes_ticket_id": str(supersedes_ticket_id or ""),
                          "at": float(now_fn())}, ensure_ascii=False)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return "exists", path            # 已有人 claim——三态判定归调用方（绝不绕过）
    try:
        os.write(fd, payload.encode("utf-8"))
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
                          now_fn=time.time) -> None:
    """终止票重开的审计链接落盘（append-only JSONL）。既有文件哪怕内容畸形（半截行/
    坏 JSON）也不阻断追加——本函数只写不读，畸形行留给未来消费方按行容错；写失败
    OSError 上抛，由调用方显式报错（审计缺失绝不静默）。"""
    p = Path(str(ledger_dir)) / REOPEN_JOURNAL_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = json.dumps({"at": float(now_fn()), "instance": str(instance_id),
                        "period": str(period),
                        "terminated_ticket_id": str(terminated_ticket_id or ""),
                        "new_ticket_id": str(new_ticket_id or "")},
                       ensure_ascii=False)
    with open(p, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


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


async def describe_period_run(client: Any, ticket_id: str) -> Tuple[Optional[bool], str, str, str]:
    """验票存在 + 读执行状态 + (实例,期) 身份（KI-114：去重判定升级为状态感知）。
    返回 (exists, status_name, instance, period)：exists 三态同 describe_period_identity
    （True/False=确定结论，None=瞬态不可判，绝不猜）；status_name 取 describe 返回的
    执行状态名（真 SDK WorkflowExecutionStatus 与 FakeClient 桩均读 .name），不可读=空串。"""
    try:
        handle = client.get_workflow_handle(ticket_id)
        desc = await handle.describe()
    except Exception as e:  # noqa: BLE001——三态翻译见 _describe_not_found
        verdict = _describe_not_found(e)
        return ((False, "", "", "") if verdict is True else (None, "", "", ""))
    status_name = getattr(getattr(desc, "status", None), "name", "")
    # tolerant：有的桩/形态把状态对象再包一层（status.name 仍是对象）——逐层取 .name
    for _ in range(3):
        if not hasattr(status_name, "name"):
            break
        status_name = status_name.name
    status_name = str(status_name or "")
    instance = period = ""
    for name, val in _sa_pairs(getattr(desc, "typed_search_attributes", None)
                               or getattr(desc, "search_attributes", None)):
        if name == SA_INSTANCE_NAME:
            instance = val
        elif name == SA_PERIOD_NAME:
            period = val
    return True, status_name, instance, period


async def describe_period_identity(client: Any, ticket_id: str) -> Tuple[Optional[bool], str, str]:
    """验票存在 + 读本票 (实例,期) 身份。返回 (exists, instance, period)：
    exists=True/False=确定结论（describe 的 RPC 打 workflow 状态本身，不依赖可见性索引，
    NotFoundFailure=确定 not found）；None=瞬态不可判（调用方按不可判处理，绝不猜）。
    （KI-114 起为 describe_period_run 的投影薄壳；去重主判定请用带状态的后者。）"""
    exists, _status, instance, period = await describe_period_run(client, ticket_id)
    return exists, instance, period


# ========================================================================================
# 开票单点（三路起票唯一实现）
# ========================================================================================

async def open_period_ticket(client: Any, *, instance_id: str, period: str,
                             project_key: str, repo_root: str = "",
                             scan_face: str = "test", decl_path: str = "",
                             task_queue: str = "",
                             workflow_cls: Any = None, input_cls: Any = None,
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

    workflow_cls/input_cls 缺省=懒 import inspection_flow（CLI/worker 进程；单测注 fake
    免 temporalio 依赖）。grace_sec 缺省=CLAIM_GRACE_SEC（测试注入用）。"""
    from shared import inspection_search_attributes, next_ticket_seq_from_ids
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

    def _err(msg: str) -> Dict[str, Any]:
        return {"ok": False,
                "error": "%s（实例 %s 期 %s）" % (msg, iid, period)}

    # ---- ① dedup 主判定：SA 查询（KI-114：命中后必须 describe 验状态——SA 章在
    #      ≠ 活票；终止票放行重开，活/已服务照旧 dedup，含糊态 fail-closed）----
    superseded_ticket_id = ""
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
        for tid in existing:
            exists, estatus, _einst, _eper = await describe_period_run(client, tid)
            if exists is None:
                return _err("同期票 %s 验票暂不可判（瞬态）——稍后重试，不猜状态" % tid)
            if not exists:
                # SA 说在、RPC 说不在：可见性与权威面矛盾，fail-closed 不猜
                return _err("同期票 %s SA 命中但 describe 不存在——可见性/权威面矛盾，"
                            "人工处置" % tid)
            slot = period_slot_verdict(estatus)
            if slot == "live":
                live_ids.append(tid)
            elif slot == "served":
                served_ids.append(tid)
            elif slot == "freed":
                freed_ids.append(tid)
            else:
                # FAILED/TIMED_OUT/未知状态名：绝不静默开第二张（fail-closed；失败票
                # 可能已写部分台账，是否重开属人工裁量）。
                return _err("同期票 %s 状态=%s（%s）——非活非终止非已服务，是否重开需"
                            "人工判定；本面 fail-closed 不自动开票" % (tid, estatus, slot))
        if len(live_ids) > 1:
            # 不该发生（SA 是起票时刻唯一盖章）；发生=有第二写入方，点名不猜
            return _err("同期**活**票出现多张：%s——每期一票被破坏，人工处置"
                        % "、".join(sorted(live_ids)))
        if live_ids:
            return {"ok": True, "result": {"triggered": False, "deduped": True,
                                           "ticket_id": live_ids[0],
                                           "dedup_source": "sa_query",
                                           "period_state": "live",
                                           "stale_pointer_cleared": cleared}}
        if freed_ids:
            # 终止票：期槽位释放（KI-114 根病因）。清残指针（留痕带旧票号）→ 放行进
            # 铸号循环开新票；审计链接在 ④ 启动成功后落 reopen journal + 回执。
            # （同窗还有已服务票=「服务过又终止」复杂史，fail-closed 人工判定。）
            if served_ids:
                return _err("同期既存已服务票 %s 又存终止票 %s——复杂史，是否重开需人工"
                            "判定；本面 fail-closed 不自动开票"
                            % ("、".join(sorted(served_ids)), "、".join(sorted(freed_ids))))
            superseded_ticket_id = ",".join(sorted(freed_ids))
            if clear_pointer(ppath):
                cleared.append("%s（终止票 %s 重开：清旧指针）" % (ppath, superseded_ticket_id))
            # 落到 ② 铸号循环——不 return
        elif served_ids:
            if len(served_ids) > 1:
                return _err("同期已服务票出现多张：%s——每期一票被破坏，人工处置"
                            % "、".join(sorted(served_ids)))
            # 该期已收口落账：dedup 照旧（重开=台账双计），回执如实报 period_state。
            return {"ok": True, "result": {"triggered": False, "deduped": True,
                                           "ticket_id": served_ids[0],
                                           "dedup_source": "sa_query",
                                           "period_state": "completed",
                                           "stale_pointer_cleared": cleared}}

    # ---- ② 铸号 + ③ 指针三态 + ④ 启动（撞号重试循环）----
    ids, scan_mode = await scan_prefix_ticket_ids(client, prefix)
    seq = next_ticket_seq_from_ids(prefix, ids)
    for attempt in range(1, MAX_ALLOC_RETRIES + 1):
        ticket_id = ticket_id_from_seq(prefix, seq)
        state, cpath = claim_pointer(ppath, iid, period, ticket_id, str(project_key or ""),
                                     now_fn=now_fn,
                                     supersedes_ticket_id=superseded_ticket_id)
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
            exists, pstatus, pinst, pper = await describe_period_run(client, ptid)
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
            if slot == "live" or slot == "served":
                if legacy_match:
                    return {"ok": True, "result": {"triggered": False, "deduped": True,
                                                   "ticket_id": ptid, "dedup_source": "pointer",
                                                   "stale_pointer_cleared": cleared,
                                                   "scan_mode": scan_mode,
                                                   "legacy": True}}
                return {"ok": True, "result": {"triggered": False, "deduped": True,
                                               "ticket_id": ptid, "dedup_source": "pointer",
                                               "period_state": "live" if slot == "live"
                                               else "completed",
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
            # FAILED/TIMED_OUT/未知：fail-closed，不猜不重开（可能已写部分台账）。
            return _err("去重指针指向 %s 状态=%s（%s）——非活非终止非已服务，是否重开"
                        "需人工判定；本面 fail-closed 不自动开票" % (ptid, pstatus, slot))
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
            handle = await client.start_workflow(
                workflow_cls, payload,
                id=ticket_id, task_queue=task_queue,
                search_attributes=inspection_search_attributes(
                    str(project_key or ""), iid, str(period)))
            if superseded_ticket_id:
                # 审计链接第三处：reopen journal（append-only JSONL）。写失败=审计缺失
                # 显式报错（票已起，报错点名双事实，绝不静默吞掉审计缺失）。
                try:
                    append_reopen_journal(ledger_dir, iid, period,
                                          superseded_ticket_id, ticket_id, now_fn=now_fn)
                except OSError as e:
                    return {"ok": False,
                            "error": "新票 %s 已启动但 reopen journal 追加失败（%s: %s）——"
                                     "审计链接缺失，人工补记（终止票 %s → 新票 %s）"
                                     % (ticket_id, type(e).__name__, e,
                                        superseded_ticket_id, ticket_id)}
            return {"ok": True, "result": {
                "triggered": True, "deduped": False, "ticket_id": ticket_id,
                "first_run_id": getattr(handle, "first_execution_run_id", ""),
                "dedup_source": "", "stale_pointer_cleared": cleared, "scan_mode": scan_mode,
                "superseded_ticket_id": superseded_ticket_id}}
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
                    "dedup_source": "already_started", "stale_pointer_cleared": cleared,
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
            exists, status, inst, per = await describe_period_run(client, tid)
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
        exists, status, _i, _p = await describe_period_run(client, ids[0])
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

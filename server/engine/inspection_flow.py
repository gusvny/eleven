"""inspection_flow —— 巡检票骨架（inspection epic 票①，t260905-03）。

轻量巡检票模板：扫 → 报 → 人门 → 收口（无方案/实现重段）。每期一票：期号=实例 id+当期
日期，票号即 workflow id（inspection-<实例>-<期号>），同票号重复触发被服务端
AlreadyStarted 拒收 = 每期一票的机械保证（重叠语义 SKIP，照搬取舍清单①；
全绿也开票——零发现票=心跳证明）。

红线（票面每份落账都带）：巡检只出报告与开票建议，绝不直接改码；修复一律走
dev-lane 工单，修复票引用巡检票号（source_inspection=<巡检票号>）。

人门（M3）：复用既有票据审批门机制——signal sign + Signature 载荷（shared.Signature：
who 由调用方注入、agent 不得自签），本模板只定义自己的门 id（inspection-close）。
未批准时收口不可达（stage_state=awaiting-human 真拦），批准后才收口。

确定性纪律：workflow 体零 IO、零 wall-clock（只有 workflow.now()）；一切副作用在
activity（run_inspection_scan / write_inspection_report，activities.py 薄壳）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from temporalio import workflow
from temporalio.common import RetryPolicy

# shared 顶层有 Path.resolve/environ（非确定性），workflow 上下文内须按仓惯例
# 透传该 import（同 workflows.py 头部口径），否则沙箱校验即红。
with workflow.unsafe.imports_passed_through():
    from shared import Signature

CLOSE_GATE_ID = "inspection-close"
INSPECTION_RED_LINE = "巡检只出报告与开票建议，绝不直接改码；修复一律走 dev-lane 工单。"
# agent 不得自签（Signature 语义复用）：人门 who 不得是 M10 五 agent 角色名。
AGENT_ROLE_NAMES = frozenset({"developer", "integration", "ops", "product-operation", "artist"})
PERIOD_RE = re.compile(r"^\d{8}$")
MAX_WHO_LEN = 64

RETRY = RetryPolicy(maximum_attempts=3)
SHORT_TO = timedelta(minutes=5)
SCAN_TO = timedelta(minutes=15)


# ========================================================================================
# 纯逻辑（单测面）：期号/票号/票面渲染/签字校验/落账
# ========================================================================================

def period_key(now: Optional[datetime] = None) -> str:
    """期号=当期日期（YYYYMMDD）。every-n-tickets 接线时期语义重定义是接线票的活。"""
    dt = now or datetime.now()
    return dt.strftime("%Y%m%d")


def inspection_ticket_id(instance_id: str, period: str) -> str:
    """巡检票号 = workflow id（同票号重复触发=同票，每期一票机械保证）。"""
    if not instance_id or not PERIOD_RE.match(period or ""):
        raise ValueError("票号组成非法：instance=%r period=%r（期号须 YYYYMMDD）" % (instance_id, period))
    return "inspection-%s-%s" % (instance_id, period)


def validate_trigger_args(instance_id: str, period: str) -> Optional[str]:
    """触发参数 fail-closed（照搬取舍清单⑥扩展）；返回错误消息或 None。"""
    if not instance_id or not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", instance_id):
        return "instance 非法：%r（小写 slug）" % instance_id
    if not PERIOD_RE.match(period or ""):
        return "period 非法：%r（须 YYYYMMDD）" % period
    return None


def build_ticket_face(
    ticket_id: str,
    instance_id: str,
    face_name: str,
    period: str,
    scan_result: Dict[str, Any],
) -> Dict[str, Any]:
    """发现清单落票面（渲染数据）：分严重度带证据 + 心跳 + 开票建议（零改码）。"""
    if not ticket_id or not instance_id:
        raise ValueError("票面缺票号/实例")
    if not isinstance(scan_result, dict) or not isinstance(scan_result.get("findings"), list):
        raise ValueError("扫描结果畸形：缺 findings 列表（fail-closed，不渲染）")
    findings = scan_result.get("findings") or []
    counts = scan_result.get("summary") or {"high": 0, "med": 0, "low": 0}
    heartbeat = bool(scan_result.get("heartbeat"))
    suggestions: List[Dict[str, Any]] = []
    for f in findings:
        if f.get("severity") not in ("high", "med"):
            continue
        suggestions.append({
            "template": "dev-lane",
            "title": "修:%s %s" % (f.get("scan", ""), str(f.get("subject", ""))[:60]),
            "source_inspection": ticket_id,           # 修复票引用巡检票号（ epic 票①④）
            "urgency": "立即开票" if f.get("severity") == "high" else "人审后定",
            "evidence": f.get("evidence", ""),
        })
    return {
        "ticket_id": ticket_id,
        "kind": "inspection",
        "instance_id": instance_id,
        "face": face_name,
        "period": period,
        "red_line": INSPECTION_RED_LINE,
        "heartbeat": heartbeat,
        "heartbeat_note": "全绿期=零发现票（心跳证明）" if heartbeat else "",
        "summary": counts,
        "findings": findings,
        "suggested_fix_tickets": suggestions,
        "scan_meta": scan_result.get("meta") or {},
    }


def validate_close_signature(sig: Any, expected_gate: str = CLOSE_GATE_ID) -> Tuple[Optional[Dict[str, str]], str]:
    """人门签字校验（复用 Signature 语义）：返回 (规整后的载荷, 错误消息)。
    agent 自签（who 命中五 agent 角色名）拒收——签字只能人。"""
    if isinstance(sig, Signature):
        payload = {"who": sig.who, "gate": sig.gate, "decision": sig.decision, "note": sig.note or ""}
    elif isinstance(sig, dict):
        payload = {"who": str(sig.get("who") or ""), "gate": str(sig.get("gate") or ""),
                   "decision": str(sig.get("decision") or ""), "note": str(sig.get("note") or "")}
    else:
        return None, "签字载荷类型非法：%s" % type(sig).__name__
    if not payload["who"].strip():
        return None, "签字缺 who（签字身份由调用方注入）"
    if len(payload["who"]) > MAX_WHO_LEN:
        return None, "who 超长（>%d）" % MAX_WHO_LEN
    if payload["who"].strip().lower() in AGENT_ROLE_NAMES:
        return None, "agent 不得自签（who=%r 是 agent 角色名；签字只能人）" % payload["who"]
    if payload["gate"] != expected_gate:
        return None, "签字 gate 不匹配：%r（本门=%r）" % (payload["gate"], expected_gate)
    if payload["decision"] not in ("approve", "reject"):
        return None, "decision 只认 approve/reject（got %r）" % payload["decision"]
    return payload, ""


def write_inspection_report_impl(face: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
    """落账（纯 impl，activity 薄壳包它）：out/inspection/<票号>.json，同票重跑覆盖单文件。"""
    ticket_id = str(face.get("ticket_id") or "")
    if not ticket_id:
        raise ValueError("落账缺 ticket_id")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("%s.json" % ticket_id)
    path.write_text(json.dumps(face, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"file": path.name, "path": str(path), "ticket_id": ticket_id}


# ========================================================================================
# Workflow：扫 → 报 → 人门 → 收口
# ========================================================================================

@dataclass
class InspectionPeriodicInput:
    """一期巡检的输入（声明实例 + 期号；period 空=由 workflow.now() 推——schedule 触发路径）。"""

    instance_id: str
    face: str = "test"
    period: str = ""
    repo_root: str = ""
    scenarios_path: str = ""


@workflow.defn
class InspectionPeriodicWorkflow:
    """一期巡检票。状态机：scan → report → close(人门) → 收口终态。
    业务拒绝不抛异常：扫描/落账失败 → blocked 终态票（可见、可查），不假绿。"""

    def __init__(self) -> None:
        self.stage: str = ""
        self.stage_state: str = "running"
        self.status: str = "running"
        self.decision: str = ""
        self.face: Dict[str, Any] = {}
        self.timeline: List[Dict[str, Any]] = []
        self._close_sig: Optional[Dict[str, str]] = None
        self._gate_err: str = ""

    def _enter(self, stage: str, state: str = "running", reason: str = "") -> None:
        self.stage = stage
        self.stage_state = state
        self.timeline.append({
            "at": workflow.now().isoformat(timespec="seconds"),
            "stage": stage, "state": state, "reason": reason})

    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """人门签字（既有审批门机制）。gate 不匹配的签字忽略留痕，不误收。"""
        payload, err = validate_close_signature(sig)
        if err:
            self._gate_err = err
            workflow.logger.warning("拒收签字：%s", err)
            return
        if self._close_sig is None:
            self._close_sig = payload

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        """票面快照（工单台/运维通道消费；shape=票：stage/stage_state/status/票面/时间线）。"""
        return {
            "id": workflow.info().workflow_id,
            "kind": "inspection",
            "template": "inspection-lite",
            "stage": self.stage,
            "stage_state": self.stage_state,
            "status": self.status,
            "decision": self.decision,
            "face": self.face,
            "timeline": self.timeline,
            "gate_error": self._gate_err,
        }

    @workflow.run
    async def run(self, inp: InspectionPeriodicInput) -> Dict[str, Any]:
        period = inp.period or period_key(workflow.now())
        ticket_id = inspection_ticket_id(inp.instance_id, period)
        self._enter("scan", "running", "测试面扫描（实例 %s 期 %s）" % (inp.instance_id, period))
        scan_result: Dict[str, Any] = await workflow.execute_activity(
            "run_inspection_scan",
            args=[{"repo_root": inp.repo_root, "scenarios_path": inp.scenarios_path}],
            start_to_close_timeout=SCAN_TO, retry_policy=RETRY)
        if not scan_result.get("ok"):
            self.status = "blocked"
            self._enter("scan", "blocked", str(scan_result.get("error") or "扫描失败"))
            self.face = {"ticket_id": ticket_id, "kind": "inspection", "instance_id": inp.instance_id,
                         "face": inp.face, "period": period, "red_line": INSPECTION_RED_LINE,
                         "heartbeat": False, "summary": {}, "findings": [],
                         "suggested_fix_tickets": [], "blocked_reason": str(scan_result.get("error"))}
            return self.snapshot()
        self._enter("report", "running", "发现清单落票面（%d 条）" % len(scan_result["result"].get("findings") or []))
        self.face = build_ticket_face(ticket_id, inp.instance_id, inp.face, period, scan_result["result"])
        written: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self.face],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if written.get("ok"):
            self.face["report_path"] = written["result"].get("path", "")
        # 人门：未批准前收口不可达（awaiting-human 真拦）
        self._enter("close", "awaiting-human", "人审发现清单：sign(gate=%s) approve=收口 / reject=毙单收口" % CLOSE_GATE_ID)
        await workflow.wait_condition(lambda: self._close_sig is not None)
        self.decision = self._close_sig["decision"]  # type: ignore[index]
        self.status = "closed"
        self.face["human_gate"] = dict(self._close_sig or {})
        self._enter("close", "running", "收口：人门决策=%s（who=%s）" % (self.decision, (self._close_sig or {}).get("who", "")))
        final: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self.face],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if final.get("ok"):
            self.face["report_path"] = final["result"].get("path", "")
        self._enter("close", "done", "巡检票收口（决策=%s，发现 high=%s/med=%s/low=%s）" % (
            self.decision, self.face.get("summary", {}).get("high", 0),
            self.face.get("summary", {}).get("med", 0), self.face.get("summary", {}).get("low", 0)))
        return self.snapshot()

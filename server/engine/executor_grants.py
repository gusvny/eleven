"""executor_grants —— 项目执行器授权声明：装载、判定、写面与审计（t260930-14）。

是什么：把执行器面板（server/plugins/executor-panel）的授权面从「纯派生显示」变成
**真声明**——面板成为项目级声明 executor-grants.json 的读写编辑器，引擎写路径在
「调用方=本项目执行器身份」时按声明判定放行/拒收（最小权限默认，fail-closed）。

声明真源（与引擎项目注册表同根——perkey_projects_root，env SANDBAR_PROJECTS_DIR 优先）：
  <root>/<key>/executor-grants.json        声明本体（TS 侧写、Python 侧读判，schema 两侧镜像）
  <root>/<key>/executor-grants-audit.jsonl 审计账（每次拒收/每次授予变更各记一行，append-only）

声明 schema（version 1）：
  {"version": 1,
   "grants": {"sign": true, "rerun": true, ...},     # 只落显式键；缺席=false=未授予
   "night_tier": {"enabled": true, "until": <ms>, "note": "..."},   # 可选；时间盒全权
   "updated_by": "<who>", "updated_at": <ms>}

身份缝（ticket scope 2 的定案，证据见交付报告）：
  - 引擎 spawn 链（agent_activities._prepare_agent_spawn）给泳道 agent 注入
    SANDBAR_CALLER_PROJECT + SANDBAR_CALLER_SURFACE="lane-agent" → 这些调用方的
    identity_src=env，**不是执行器**，维持今天的行为（零回归红线）；
  - 宿主控制台/CLI 跑在引擎仓树内，cwd 一律不推导身份（caller_gate C1 红线）
    → 也不是执行器；
  - watchdog 代建的执行器会话（宿主 Session API，cwd=项目主目录；0.1.5 实证
    SessionCreateRequest 无 env 字段、preset 组合无法注入 shell env）调用写路径时
    身份只能落 **cwd 推导**——ticket.py 把推导出处经
    SANDBAR_CALLER_IDENTITY_SRC="cwd" 透传给 client.py，CHANNEL=cwd 即执行器身份。
  - 残余风险如实记档：真人在项目目录手工直跑写路径同样落 CHANNEL=cwd，会被当作
    执行器受闸（受闸≠提权：未被授予的操作被拒收并点名授予路径）。这与既有的
    injected_by「尽力面标签非安全断言」同一信任档位。

元权限反锁：改/扩授予清单本身是特权操作（META_OP），执行器身份永远不能做——
先于声明读取判定（声明缺席/畸形也锁得住），夜间档也解不开。
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

import json
import os
import time

import shared

# 声明文件名（面板 TS 侧 executor-grants.ts 用同名常量，漂移由两侧测试锁）。
DECL_FILE = "executor-grants.json"
AUDIT_FILE = "executor-grants-audit.jsonl"
DECL_VERSION = 1

# 执行器身份通道：ticket.py 从 cwd 推导出的调用方项目身份（经
# shared.CALLER_IDENTITY_SRC_ENV 透传）。其余通道（arg/env/none）一律不设闸。
EXECUTOR_CHANNEL = "cwd"

# 引擎固定授予操作面（设计稿词表；面板 grants.ts FIXED_OPS 同源——
# 面板用 'reject' 命名打回，本模块用设计稿原文 'send-back'，TS 侧做别名映射）。
GRANT_OPS = ("sign", "send-back", "rerun", "open-ticket", "pause-resume", "cleanup")
# 元权限操作：改/扩授予清单。执行器永远不可做（反锁），不属于 GRANT_OPS。
META_OP = "manage-grants"

# 引擎写 op → 授予操作映射（写闸消费；不在映射内的写 op 对执行器=不可授予，
# 结构化拒收并点名——宿主/引擎件操作面不向执行器开放）。
ENGINE_OP_TO_GRANT: Dict[str, str] = {
    "sign": "sign",
    "authorize": "sign",          # 授权签发走 sign 信号面，同属「签」
    "rework": "send-back",
    "retry_qc": "rerun",
    "ticket-start": "open-ticket",
    "pause": "pause-resume",
    "resume": "pause-resume",
    "cancel": "cleanup",
    "ticket-cancel": "cleanup",
}
# 引擎写 op 中明确不向执行器开放的（引擎件/宿主裁决面——拒收文案按 op 点名）。
ENGINE_HOST_ONLY_OPS = ("update", "ruling")

# 夜间档时间盒上限（毫秒；防「一觉睡到下辈子」的失锁声明——最长 7 天）。
NIGHT_TIER_MAX_MS = 7 * 24 * 3600 * 1000


def grants_root() -> str:
    """声明根（与项目注册表同根：SANDBAR_PROJECTS_DIR > ~/.sandbar/projects）。"""
    return str(shared.perkey_projects_root())


def declaration_path(key: str) -> str:
    return os.path.join(grants_root(), str(key), DECL_FILE)


def audit_path(key: str) -> str:
    return os.path.join(grants_root(), str(key), AUDIT_FILE)


# ---------- 声明装载与校验 ----------

def _read_json(path: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "absent"
    except (OSError, UnicodeDecodeError) as e:
        return None, "unreadable: %s: %s" % (type(e).__name__, e)
    except json.JSONDecodeError as e:
        return None, "malformed: JSON 解析失败（%s）" % e


def validate_declaration(doc: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """声明形状校验（单点；TS 侧写入前过同规则镜像）。返回 (normalized, error)。

    fail-closed 口径：顶层非对象 / version 非 1 / grants 非对象 / grants 值非 bool /
    grants 键不在 GRANT_OPS / night_tier 形状坏 / until 非未来合理时间盒 → 点名拒收。
    """
    if not isinstance(doc, dict):
        return {}, "声明顶层必须是 JSON 对象（收到 %s）" % type(doc).__name__
    if doc.get("version") != DECL_VERSION:
        return {}, "声明 version 必须是 %d（收到 %r）" % (DECL_VERSION, doc.get("version"))
    grants_in = doc.get("grants", {})
    if not isinstance(grants_in, dict):
        return {}, "grants 必须是 JSON 对象（收到 %s）" % type(grants_in).__name__
    grants: Dict[str, bool] = {}
    for k, v in grants_in.items():
        if k not in GRANT_OPS:
            return {}, "grants 键 %r 不在固定操作面 %s 内——未知操作不给静默承认" % (k, list(GRANT_OPS))
        if not isinstance(v, bool):
            return {}, "grants.%s 必须是 boolean（收到 %r）" % (k, v)
        if v:
            grants[k] = True
    night = doc.get("night_tier")
    night_ok: Optional[Dict[str, Any]] = None
    if night is not None:
        if not isinstance(night, dict):
            return {}, "night_tier 必须是对象 {enabled, until, note?}（收到 %s）" % type(night).__name__
        en, until = night.get("enabled"), night.get("until")
        if not isinstance(en, bool) or not isinstance(until, (int, float)) or isinstance(until, bool):
            return {}, "night_tier 需 {enabled: boolean, until: 毫秒时间戳}（收到 enabled=%r until=%r）" % (en, until)
        note = night.get("note", "")
        if not isinstance(note, str):
            return {}, "night_tier.note 必须是字符串（收到 %r）" % (note,)
        night_ok = {"enabled": en, "until": int(until), "note": note[:500]}
    out: Dict[str, Any] = {"version": DECL_VERSION, "grants": grants}
    if night_ok is not None:
        out["night_tier"] = night_ok
    for meta_k in ("updated_by", "updated_at"):
        if meta_k in doc:
            out[meta_k] = doc[meta_k]
    return out, None


def load_declaration(key: str) -> Dict[str, Any]:
    """声明装载（单一读口）。返回：
      {"ok": True, "file", "decl", "grants", "night_tier", "declared": True}
      {"ok": False, "kind": "absent"|"malformed"|"unreadable", "reason", "file"}
    absent=项目还没声明过（真声明缺席，不是空授予冒充）；declared=False 只随 absent。"""
    path = declaration_path(key)
    doc, err = _read_json(path)
    if doc is None:
        if err == "absent":
            return {"ok": False, "kind": "absent", "declared": False,
                    "reason": "项目 %s 尚无执行器授权声明（缺 %s）——零授予=只读与问" % (key, path),
                    "file": path}
        kind = "unreadable" if str(err).startswith("unreadable") else "malformed"
        return {"ok": False, "kind": kind, "declared": True,
                "reason": "执行器授权声明不可判定（%s：%s）——fail-closed 拒收，绝不静默放行" % (kind, err),
                "file": path}
    normalized, verr = validate_declaration(doc)
    if verr:
        return {"ok": False, "kind": "malformed", "declared": True,
                "reason": "执行器授权声明被拒收（%s：%s）——fail-closed 拒收，绝不静默放行" % (path, verr),
                "file": path}
    return {"ok": True, "declared": True, "file": path, "decl": normalized,
            "grants": dict(normalized.get("grants") or {}),
            "night_tier": normalized.get("night_tier")}


def provenance_of(load: Dict[str, Any], grant_op: str, now_ms: int) -> Dict[str, Any]:
    """「哪个声明键定了当前值」的溯源面（与 config-provenance 同纪律：透传不二次推导）。"""
    if not load.get("ok"):
        return {"file": load.get("file"), "keys": {grant_op: "no-usable-declaration (%s)" % load.get("kind")}}
    keys: Dict[str, str] = {}
    if (load.get("grants") or {}).get(grant_op) is True:
        keys[grant_op] = "grants.%s @ %s" % (grant_op, load.get("file"))
    night = load.get("night_tier")
    if isinstance(night, dict) and night.get("enabled") and float(night.get("until") or 0) > now_ms:
        keys.setdefault(grant_op, "night_tier.until=%s @ %s" % (night.get("until"), load.get("file")))
    keys.setdefault(grant_op, "not-declared (default: refuse) @ %s" % load.get("file"))
    return {"file": load.get("file"), "keys": keys}


# ---------- 审计（每次拒收 / 每次授予变更各一行） ----------

def append_audit(key: str, row: Dict[str, Any]) -> None:
    """审计落账（append-only JSONL；写失败不掩盖主流程——审计是尽力面，判定不受它反向影响）。"""
    path = audit_path(key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


# ---------- 判定核 ----------

def _refuse(why: str, grant_op: str, load: Optional[Dict[str, Any]],
            now_ms: int, audit_sink: Optional[Callable[[str, Dict[str, Any]], None]],
            key: str, op: str) -> Dict[str, Any]:
    if audit_sink is not None:
        audit_sink(key, {"at": now_ms, "action": "refuse", "project": key, "op": op,
                         "grant_op": grant_op, "why": why[:500]})
    out: Dict[str, Any] = {"allowed": False, "why": why, "grant_op": grant_op,
                           "provenance": provenance_of(load, grant_op, now_ms) if load else None}
    return out


def judge_core(channel: str, op: str, key: str,
               load_face: Callable[[str], Dict[str, Any]],
               now_ms: int,
               audit_sink: Optional[Callable[[str, Dict[str, Any]], None]] = append_audit,
               ) -> Dict[str, Any]:
    """执行器授权判定核（IO 注入式纯核；judge() 是真 IO 包装）。

    channel != cwd（泳道 agent=env 注入 / 显式参数 / 引擎仓树内未推导）→ 放行不设闸
    ——「零回归红线」：非执行器调用方一个字节的行为都不变。"""
    op_s = str(op or "")
    # op 双形接受：引擎写 op 名（映射）或授予面名（GRANT_OPS 原词）。
    grant_op = op_s if op_s in GRANT_OPS else ENGINE_OP_TO_GRANT.get(op_s)
    if channel != EXECUTOR_CHANNEL:
        return {"allowed": True, "why": "", "grant_op": grant_op, "enforced": False,
                "provenance": None}
    # 元权限反锁：先于声明读取（声明缺席/畸形也锁得住），夜间档也解不开。
    if op_s == META_OP:
        return _refuse(
            "执行器元权限反锁：改/扩授予清单（%s）是宿主特权操作，执行器永远不能自己做"
            "（声明缺席/畸形/夜间档均不解锁）——由宿主在执行器面板 Grants 页操作" % META_OP,
            META_OP, None, now_ms, audit_sink, key, op_s)
    if grant_op is None:
        hint = "（%s 属宿主/引擎件操作面）" % op_s if op_s in ENGINE_HOST_ONLY_OPS else ""
        return _refuse(
            "执行器授权拒收：操作 %s 不在可授予的固定操作面 %s 内%s——固定面外没有"
            "「执行器可做」这回事（fail-closed）" % (op_s, list(GRANT_OPS), hint),
            grant_op or "(unmapped)", None, now_ms, audit_sink, key, op)
    load = load_face(key)
    if not load.get("ok"):
        return _refuse(
            "%s——要在执行器面板 Grants 页为项目 %s 授予 %s（声明文件 %s）"
            % (load.get("reason"), key, grant_op, load.get("file")),
            grant_op, load, now_ms, audit_sink, key, op)
    if (load.get("grants") or {}).get(grant_op) is True:
        return {"allowed": True, "why": "", "grant_op": grant_op, "enforced": True,
                "provenance": provenance_of(load, grant_op, now_ms)}
    night = load.get("night_tier")
    if isinstance(night, dict) and night.get("enabled") and float(night.get("until") or 0) > now_ms:
        return {"allowed": True, "why": "", "grant_op": grant_op, "enforced": True,
                "provenance": provenance_of(load, grant_op, now_ms)}
    return _refuse(
        "执行器授权拒收：声明 %s 未授予 %s（grants.%s 缺席或=false）——要授予请在"
        "执行器面板 Grants 页保存 {\"grants\": {\"%s\": true}}（宿主操作）"
        % (load.get("file"), grant_op, grant_op, grant_op),
        grant_op, load, now_ms, audit_sink, key, op)


def judge(identity: Dict[str, Any], op: str, key: str, now_ms: Optional[int] = None) -> Dict[str, Any]:
    """真 IO 判定（client.py 写闸消费）。identity 取 caller_gate.resolve_identity 输出
    （外加 client._caller_identity 注入的 channel_src——ticket.py 透传的推导出处）。

    key=目标票/创建目标所属项目（判定对象是「本项目的执行器动本项目的票」；跨项目
    已由跨项目闸先行拒收，这里 key 只在 pass 之后消费）。"""
    channel = str(identity.get("channel_src") or identity.get("src") or "")
    ms = int(now_ms if now_ms is not None else time.time() * 1000)
    return judge_core(channel, str(op or ""), str(key or ""), load_declaration, ms)


# ---------- 声明写面（面板 TS 侧是主编辑器；本函数=引擎侧同规则写口与测试/CLI 面） ----------

# dead-man-exempt: save_declaration
# （引擎侧声明写口=反锁与原子写的单一真源：面板 TS 侧 saveGrantsDecl 是主编辑器，
#   本函数是同规则镜像写口——消费面=本模块 UT 与后续宿主 CLI/代理接线；非死码。
#   退役前先删 TS 镜像，两侧一起退役。）
def save_declaration(key: str, grants: Dict[str, Any], by: str, now_ms: int,
                     night_tier: Optional[Dict[str, Any]] = None,
                     caller_channel: str = "",
                     audit_sink: Callable[[str, Dict[str, Any]], None] = append_audit,
                     ) -> Dict[str, Any]:
    """声明写入（原子：tmp → 校验 → 回读再校验 → rename；任一步失败原文件逐字节不动）。

    反锁：caller_channel=cwd（执行器身份）一律拒收——执行器永远不能写自己的授予
    清单，哪怕「缩小」。返回 {"saved": bool, "reason"?, "file", "resolved"?}。"""
    if not str(key or ""):
        return {"saved": False, "reason": "缺项目 key", "file": None}
    if caller_channel == EXECUTOR_CHANNEL:
        return {"saved": False, "file": declaration_path(key),
                "reason": "执行器元权限反锁：执行器身份不能改/扩/缩自己的授予清单"
                          "（manage-grants 是宿主特权）——由宿主在执行器面板 Grants 页操作"}
    who = str(by or "").strip()
    if not who:
        return {"saved": False, "reason": "缺 by（谁在改授予清单——授予变更必须记名）", "file": None}
    if not isinstance(grants, dict):
        return {"saved": False, "reason": "grants 必须是对象 {op: boolean}", "file": None}
    doc: Dict[str, Any] = {"version": DECL_VERSION,
                           "grants": {k: bool(v) for k, v in grants.items() if v is True},
                           "updated_by": who[:64], "updated_at": int(now_ms)}
    if night_tier is not None:
        doc["night_tier"] = night_tier
    normalized, verr = validate_declaration(doc)
    if verr:
        return {"saved": False, "reason": verr, "file": declaration_path(key)}
    path = declaration_path(key)
    prev_raw, _ = _read_json(path)
    prev_norm: Dict[str, Any] = {}
    if isinstance(prev_raw, dict):
        prev_norm, _ = validate_declaration(prev_raw)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        serialized = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(serialized)
        with open(tmp, "r", encoding="utf-8") as f:
            back = json.load(f)
        re_norm, re_err = validate_declaration(back)
        if re_err:
            os.unlink(tmp)
            return {"saved": False, "reason": "回读校验被拒收（不落一份坏声明）：%s" % re_err, "file": path}
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return {"saved": False, "reason": "写盘失败：%s: %s" % (type(e).__name__, e), "file": path}
    audit_sink(key, {"at": int(now_ms), "action": "grant-change", "project": key,
                     "who": who[:64],
                     "from": prev_norm.get("grants") or {}, "to": normalized.get("grants") or {},
                     "night_tier": normalized.get("night_tier")})
    return {"saved": True, "file": path, "resolved": normalized}

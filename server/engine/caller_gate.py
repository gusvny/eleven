"""caller_gate — 跨项目写操作闸：调用方身份解析与判定矩阵（t260915-12）。

层次与真源：
  - 常量与 workflow 侧纯判定在 shared.py（CALLER_PROJECT_ENV / CALLER_UNDECLARED_MARK /
    UNDECLARED_POLICY / 上限常量 / cross_project_judge）——worker 沙箱只依赖 shared；
  - This module = the **client-side** resolution and matrix. Identity priority order:
    explicit arg > env > narrow cwd fallback > declared-executor-session seam >
    undeclared. The cwd fallback carries the **repo-tree exclusion**
    (shared.project_key_for_dir): a client run inside a real project workspace derives
    identity from cwd (source = cwd x registry); a cwd inside the engine repo tree
    (dsh toolchain spawn, console plugins, other indirect calls) never derives — a
    repo-tree cwd names "the engine being called", not "the calling session", and the
    gate prefers undeclared over an invented identity (review C1 behaviour red line).
    The single exception is the declared-executor-session seam (t261004-31): a cwd
    swallowed by the repo-tree exclusion that still resolves, ignoring the exclusion,
    to exactly one registered project, AND whose caller session id is named in that
    project's executor_sessions — both anchors (cwd x host declaration) must hold;
    an unnamed session or a missing session id stays undeclared. Pure functions;
    shared is the only dependency (KI-032 single-source discipline).

口径（工单验收与 review 条件的落点）：
  - 身份不许凭空自认：值必须过 PROJECT_KEY_RE 形状白名单；形状非法的显式声明/env
    =结构化拒收（误配显式暴露，不静默当 undeclared）。
  - 形状合法但注册表查无此 key：**仍按 declared 处理**（review C2②：不匹配即拒、
    误配显式暴露，fail-closed 方向），回执附 caller_project_registered=false 观测键。
  - 目标票 project 读取失败≠越权（KI-025）：瞬时失败=KIND_TRANSIENT 可重试，不存在=
    KIND_NOT_FOUND，闸不把抖动当越权（客户端把这些归 client.py 的既有分级）。
  - undeclared 策略：shared.undeclared_policy()（旋钮 SANDBAR_UNDECLARED_POLICY，缺省
    "refuse"——t260925-08 翻严；record=旋钮显式选入的过渡记名）。
"""
from typing import Any, Dict, Optional, Tuple

import os

import shared


def _norm(path: str) -> str:
    """路径归一（realpath）；空/异常→空串（探测路径坏掉=不推导，不炸）。"""
    try:
        return os.path.realpath(str(path or ""))
    except Exception:  # noqa: BLE001
        return ""

# 判定决策（judge_caller 返回值 decision 字段）：
#   pass             放行（declared 同项目 / 无比对对象）
#   pass_override    放行+越权记名（declared 异项目+旗）
#   record_undeclared 放行+undeclared 记名（哨兵盖章，workflow 侧落账）
#   refuse           拒收（declared 异项目无旗 / 畸形旗 / undeclared 且策略=refuse）


class CallerIdentityError(ValueError):
    """调用方身份声明形状非法（显式参数/env 值不过 PROJECT_KEY_RE）。fail-closed：
    误配显式暴露给人话，不静默回落 undeclared。"""


def _check_shape(value: str, origin: str) -> str:
    v = str(value or "").strip()
    if not v:
        raise CallerIdentityError(
            "caller project identity (%s) is empty/blank only — either drop the "
            "declaration (= undeclared identity, recorded or refused per policy), "
            "or give a valid project key (allowlist: lowercase letters/digits/hyphen)" % origin)
    if len(v) > 64 or not shared.PROJECT_KEY_RE.match(v):
        raise CallerIdentityError(
            "caller project identity has an invalid shape: %r (from %s; allowlist %s) "
            "— fix %s or the caller injection chain and retry"
            % (v[:64], origin, shared.PROJECT_KEY_RE.pattern, origin))
    return v


def resolve_identity(explicit: str, env_raw: str,
                     cwd: str = "", exclude_trees: Tuple[str, ...] = (),
                     projects: Optional[list] = None,
                     caller_session: str = "",
                     declared_sessions_by_key: Optional[Dict[str, Any]] = None,
                     ) -> Dict[str, Any]:
    """Caller identity resolution (single entry). Priority: explicit arg > env >
    narrow cwd fallback (a cwd under an exclude tree — the engine repo tree — never
    derives) > declared-executor-session seam (t261004-31) > undeclared.

    Declared-executor-session seam: with the cwd under an exclude tree (the exclusion
    itself stays fully in force for anyone not named), if (a) the cwd still resolves,
    ignoring the exclusion, to exactly one registered project, and (b) the caller
    session id is named in that project's executor_sessions — identity = that project,
    src="declared-session". Both anchors must hold: cwd anchors which project, the
    host-written declaration anchors who may claim it. An indirect call with no session
    id, or a session id not named, still resolves to none; the repo-tree red line is
    unchanged. Pure parameter injection: caller_session and declared_sessions_by_key
    are loaded and passed by the caller (client._caller_identity /
    executor_requests.resolve_caller); this function does no IO.

    Returns {"value": raw key before the shared.CALLER_UNDECLARED_MARK swap, "src":
    "arg"|"env"|"cwd"|"declared-session"|"none", "identity_class":
    "declared"|"undeclared"} — an empty value means undeclared (the caller swaps in the
    shared.CALLER_UNDECLARED_MARK sentinel at stamp time). A malformed shape raises
    immediately (fail-closed)."""
    if str(explicit or "").strip():
        return {"value": _check_shape(explicit, "explicit arg caller_project"),
                "src": "arg", "identity_class": "declared"}
    if str(env_raw or "").strip():
        return {"value": _check_shape(env_raw, "env %s" % shared.CALLER_PROJECT_ENV),
                "src": "env", "identity_class": "declared"}
    ncwd = _norm(cwd)
    if ncwd:
        trees = tuple(_norm(t) for t in exclude_trees)
        key = shared.project_key_for_dir(ncwd, projects or [], trees)
        if key:
            return {"value": key, "src": "cwd", "identity_class": "declared"}
        # t261004-31 declared-executor-session seam: opens only for a cwd the repo-tree
        # exclusion swallowed, and only for a session the project declaration names —
        # nobody named (declaration absent/malformed, session id absent) stays src=none.
        if trees:
            raw_key = shared.project_key_for_dir(ncwd, projects or [], ())
            sessions = (declared_sessions_by_key or {}).get(raw_key) or ()
            sid = str(caller_session or "").strip()
            if raw_key and sid and sid in tuple(sessions):
                return {"value": raw_key, "src": "declared-session",
                        "identity_class": "declared"}
    return {"value": "", "src": "none", "identity_class": "undeclared"}


def validate_override(args: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], str]:
    """越权旗归一与校验（review C3/C4：by/reason 必填非空+上限；畸形旗=拒收不静默）。

    接受两形：args["cross_project"]={"by","reason"}（结构形，schema 主形——**by 严格
    必填，不从 args.who 兜底**：旗在场却缺记名人=畸形，fail-closed 拒收，防「who 是
    操作人、by 是越权人」两个语义被悄悄合并）或 args["cross_project_reason"]（扁平形，
    CLI 人体工学；by 缺省取 args["by"]|args["who"]——同一次调用里操作人与越权人显式
    合一，由调用方自认）。
    返回 ({"by","reason"}|None, err)；旗不在场=(None, "")。"""
    flag = args.get("cross_project")
    flat_reason = str(args.get("cross_project_reason") or "").strip()
    if flag is None and not flat_reason:
        return None, ""
    by, reason = "", ""
    if isinstance(flag, dict):
        by = str(flag.get("by") or "").strip()
        reason = str(flag.get("reason") or "").strip()
    elif flag is not None:
        return None, ("override flag cross_project must be an object {by, reason} (got %s) — "
                      % type(flag).__name__)
    if flat_reason:
        if reason:
            return None, "duplicate override reason: give only one of cross_project.reason and cross_project_reason"
        reason = flat_reason
        by = str(args.get("by") or args.get("who") or "").strip()  # 扁平形才兜底
    if not by:
        return None, "override flag missing by (who overrides — the flag must be named); or use the flat form cross_project_reason so by takes the operator by|who"
    if not reason:
        return None, "override flag missing reason (why cross-project — reason is required; the record stays auditable)"
    if len(by) > shared.CROSS_PROJECT_BY_LIMIT:
        return None, "override flag by over limit (%d > %d chars)" % (len(by), shared.CROSS_PROJECT_BY_LIMIT)
    if len(reason) > shared.CROSS_PROJECT_NOTE_LIMIT:
        return None, ("override flag reason over limit (%d > %d chars) — split it and add the rest in the target ticket's ruling/pending"
                      % (len(reason), shared.CROSS_PROJECT_NOTE_LIMIT))
    return {"by": by, "reason": reason}, ""


def judge_caller(identity: Dict[str, Any], target: str,
                 override: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """客户端判定矩阵（唯一权威实现；README 的矩阵表是它的文档投影）。

    identity=resolve_identity 输出；target=目标票 project（""=引擎件无项目面）；
    override=validate_override 输出。返回：
      {"decision", "why", "stamp", "notice", "override_used"}
      stamp=应盖进信号载荷的 caller_project 值（declared=key；undeclared=哨兵；
      拒收路径无意义）。target=""（engine-internal）时恒 pass——调用量身记
      identity_class=engine-internal 由调用方（client.py）覆写。"""
    value = str(identity.get("value") or "")
    iclass = str(identity.get("identity_class") or "undeclared")
    target = str(target or "")
    if iclass == "undeclared":
        # target=""（引擎件无项目面）=无比对对象，恒放行（与 declared 同项目口径一致；
        # t260925-08 零回归：cancel 打在无 ProjectKey SA 的引擎件上仍是 pass，stamp 用
        # 哨兵保留身份信息面，identity_class=engine-internal 由调用方覆写）。策略解析
        # 只对有比对对象的写生效——引擎件不该被「调用方没声明项目」卡死。
        if not target:
            return {"decision": "pass", "why": "", "stamp": shared.CALLER_UNDECLARED_MARK,
                    "notice": "", "override_used": False}
        # t260925-08：策略走 undeclared_policy() 单点（旋钮 env；缺省=refuse）。
        # 旋钮畸形值不外抛——转结构化拒收（人话点名误配原文），client 侧同形状回执（N3）。
        try:
            policy = shared.undeclared_policy()
        except ValueError as e:
            return {"decision": "refuse",
                    "why": "cross-project gate: %s (refused fail-closed on a malformed policy value)" % e,
                    "stamp": "", "notice": "", "override_used": False}
        if policy == "refuse":
            return {"decision": "refuse",
                    "why": "cross-project gate: caller project identity undeclared "
                           "(%s not injected and no explicit arg); engine policy = "
                           "refuse — declare the caller project through the injection "
                           "chain/wrapper, then operate"
                           % shared.CALLER_PROJECT_ENV,
                    "stamp": "", "notice": "", "override_used": False}
        return {"decision": "record_undeclared", "why": "",
                "stamp": shared.CALLER_UNDECLARED_MARK,
                "notice": ("caller project identity undeclared (%s not injected and no "
                           "explicit arg); this write passes under the record policy "
                           "(explicitly opted in via knob %s=record; default policy = "
                           "refuse; injection contract in server/engine/README.md)"
                           % (shared.CALLER_PROJECT_ENV, shared.UNDECLARED_POLICY_ENV)),
                "override_used": False}
    # declared
    if not target:
        return {"decision": "pass", "why": "", "stamp": value,
                "notice": "", "override_used": False}
    if value == target:
        return {"decision": "pass", "why": "", "stamp": value,
                "notice": "", "override_used": False}
    if override is None:
        return {"decision": "refuse",
                "why": "cross-project write refused: caller project identity %s does "
                       "not match the target ticket's project %s and no override flag "
                       "is present — operate only on this project's tickets; for a true "
                       "cross-project need use the explicit override flag "
                       "cross_project={by, reason required} (the record stays auditable)" % (value, target),
                "stamp": "", "notice": "", "override_used": False}
    return {"decision": "pass_override", "why": "",
            "stamp": value,
            "notice": ("cross-project override recorded: caller project %s operates on "
                       "project %s tickets (by=%s, reason=%s)"
                       % (value, target, override["by"], override["reason"][:120])),
            "override_used": True}


def identity_receipt(identity: Dict[str, Any], verdict: Dict[str, Any],
                     identity_class: str = "") -> Dict[str, Any]:
    """回执身份键（单一构造点；admin.log 行键由 _emit 从回执同键提取，audit.py 落账）。

    injected_by（t260925-08）：**尽力面标签，非安全断言**——只当 identity_src=env 时给，
    值域 {lane-agent, external-env}：env 伴随 CALLER_SURFACE_ENV="lane-agent"（引擎
    spawn 链注入时设置）→ lane-agent，否则 external-env（手工旁路设 env 也落此值）。
    标签只回答「身份从哪个面进来」，不回答「谁注入的」——审计不得单凭此键下
    「谁操作」断言（安全断言归 spawn 链注入 + 越权旗 by/reason 必填两机制）。"""
    iclass = identity_class or str(identity.get("identity_class") or "undeclared")
    keys = {
        "caller_project": str(verdict.get("stamp") or identity.get("value") or ""),
        "identity_src": str(identity.get("src") or "none"),
        "identity_class": iclass,
    }
    if keys["identity_src"] == "env":
        keys["injected_by"] = shared.CALLER_SURFACE_LANE_AGENT \
            if str(os.environ.get(shared.CALLER_SURFACE_ENV) or "").strip() \
            == shared.CALLER_SURFACE_LANE_AGENT else "external-env"
    if keys["caller_project"] == shared.CALLER_UNDECLARED_MARK:
        keys["caller_project"] = ""  # 回执面向人：undeclared 用空值+identity_class 表达
    if verdict.get("override_used"):
        keys["cross_project_used"] = True
    if verdict.get("notice"):
        keys["cross_project_notice"] = verdict["notice"]
    return keys

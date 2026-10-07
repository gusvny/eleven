# -*- coding: utf-8 -*-
"""executor_requests —— 执行器请求的引擎侧投递口（t261004-23）。

是什么：面板写面凭据门（t261004-18，KI-193）收口了 POST /api/requests 之后，执行器
唯一的「把请求摆到宿主面前」的合法通道。本模块=引擎侧投递口：辨认调用方身份、按
请求契约（notes/discussions/261003-executor-panel-redesign.md §8 写侧一半）校验形状、
把一行请求追加进项目请求账 `<ledger_root>/<key>/requests.jsonl`，并带显式来源标记
`surface: "engine"`——面板读侧零改动（readRequests 透传未知键）即可把引擎投递的行
显示进 waiting 列表。

宿主侧的应答/授权/dismiss 仍只在面板（控制台会话凭据门后）；本模块不提供任何应答面。

Thread face (t261007-02): request_thread.py lands reply / state / link rows on
the same ledger (five states, four link kinds, the two ownership fields, three
register-derived source classes). This gate's head-row contract is unchanged
(the new fields subject/epic/... land through the thread face's op=file);
legacy head rows are valid history and readers tolerate them.

CLI（与其他引擎条目同形：一个 JSON argv）：
    python3 server/engine/executor_requests.py '<json>'
  输入体：{op:"file", project:<key>, kind, question, detail?, options?,
           default_action?, expires_at?, raised_by?, caller_project?}
  输出：stdout 一行 JSON 回执；ok=true 带 row，拒收带 field（失败字段名）+ error。
  退出码：0=落账；2=拒收（含 argv 非 JSON/非对象——field=body）。

身份（无匿名投递）：调用方项目身份经 caller_gate.resolve_identity（arg > env
SANDBAR_CALLER_PROJECT > cwd 窄兜底带引擎仓树排除）；会话 id 经
executor_grants.caller_session_id()（DSH_SESSION_ID > DSH_HEADLESS_SESSION，dsh
工具链注入，调用方 prompt 改不了注入链）；执行器判定经
executor_grants.is_executor_channel（cwd 推导通道 或 声明 executor_sessions 点名）。
三关任一不过=结构化拒收，reason 点名（undeclared / session-absent /
lane-agent-exempt / session-not-named）。行内 raised_by=解析出的会话 id；调用方自报
raised_by 且与解析值不符=拒收（field=raised_by）——来源必须真实。

账本根（与面板 requestsLedgerFile 同词表，漂移由单测锁）：
  SANDBAR_PANEL_DIR > 实例 projects 根（缺省实例 $HOME/.sandbar/projects；
  非缺省实例 <DSH_HOME>/sandbar/projects——t261003-04：临时实例绝不顺 $HOME
  兜底摸进生产请求账）。

刻意收窄（review 意见 #1，如实记档）：面板 TS appendRequest 的 fail-closed 地板是
选项 ≤8 项、单项 ≤80 字符；本口按 §8 散文上限收紧为 2–4 项、单项 ≤20 字符——
引擎会拒掉账本本身肯收的体（如 5 个选项）。这是契约收窄不是 bug；拒收文案带
实际计数/长度。

Direct-write closure (t261006-05, KI-208): resident executor sessions (the
cwd-derived channel, or the declared-session dual-anchor seam) must NOT append
the ledger in their own process. The ledger sits outside the session's
workspace-write sandbox, so a denied append leaves only the escalation prompt,
and an executor deployment has no approval answerer (261006 evidence: a session
parked on approval/asked for four hours). Callers on those channels get a
structured refusal (field=channel) naming the way out: client.py deliver
(face "request") — the engine process performs the append, never the session's
sandbox. The env channel (explicit SANDBAR_CALLER_PROJECT) stays open: env
injection is the scripts/fixtures/ops face, not the resident-session shape
(the host Session API cannot inject shell env into a session — caller_gate's
machine-observable seam note). Callers whose identity cannot resolve at all are
already refused by the existing caller gates (zero writes); this closure does
not depend on them.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import caller_gate
import executor_grants
import shared

# 来源标记：面板投递的行无此键，引擎投递的行恒带——读方据此分辨。
SURFACE_ENGINE = "engine"

# Direct-write closure (t261006-05, KI-208): these two channels ARE the resident
# executor session (watchdog-created shape). An in-process append lands outside
# the sandbox; a denial leaves only the escalation prompt, which has no answerer.
# Closed as a structured refusal; the way out is the engine-side delivery face.
RESIDENT_EXECUTOR_CHANNELS = ("cwd", "declared-session")
DIRECT_WRITE_REFUSAL = (
    "direct in-process ledger append is closed for resident executor sessions "
    "(channel=%s): the project ledger sits outside the session workspace, a denied "
    "append leaves only the escalation prompt, and an executor session has no "
    "approval answerer (KI-208). Submit through the engine-side delivery face "
    "instead: python3 server/engine/client.py deliver '<json>' (face \"request\") — "
    "the engine process performs the append."
)

# 请求契约（§8 写侧一半；与 TS 账本地板刻意收窄的差异见模块头）。
QUESTION_MAX = 60          # 一次请求=一个决定，问句一行 ≤60 字符
OPTIONS_MIN = 2
OPTIONS_MAX = 4
OPTION_LABEL_MAX = 20      # 短标签，不展开就能点
KIND_MAX = 40              # 与 TS appendRequest 同地板：非空短字符串
RAISED_BY_MAX = 120        # 与 TS 同地板：非空短会话 id

USAGE = ("usage: python3 server/engine/executor_requests.py "
         "'{\"op\":\"file\",\"project\":\"<key>\",\"kind\":...,\"question\":...}'")


# ---------- 账本根（TS requestsLedgerFile 词表的 python 镜像） ----------

def _join(*parts: str) -> str:
    return os.path.join(*[p for p in parts if p])


def instance_projects_root(env: Dict[str, str]) -> str:
    """实例 projects 根兜底（watchdog config.ts instanceProjectsRoot 的镜像）：
    缺省实例（DSH_HOME 解析后 = $HOME/.dsh）→ $HOME/.sandbar/projects；
    非缺省实例 → <DSH_HOME>/sandbar/projects——绝不顺 $HOME 兜底。"""
    home = str(env.get("HOME") or "")
    dsh_home = str(env.get("DSH_HOME") or "") or _join(home, ".dsh")
    try:
        default_dsh = os.path.realpath(_join(home, ".dsh"))
        is_default = os.path.realpath(dsh_home) == default_dsh
    except OSError:
        is_default = dsh_home == _join(home, ".dsh")
    sandbar_root = _join(home, ".sandbar") if is_default else _join(dsh_home, "sandbar")
    return _join(sandbar_root, "projects")


def ledger_root(env: Optional[Dict[str, str]] = None) -> Path:
    """请求账根：SANDBAR_PANEL_DIR > 实例 projects 根（与 TS requestsLedgerFile 同序）。"""
    env = dict(os.environ if env is None else env)
    panel = str(env.get("SANDBAR_PANEL_DIR") or "")
    return Path(panel if panel else instance_projects_root(env))


def ledger_file(key: str, env: Optional[Dict[str, str]] = None) -> Path:
    return ledger_root(env) / str(key) / "requests.jsonl"


# ---------- 形状校验（拒收一律点名失败字段） ----------

def _refuse(field: str, error: str) -> Dict[str, Any]:
    return {"ok": False, "field": field, "error": error}


def validate_request(body: Dict[str, Any]) -> Dict[str, Any]:
    """§8 写侧契约校验。返回 {"ok": True, "fields": {...norm fields...}} 或拒收。"""
    question = body.get("question")
    if not isinstance(question, str) or question.strip() == "":
        return _refuse("question", "question must be a non-empty string (one plain question per request)")
    if len(question.strip()) > QUESTION_MAX:
        return _refuse("question", "question too long for a card (%d > %d chars) — keep it to one line"
                       % (len(question.strip()), QUESTION_MAX))
    kind = body.get("kind")
    if not isinstance(kind, str) or kind.strip() == "" or len(kind) > KIND_MAX:
        return _refuse("kind", "kind must be a non-empty string of at most %d chars" % KIND_MAX)
    detail = body.get("detail", "")
    if detail is None:
        detail = ""
    if not isinstance(detail, str):
        return _refuse("detail", "detail must be a string (evidence only, under the question)")
    options_in = body.get("options")
    options: Optional[List[str]] = None
    if options_in is not None:
        if not isinstance(options_in, list):
            return _refuse("options", "options must be an array of short labels (got %s)" % type(options_in).__name__)
        options = []
        for o in options_in:
            if not isinstance(o, str) or o.strip() == "":
                return _refuse("options", "every option must be a non-empty string (blank labels are not accepted)")
            label = o.strip()
            if len(label) > OPTION_LABEL_MAX:
                return _refuse("options", "option label too long (%d > %d chars): %s"
                               % (len(label), OPTION_LABEL_MAX, label[:40]))
            if label not in options:
                options.append(label)
        if len(options) < OPTIONS_MIN or len(options) > OPTIONS_MAX:
            return _refuse("options", "options must be %d to %d short labels (got %d)"
                           % (OPTIONS_MIN, OPTIONS_MAX, len(options)))
    default_action = body.get("default_action", "")
    if default_action is None:
        default_action = ""
    if not isinstance(default_action, str):
        return _refuse("default_action", "default_action must be a string")
    if not options and default_action.strip() == "":
        return _refuse("default_action", "default_action is required when there are no options "
                                         "(state what happens if the host does not answer)")
    expires_in = body.get("expires_at")
    expires: Optional[int] = None
    if expires_in is not None:
        if isinstance(expires_in, bool):
            return _refuse("expires_at", "expires_at must be a millisecond timestamp, an ISO 8601 string, or null")
        if isinstance(expires_in, (int, float)):
            if expires_in < 0:
                return _refuse("expires_at", "expires_at must be a non-negative millisecond timestamp (got %r)" % (expires_in,))
            expires = int(expires_in)
        elif isinstance(expires_in, str):
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(expires_in.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                expires = int(dt.timestamp() * 1000)
            except ValueError:
                return _refuse("expires_at", "expires_at string must parse as ISO 8601 (got %s)" % expires_in[:64])
        else:
            return _refuse("expires_at", "expires_at must be a millisecond timestamp, an ISO 8601 string, or null")
    return {"ok": True, "fields": {
        "kind": kind, "question": question, "detail": detail,
        "default_action": default_action,
        "options": options, "expires_at": expires,
    }}


def make_request_id(now_ms: int, seq: int) -> str:
    """与 TS makeRequestId 同形：req-<ms>-<四位序号>（序号由调用方给，测试可预测）。"""
    return "req-%d-%04d" % (now_ms, seq)


# ---------- 身份辨认（无匿名投递） ----------

def resolve_caller(explicit_project: str = "",
                   env: Optional[Dict[str, str]] = None,
                   cwd: str = "",
                   projects: Optional[Sequence[Dict[str, Any]]] = None,
                   exclude_trees: Sequence[str] = (),
                   load_decl: Optional[Callable[[str], Dict[str, Any]]] = None,
                   ) -> Dict[str, Any]:
    """调用方身份三关：项目身份 > 会话 id > 执行器通道判定。

    返回 {"ok": True, "project", "session", "channel"} 或
    {"ok": False, "field": "caller", "reason": <named reason>}。
    reason 词表：caller-undeclared / session-absent / lane-agent-exempt /
    session-not-named。env/cwd/projects/exclude_trees/load_decl 全注入（测试零真环境）。"""
    env = dict(os.environ if env is None else env)
    load_decl = load_decl or executor_grants.load_declaration
    session = ""
    for env_name in executor_grants.CALLER_SESSION_ENVS:
        sid = str(env.get(env_name) or "").strip()
        if sid:
            session = sid
            break
    # Declaration anchor of the declared-executor-session seam (t261004-31): load
    # executor_sessions per registered project; absent/malformed all count as empty
    # (the seam stays closed; a broken declaration file never escalates). When the cwd
    # sits inside an exclude tree, resolve_identity uses this to judge a named session;
    # empty projects = no seam at all.
    declared_by_key: Dict[str, tuple] = {}
    for p in projects or ():
        pkey = str((p or {}).get("key") or "")
        if pkey and shared.PROJECT_KEY_RE.match(pkey):
            load = load_decl(pkey)
            if load.get("ok"):
                declared_by_key[pkey] = tuple(load.get("executor_sessions") or ())
    try:
        identity = caller_gate.resolve_identity(
            str(explicit_project or ""),
            str(env.get(shared.CALLER_PROJECT_ENV) or ""),
            cwd=str(cwd or ""), exclude_trees=tuple(exclude_trees or ()),
            projects=list(projects or []) or None,
            caller_session=session,
            declared_sessions_by_key=declared_by_key)
    except caller_gate.CallerIdentityError as e:
        return {"ok": False, "field": "caller",
                "reason": "caller-identity-malformed: %s" % e}
    key = str(identity.get("value") or "")
    if not key:
        return {"ok": False, "field": "caller",
                "reason": "caller-undeclared: no caller project identity "
                          "(set %s, pass caller_project, or run inside the project directory)"
                          % shared.CALLER_PROJECT_ENV}
    if not session:
        return {"ok": False, "field": "caller",
                "reason": "session-absent: no caller session id in %s — the row must record who raised it"
                          % "/".join(executor_grants.CALLER_SESSION_ENVS)}
    channel = str(env.get(shared.CALLER_IDENTITY_SRC_ENV) or "").strip() \
        or str(identity.get("src") or "")
    lane_surface = str(env.get(shared.CALLER_SURFACE_ENV) or "")
    load = load_decl(key)
    sessions = tuple(load.get("executor_sessions") or ()) if load.get("ok") else ()
    if not executor_grants.is_executor_channel(channel, lane_surface, sessions, session):
        if channel == "env" and lane_surface.strip() == shared.CALLER_SURFACE_LANE_AGENT:
            reason = ("lane-agent-exempt: lane agents are not executors; "
                      "requests are filed by the project executor session")
        else:
            reason = ("session-not-named: session %s is not named in %s executor_sessions — "
                      "the host names executor sessions in the panel Grants page"
                      % (session, executor_grants.DECL_FILE))
        return {"ok": False, "field": "caller", "reason": reason}
    return {"ok": True, "project": key, "session": session, "channel": channel}


# ---------- 落账 ----------

def append_request(body: Dict[str, Any], now_ms: int, seq: int = 1,
                   env: Optional[Dict[str, str]] = None,
                   cwd: str = "",
                   projects: Optional[Sequence[Dict[str, Any]]] = None,
                   exclude_trees: Sequence[str] = (),
                   load_decl: Optional[Callable[[str], Dict[str, Any]]] = None,
                   delivered_via: Optional[str] = None,
                   ) -> Dict[str, Any]:
    """Engine-side filing: caller identity gates + contract validation + one
    O_APPEND line. Returns a receipt (with row) or a refusal (with field).

    delivered_via (t261004-27): optional write-channel stamp on the row —
    None = key omitted (the direct-CLI row shape is unchanged); "engine-process"
    = the row was appended by the engine process on behalf of the caller
    (client.py deliver). Row construction stays single-sourced in this module;
    wrappers must not post-stamp."""
    env = dict(os.environ if env is None else env)
    body = _sanitize(body)  # 入界消毒：坏字符可见化，不崩进程、不写坏账本行
    caller = resolve_caller(str(body.get("caller_project") or ""), env=env, cwd=cwd,
                            projects=projects, exclude_trees=exclude_trees,
                            load_decl=load_decl)
    if not caller.get("ok"):
        return caller
    key = caller["project"]
    session = caller["session"]
    # Direct-write closure (t261006-05, KI-208): resident-executor channels (cwd /
    # declared-session) must not append in-process — refuse BEFORE any file write
    # (zero rows) and name the delivery face. The env channel stays open (module
    # header: env injection is the scripts/fixtures face, not a resident session);
    # a non-empty delivered_via = the engine process performs the append.
    if delivered_via is None and str(caller.get("channel") or "") in RESIDENT_EXECUTOR_CHANNELS:
        return _refuse("channel", DIRECT_WRITE_REFUSAL % caller.get("channel"))
    if not shared.PROJECT_KEY_RE.match(key or ""):
        return _refuse("project", "project key shape invalid: %r" % (key or "",))
    raised = body.get("raised_by")
    if raised is not None and raised != "":
        if not isinstance(raised, str):
            return _refuse("raised_by", "raised_by must be a string session id (the engine stamps the resolved session)")
        if raised.strip() and raised.strip() != session:
            return _refuse("raised_by", "raised_by %r does not match the resolved caller session %s — "
                                        "the engine records the true raiser" % (raised.strip()[:64], session))
    checked = validate_request(body)
    if not checked.get("ok"):
        return checked
    fields = checked["fields"]
    row: Dict[str, Any] = {
        "type": "request",
        "id": make_request_id(now_ms, seq),
        "at": now_ms,
        "project": key,
        "kind": fields["kind"],
        "question": fields["question"],
        "detail": fields["detail"],
        "default_action": fields["default_action"],
        "expires_at": fields["expires_at"],
        "raised_by": session,
        "surface": SURFACE_ENGINE,
    }
    if fields["options"] is not None:
        row["options"] = fields["options"]
    if delivered_via:
        row["delivered_via"] = delivered_via
    path = ledger_file(key, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    return {"ok": True, "row": row, "file": str(path)}


# ---------- CLI（一个 JSON argv；与其他引擎条目同形） ----------

def _sanitize(obj: Any) -> Any:
    """入界消毒（与 ticket.py/client.py 同款）：lone surrogate 等 utf-8 不可编码字符
    变成可见转义文本——坏字符只许变得可见，不许崩进程、不许毁回执或账本行。"""
    if isinstance(obj, str):
        return obj.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _emit(out: Dict[str, Any]) -> None:
    # 回执出口兜底（KI-185/186，t261002-14 白名单纪律）：坏字符以 \udcXX 可见转义
    # 出界，绝不带走整条 JSON 回执（print 崩溃=回执丢失）。
    print((json.dumps(out, ensure_ascii=False)
           .encode("utf-8", "backslashreplace").decode("utf-8")))


def _cli(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        _emit({"ok": False, "field": "body", "error": USAGE})
        return 2
    try:
        doc = json.loads(argv[0])
    except json.JSONDecodeError as e:
        _emit({"ok": False, "field": "body", "error": "argument is not valid JSON: %s" % e})
        return 2
    if not isinstance(doc, dict):
        _emit({"ok": False, "field": "body",
               "error": "argument must be a JSON object (got %s)" % type(doc).__name__})
        return 2
    import time as _time
    now_ms = int(_time.time() * 1000)
    try:
        cwd = os.path.realpath(os.getcwd())
    except OSError:
        cwd = ""
    try:
        projects, _quarantined = shared.load_projects_registry()
    except Exception:  # noqa: BLE001 — 注册表故障不放大成全拒收（身份退回 arg/env）
        projects = None
    exclude_trees = (os.path.realpath(str(shared.REPO_ROOT)),)
    out = append_request(doc, now_ms, cwd=cwd, projects=projects,
                         exclude_trees=exclude_trees)
    _emit(out)
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))

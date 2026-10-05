"""authz_gates — 人授权例外判定（工单 t260912-03）。

受保护路径闸的「经人授权后合法通过」判定落点：闸的默认 fail-closed 立场与名单真源
仍归 path_gates（本模块只 import，不复制名单、零新字面量——KI-074「机制在引擎、内容
在项目声明」的对账声明见工单结算）。

三条纪律：
  ① 零 IO 零进程零网络，全部纯函数（单测与场景可直调）；
  ② **无授权 = 逐字节同 path_gates.judge_protected_paths**（split_protected 直接以其
     结果为底，只做「豁免摘除」——零回归面由此机械保证，不靠人眼对比）；
  ③ 授权记录**结构化逐条可归因**（C1）：每条记录带 who/issued/reason/scope，命中文件
     能回答「谁在何时基于什么理由批准了哪一条路径」；多条覆盖同一路径时 issued 最新者胜
     （归属规则写死，防串味）。

⚠ 残留（如实声明，见工单遗留节）：本模块**不在** path_gates.PROTECTED_PATHS 名单内
——「存在才拦」只对名单内路径生效，故本模块落地后不受名单保护（本票不能自加入：那是
自举）。过渡期缓解＝零 IO 纯函数 + 单测源码锁定 + 场景负锁；处置＝后续 main 侧票把它
加入名单（那道改动本身走本票建出的授权通道）。
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import path_gates
import shared


def _get(auth: Any, key: str, default: Any = None) -> Any:
    """字段双读（HumanAuthorization 数据类 | dict）：外部输入两形都容忍，其余=默认。"""
    if isinstance(auth, dict):
        return auth.get(key, default)
    return getattr(auth, key, default)


def _scope_list(auth: Any) -> List[str]:
    raw = _get(auth, "scope")
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(s) for s in raw]


def validate_authorization(auth: Any, now_epoch: int, ticket_id: str) -> str:
    """intake 校验（纯函数）：返回 "" = 合法，否则人话拒收原因（调用方落 refused，
    不进 Temporal 事件历史——与 host_ruling/pause 同款双形态）。"""
    if auth is None:
        return "authorization payload missing"
    kind = str(_get(auth, "kind") or "")
    if kind not in shared.AUTH_KINDS:
        return "invalid kind: %r (only %s accepted)" % (kind, "|".join(shared.AUTH_KINDS))
    who_raw = _get(auth, "who")
    who = str(who_raw or "")
    if not who.strip():
        return "missing who (the authorizer identity is injected by the caller)"
    if len(who) > shared.AUTHZ_WHO_MAX_LEN:
        return "who too long (%d > %d)" % (len(who), shared.AUTHZ_WHO_MAX_LEN)
    norm = who.strip().lower()
    if norm in shared.AUTHZ_AGENT_ROLE_NAMES:
        return "an agent must not self-authorize (who=%r is an agent role name; only a human issues authorization)" % who
    if norm.endswith("-agent"):
        return "an agent must not self-authorize (who=%r is in the agent display-name family: the -agent suffix)" % who
    reason = str(_get(auth, "reason") or "")
    if not reason.strip():
        return "missing reason (it must answer \"approved on what grounds\")"
    if len(reason) > shared.AUTHZ_REASON_MAX_LEN:
        return "reason too long (%d > %d)" % (len(reason), shared.AUTHZ_REASON_MAX_LEN)
    scope = _scope_list(auth)
    if not scope:
        return "empty scope (an authorization must name paths or a ticket id)"
    if len(scope) > shared.AUTHZ_SCOPE_MAX_ITEMS:
        return "too many scope entries (%d > %d)" % (len(scope), shared.AUTHZ_SCOPE_MAX_ITEMS)
    for s in scope:
        if not s.strip():
            return "scope carries a blank entry"
        if len(s) > shared.AUTHZ_SCOPE_ITEM_MAX_LEN:
            return "scope entry too long (%d > %d): %s…" % (
                len(s), shared.AUTHZ_SCOPE_ITEM_MAX_LEN, s[:40])
        if not path_gates._is_safe_path(s):
            return "scope entry is not a safe path: %r" % s
    if kind == shared.AUTH_ARBITRATION_VERDICT:
        if not str(ticket_id or ""):
            return "arbitration_verdict is missing this ticket's id context (an ownerless authorization is refused)"
        if [s.strip() for s in scope] != [str(ticket_id)]:
            return ("arbitration_verdict scope must be exactly this ticket's id %r "
                    "(other tickets are untouched; one authorization covers only the "
                    "named ticket)" % str(ticket_id))
    exp = shared._authz_int(_get(auth, "expires"))
    now = shared._authz_int(now_epoch)
    if exp <= 0:
        return "expires missing or invalid (epoch seconds, required — an authorization must expire)"
    if exp <= now:
        return "expires already passed (%d <= issue time %d); a dead authorization never enters history" % (exp, now)
    if exp > now + shared.AUTHZ_EXPIRES_MAX_SEC:
        return ("expires over the cap (%d s after issue > %d s) — one authorization may "
                "not last more than %d days"
                % (exp - now, shared.AUTHZ_EXPIRES_MAX_SEC,
                   shared.AUTHZ_EXPIRES_MAX_SEC // 86400))
    return ""


def authorization_record(auth: Any, now_epoch: int) -> Dict[str, Any]:
    """规范化落账记录（纯函数，调用方须先过 validate_authorization）：issued 由
    workflow.now() 盖写（不信任调用方）；uses 为消费留痕（只真消费才 append）。"""
    return {
        "kind": str(_get(auth, "kind") or ""),
        "who": str(_get(auth, "who") or "").strip(),
        "scope": [s.strip() for s in _scope_list(auth)],
        "reason": str(_get(auth, "reason") or "").strip(),
        "issued": shared._authz_int(now_epoch),
        "expires": shared._authz_int(_get(auth, "expires")),
        "uses": [],
    }


def _protected_records(authorizations: Any, now_epoch: Optional[int]) -> List[Dict[str, Any]]:
    """args 面的结构化记录清洗：只留 kind=protected_path 且 who/scope 结构合法的条目；
    now_epoch 给定则再做一次时效防线（workflow 侧已过滤，这里是纵深防御），
    None=信任调用方（activity 不读墙钟——重放/复跑判定不吃墙钟）。"""
    out: List[Dict[str, Any]] = []
    for it in authorizations if isinstance(authorizations, (list, tuple)) else []:
        if not isinstance(it, dict):
            continue
        if str(it.get("kind") or "") != shared.AUTH_PROTECTED_PATH:
            continue
        if not str(it.get("who") or "").strip():
            continue
        scopes = it.get("scope")
        scopes = [str(s) for s in scopes if str(s).strip()] \
            if isinstance(scopes, (list, tuple)) else []
        if not scopes:
            continue
        if now_epoch is not None and shared._authz_int(it.get("expires")) <= \
                shared._authz_int(now_epoch):
            continue
        out.append({"who": str(it.get("who")).strip(),
                    "issued": shared._authz_int(it.get("issued")),
                    "reason": str(it.get("reason") or "").strip(),
                    "scope": scopes})
    return out


def _match(path: str, records: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """命中归属：scope 覆盖该路径（复用 path_gates._within 语义：条目==路径 或
    条目+「/」目录前缀——不自写 startswith，防 baselines/baselines2 误命中）；
    多条命中时 issued 最新者胜（同 issued 取先出现者）。"""
    hit = None
    for r in records:
        if not path_gates._within(path, r["scope"]):
            continue
        if hit is None or r["issued"] > hit["issued"]:
            hit = r
    return hit


def exempt_authorized(violations: Sequence[str], authorizations: Any = (),
                      now_epoch: Optional[int] = None
                      ) -> Tuple[List[str], List[Dict[str, Any]]]:
    """对受保护闸的 violations 做「人授权豁免摘除」（纯函数）。返回
    (remaining, authorized_passed)：

    - remaining：仍被拒的受保护文件（无授权/不匹配时**逐字节等于入参**——零回归面）；
    - authorized_passed：[{path, who, issued, reason}]——经生效授权放行的文件，逐条
      可归因（note 记名与机读键由此生成）。

    调用方（settle 单点）先用 path_gates.judge_protected_paths 定性（「存在才拦」谓词
    的单一实现不重写），再调本函数做豁免摘除——判定顺序仍是「受保护闸先于任何 git add」。"""
    base = [str(f) for f in (violations or [])]
    if not base:
        return ([], [])
    records = _protected_records(authorizations, now_epoch)
    if not records:
        return (list(base), [])
    remaining: List[str] = []
    passed: List[Dict[str, Any]] = []
    for f in base:
        m = _match(f, records)
        if m is None:
            remaining.append(f)
        else:
            passed.append({"path": f, "who": m["who"], "issued": m["issued"],
                           "reason": m["reason"]})
    return (remaining, passed)


def split_protected(files: Iterable[Any],
                    exists_at_base: Optional[Any] = None,
                    authorizations: Any = (),
                    now_epoch: Optional[int] = None
                    ) -> Tuple[List[str], List[Dict[str, Any]]]:
    """受保护名单判定 + 人授权豁免（纯函数，单测/场景直调入口）：
    = path_gates.judge_protected_paths（定性）→ exempt_authorized（豁免摘除）。

    无授权时 violations **逐字节同** judge_protected_paths（零回归面机械保证）。"""
    base_violations, _reason = path_gates.judge_protected_paths(files, exists_at_base)
    return exempt_authorized(base_violations, authorizations, now_epoch)


def authorized_passage_note(passed: Sequence[Dict[str, Any]]) -> str:
    """放行回执（单行，settle note 以「；」拼接）：人读记名点名 + 机读键
    path_gate_authz_used=<who>@<issued>:<f1,f2>（同一授权人+签发时刻归一组，
    多条授权覆盖不同路径时不得串味）。reason 在回执里截断净化（换行换空格，
    全文真源仍在 meta['authorizations']）。"""
    if not passed:
        return ""
    groups: List[Tuple[str, int, List[str]]] = []
    for p in passed:
        key = (str(p.get("who") or ""), shared._authz_int(p.get("issued")))
        for g in groups:
            if g[0] == key[0] and g[1] == key[1]:
                g[2].append(str(p.get("path") or ""))
                break
        else:
            groups.append((key[0], key[1], [str(p.get("path") or "")]))
    names = ", ".join(str(p.get("path") or "") for p in passed)
    details = []
    for who, issued, files in groups:
        reason = ""
        for p in passed:
            if str(p.get("who") or "") == who and shared._authz_int(p.get("issued")) == issued:
                reason = str(p.get("reason") or "")
                break
        reason = reason.replace("\n", " ").replace("\r", " ").strip()
        if len(reason) > 120:
            reason = reason[:120] + "… (full text in meta.authorizations)"
        details.append("authorizer %s @ %s, reason %s"
                       % (who, fmt_ts(issued), reason or "(not recorded)"))
    keys = "; ".join("%s%s@%d:%s" % (shared.AUTHZ_USED_KEY, who, issued, ",".join(files))
                     for who, issued, files in groups)
    return "protected paths passed under human authorization: %s (%s); %s" % (names, "; ".join(details), keys)


def fmt_ts(epoch: int) -> str:
    """epoch 秒 → UTC 人读（纯函数，固定 UTC 防机器时区漂移出历史）。"""
    import datetime
    try:
        return datetime.datetime.fromtimestamp(
            epoch, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return "ts=%d" % epoch

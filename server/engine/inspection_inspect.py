"""inspection_inspect — 巡检 inspect 段（agent 审查）契约与机械复核纯函数层
（t260916-22；设计定稿 v1=notes/discussions/260916-inspection-agent-design.md）。

定位：静态扫描器（inspection_scan*.py，t260916-22 退役留档）的语义接替者。
本模块=零 temporalio 依赖的**纯函数层**（场景/UT/inspection_decl 都可直接 import，
同 t260905-03 的 inspection_decl 纪律）；活动壳在两处：
  - agent_activities.run_inspection_inspect —— spawn 只读 agent（role=inspection，
    kimi-coding/k3 路由、read-only 预设 pin、stdout 围栏 JSON 捕获、全终态 reap）；
  - activities.verify_inspection_findings —— report 段机械复核链的 IO 壳（读上期
    台账与裁定台账，纯函数做判定）。

三条硬契约（工单要点逐条落位）：
  ① 输出强 schema：agent 最终消息**末尾恰一块** ```json 围栏 {"findings":[…]}；
     条目=subject/severity/evidence[{path,line,quote}]/why/suggestion/confidence；
     **id 不由 agent 提供**——机械侧按内容铸（mint_finding_id，同内容跨期稳定）。
     引文超长是**软提醒不判红**（宿主令 260921；t260922-01 实案：227 字擦边超限曾
     整份报废六条发现）：截断保留原文前缀 + 逐条人话点名 + 报告计数位
     quote_overlong_warn；判红只留「无法定位/不可复核」形态（evidence 缺空、
     quote 缺空、path/line 畸形、围栏缺失/多块/坏 JSON、findings 非列表）。
  ② 证据机械复核：文件存在、行号在范围、引文匹配（容空白差异）；不过者降级
     unverified 并逐项点名（不静默丢）。
  ③ 建议门/预算：suggested_fix_tickets 只从 verified && confidence≥阈值 &&
     severity≥med 生成；新发现条数上限（缺省 40）+超时（缺省 30 分钟，超时=
     「agent 未完成」不假绿——超时判定在活动/workflow 双闸）。

红线：巡检只出报告与开票建议，绝不改码——agent 侧由 read-only 预设 pin 承担
（agent_activities 一次性 patch），本模块承担的是**判定面**（复核/去重/预算）。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

# ========================================================================================
# 词表与常量（单一真源：inspection_decl 的 inspect_profile 词表/缺省预算都从这里 import）
# ========================================================================================

#: agent 发现的 scan 来源标记（票面 findings[].scan；与 deadman/suite 等机械来源并列）
AGENT_SCAN_TAG = "agent"
#: 严重度词表（形状与 inspection_scan.SEVERITY_ORDER 一致；留档文件不再被新代码接线，
#: 故本模块自持一份——三值词表，漂移面可忽略且各有 UT 钉住）
SEVERITIES: Tuple[str, ...] = ("high", "med", "low")
SEVERITY_RANK: Dict[str, int] = {"high": 0, "med": 1, "low": 2}
#: 发现级裁定词表（工单要点⑥：假报/待修/存疑；机器 token + 中文别名双收）
VERDICT_FAKE = "false-positive"
VERDICT_TO_FIX = "to-fix"
VERDICT_DOUBT = "doubt"
VERDICTS: Tuple[str, ...] = (VERDICT_FAKE, VERDICT_TO_FIX, VERDICT_DOUBT)
VERDICT_ALIASES: Dict[str, str] = {
    "假报": VERDICT_FAKE, "待修": VERDICT_TO_FIX, "存疑": VERDICT_DOUBT,
}
#: 建议门置信阈值（工单要点③的「阈值」：verified && confidence≥0.6 && severity≥med）
SUGGEST_CONFIDENCE = 0.6
#: 预算缺省（宿主 260916 裁定③：起步 40 条 / 30 分钟；声明实例段可配，见 inspection_decl。
#: 260924 宿主直修令调大 30→60：连续两期实案（260923/260924）审查段跑满 1800s 预算
#: 必超时、产出恒空壳「本期不假绿」——套件段 55 分钟量级下审查 30 分钟预算错配。）
DEFAULT_MAX_FINDINGS = 40
DEFAULT_INSPECT_TIMEOUT_MIN = 60
#: 缩面硬上限两键（t260924-06）：inspect 段审查范围=活动侧给定的本期变化面清单，
#: 分片（子代理）数与每片文件数在此机械封顶——防「分派 7 子代理审 368 个场景文件」
#: 式无界扇出复发（260926 期实测：扇出恰是 dsh fatal 零产出的直接诱因）。
DEFAULT_MAX_SHARDS = 4
DEFAULT_MAX_FILES_PER_SHARD = 40
#: 预算双闸 margin（活动内 deadline = workflow start_to_close − margin；不等式由
#: test_t260916_22_inspect_flow 锁定，SUITE_TO 纪律同款）
INSPECT_DEADLINE_MARGIN_SEC = 60
#: 引文长度软提醒线（设计稿 4.2 原口径=「quote ≤200 字」仅 prompt 引导语；宿主令
#: 260921「软提醒不判红」：超限不判红——截断保留原文前缀（复核仍可按子串校验）+
#: 逐条人话点名 + 报告计数位 quote_overlong_warn（apply_budget 记账面，口径=保留集
#: 在册条目）。阈值改这里单点生效（prompt 插值 build_inspect_prompt 同源读本常量）；
#: 「无法定位/不可复核」形态（quote 缺空、path/line 畸形等）仍 fail-closed，与本线无关。
MAX_QUOTE_CHARS = 200
#: 裁定台账文件名后缀（deadman ledger_periods 的「已知非台账件」排除表消费本常量）
VERDICTS_RECEIPT_SUFFIX = "-verdicts.json"
#: 分面词表（与 inspection_decl.WIRED_FACES 同集合；真源=本表，decl import 本表，
#: 防「声明词表↔prompt 分面清单」两处漂移——t260916-05 双真源锁同款教训）
PROFILE_FACES: Tuple[str, ...] = ("test", "doc", "stage", "mechanism", "simplify")


class InspectParseError(ValueError):
    """agent 产出解析失败（围栏块缺失/多块/坏 JSON/schema 畸形）。点名原因，不猜不挑。"""


# ========================================================================================
# 输出契约：围栏 JSON 提取 + 强 schema 校验
# ========================================================================================

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.S)


def extract_findings_json(text: str) -> List[Dict[str, Any]]:
    """从 agent 最终消息提取 findings（恰一块含 "findings" 键的围栏 JSON）。

    parse_arbitration_summary 同族纪律：0 块或 ≥2 块含 findings 的围栏块=格式失败
    （不猜不挑）；坏 JSON 同罪。返回原始 list（未做 schema 校验）。"""
    hits: List[str] = []
    for m in _FENCE_RE.finditer(text or ""):
        body = (m.group(1) or "").strip()
        if not body:
            continue
        try:
            obj = json.loads(body)
        except (ValueError, TypeError):
            continue          # 别的围栏块（叙述代码段）不是坏 JSON 证据，跳过
        if isinstance(obj, dict) and "findings" in obj:
            hits.append(body)
    if len(hits) != 1:
        raise InspectParseError(
            "findings 围栏块必须恰一块，实际 %d 块（0=没产出；≥2=多块互相矛盾，"
            "机械侧绝不猜哪块是真的）" % len(hits))
    try:
        obj = json.loads(hits[0])
    except (ValueError, TypeError) as e:
        raise InspectParseError("findings 围栏块不是合法 JSON：%s" % e)
    findings = obj.get("findings")
    if not isinstance(findings, list):
        raise InspectParseError("findings 必须是列表（got %s）" % type(findings).__name__)
    return list(findings)   # 条目逐个交给 validate_finding（None/非 dict 也由它点名）


def _norm_quote(s: Any) -> str:
    """引文规范化（跨期稳定 id 与空白容差匹配共用）：连续空白折叠+首尾剥除。"""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _norm_rel_path(s: Any) -> str:
    """证据 path 规范化：反斜杠归正斜杠、剥 ./ 前缀、剥首尾空白（id 稳定用）。"""
    p = str(s or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def validate_finding(raw: Any, idx: int) -> Dict[str, Any]:
    """单条发现的强 schema 校验+规范化（白名单字段，多余键丢弃——票面不收垃圾）。

    畸形一律 InspectParseError 点名条目序号（idx 从 1 起，人可对回 agent 输出）。
    唯一软面=引文超长（宿主令 260921）：不判红，截断保原文前缀 + quote_truncated/
    quote_original_chars 标注 + quote_warns 人话点名；不超长条目零新键（逐字节兼容）。"""
    where = "findings[%d]" % idx
    if not isinstance(raw, dict):
        raise InspectParseError("%s：条目必须是对象（got %s）" % (where, type(raw).__name__))
    subject = str(raw.get("subject") or "").strip()
    if not subject:
        raise InspectParseError("%s：subject 缺失或空（一句话含 file:line）" % where)
    severity = str(raw.get("severity") or "").strip()
    if severity not in SEVERITIES:
        raise InspectParseError("%s：severity %r 越域（合法：%s）"
                                % (where, severity, "|".join(SEVERITIES)))
    why = str(raw.get("why") or "").strip()
    if not why:
        raise InspectParseError("%s：why 缺失或空（为什么这是问题，语义判断）" % where)
    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) \
            or not (0.0 <= float(confidence) <= 1.0):
        raise InspectParseError("%s：confidence %r 越域（0.0~1.0 数值）" % (where, confidence))
    evidence_raw = raw.get("evidence")
    if not isinstance(evidence_raw, list) or not evidence_raw:
        raise InspectParseError("%s：evidence 必填且非空列表（发现必须可证伪）" % where)
    evidence: List[Dict[str, Any]] = []
    warns: List[str] = []      # 引文超长软提醒点名（宿主令 260921；空=条目零新键）
    for j, ev in enumerate(evidence_raw):
        ew = "%s.evidence[%d]" % (where, j)
        if not isinstance(ev, dict):
            raise InspectParseError("%s：必须是对象" % ew)
        path = _norm_rel_path(ev.get("path"))
        if not path:
            raise InspectParseError("%s：path 缺失或空" % ew)
        line = ev.get("line")
        # line=0 结构合法（agent 报 0 行=可疑证据，复核层必降级 unverified 点名）；
        # 负数/非整数=结构畸形，解析层拒（场景子用例3 八态契约：行号 0 归复核不归解析）。
        if isinstance(line, bool) or not isinstance(line, int) or line < 0:
            raise InspectParseError("%s：line 必须是 ≥0 的整数（got %r）" % (ew, line))
        quote = str(ev.get("quote") or "")
        if not quote.strip():
            raise InspectParseError("%s：quote 缺失或空（原文引用必填）" % ew)
        item: Dict[str, Any] = {"path": path, "line": line, "quote": quote}
        # 引文超长=软提醒不判红（宿主令 260921；旧口径「超限即抛→整份报废」废止）：
        # 截断保留**纯原文前缀**（不拼省略号等标记，防污染 recheck 的空白容差子串
        # 匹配）+ 逐条人话点名（软提醒≠静默，第 N 条可对回票面清单序）。
        if len(quote) > MAX_QUOTE_CHARS:
            item["quote"] = quote[:MAX_QUOTE_CHARS]
            item["quote_truncated"] = True
            item["quote_original_chars"] = len(quote)
            warns.append("第 %d 条发现 %s：引文 %d 字 > 上限 %d，已截断保留前 %d 字"
                         "（机械复核仍按原文前缀校验）"
                         % (idx, ew.split(".", 1)[1], len(quote),
                            MAX_QUOTE_CHARS, MAX_QUOTE_CHARS))
        evidence.append(item)
    out: Dict[str, Any] = {
        "subject": subject,
        "severity": severity,
        "evidence": evidence,
        "why": why,
        "suggestion": str(raw.get("suggestion") or "").strip(),
        "confidence": round(float(confidence), 4),
    }
    if warns:
        out["quote_warns"] = warns
    return out


def parse_agent_findings(text: str) -> List[Dict[str, Any]]:
    """agent 输出全量解析：提取 + 逐条 schema 校验。任一条畸形=整体失败（不降级不猜，
    fail-closed 由 workflow 转 blocked 点名——半信半疑的清单比没有清单更危险）。

    唯一例外=引文超长（宿主令 260921「软提醒不判红」）：该条照常入册，超长引文截断
    保原文前缀并标注/点名——t260922-01 实案（227 字擦边超限→整份拒收→当日巡检零产出）
    证伪了旧口径「一处擦边报废整份」；判红只留无法定位/不可复核形态。"""
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(extract_findings_json(text), start=1):
        out.append(validate_finding(raw, i))
    return out


def mint_finding_id(finding: Dict[str, Any]) -> str:
    """内容哈希 id（前 8 hex）：同内容跨期稳定（去重键），内容变即新 id。

    规范化=subject/why 空白折叠 + evidence 按 (path,line,quote) 排序后逐项折叠——
    agent 两期叙述空白差异不改 id，调换 evidence 顺序也不改 id（可证伪内容不变）。"""
    parts = [_norm_quote(finding.get("subject")), _norm_quote(finding.get("why"))]
    evs = sorted(
        (_norm_rel_path(ev.get("path")), int(ev.get("line") or 0), _norm_quote(ev.get("quote")))
        for ev in (finding.get("evidence") or []) if isinstance(ev, dict))
    for path, line, quote in evs:
        parts.append("%s\x1f%d\x1f%s" % (path, line, quote))
    return hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()[:8]


#: 缩面塌陷发现的 scan 标签（260929 宿主令：塌陷记在**票面**上，不记 KI 册）。
SCOPE_SCAN_TAG = "scope"


def scope_collapse_findings(scope_meta: Any) -> List[Dict[str, Any]]:
    """审查范围塌陷 → 票面发现（纯函数，260929）。

    为什么必须出发现：本期 simplify-face 实况＝无泳道 ⇒ 本期基点空 ⇒ 变化面差分未做 ⇒
    **审查范围 0 个文件**，agent 只能核 KI 册（3 分 15 秒跑完，代码一行没看），而这件事
    此前只躺在台账 `scan_meta.scope_note` 里——宿主看到的形态是「巡检跑完了，9 条发现」，
    **跑完 ≠ 审过**。零文件范围必须是票面上的发现，不许只做 meta 注记。

    判据（只认「差分没做成」，不误伤「真无变化」）：scope_files 为 0 且出现
    `scope_note`（无基点/基点不可得）、`base_error`（基点取不到）或 `diff_error`
    （git 差分失败）。**真空变化面（`diff_empty`＝差分成功且零改动）明确不报**——
    那是合法的「本期没动」，报了就是天天假红（260929 假红守门）。
    严重度=med：本期票面仍有 KI/回执面产出，但**代码审查这一半没发生**。"""
    m = scope_meta if isinstance(scope_meta, dict) else {}
    if int(m.get("scope_files") or 0) != 0:
        return []
    why = ""
    if m.get("diff_empty"):
        return []                      # 差分成功且零改动＝合法空范围
    if m.get("diff_error"):
        # 261001：引擎自产的发现也必须守「报告面英文」令——否则会被本仓自己的语言闸
        # （activities.verify_findings → mark_non_english，扫 subject/why/suggestion）
        # 判 unverified 并追加聚合条：**自己的系统信号被自己判成不合规**，
        # 真机上表现为「本期没审代码」这条提示反而带 unverified + 一条 agent 归因的聚合条。
        why = "git diff failed: %s" % str(m["diff_error"])[:200]
    elif m.get("scope_note"):
        why = str(m["scope_note"])[:240]
    elif m.get("base_error"):
        why = "this period's base point is unavailable: %s" % str(m["base_error"])[:200]
    if not why:
        return []
    # 证据=台账里那段范围 meta 本身（**不编造文件路径**：这条塌陷的证据就在台账字段里）
    ev = [{"path": "scan_meta.inspect.scope（本期台账字段）",
           "quote": str({k: m[k] for k in ("scope_files", "scope_note", "diff_error",
                                           "base_error", "base_source_this", "diff_empty")
                         if k in m})[:300]}]
    return [{
        "scan": SCOPE_SCAN_TAG, "severity": "med",
        "subject": ("Scope collapsed to 0 files: the change-surface diff was not made, so this "
                    "period did NOT review code (agent reviewed receipts/KI/previous ledger only)"),
        "evidence": ev,
        "suggestion": ("Give this instance a usable review base point: for an instance without a "
                       "lane (declaration carries no suite), use \"previous period's recorded HEAD → "
                       "this period's HEAD\" (already wired: this period seeds the current HEAD into "
                       "the ledger, so the next period can diff); if the base point is still missing, "
                       "fix the declaration/lane first — do not treat \"ran\" as \"reviewed\"."),
        "suggest": False,
    }]


def with_ids(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给每条发现铸内容 id（活动侧在 parse 之后立刻调用；id 不信任 agent 自报）。"""
    for f in findings:
        f["id"] = mint_finding_id(f)
        f.setdefault("scan", AGENT_SCAN_TAG)
    return findings


# ========================================================================================
# report 段机械复核链：证据复核 → 跨期去重/假报压制 → 预算截断 → 汇总/心跳
# ========================================================================================

# —— 报告面语言闸（260930 宿主令 + 实案：agent 自写的 findings 仍有中文 subject）——
# 提示词只是**引导**，LLM 会漂；机械面必须有一道**可判**的闸：叙述字段（subject/why/
# suggestion）出现 CJK ⇒ 该发现降级 unverified 并点名 `non_english_text` 原因（可见、
# 且因 verified 门不生成修码建议票）。**数据字段不译**：evidence 的 quote / path（被测
# 文件原文与路径）允许任意语言——那是数据不是文案。
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
#: 必须英文的叙述字段（报告制品直接消费它们）
NARRATIVE_FIELDS: Tuple[str, ...] = ("subject", "why", "suggestion")
#: 语言违规的机器原因 token（进 unverified_reasons / meta，运维可 grep）
NON_ENGLISH_REASON = "non_english_text"


def finding_language_violations(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """逐条查「叙述字段含 CJK」→ [{index,id,fields:[...]}]（纯函数，UT 主面）。

    判据只扫 `NARRATIVE_FIELDS`；evidence 的 quote/path 与其它标识符**不扫**（数据不译）。
    畸形输入一律保守（非 dict/字段非串/空=跳过，不抛）——语言闸绝不让整轮复核炸。"""
    out: List[Dict[str, Any]] = []
    for i, f in enumerate(findings if isinstance(findings, list) else []):
        if not isinstance(f, dict):
            continue
        bad = [k for k in NARRATIVE_FIELDS
               if isinstance(f.get(k), str) and CJK_RE.search(f[k])]
        if bad:
            out.append({"index": i, "id": str(f.get("id") or ""), "fields": bad})
    return out


def mark_non_english(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """语言闸动作面（纯函数）：叙述字段含 CJK 的发现 → verified="unverified" +
    `unverified_reasons` 追加一条点名（保留判定理由，不静默丢；已 unverified 的条目保留
    原证据理由并追加）。返回入参列表（就地改，链式调用方便）。"""
    for v in finding_language_violations(findings):
        f = findings[v["index"]]
        reasons = [r for r in (f.get("unverified_reasons") or []) if isinstance(r, str)]
        reasons.append(
            "%s: narrative fields must be English (report face is English): %s — the "
            "finding is kept visible but marked unverified and produces no fix ticket"
            % (NON_ENGLISH_REASON, ", ".join(v["fields"])))
        f["verified"] = "unverified"
        f["unverified_reasons"] = reasons
    return findings


def recheck_evidence(findings: List[Dict[str, Any]], base_dir: Any) -> List[Dict[str, Any]]:
    """逐条逐证据机械复核（工单要点②）：文件存在、行号在范围、引文匹配（容空白差异）。

    全过 → verified="verified"；任一不过 → verified="unverified" +
    unverified_reasons=[逐项人读原因]（**保留票面点名，不静默丢**）。
    base_dir=审查基座（suite 期=泳道 worktree；非 suite 期=repo_root）。"""
    base = Path(base_dir)
    out: List[Dict[str, Any]] = []
    for f in findings:
        reasons: List[str] = []
        for ev in f.get("evidence") or []:
            rel = _norm_rel_path(ev.get("path"))
            line = int(ev.get("line") or 0)
            quote = _norm_quote(ev.get("quote"))
            if PurePosixPath(rel).is_absolute():
                reasons.append("%s:%d 证据 path 是绝对路径（契约=相对基座）" % (rel, line))
                continue
            target = base / rel
            try:
                if not target.is_file():
                    reasons.append("%s:%d 证据文件不存在（基座 %s）" % (rel, line, base))
                    continue
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as e:
                reasons.append("%s:%d 证据文件不可读：%s" % (rel, line, e))
                continue
            if line < 1 or line > len(lines):
                reasons.append("%s:%d 行号越界（合法 1~%d）" % (rel, line, len(lines)))
                continue
            if _norm_quote(lines[line - 1]).find(quote) < 0:
                reasons.append("%s:%d 引文与文件内容不符（容空白差异后仍未命中）" % (rel, line))
        if reasons:
            f["verified"] = "unverified"
            f["unverified_reasons"] = reasons
        else:
            f["verified"] = "verified"
            f.pop("unverified_reasons", None)
        out.append(f)
    return out


def dedupe_and_suppress(findings: List[Dict[str, Any]], prev_ids: Any,
                        fake_ids: Any) -> List[Dict[str, Any]]:
    """跨期去重 + 假报压制（工单要点④⑥）：
    - id ∈ 上期清单 → recurring=True（不进 summary 计数、不进建议；裁定④「不累计」）；
    - id ∈ 历史 false-positive 裁定集 → verdict=false-positive + suppressed=True
      （同上排除；假报跨期不再重复计数，但票面仍点名可见）。"""
    prev = set(prev_ids or [])
    fake = set(fake_ids or [])
    for f in findings:
        fid = str(f.get("id") or "")
        if fid and fid in prev:
            # recurring 先标（上期已见）；若同条又被裁过假报，下面的 fake 分支覆盖
            # verified 态——人已裁定是更终局的事实（场景 P2 契约：压制优先可读）。
            f["recurring"] = True
            f["verified"] = "recurring"
        if fid and fid in fake:
            f["verdict"] = VERDICT_FAKE
            f["suppressed"] = True
            # verified 字段双写 dedupe 态（单值态字段契约：票面/场景 finding_state
            # 直接读 verified ∈ {verified,unverified,recurring,suppressed}）
            f["verified"] = "suppressed"
    return findings


def is_counted(finding: Dict[str, Any]) -> bool:
    """该发现是否计入摘要/预算/建议（recurring 与假报压制都不算「本期新问题」）。"""
    return not finding.get("recurring") and not finding.get("suppressed")


def count_quote_overlong(findings: List[Dict[str, Any]]) -> int:
    """超长引文软提醒计数（宿主令 260921 报告计数位 quote_overlong_warn 的口径单点）。

    口径=给定清单**在册**条目里带 quote_truncated 标注的证据项总数（一条发现多证据
    可贡献多条）；apply_budget 只对保留集计（被预算截掉的条目不在票面/报告在册，
    计数也不含它），与票面 findings[].quote_warns 逐项可对账（review 条件②）。
    畸形条目（非 dict/缺 evidence/证据项非 dict）不炸计 0。"""
    return sum(
        1 for f in findings if isinstance(f, dict)
        for ev in (f.get("evidence") or [])
        if isinstance(ev, dict) and ev.get("quote_truncated"))


def apply_budget(findings: List[Dict[str, Any]], cap: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """预算截断（宿主裁定③：缺省 40，超出按 severity 截断并注明）。

    只对「新发现」（非 recurring/非压制）计预算：按 (severity, confidence 降序) 取前
    cap 条；recurring/压制条目不占预算、全保留。输出保持**输入原序**（票面清单稳定
    可读），被截条目计数进 meta.truncated。"""
    cap = max(1, int(cap))
    fresh = [f for f in findings if is_counted(f)]
    keep_ids = {f.get("id") for f in sorted(
        fresh, key=lambda f: (SEVERITY_RANK.get(str(f.get("severity")), 9),
                              -float(f.get("confidence") or 0.0)))[:cap]}
    kept: List[Dict[str, Any]] = []
    truncated = 0
    for f in findings:
        if is_counted(f) and f.get("id") not in keep_ids:
            truncated += 1
            continue
        kept.append(f)
    # quote_overlong_warn（宿主令 260921 报告计数位）口径=**保留集**（review 条件②）：
    # 被预算截掉的条目不在票面/报告 findings 在册，计数也不含它——计数位与票面
    # quote_warns 逐项可对账。本 meta 经 verify 活动 **budget_meta 摊开进报告
    # scan_meta（落账面），活动壳零改动。
    return kept, {"truncated": truncated,
                  "quote_overlong_warn": count_quote_overlong(kept)}


def summarize_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    """按严重度计数（口径=is_counted：recurring/假报压制不算「本期新问题」；
    与 build_ticket_face 的重计循环共用本函数，杜绝两处口径漂移）。"""
    counts = {"high": 0, "med": 0, "low": 0}
    for f in findings:
        sev = str(f.get("severity") or "")
        if sev in counts and is_counted(f):
            counts[sev] += 1
    return counts


def heartbeat_of(findings: List[Dict[str, Any]]) -> bool:
    """心跳语义（t260916-22 口径）：本期**新发现**==0 即心跳（recurring/假报压制是
    可见的老问题记账，不再否定心跳——宿主裁定④「重复项不累计计数」的延伸；
    套件绿与否的合成仍在 build_ticket_face（t260913-02 口径不变）。"""
    return not any(is_counted(f) for f in findings)


# ========================================================================================
# 台账读取（report 段活动壳的 IO 面；期号比较=数值键，同日多桶不字典序错乱）
# ========================================================================================

def period_sort_key(period: str) -> Tuple[int, int]:
    """期号排序键：YYYYMMDD[-bucket] → (日期, 桶)。cron 期（无桶）= 当日桶 0，
    计数期按数值比（-10 不会排在 -2 前——字典序会错，数值序不会）。"""
    m = re.match(r"^(\d{8})(?:-([1-9]\d*))?$", str(period or ""))
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2) or 0))


def verdicts_ledger_name(instance_id: str, period: str) -> str:
    """裁定台账文件名（单点；与 inspection_flow.inspection_ledger_name 同族）。"""
    return "inspection-%s-%s%s" % (instance_id, period, VERDICTS_RECEIPT_SUFFIX)


def _ledger_candidates(ledger_dir: Path, instance_id: str, suffix: str) -> List[Tuple[str, Path]]:
    """本实例、合法期号词法、指定后缀的台账文件清单，按期号新→旧排。"""
    out: List[Tuple[str, Path]] = []
    prefix = "inspection-%s-" % str(instance_id or "")
    try:
        entries = sorted(Path(ledger_dir).iterdir())
    except OSError:
        return out
    for p in entries:
        if not p.is_file() or not p.name.startswith(prefix) or not p.name.endswith(suffix):
            continue
        period = p.name[len(prefix):-len(suffix)]
        if re.match(r"^\d{8}(-[1-9]\d*)?$", period):
            out.append((period, p))
    out.sort(key=lambda t: period_sort_key(t[0]), reverse=True)
    return out


def read_prev_ledger_doc(ledger_dir: Any, instance_id: str,
                         before_period: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """最近一个更早期台账的完整 doc（inspect 活动的 prompt 摘要消费）。
    返回 (doc 或 None, 人读 note)：无更早期=(None, "无更早期台账")；读不出（坏 JSON/
    缺 findings/非列表）=(None, 点名原因)——「无对照」对 agent 可见，绝不静默当空。"""
    inst = str(instance_id or "")
    if not inst:
        return None, "实例为空，无从对照上期台账"
    cands = [t for t in _ledger_candidates(Path(ledger_dir), inst, ".json")
             if period_sort_key(t[0]) < period_sort_key(before_period)]
    if not cands:
        return None, "无更早期台账"
    period, path = cands[0]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, "上期台账 %s 不可读（%s: %s）——跨期去重分支缺席" % (path.name, type(e).__name__, e)
    if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
        return None, "上期台账 %s 缺 findings 列表——跨期去重分支缺席" % path.name
    return doc, "对照上期 %s" % period


def read_prev_ledger_ids(ledger_dir: Any, instance_id: str,
                         before_period: str) -> Tuple[Optional[set], str]:
    """最近一个更早期台账的发现 id 集（跨期去重的对照面）。

    返回 (ids 或 None, 人读 note)：无更早期=(set(), "无更早期台账")；读不出（坏 JSON/
    缺 findings/非列表）=(None, 点名原因)——调用方必须把 note 进 meta 点名（去重分支
    缺席可见，绝不静默当空集）。"""
    inst = str(instance_id or "")
    if not inst:
        return None, "实例为空，无从对照上期台账"
    doc, note = read_prev_ledger_doc(ledger_dir, inst, before_period)
    if doc is None:
        return (set(), note) if note == "无更早期台账" else (None, note)
    ids = {str(f.get("id")) for f in doc.get("findings") or []
           if isinstance(f, dict) and str(f.get("id") or "").strip()}
    return ids, "%s（%d 条）" % (note, len(ids))


def read_verdicts_file(path: Any) -> Dict[str, Any]:
    """裁定台账读取（返回 {"entries": [...], "error": ""}；坏文件不炸，error 点名）。"""
    p = Path(path)
    if not p.is_file():
        return {"entries": [], "error": ""}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"entries": [], "error": "%s: %s" % (type(e).__name__, e)}
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return {"entries": [], "error": "entries is not a list (%s)" % p.name}
    return {"entries": [e for e in entries if isinstance(e, dict)], "error": ""}


def append_verdict_entry(path: Any, entry: Dict[str, Any],
                         dedupe: bool = False) -> bool:
    """裁定台账追加一条（读-改-写；坏既有文件=ValueError 点名，绝不静默重建——
    覆盖会抹掉历史裁定）。dedupe=True：**内容级幂等**——除 booked_at 外逐键全等
    （finding_id/verdict/who/note/source_ticket/mode）才跳过。语义两分：同内容重复
    （Temporal 活动至少一次重放/重试）=幂等跳过；同发现**改口**（verdict/who/note
    变）=新裁定必追加——裁定演进全留痕、票面/取最新消费侧取最后一条（工单要点⑥）。"""
    p = Path(path)
    doc: Dict[str, Any]
    if p.is_file():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ValueError("裁定台账 %s 不可读（%s: %s）——不覆盖重建，人工处置"
                             % (p, type(e).__name__, e))
        if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
            raise ValueError("裁定台账 %s 形状坏（缺 entries 列表）——不覆盖重建" % p)
    else:
        doc = {"entries": []}
    if dedupe:
        fresh = {k: str((entry or {}).get(k) or "")
                 for k in ("finding_id", "verdict", "who", "note", "source_ticket", "mode")}
        for e in doc["entries"]:
            if not isinstance(e, dict):
                continue
            if all(str(e.get(k) or "") == v for k, v in fresh.items()):
                return False
    doc["entries"].append(dict(entry or {}))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def collect_fake_ids(ledger_dir: Any, instance_id: str,
                     before_period: str) -> Tuple[set, List[str]]:
    """本实例全部更早期裁定台账里的 false-positive id 集（假报跨期压制消费）。
    单个坏文件只记 note 不炸整链（其余期照常收集）。"""
    inst = str(instance_id or "")
    fake: set = set()
    notes: List[str] = []
    if not inst:
        return fake, notes
    for period, path in _ledger_candidates(Path(ledger_dir), inst, VERDICTS_RECEIPT_SUFFIX):
        if period_sort_key(period) >= period_sort_key(before_period):
            continue
        res = read_verdicts_file(path)
        if res["error"]:
            notes.append("裁定台账 %s 不可读（%s）——该期压制分支缺席" % (path.name, res["error"]))
            continue
        for e in res["entries"]:
            if str(e.get("verdict") or "") == VERDICT_FAKE and str(e.get("finding_id") or ""):
                fake.add(str(e["finding_id"]))
    return fake, notes


# ========================================================================================
# 发现级裁定（纯面；CLI=inspection_trigger.py verdict、signal=flow.finding_verdict）
# ========================================================================================

def normalize_verdict(raw: Any) -> str:
    """裁定值归一：英文 token 或中文别名（假报/待修/存疑）；词表外=显式报错。"""
    v = str(raw or "").strip()
    if v in VERDICTS:
        return v
    if v in VERDICT_ALIASES:
        return VERDICT_ALIASES[v]
    raise ValueError("verdict %r 越域（合法：%s 或中文别名 %s）"
                     % (raw, "|".join(VERDICTS), "|".join(VERDICT_ALIASES)))


def apply_verdict_to_face(face: Dict[str, Any], finding_id: str, verdict: str,
                          who: str, note: str) -> str:
    """把裁定写进票面 findings 对应条目（返回 ""=成功；否则人读错误）。
    只记账不拦闸：不改 stage/status/gate 任何字段。"""
    fid = str(finding_id or "").strip()
    if not fid:
        return "finding-id 缺失"
    findings = (face or {}).get("findings")
    if not isinstance(findings, list):
        return "票面缺 findings 列表（未到 report 段的票不可逐条裁定）"
    for f in findings:
        if isinstance(f, dict) and str(f.get("id") or "") == fid:
            f["verdict"] = verdict
            f["verdict_who"] = str(who or "")
            f["verdict_note"] = str(note or "")
            # verified 态双写（单值态字段契约，与 dedupe_and_suppress 同口径）：
            # 假报=suppressed；待修/存疑=裁定值本身（票面/场景 finding_state 单值读）。
            f["verified"] = "suppressed" if verdict == VERDICT_FAKE else verdict
            return ""
    return "finding-id %s 不在本票发现清单（%d 条）中" % (fid, len(findings))


# ========================================================================================
# prompt 构建（通用骨架 + 分面清单 + persona patch）
# ========================================================================================

PERSONA = (
    "你是 sandbar 项目的巡检审查员（role=inspection）。你是**只读审查员**：产出可证伪的"
    "发现，宁可少报、不可虚报——没有把握的问题不要报。你绝不修改任何文件、绝不写任何"
    "仓库内容（工具面只读：读文件、grep、读巡检套件回执）。每条发现必须带 file:line "
    "证据引用，且引用必须真实存在（机械侧会逐条复核：文件存在、行号在范围、引文与该行"
    "原文匹配，容空白差异；复核不过的发现会降级 unverified 并在票面点名，虚报即曝光）。"
)

_SKELETON = """\
# 巡检审查任务（实例 {instance} 期 {period}，审查面 {face}）

{persona}

## 本期审查范围
- 审查基座目录：{base_dir}（所有证据 path 相对本目录；这是你的工作目录，也是你唯一
  允许读取的范围之外都不看）。
- 审查基点：{base_head}
{suite_block}
{prev_block}
{scope_block}
## 分面审查清单（{face}；只对上列范围内文件套用）
{profile_text}

## 预算
- 本期发现条数上限 **{max_findings} 条**（超出部分机械侧按 severity 截断丢弃——宁可
  精选最有把握的 {max_findings} 条，不要灌水）。

## 语言（宿主令 260927「报告用英语写」）
- findings 的 **subject / why / suggestion** 一律用**英文**书写（报告 JSON 与票面直接消费
  它们，跨项目收件人读英文面）。
- **数据不译**：evidence 里的 `quote`（被测文件原文）、`path`/filename、命令原文、标识符
  一律**照抄原样**，不得翻译/改写（机械复核按原文子串匹配，翻译即判 unverified）。
- 你要调用的 SKILL.md / 仓库内文档里出现其它语言（含中文）时，照读不误；只有你**输出**的
  这三段叙述文字用英文。

## 输出契约（必须逐字遵守）
在回答的**最末尾**输出**恰好一块** ```json 围栏代码块，内容形如：
```json
{{"findings": [
  {{"subject": "One-line summary (include file:line) — in English",
    "severity": "high|med|low",
    "evidence": [{{"path": "path relative to the base dir", "line": 123, "quote": "verbatim snippet of that line (keep it within ~{max_quote} chars)"}}],
    "why": "Why this is a problem (semantic judgement) — in English",
    "suggestion": "Suggested action (or 'no fix needed, record only') — in English",
    "confidence": 0.0}}
]}}
```
硬性规则：
- findings 必须是列表（可为空列表=本期零发现）；围栏块**只有这一块**，之前不要再输出
  其它 ```json 代码块。
- **不要输出 id**：id 由机械侧按内容哈希铸造，你报的任何 id 都会被丢弃。
- evidence 每项必填 path（相对路径）/line（≥1 整数）/quote（该行原文片段）；
  evidence 至少一条。
- quote 建议精炼在 {max_quote} 字内：超出**不会被拒收**——机械侧自动截断保留原文
  前缀并在报告点名，所以别为守字数丢证据信息；但引文必须真实抄自标注的那一行
  （机械逐条复核，不符=该条降级 unverified 并点名）。
- severity 只认 high|med|low；confidence 是 0.0~1.0 的小数。
- **硬约束（机械执法，不是建议）：subject / why / suggestion 必须全英文**——任何 CJK
  出现在这三段里，机械复核会把该条**判为 unverified 并点名 `non_english_text`**（票面可见，
  但不会生成修码建议票）。即：写中文=白写这条发现。
  - 例外只有**数据**：evidence 的 `quote`（被测文件原文）、`path`、命令原文可含任意语言，
    照抄不译；被测文件里的中文**不要**搬到 subject/why 里复述，要用英文概括。
- HARD RULE (mechanically enforced, not a suggestion): subject/why/suggestion MUST be
  English. Any CJK there makes the mechanical recheck mark that finding unverified with
  reason `non_english_text` — it stays visible on the ticket face but opens no fix ticket.
  Data (evidence `quote`/`path`, command text) is copied verbatim and never translated.
- 红线：巡检只出报告与建议，绝不改码。
"""


# ========================================================================================
# 缩面：本期变化面（t260924-06）——四路输入解析与 scope 组装，全纯函数、一律不抛出
# ========================================================================================
#
# 审查目标=「本期有什么新病灶」，不是全仓普查（宿主 260924 拍定）。四路输入逐路
# 失败语义（review R1 闭合口径）：回落值 + meta 计数 + scope_block 点名三件套，且
# **任何一路畸形都不回落全仓**——缩面纪律在畸形路径下依然成立。


def parse_name_status(text: str) -> Tuple[List[str], Dict[str, Any]]:
    """`git diff --name-status` 输出 → 变化面文件行清单（「M\tpath」原样保留）。

    失败语义（不抛出）：可解析行照收（首列单字母状态 + 非空路径）；不可解析行丢弃并
    计 meta["diff_malformed_lines"]；输入整体为空=([], {"diff_error": "变化面 diff 输出
    为空"})。路径剥首尾空白、拒含 "\\0"（二进制污染防呆）。"""
    meta: Dict[str, Any] = {}
    rows: List[str] = []
    bad = 0
    for line in str(text or "").splitlines():
        line = line.strip("\r")
        if "\0" in line:
            bad += 1
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2 and len(parts[0]) == 1 and parts[0].strip() \
                and parts[1].strip():
            rows.append("%s\t%s" % (parts[0], parts[1].strip()))
        elif line.strip():
            bad += 1
    if bad:
        meta["diff_malformed_lines"] = bad
    if not rows and not bad:
        meta["diff_error"] = ("change-face diff output is empty (no difference between the previous "
                              "base and this period's base, or the diff failed)")
    return rows, meta


def suite_receipt_rows(path: Any) -> Tuple[List[str], Dict[str, Any]]:
    """本期套件回执 → 红/环境红/漏跑条目清单（人话行，进 scope_block）。

    失败语义（不抛出）：文件缺失/坏 JSON/顶层非 dict/缺键=([], {"suite_note": 点名
    原因})——该路按「无条目」处理但必须点名「回执不可读，套件红面未纳入审查范围」，
    绝不因回执烂而阻断 inspect。"""
    meta: Dict[str, Any] = {}
    p = Path(path) if path else None
    if p is None or not p.is_file():
        return [], {"suite_note": ("no suite receipt for this period (%s) — the suite "
                                   "red/missed faces are not part of the review scope"
                                   % (p.name if p else "<empty path>"))}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [], {"suite_note": ("suite receipt unreadable (%s: %s) — the suite red face "
                                   "is not part of the review scope"
                                   % (type(e).__name__, e))}
    if not isinstance(doc, dict):
        return [], {"suite_note": ("suite receipt is not a mapping at the top level — the suite red "
                               "face is not part of the review scope")}
    rows: List[str] = []
    err = str(doc.get("error") or "").strip()
    if err:
        rows.append("套件整体异常：%s" % err)
    if int(doc.get("env_fail") or 0):
        rows.append("套件环境红（env_fail=%s）" % doc.get("env_fail"))
    if int(doc.get("ran") or 0) == 0 and not err:
        rows.append("套件零运行（ran=0）——漏跑嫌疑")
    details = doc.get("details")
    if isinstance(details, list):
        for d in details:
            if isinstance(d, dict) and str(d.get("status") or "") in ("FAIL", "ENV_FAIL"):
                rows.append("场景 %s：%s" % (d.get("name") or d.get("ticket_id") or "?",
                                             d.get("status")))
    elif details is not None:
        meta["suite_note"] = "套件回执 details 非列表（got %s）——逐场景条目缺席" \
            % type(details).__name__
    return rows, meta


def ki_open_entries(path: Any) -> Tuple[List[str], Dict[str, Any]]:
    """KI 册（notes/debts/known-issues.md）→ open 条目清单。

    失败语义（不抛出）：文件缺失=([], {"ki_note": "KI 册不可读：<路径>"})；零 open
    条目或全烂行=([], {"ki_note": "KI 册无 open 条目或不可解析"})。条目锚=含「KI-」
    编号且行内标 open 的行（宽容大小写/中英冒号）。"""
    meta: Dict[str, Any] = {}
    p = Path(path) if path else None
    if p is None or not p.is_file():
        return [], {"ki_note": "KI register unreadable: %s" % (p if p else "<empty path>")}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [], {"ki_note": "KI register unreadable: %s (%s)" % (p, e)}
    rows: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if "KI-" in s and "open" in s.lower():
            rows.append(s[:160])
    if not rows:
        return [], {"ki_note": "KI register has no open entries or is unparseable: %s" % p.name}
    return rows, meta


def build_change_scope_text(diff_rows: List[str], suite_rows: List[str],
                            ki_rows: List[str], notes: Dict[str, Any],
                            prev_summary: str, max_shards: int,
                            max_files_per_shard: int) -> Tuple[str, Dict[str, Any]]:
    """四路输入 → scope_block（prompt 的「本期审查范围」段）+ scope_meta。

    硬上限（U6）：变化面超 max_shards×max_files_per_shard 时截断，meta["truncated"]
    记弃置数、scope_block 点名截断数。meta 汇聚各路 note（diff_malformed_lines/
    diff_error/suite_note/ki_note/scope_note）。零文件也不空转：scope_block 显式
    「本期变化面为空」——审查范围=给定清单，清单外不看，绝不回落全仓。"""
    meta: Dict[str, Any] = dict(notes)
    cap = max(1, int(max_shards)) * max(1, int(max_files_per_shard))
    total = len(diff_rows)
    meta["scope_files"] = min(total, cap)
    kept = diff_rows
    if total > cap:
        kept = diff_rows[:cap]
        meta["truncated"] = total - cap
    lines: List[str] = [
        "## 本期审查范围（审查范围=本清单，清单之外的文件一律不看——"
        "目标是「本期有什么新病灶」，不是全仓普查；**禁止 spawn 任何子代理**，"
        "the shard cap (%d shards, <=%d files each) was enforced by the mechanical side)"
        % (max_shards, max_files_per_shard),
        "",
        "### 变化面（上期基点→本期基点，git diff --name-status）",
    ]
    if meta.get("truncated"):
        lines.append("- （变化面共 %d 个文件，超出上限已截断弃置 %d 个——只审保留集）"
                     % (total, meta["truncated"]))
    if kept:
        lines += ["- %s" % r for r in kept]
    else:
        lines.append("- （本期变化面为空）")
    lines.append("")
    lines.append("### 本期套件回执条目（红/环境红/漏跑）")
    lines += ["- %s" % r for r in suite_rows] if suite_rows else ["- （无条目）"]
    lines.append("")
    lines.append("### KI 册 open 条目（复发征兆重点看）")
    lines += ["- %s" % r for r in ki_rows] if ki_rows else ["- （无条目）"]
    lines.append("")
    lines.append("### 上期发现与裁定（重复项机械侧自动去重，勿复述上期原样内容）")
    lines.append(prev_summary or "- （无对照）")
    warned = [k for k in ("diff_error", "diff_malformed_lines", "suite_note",
                          "ki_note", "scope_note") if meta.get(k)]
    if warned:
        lines.append("")
        lines.append("### 输入面点名（畸形/缺席路径，机械侧已按回落语义处置）")
        for k in warned:
            lines.append("- %s: %s" % (k, meta[k]))
    return "\n".join(lines), meta


def build_inspect_prompt(instance_id: str, period: str, face: str, base_dir: str,
                         base_head: str, max_findings: int,
                         suite_receipt: str = "", prev_summary: str = "",
                         scope_block: str = "") -> str:
    """组装 inspect 段 prompt（骨架+缩面范围+分面清单+输出契约）。face 词表外=显式报错。

    scope_block（t260924-06 缩面）：活动侧给定的本期变化面清单段；空=回落旧全仓骨架
    （老调用点/回放形态兼容——生产活动必传，测试可断言两形态）。"""
    if face not in PROFILE_FACES:
        raise ValueError("inspect_profile %r 未接线（可指名：%s）" % (face, "、".join(PROFILE_FACES)))
    if scope_block:
        # 缩面形态：审查范围=给定清单（scope_block 自带硬上限与禁子代理规则），
        # 旧 suite/prev 块并入清单段，不再单列——避免同一事实两处口径漂移。
        return _SKELETON.format(
            instance=instance_id, period=period, face=face, persona=PERSONA,
            base_dir=base_dir, base_head=base_head or "（未取到，以基座工作区实况为准）",
            suite_block="", prev_block="",
            scope_block=scope_block,
            profile_text=PROFILE_TEXTS[face], max_findings=max_findings,
            max_quote=MAX_QUOTE_CHARS)
    suite_block = "- 当期套件回执：%s（读它，结合套件红绿给发现；无套件档=无此文件）" % suite_receipt \
        if suite_receipt else "- 本期无套件档（没有套件回执可读）"
    prev_block = ("- 上期发现摘要（跨期对照参考；重复项机械侧自动去重，不要为了凑数复述"
                  "上期原样内容）:\n%s" % prev_summary) if prev_summary \
        else "- 上期无台账（首期或上期未落账），无对照参考"
    return _SKELETON.format(
        instance=instance_id, period=period, face=face, persona=PERSONA,
        base_dir=base_dir, base_head=base_head or "（未取到，以基座工作区实况为准）",
        suite_block=suite_block, prev_block=prev_block, scope_block="",
        profile_text=PROFILE_TEXTS[face], max_findings=max_findings,
        max_quote=MAX_QUOTE_CHARS)


#: 分面附加清单（宿主裁定②：通用骨架 + 每 face 一段附加清单）
PROFILE_TEXTS: Dict[str, str] = {
    "test": """\
- 守卫是否还有效：integration/ 场景守卫断言的对象（函数/选择器/字面锚）在仓内是否仍真实
  存在且语义未变（退役清单被当断言失效、夹具路径被当仓内资产是历史假报重灾区——引用前
  先确认对象真的在生产侧）；
- 场景是否冗余/互相覆盖（同 intent 重复看守）；
- 场景三态纪律（PASS/FAIL/ENV_FAIL）是否被绕过（SKIP 残留、假绿路径）。""",
    "doc": """\
- 文档漂移：docs/ 定稿库与代码现实是否脱节（接口/路径/流程改名后文档没跟）；
- docs/README.md 索引与实际文件是否一致（frontmatter/index.json 漂移）；
- 相互链接是否断（引用了不存在的文档路径）。""",
    "stage": """\
- 台面容量与撞闸：stage_docker 清点面（孤儿容器/容量逼近/域外在册）；
- 巡检绝不拆台：发现只报告，回收动作只属于 stage_docker sweep 与引擎所有者路径。""",
    "mechanism": """\
- 引擎机制面：dev-lane/巡检/watcher 的机械防线是否有失效征兆（版本门/写集闸/失败分类）；
- 已知 KI 家族的复发征兆（notes/debts/known-issues.md 的 open 条目）。""",
    "simplify": """\
- 可简化面：重复实现/死代码/过度抽象（只报有把握、有明确收益的）；
- 报告时附「删了会破坏什么」的证据，不凭感觉。""",
}


def build_persona_patch() -> str:
    """inspect agent 的一次性 cordis patch（persona 覆盖；agent_activities spawn 时
    --patch 注入）。role=inspection 不落 server/roles/ 文件（机制自有，免写集外依赖）；
    role patch 查表缺席天然软跳过，本 patch 显式覆盖同 id。

    t260924-06 缩面：追加「禁止 spawn 子代理」硬规则（纵深防御第二层——第一层是
    活动侧给定的范围清单与 inspect_max_shards/每片文件数机械封顶；260926 期实测
    7 子代理无界扇出正是 dsh fatal 零产出的直接诱因）。"""
    persona_yaml = PERSONA.replace("\n", " ")
    return (
        "# 本文件由 run_inspection_inspect 每次 spawn 生成（t260916-22；真源="
        "inspection_inspect.build_persona_patch）。role=inspection 的只读审查员 persona。\n"
        "- id: system-prompt\n"
        "  config:\n"
        "    persona: >-\n"
        "      %s 不派生任何子代理（子代理扇出被禁止：审查范围已由机械侧给定并封顶，"
        "自行扩面=违纪）\n" % persona_yaml)


def readonly_pin_patch() -> str:
    """inspect agent 的只读 pin patch（晚于 profile/docker pin 追加=覆盖生效）：
    sandbox-policy.mode: read-only + permission 表内自带 read-only 预设、defaultPreset
    选它（read-only = sandbox: read-only + approval: ask）。

    260920 修正（宿主令「直接修」，巡检每日必失败实案 t260920-02）：
    本机生产 dsh（0.1.1-rc.2）的**权限预设表缺省只有 workspace-write / danger-full-access**
    ——原实现直接引用 `defaultPreset: 'read-only'` 会在 PermissionPresetService 构造期抛
    `permission: unknown preset "read-only"`，巡检 inspect 段起不来、每期巡检查红
    （09-18/09-19 FAILED、09-20 blocked）。
    **不可**简单换成 workspace-write：`dsh-permission-presets` 的预设**自带 sandbox 模式**
    （apply() 会把会话 sandbox 设成预设的 sandbox），换名等于把只读沙箱改写成可写——
    等于悄悄废掉只读红线。故本补丁**自带一条 read-only 预设**（保留全部三条表项），
    语义与 t260916-22 方案 §2.2「read-only=(sandbox: read-only, approval: ask)」逐字一致，
    只是把「假设表里已有」改成「自己写进表里」。
    design.md:18/194 记的「预设表含 read-only（--dump-default-config 实证）」与本机版本
    不符，属设计假设与生产 dsh 版本的口径冲突（实证面另案）。"""
    return (
        "# 本文件由 run_inspection_inspect 每次 spawn 生成（t260916-22 只读红线 / "
        "260920 修正：permission 表内自带 read-only 预设，语义不变只补表项；"
        "晚于 docker pin 追加=覆盖生效）。\n"
        "- id: sandbox-policy\n"
        "  disabled: false\n"
        "  config:\n"
        "    mode: 'read-only'\n"
        "- id: permission\n"
        "  disabled: false\n"
        "  config:\n"
        "    presets:\n"
        "      read-only:\n"
        "        sandbox: 'read-only'\n"
        "        approval: 'ask'\n"
        "        name: 'read-only'\n"
        "        description: '巡检只读：文件系统级只读沙箱 + 有问必拒（headless 无应答面，写操作走不通）'\n"
        "      workspace-write:\n"
        "        sandbox: 'workspace-write'\n"
        "        approval: 'ask'\n"
        "        name: 'workspace-write'\n"
        "        description: 'Write inside the workspace and permitted temporary directories'\n"
        "      danger-full-access:\n"
        "        sandbox: 'danger-full-access'\n"
        "        approval: 'never'\n"
        "        name: 'danger-full-access'\n"
        "        description: 'Full file access without approval prompts'\n"
        "    defaultPreset: 'read-only'\n")


def sanitize_agent_home(raw_home, fallback_root, name):
    """agent_home 泳道锚守卫（260924 宿主直修令；纯函数便于回归棒直测）。

    260924 实案：agent_home 解析落进泳道树（路径含 .lane 段）后，套件段拆掉泳道、
    agent 随后 home.mkdir(parents=True) 把目录壳**复活**（agent 会话存储重建
    <lane>/server/engine/out/…）——拆除回执「已清零残留」与清扫「无可清条目」被这
    种壳两头戏弄（260922/260924 双实案躺壳）。守卫：命中 .lane 段即回落
    fallback_root/name，返回人读 note 点名原锚；场景注入的 /tmp 隔离台无 .lane
    段，不受影响。
    """
    try:
        parts = raw_home.resolve().parts
    except OSError:  # 极端 IO 故障时退回未解析形态判定（仍只认整段 .lane）
        parts = raw_home.parts
    if ".lane" in parts:
        return fallback_root / name, "泳道锚回落：%s -> %s" % (raw_home, fallback_root / name)
    return raw_home, ""


def sweep_stub_dir_names(names, instance, keep="", target=""):
    """目录壳候选筛选（纯函数；260924 验货精修升格）：从 lane_parent 现存目录名清单里
    挑本实例的壳候选。壳名两形：inspection-<实例>-<期>（分支名「/」→「-」化）与早期形
    <实例>-<期>（260922/20260924/20260926 三实案都要能收）。期号=YYYYMMDD 字典序即
    时间序：定向态（target 非空）仅收精确等于该期；水位态（keep 非空）仅收**早于**水位
    （setup 清扫自愈面，与 worktree/分支同语义）；两者皆空=[]（判不准不动）。"""
    if not instance or (not keep and not target):
        return []
    out = []
    for name in names:
        for pre in ("inspection-%s-" % instance, "%s-" % instance):
            if name.startswith(pre) and name != pre:
                period = name[len(pre):]
                if not period.isdigit():
                    continue
                if target and period == target:
                    out.append(name)
                elif keep and not target and period < keep:
                    out.append(name)
                break
    return sorted(set(out))


def stub_embedded_repo(stub):
    """目录壳内嵌真仓判定（260924 验货精修；t260916-20 教训承袭）——三态分明：
    ①顶层 .git **文件**=worktree 痕迹（对象库在主仓），壳可清，**不算**嵌套仓；
    ②顶层 .git **目录**=独立仓根（对象库在内）→ 拒拆，返回其路径；
    ③任意更深层 .git（文件/目录）=未注册嵌套仓 → 拒拆，返回其路径。
    无内嵌仓 → None（可清）。"""
    top = stub / ".git"
    if top.is_dir():
        return top
    for q in stub.rglob(".git"):
        if q != top:
            return q
    return None

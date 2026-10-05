#!/usr/bin/env python3
"""inspection_scan — the test-face scanner (inspection epic ticket 1, first instance,
t260905-03).

------------------------------------------------------------------------
【退役留档（t260916-22，宿主令「不需要这个静态扫描，我们巡检要用 agent 来做」）】
本模块已从生产路径摘除：InspectionPeriodicWorkflow 新票走 inspect 段
（agent 审查，见 inspection_inspect.py / agent_activities.run_inspection_inspect）。
本文件保留一版只服务老在途票 replay（Temporal 重放历史里的 run_inspection_scan
调用必须仍能匹配）——新代码禁接线本模块；S1~S4 静态发现自此不再产出，274 条旧
发现整体作废不迁移（宿主裁定④）。deadman/suite 机械面不受影响。
------------------------------------------------------------------------

Red line: inspection only produces reports and ticket-opening suggestions, it never
modifies code — this module is a pure-read static surface with zero write operations.

Four scans (severity criteria fixed by review_plan conditional-pass comment C1):
  S1 duplicate   duplicate-scenario detection: token overlap (Jaccard) of SCENARIOS
                 name+intent ≥ DUP_JACCARD → med.
  S2 guard-anchor guard-anchor → producer wording-presence verification (KI-051 made
                 permanent, as a standalone scan): extract the literal anchors asserted
                 by guard scenario source and reverse-index the **presence of the
                 wording** in producer source (not file/function existence).
                 Template-aware tiers:
                   (1) exact literal hit → present;
                   (2) combined fragments: split the anchor into fragments; if any single
                     line of any producer file contains all of them → present;
                   (3) core-fragment (length ≥ 3) coverage = 0 (both the literal and the
                     combined fragments missing, with the producer context located) →
                     **high (confirmed drift)**;
                   (4) core coverage > 0 but the combination fails (similarity
                     suspended) → med, handed to human review.
                 When the producer context cannot be located (the guard source references
                 no existing file), the anchor is skipped and noted in meta, producing no
                 finding — preventing "cannot locate = a screen full of false positives".
                 KI-051 rationale: this scan is a **static surface** and does not depend
                 on scenarios actually running, so it naturally sidesteps env_fail
                 covering up a true red (the root cause of KI-051 being masked by
                 environment reds for days) — that is exactly why it exists. The real
                 capture.mjs case (old and new copy sharing the prefix "隔离台") lands in
                 tier 4 med and is still reported; a fixture replicating a pure rewrite
                 takes the tier 3 high branch (see the tests and scenarios).
  S3 stale-ref   stale assertions: a file path referenced by a guard no longer exists
                 (moved/deleted) → high; a referenced line number exceeds the target
                 file's line count → high (line number out of range).
  Summary        zero findings = heartbeat true (an all-green period opens a
                 zero-finding ticket as heartbeat proof).

Input surface (all injectable for unit-test stubs; malformed input never crashes, it
degrades item by item into meta/findings):
  - Scenario manifest: SCENARIOS from integration/run_scenarios.py — read with ast as
    literals only, never importing the runner (zero side effects); a malformed tuple → a
    named S1-level med finding.
  - Guard source: integration/**/sc_*.py|.mjs|.ts|.tsx|.js (the existing "every sc_ file
    must be registered" discipline).
  - Producer source: text source files under PRODUCER_ROOTS plus existing files
    referenced from guard source.

CLI (ops/scenario channel): stdout always emits a single line of JSON {ok, result|error}
(same contract as client.py).
    python3 inspection_scan.py --repo-root <repo> [--scenarios-path <run_scenarios.py>]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SCAN_NAMES = ("duplicate", "guard-anchor", "stale-ref")
SEVERITY_ORDER = {"high": 0, "med": 1, "low": 2}
DUP_JACCARD = 0.55          # S1 threshold (calibration notes from the real repo live in the ticket report; changing it changes behavior, so it needs test cases)
_WINDOW_ALL = 1.0           # combined fragments: all fragments hit within a single line
STOPWORDS = {"the", "a", "an", "of", "for", "and", "with", "by", "to", "in", "on", "vs", "at", "is", "be"}
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PATH_RE = re.compile(r"(?:\.\./|\./)?[A-Za-z0-9_][A-Za-z0-9_\-./]*\.(?:py|mjs|ts|tsx|js|sh|md|ya?ml|json)\b")
_LINE_REF_RE = re.compile(r"\bL(\d{1,5})\b")
_PRODUCER_EXTS = {".py", ".mjs", ".ts", ".tsx", ".js", ".md", ".sh", ".yaml", ".yml", ".json"}
GUARD_EXTS = {".py", ".mjs", ".ts", ".tsx", ".js"}
# 扫描根排除表（t260910-11 误报校准）：泳道与过程目录不是生产方源码——旧泳道副本
# （.lane/<票>/…）曾被 S2 当成生产方、把已删文案判成「在场」（假绿）或反衬出满屏 high。
# 单点常量：collect_producers / collect_guards / build_ref_resolver 三处共用。
EXCLUDED_DIRS = frozenset((
    "node_modules", ".git", "out", ".venv", "data", "__pycache__",
    ".lane", ".worktrees", ".suyou", ".sandbar", ".dsh",  # naming-compat（工单③点名的排除目录，数据非新标识）
))


class ScanError(Exception):
    """The scan cannot start (repo root/manifest missing) — fail-closed and named, never a
    silent empty return."""


@dataclass
class Finding:
    """One finding (the smallest unit that lands on the ticket face: severity with
    evidence)."""

    scan: str
    severity: str                # high | med | low
    subject: str
    evidence: str
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": finding_id(self.scan, self.subject),
            "scan": self.scan,
            "severity": self.severity,
            "subject": self.subject,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }


def finding_id(scan: str, subject: str) -> str:
    """Deterministic id (a short sha1 digest) — stable for the same finding across
    periods, for fix-ticket references and dedupe."""
    return "%s:%s" % (scan, hashlib.sha1(("%s|%s" % (scan, subject)).encode("utf-8")).hexdigest()[:10])


def summarize(findings: List[Finding]) -> Dict[str, Any]:
    counts = {"high": 0, "med": 0, "low": 0}
    by_id: Dict[str, Finding] = {}
    for f in findings:                       # the same finding (same id) recurring across anchors is recorded once
        by_id.setdefault(finding_id(f.scan, f.subject), f)
    deduped = list(by_id.values())
    for f in deduped:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    ordered = sorted(deduped, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.scan, f.subject))
    return {"counts": counts, "total": len(deduped), "ordered": ordered}


# ========================================================================================
# S1 duplicate — duplicate-scenario detection (anchor/assertion overlap)
# ========================================================================================

def tokenize(text: str) -> set:
    """Deterministic tokenization: ascii words + CJK bigrams; stopwords removed."""
    tokens: set = set()
    low = (text or "").lower()
    ascii_words = re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", low)
    tokens.update(w for w in ascii_words if w not in STOPWORDS and not w.isdigit())
    for run in re.findall(r"[\u4e00-\u9fff]+", low):
        if len(run) == 1:
            tokens.add(run)
            continue
        for i in range(len(run) - 1):
            tokens.add(run[i:i + 2])
    return tokens


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


_CMD_JACCARD = 0.75          # S1 第二级（断言对象）阈值（近重必近同 cmd；单 token 差异形态=守不同对象，须压掉）
_SELECTOR_JACCARD = 0.50     # S1 第三级（选择器/锚点字面）阈值


def _quoted_literals(text: str) -> set:
    """cmd/断言里的引号字面（选择器/锚点形态的提取面；无引号=空集=该维度无分歧）。"""
    out = set()
    for m in re.finditer(r'"([^"\\]+)"|' + r"'([^'\\]+)'" + r"|`([^`\\]+)`", text or ""):
        out.add(next(g for g in m.groups() if g is not None))
    return out


def _pair_is_true_duplicate(name_a: str, tok_a: set, entry_a: Dict[str, Any],
                            name_b: str, tok_b: set, entry_b: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """S1 三级复核（t260910-11 校准）：意图 + 断言对象 + 选择器三级全符才判重；
    任一维度分歧不判重（返回 False，调用方计入 duplicate_suppressed）——防阈值
    一级就吞掉「意图相近但守不同对象」的真重复，也防静默放过真重复（复核链路
    在 meta 里留计数，人可查）。"""
    detail = {"pair": "%s × %s" % (name_a, name_b)}
    # 一级：意图（name+intent 词 Jaccard，调用方已过阈值）
    cmd_a, cmd_b = str(entry_a.get("cmd", "")), str(entry_b.get("cmd", ""))
    tok_cmd_a, tok_cmd_b = tokenize(cmd_a), tokenize(cmd_b)
    # 二级：断言对象（cmd 词 Jaccard；双方 cmd 均无 token 视为该维度不分歧）
    if tok_cmd_a or tok_cmd_b:
        if jaccard(tok_cmd_a, tok_cmd_b) < _CMD_JACCARD:
            detail["diverge"] = "cmd"
            return False, detail
    # 三级：选择器/锚点字面（cmd 引号字面 Jaccard；双方均无字面=不分歧）
    sel_a, sel_b = _quoted_literals(cmd_a), _quoted_literals(cmd_b)
    if sel_a or sel_b:
        if jaccard(sel_a, sel_b) < _SELECTOR_JACCARD:
            detail["diverge"] = "selector"
            return False, detail
    return True, detail


def scan_duplicate_scenarios(entries: List[Dict[str, Any]]) -> Tuple[List[Finding], Dict[str, Any]]:
    """entries: [{name, intent, cmd}] (malformed entries are shape-normalized by
    parse_scenarios but may still carry errors). Returns (findings, meta). O(n²) pairwise
    comparison, n at the scale of hundreds."""
    meta: Dict[str, Any] = {"compared": 0, "duplicate_suppressed": 0}
    findings: List[Finding] = []
    norm = []
    for e in entries:
        text = "%s %s" % (e.get("name", ""), e.get("intent", ""))
        norm.append((str(e.get("name", "")), tokenize(text), e))
    for i in range(len(norm)):
        for j in range(i + 1, len(norm)):
            name_a, tok_a, e_a = norm[i]
            name_b, tok_b, e_b = norm[j]
            meta["compared"] += 1
            score = jaccard(tok_a, tok_b)
            if score < DUP_JACCARD:
                continue
            # 一级过阈值后走三级复核（t260910-11）：意图+断言对象+选择器全符才判重
            is_dup, detail = _pair_is_true_duplicate(name_a, tok_a, e_a, name_b, tok_b, e_b)
            if not is_dup:
                meta["duplicate_suppressed"] += 1
                continue
            findings.append(Finding(
                scan="duplicate", severity="med",
                subject="dup:%s × %s" % (name_a, name_b),
                evidence="三级复核全符（意图 Jaccard=%.2f ≥ %.2f + 断言对象/选择器不分歧），"
                         "共享词 %d 个" % (score, DUP_JACCARD, len(tok_a & tok_b)),
                suggestion="两场景意图/对象/选择器三近重——合并或显式分化（intent 级重复禁止是清单纪律）"))
    return findings, meta


# ========================================================================================
# Scenario manifest parsing (ast takes literals only, the runner is never imported)
# ========================================================================================

def parse_scenarios(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    """Extract the SCENARIOS triples/quadruples from run_scenarios.py; malformed items go
    into problems (no crash)."""
    problems: List[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as e:
        raise ScanError("场景清单不可解析：%s（%s）" % (path, e)) from e
    raw: Any = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "SCENARIOS" for t in node.targets):
            raw = node.value
            break
    if raw is None:
        raise ScanError("场景清单缺 SCENARIOS 定义：%s" % path)
    if not isinstance(raw, (ast.List, ast.Tuple)):
        problems.append("SCENARIOS 不是列表/元组字面量")
        return [], problems
    entries: List[Dict[str, str]] = []
    for idx, el in enumerate(raw.elts):
        try:
            parts = [ast.literal_eval(x) for x in el.elts]  # non-tuple / non-constant member → ValueError
            if not isinstance(el, ast.Tuple):
                raise ValueError("entry is not a tuple")
            if len(parts) < 3:
                raise ValueError("field count %d<3" % len(parts))
            entries.append({"name": str(parts[0]), "intent": str(parts[1]),
                            "cmd": " ".join(str(p) for p in parts[2:])})
        except Exception as e:  # noqa: BLE001 — each malformed manifest entry degrades on its own; one bad item must not ruin the whole scan
            problems.append("SCENARIOS[%d] 畸形（%s）" % (idx, e))
    return entries, problems


# ========================================================================================
# Guard-anchor extraction + S2/S3
# ========================================================================================

def extract_string_literals(source: str, ext: str) -> List[str]:
    """Pull string literals out of guard source: .py goes through ast (a syntax error →
    ScanError, degraded per file by the caller); other extensions go through a quoting
    regex (mjs/ts/js template strings and single/double quotes)."""
    if ext == ".py":
        vals: List[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                vals.append(node.value)
        return vals
    out: List[str] = []
    for m in re.finditer(r"\"([^\"\\\n]{1,400})\"|'([^'\\\n]{1,400})'|`([^`\\\n]{1,400})`", source):
        out.append(next(g for g in m.groups() if g is not None))
    return out


def is_anchor_literal(s: str) -> bool:
    """Candidate literal anchors for guard assertions (tightened criteria to avoid a
    screen full of false positives; calibrated on the real repo 260905):
    long enough, contains ≥2 CJK characters (UI-copy shape; this repo's anchors are all
    Chinese); excludes template interpolation (${…} = the guard's own error text),
    multi-line template strings, and selector/path/URL shapes."""
    s = s.strip()
    if len(s) < 6 or "\n" in s:
        return False
    if "${" in s or "://" in s or s.startswith(("./", "/", "#", ".")):
        return False
    if len(CJK_RE.findall(s)) < 2:
        return False
    if re.match(r"^[\w\-./: ]+$", s):   # a pure ascii selector/path with spaces
        return False
    if re.search(r"[？！?]", s) or s.endswith("："):  # 疑问/说明语气=守卫自述散文，非文案锚
        return False
    if re.search(r"（[^（）]*[A-Za-z0-9][^（）]*）", s):  # 全角括号内嵌 ascii=注释性短语（执行规格（spec）），非文案字面
        return False
    if re.search(r"\([^()]*[A-Za-z0-9][^()]*\)", s):    # 半角括号内嵌 ascii 同理（KI-036 注释形态）
        return False
    if re.search(r"%[sdrif]", s):        # assertion/log format strings (the guard's own wording, not a producer anchor)
        return False
    if re.search(r"\[\w+[=~^|]?", s):    # attribute selectors (DOM locators, not copy anchors)
        return False
    return True


# 断言行/守卫自述行判据（t260910-11 校准）：文案锚只可能出现在「对捕获到的页面文本做
# 断言」的行上；throw/Error/日志行里的长散文是守卫自己的失败说明（首期 high 误报主体），
# 不是生产方文案锚。
_ASSERT_LINE_RE = re.compile(r"\b(assert|check|expect|toContain|includes|toBe|toHave|match|snapshot)\w*\b")
_GUARDSELF_LINE_RE = re.compile(r"(throw\b|new Error\(|console\.|\bprint\(|\blog\(|FAIL_REASON)")


_FIXTURE_WRITE_CALL_RE = re.compile(r"\.\s*write\s*\(|write_text\s*\(|write_scenarios\s*\(")


def _fixture_write_span(source: str) -> set:
    """夹具造文件语句（t.write(…)/write_text(…)/write_scenarios(…)）的实参行号集合
    （含续行直到括号闭合）——这些行里的路径字面是**写进夹具树的数据**，不是对真仓
    的路径断言（自举夹具场景与 lib 型共享夹具的合法形态），S3 不判 stale、S2 不取锚。
    括号不平衡/截断时保守地只标记到文件尾（宁可多豁免一行散文，不误判夹具数据）。"""
    out: set = set()
    depth = 0
    in_call = False
    for no, line in enumerate((source or "").splitlines(), start=1):
        if not in_call and _FIXTURE_WRITE_CALL_RE.search(line):
            in_call = True
            depth = 0
        if in_call:
            out.add(no)
            for ch in line:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            if depth <= 0:
                in_call = False
    return out


def _anchor_candidate_lines(source: str) -> List[str]:
    """Source → the lines where copy anchors may live (assertion lines minus guard-self
    prose lines). Malformed lines simply yield no literals — degradation, not crash."""
    fixture_span = _fixture_write_span(source)
    out = []
    for no, line in enumerate((source or "").splitlines(), start=1):
        if no in fixture_span:
            continue
        if _GUARDSELF_LINE_RE.search(line):
            continue
        if _ASSERT_LINE_RE.search(line):
            out.append(line)
    return out


def _line_string_literals(line: str) -> List[str]:
    """Quoted literals from one line (single/double/backtick; no escapes spanning)."""
    out = []
    for m in re.finditer(r'"([^"\\\n]{1,400})"|' + r"'([^'\\\n]{1,400})'" + r"|`([^`\\\n]{1,400})`", line):
        out.append(next(g for g in m.groups() if g is not None))
    return out


_ASSEMBLED_RE = re.compile(
    r"[\u4e00-\u9fff]\s*[+|=<>(){}\[\]/\\]"   # CJK 粘连操作符
    r"|[A-Za-z0-9]\s*[+|=<>(){}\[\]]"            # ascii 胶水（last+1 形态=行为描述非文案）
    r"| getBy\(|aria-")


def is_assembled_or_dom_anchor(anchor: str) -> bool:
    """运行时拼装文本/DOM 结构锚判据（t260910-11 误报校准）：锚内 CJK 直接粘连 ASCII
    操作符/选择器（「文案甲 + 文案乙」、aria-*、getBy(…)），说明锚描述的是运行时拼装
    输出或 DOM 结构而非人读文案字面——这类锚组合失败可能是拼装顺序变了而非文案漂移，
    **不得报 high**（校准红线），最高 med 交人审。注意全角引号内的按钮符号（「+ 新建」）
    不是拼装痕迹——『』「」是 UI 文案字面的常态装饰，KI-051 回放锚（真文案漂移）必须
    仍走 high 支路，判据不能把它误吞。"""
    return bool(_ASSEMBLED_RE.search(anchor or ""))


def anchor_fragments(anchor: str) -> List[str]:
    """Anchor → fragments (the combined-fragment strategy): split on non-CJK/non-
    alphanumeric boundaries, keeping segments of length ≥ 2."""
    parts = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", anchor)
    return [p for p in parts if len(p) >= 2]


def _producer_hit(content: str, anchor: str, fragments: List[str]) -> Tuple[bool, float]:
    """Decide an anchor's presence within one producer file's content: exact literal hit →
    (True, 1.0); all combined fragments within a single line → (True, 1.0); otherwise
    (False, core-fragment coverage)."""
    if anchor in content:
        return True, 1.0
    if not fragments:
        return False, 0.0
    core = [f for f in fragments if len(f) >= 3] or fragments
    best_cov = 0.0
    for line in content.splitlines():
        if all(f in line for f in fragments):
            return True, 1.0
        cov = sum(1 for f in core if f in line) / len(core)
        # Cross-line coverage: a core fragment appearing anywhere in the file also counts
        # as partial evidence (used for the suspended judgment)
        best_cov = max(best_cov, cov)
    any_cov = sum(1 for f in core if f in content) / len(core)
    return False, max(best_cov, any_cov)


def is_ui_guard(source: str) -> bool:
    """Decide whether a guard captures UI (the S2 scope gate; calibrated on the real repo
    260905): the source contains DOM/page capture markers.
    Non-UI guards (pure logic assertions) have no copy producer to index — their strings
    are scenario self-descriptions/assertion labels, and mixing them in is pure noise
    (the lesson of the first scan's 1300+ findings); those guards only enter S1/S3."""
    return any(marker in (source or "") for marker in
               ("page.", "locator(", "getBy", "innerText", "textContent", "page(", "driver."))


def scan_guard_anchor_presence(
    guards: List[Tuple[str, str, List[str]]],
    producer_contents: Dict[str, str],
    repo_wide_producers: Optional[Dict[str, str]] = None,
) -> Tuple[List[Finding], Dict[str, Any]]:
    """guards: [(rel_path, source, producer_rels)] — producer_rels is the list of
    repo-relative producer paths this guard resolved to (state=ok); producer_contents
    holds their content. Criteria in header tiers (1)-(4). Returns (findings, meta).
    repo_wide_producers（t260910-11 校准）：tier-3（守卫定位的生产方内双缺）先做全仓
    在场回退——锚字面/片段在仓内**任何**生产方文件在场 → 措辞未漂移，只是守卫引用的
    生产方定位不完整 → 记 meta 不出发现（真实报告满屏 high 的主根因即此）；全仓双缺
    才进确证/降级判定。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"guards": len(guards), "anchors_checked": 0,
                            "anchors_skipped_no_producer": 0, "guards_no_producer": [],
                            "guards_non_ui": 0, "anchors_present_repo_wide": 0}
    for rel, source, producer_rels in guards:
        if not is_ui_guard(source):
            meta["guards_non_ui"] += 1
            continue
        producer_here = {p: c for p, c in producer_contents.items() if p in producer_rels}
        if not producer_here:
            meta["guards_no_producer"].append(rel)
            continue
        ext = Path(rel).suffix
        # t260910-11 校准：文案锚只从断言行取字面（守卫自述散文行豁免）——首期 147 条
        # high 的主体是 throw/日志行里的失败说明散文被当成了文案锚
        literals = [lit for line in _anchor_candidate_lines(source)
                    for lit in _line_string_literals(line)]
        for lit in literals:
            if not is_anchor_literal(lit):
                continue
            meta["anchors_checked"] += 1
            frags = anchor_fragments(lit)
            hit_files = [p for p, c in producer_here.items() if _producer_hit(c, lit, frags)[0]]
            if hit_files:
                continue  # tiers 1/2: present, zero findings
            cov = max((_producer_hit(c, lit, frags)[1] for c in producer_here.values()), default=0.0)
            assembled = is_assembled_or_dom_anchor(lit)
            if cov <= 0.0 and repo_wide_producers:
                elsewhere = any(_producer_hit(c, lit, frags)[0]
                                for c in repo_wide_producers.values())
                if elsewhere:
                    meta["anchors_present_repo_wide"] += 1
                    continue  # 措辞在仓内在场：定位不完整 ≠ 漂移，不出发现
            if cov <= 0.0 and assembled:
                # 校准降级（t260910-11）：拼装/DOM 形态锚核心片段全缺也只 med——拼装顺序
                # 变化 ≠ 文案漂移，静态面无法确证，交人审（校准红线：不得报 high）
                findings.append(Finding(
                    scan="guard-anchor", severity="med",
                    subject="%s ⇢ %s" % (rel, lit[:40]),
                    evidence="拼装/DOM 形态锚（含运行时拼接或选择器痕迹）核心片段全缺——"
                             "可能拼装顺序变化而非文案漂移，降级 med 交人审（生产方：%s）"
                             % "、".join(sorted(producer_here)),
                    suggestion="人审比对锚与生产方现措辞；确认漂移则修守卫（dev-lane 工单）"))
            elif cov <= 0.0:
                # tier 3 confirmed drift: the producer context is in place, both the
                # literal and the combined fragments are missing, and every core fragment
                # is missing
                findings.append(Finding(
                    scan="guard-anchor", severity="high",
                    subject="%s ⇢ %s" % (rel, lit[:40]),
                    evidence="守卫字面锚在生产方源码字面与组合片段双缺（核心片段覆盖率 0；"
                             "生产方已定位：%s）——守卫锚 vs 生产方措辞漂移（KI-051 形态）"
                             % "、".join(sorted(producer_here)),
                    suggestion="改锚措辞兼容生产方现文案（锚语义不锚字面），或确认实现回退——修一律走 dev-lane 工单"))
            else:
                # tier 4 similarity suspended: some fragments are present — hand to human
                # review, judging neither green nor red
                findings.append(Finding(
                    scan="guard-anchor", severity="med",
                    subject="%s ⇢ %s" % (rel, lit[:40]),
                    evidence="守卫字面锚组合片段未命中，但核心片段覆盖率 %.0f%%（相似度悬置）——"
                             "静态面无法确证，交人审" % (cov * 100),
                    suggestion="人审比对守卫锚与生产方现措辞；确认漂移则修守卫或修实现（dev-lane 工单）"))
    return findings, meta


# Repo-top directory vocabulary: only path references starting with one of these are
# judged "in-repo absolute path" when missing = high;
# other path misses (~/ credentials, host-relative context) have unclear context → med,
# handed to human review (no wrongful conviction).
REPO_TOP_DIRS = ("integration", "server", "docs", "app", "bin", "notes", "tools")
# Environment-dependent path segments: a reference containing any of these is always
# external (installation-state related, not code drift).
_ENV_PATH_SEGMENTS = ("node_modules", ".venv", "out/", "/out", "__pycache__")


def scan_stale_assertions(
    guards: List[Tuple[str, str, List[str], Dict[str, str]]],
    line_count: Callable[[str], Optional[int]],
) -> Tuple[List[Finding], Dict[str, Any]]:
    """S3 stale assertions. Reference resolution already happened in the outer layer (the
    fourth tuple element maps ref → state):
      missing: a path reference starting with a repo-top directory, or a bare code name
               with no hit anywhere in the repo → high (moved/deleted);
               a path miss in any other context → med, handed to human review;
      ok with a referenced line number beyond the target's line count → high (line number
               out of range);
      external (environment paths / bare names in config docs etc.) → not judged, noted
               in meta to prevent false positives."""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"refs_checked": 0, "refs_external": 0,
                            "refs_fixture_or_doc": 0}
    scratch_re = re.compile(
        r"(^x_|fake|dummy|fixture|sample|_any\b|tmp_|example"
        r"|^(x|bg|other|staged|missing|test|tmp|demo|example|foo|bar|baz)([.\-_]|$))",
        re.IGNORECASE)
    for rel, source, _resolved, ref_states in guards:
        fixture_span = _fixture_write_span(source)
        for line_no, line in enumerate(source.splitlines(), start=1):
            if line_no in fixture_span:
                continue  # 夹具造文件语句的实参行：路径是写进夹具树的数据，非真仓断言
            for ref in _path_refs(line):
                if is_self_ref(ref, rel):
                    continue  # self-reference (including sc_ prefix variants)
                if any(seg in ref for seg in _ENV_PATH_SEGMENTS):
                    meta["refs_external"] += 1
                    continue
                meta["refs_checked"] += 1
                state, target = ref_states.get(ref, ("external", None))
                if state == "external":
                    meta["refs_external"] += 1
                    continue
                if state == "missing":
                    # 语境豁免（t260910-11 校准）：①注释/文档散文行（* # // > 开头）——
                    # 交叉引用不是路径断言；②fixture/纯函数测试数据行（check/assert 调用、
                    # == 断言、repo/workdir 等夹具变量）——路径是喂给夹具的数据，本就不该
                    # 在真仓存在；③scratch 命名（x_fake.py / *_any 等）——自证非生产资产。
                    # 三类只计数不出发现（首期 stale-ref 误报主体）。
                    stripped = line.strip()
                    if (stripped.startswith(("*", "#", "//", ">", "|"))   # 注释/文档散文（含 //；修复点：前版 [:1] 只比单字符永远吃不到 //）
                            or re.search(r"\b(check|assert|expect|record|ok|log|print)\w*\(", line)
                            or re.search(r"(console\.|ENV_FAIL|FAIL_REASON)", line)
                            or "==" in line
                            or re.search(r"[\"']\s+(not\s+)?in\s+", line)   # 成员测试（消息/集合数据，非路径断言）
                            or re.search(r" is (True|False)\b", line)
                            or re.search(r"(repo|workdir|tmp_path|tmp_repo|fixture|sandbox)", line)
                            or re.search(r":\s*[\"']", line)          # path→content 映射（夹具文件表）
                            or re.search(r"\[[^\]]*[\"'][^\]]*\]", line)  # 字符串列表实参（write_set/refs 数据）
                            or re.search(r"\.write\(|write_text\(|mkdir|makedirs", line)  # 夹具造文件调用
                            or re.match(r"[A-Z_]{2,}\s*=\s*[\"']", stripped)  # 夹具常量表（UI_PROD = "…"）
                            or scratch_re.search(Path(ref).name)):
                        meta["refs_fixture_or_doc"] += 1
                        continue
                    repo_anchored = ref.split("/")[0] in REPO_TOP_DIRS
                    findings.append(Finding(
                        scan="stale-ref",
                        severity="high" if repo_anchored or "/" not in ref else "med",
                        subject="%s:%d ⇢ %s" % (rel, line_no, target or ref),
                        evidence=("守卫引用的代码资产不存在（按守卫目录/仓根/全仓名解析均未命中）——断言对象已挪/已删"
                                  if repo_anchored or "/" not in ref else
                                  "守卫引用路径不存在且非仓顶目录语境（宿主相对/外部路径）——语境不明交人审"),
                        suggestion="更新引用路径；若对象已退役，删除断言或改指新对象（dev-lane 工单）"))
                    continue
                total = line_count(target) if target else None
                if total is None:
                    continue
                for m in _LINE_REF_RE.finditer(line):
                    ln = int(m.group(1))
                    if ln > total:
                        findings.append(Finding(
                            scan="stale-ref", severity="high",
                            subject="%s:%d ⇢ %s L%d" % (rel, line_no, target, ln),
                            evidence="引用行号越界：L%d > 文件实际行数 %d——行号断言已过时" % (ln, total),
                            suggestion="改用锚语义断言（不锚行号），或更新行号（dev-lane 工单）"))
    return findings, meta


def _path_refs(source: str) -> set:
    """Path reference extraction (t260910-11 calibrated): only **path-shaped** refs —
    a ref must carry a path separator (relative `./ ../ dir/…` or repo-root-relative).
    Bare file names (`index.mjs`) are module-specifier shapes (import/require forms),
    not file-path assertions — emitting them was the main S3 false-positive source
    (a module name is not a path that must exist). Dot-prefixed directory names
    (.dsh/.git etc.) and HOME-relative (`~/`) contexts stay excluded as before."""
    out = set()
    for m in _PATH_RE.finditer(source or ""):
        if m.start() > 0 and source[m.start() - 1] in (".", "~"):
            continue
        ref = m.group(0)
        if "/" not in ref:
            continue  # 模块加载形态（裸名）：不是路径断言，不判 stale
        out.add(ref)
    return out


def build_ref_resolver(repo_root: Path):
    """Three-state reference resolver (shared by S2 producer locating and S3 existence;
    the source of truth for the criteria):
      (1) ./ ../ relative references → the guard file's directory (leaving the repo =
          external);
      (2) directory-carrying references (containing /) → repo-root relative (absent =
          missing);
      (3) bare file names → repo-wide search by name (code extensions; a hit = ok, taking
          the stable first order; zero hits: a code extension = missing, config/docs =
          external — these usually point outside the repo, so no false positive).
    Returns resolve(ref, guard_rel) -> (state, repo_rel_path|None), state ∈
    ok|missing|external."""
    root = repo_root.resolve()
    basename_index: Dict[str, List[str]] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in _PRODUCER_EXTS:
            continue
        if EXCLUDED_DIRS.intersection(p.parts):
            continue
        basename_index.setdefault(p.name, []).append(p.relative_to(root).as_posix())

    def resolve(ref: str, guard_rel: str) -> Tuple[str, Optional[str]]:
        if ref.startswith(("./", "../")):
            base = (root / guard_rel).parent
            target = (base / ref).resolve()
            if target.is_file() and target.is_relative_to(root):
                return "ok", target.relative_to(root).as_posix()
            return "external", None
        if "/" in ref:
            # `..` 段归一化（server/../server/... 形态）：守卫里常见的「保险前缀」写法
            # 不归一化会假性 missing（t260910-11 校准）
            parts = []
            for seg in ref.split("/"):
                if seg == ".." and parts:
                    parts.pop()
                    continue
                parts.append(seg)
            ref = "/".join(parts)
            if (root / ref).is_file():
                return "ok", ref
            # Naming-convention variant fallback: -/_ swapped, sc_ prefix toggled (two
            # generations of scenario file naming coexist)
            d, b = ref.rsplit("/", 1)
            variants = {b, "sc_" + b, b[3:] if b.startswith("sc_") else b,
                        b.replace("-", "_"), "sc_" + b.replace("-", "_")}
            for alt in sorted(variants):
                if alt and (root / d / alt).is_file():
                    return "ok", "%s/%s" % (d, alt)
            return "missing", ref
        name = Path(ref).name
        # Bare-name variant resolution: sc_ prefix toggled, -/_ swapped (scenario files
        # are often referenced by their old name)
        bare_variants = {name, "sc_" + name, name[3:] if name.startswith("sc_") else name,
                         name.replace("-", "_"), "sc_" + name.replace("-", "_")}
        for cand in sorted(bare_variants):
            hits = basename_index.get(cand, [])
            if hits:
                return "ok", hits[0]
        # t260910-11 校准：裸名（无路径分隔符）不再判 missing（模块名不是必须存在的
        # 路径）——语境不明一律 external，只记 meta 不出发现
        return "external", None

    return resolve


def is_self_ref(ref: str, guard_rel: str) -> bool:
    """Guard self-reference check (including sc_ prefix variants: a guard's header often
    refers to itself without the sc_ prefix);
    also filters wildcard fragments (e.g. `*.d.ts` truncated to `d.ts` — a stem of ≤1
    character)."""
    stem = Path(ref).stem
    if len(stem) <= 1:
        return True
    guard_name = Path(guard_rel).name
    ref_name = Path(ref).name
    return ref_name in (guard_name, "sc_" + guard_name, guard_name[3:] if guard_name.startswith("sc_") else "")


# ========================================================================================
# Summary entry point (consumed by the activity; pure read)
# ========================================================================================

PRODUCER_ROOTS = ("server", "app", "bin", "docs")


def collect_guards(repo_root: Path) -> List[Tuple[str, str]]:
    base = repo_root / "integration"
    out: List[Tuple[str, str]] = []
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("sc_*")):
        if p.suffix not in GUARD_EXTS or not p.is_file():
            continue
        try:
            out.append((p.relative_to(repo_root).as_posix(), p.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as e:
            # Unreadable (permissions/encoding corruption) = an observable degradation:
            # noted in meta, neither silent nor fatal
            out.append((p.relative_to(repo_root).as_posix() + " (unreadable: %s)" % e, ""))
    return out


def collect_producers(repo_root: Path, extra_refs: set, producer_roots: Tuple[str, ...] = PRODUCER_ROOTS) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for root in producer_roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix not in _PRODUCER_EXTS or not p.is_file():
                continue
            if EXCLUDED_DIRS.intersection(p.parts):
                continue
            rel = p.relative_to(repo_root).as_posix()
            try:
                out[rel] = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    for ref in sorted(extra_refs):
        p = repo_root / ref
        if p.is_file() and ref not in out:
            try:
                out[ref] = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
    return out


def run_test_face_scan(
    repo_root: Path,
    scenarios_path: Optional[Path] = None,
    producer_roots: Optional[Tuple[str, ...]] = None,
) -> Dict[str, Any]:
    """Main entry point of the test-face scan (the activity is a thin shell around it).
    Returns the result shape of the single-line JSON output."""
    repo_root = Path(repo_root)
    if not repo_root.is_dir():
        raise ScanError("仓库根不存在：%s" % repo_root)
    sp = Path(scenarios_path) if scenarios_path else repo_root / "integration" / "run_scenarios.py"
    if not sp.is_file():
        raise ScanError("场景清单缺位：%s" % sp)
    entries, problems = parse_scenarios(sp)
    findings: List[Finding] = []
    for p in problems:
        findings.append(Finding(
            scan="duplicate", severity="med", subject="scenarios-manifest:%s" % p[:60],
            evidence="SCENARIOS 清单条目畸形（ast 只取字面量，不执行）：%s" % p,
            suggestion="修 SCENARIOS 三元组结构（L4 纪律）"))
    dup_findings, dup_meta = scan_duplicate_scenarios(entries)
    findings.extend(dup_findings)
    guards = collect_guards(repo_root)
    parsed_guards: List[Tuple[str, str]] = []
    bad_guards: List[str] = []
    for rel, source in guards:
        if "(unreadable" in rel:
            bad_guards.append(rel)
            continue
        if rel.endswith(".py"):
            try:
                ast.parse(source)
            except (SyntaxError, ValueError) as e:  # ValueError = corrupted source such as embedded NUL bytes
                bad_guards.append("%s (unparseable: %s)" % (rel, e))
                continue
        parsed_guards.append((rel, source))
    # Three-state reference resolution (one source of truth for the criteria, shared by
    # S2 producer locating and S3 existence)
    resolver = build_ref_resolver(repo_root)
    guard_states: List[Tuple[str, str, List[str], Dict[str, Tuple[str, Optional[str]]]]] = []
    producers_needed: set = set()
    for rel, source in parsed_guards:
        refs = _path_refs(source)
        states: Dict[str, Tuple[str, Optional[str]]] = {}
        producer_rels: List[str] = []
        for ref in sorted(refs):
            if is_self_ref(ref, rel):
                continue
            state, target = resolver(ref, rel)
            states[ref] = (state, target)
            if state == "ok" and target:
                producer_rels.append(target)
                producers_needed.add(target)
        guard_states.append((rel, source, producer_rels, states))
    producers = collect_producers(repo_root, producers_needed, producer_roots or PRODUCER_ROOTS)
    repo_wide = collect_producers(repo_root, set(), producer_roots or PRODUCER_ROOTS)
    anchor_findings, anchor_meta = scan_guard_anchor_presence(
        [(rel, source, producer_rels) for rel, source, producer_rels, _ in guard_states], producers,
        repo_wide_producers=repo_wide)
    findings.extend(anchor_findings)

    def _lines(ref: str) -> Optional[int]:
        p = repo_root / ref
        if not p.is_file():
            return None
        try:
            return len(p.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            return None

    stale_findings, stale_meta = scan_stale_assertions(guard_states, _lines)
    findings.extend(stale_findings)
    summary = summarize(findings)
    ordered = [f.to_dict() for f in summary["ordered"]]
    counts = summary["counts"]
    return {
        "face": "test",
        "findings": ordered,
        "summary": counts,
        "heartbeat": len(findings) == 0,
        "meta": {
            "scenarios": len(entries),
            "duplicate_compared": dup_meta.get("compared", 0),
            "duplicate_suppressed": dup_meta.get("duplicate_suppressed", 0),
            "guards": anchor_meta.get("guards", 0),
            "guards_unparseable": bad_guards,
            "anchors_checked": anchor_meta.get("anchors_checked", 0),
            "anchors_skipped_no_producer_ctx": len(anchor_meta.get("guards_no_producer", [])),
            "guards_non_ui": anchor_meta.get("guards_non_ui", 0),
            "stale_refs_checked": stale_meta.get("refs_checked", 0),
            "stale_refs_external": stale_meta.get("refs_external", 0),
            "red_line": "Inspection only produces reports and ticket-opening suggestions; it never changes code.",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="测试面扫描器（inspection 票①）")
    ap.add_argument("--repo-root", default=".", help="仓库根（缺省当前目录）")
    ap.add_argument("--scenarios-path", default=None, help="run_scenarios.py 路径（缺省 <repo>/integration/run_scenarios.py）")
    args = ap.parse_args()
    try:
        result = run_test_face_scan(Path(args.repo_root), Path(args.scenarios_path) if args.scenarios_path else None)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
    except ScanError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
        sys.exit(1)


if __name__ == "__main__":
    main()

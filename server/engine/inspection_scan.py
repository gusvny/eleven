#!/usr/bin/env python3
"""inspection_scan —— 测试面扫描器（inspection epic 票①第一实例，t260905-03）。

红线：巡检只出报告与开票建议，绝不直接改码——本模块是纯读静态面，零写操作。

四项扫描（severity 判据按 review_plan 附条件意见 C1 定死）：
  S1 duplicate   重复场景检测：SCENARIOS 的 name+intent 分词重叠度（Jaccard）
                 ≥ DUP_JACCARD → med。
  S2 guard-anchor 守卫锚→生产方在场性核验（KI-051 常驻化，独立扫描项）：提取守卫
                 场景源码断言的字面锚，反向索引生产方源码的**措辞在场性**（不是
                 文件/函数存在性）。模板感知分层：
                   ① 字面精确命中 → 在场；
                   ② 组合片段：锚拆片段，任一生产方文件单行内全片段命中 → 在场；
                   ③ 核心片段（长度≥3）覆盖率=0（字面与组合片段双缺，且生产方
                     上下文已定位到）→ **high（确证漂移）**；
                   ④ 核心片段覆盖率>0 但组合失败（相似度悬置）→ med 交人审。
                 生产方上下文定位不到（守卫源码无现存文件引用）→ 锚跳过记 meta，
                 不出发现——防「无法定位=误报满屏」。
                 KI-051 判定话术：本项是**静态面**，不依赖场景真跑，天然绕开
                 env_fail 捂真红（KI-051 被环境红捂数日的根因）——这正是它存在的
                 理由。真实 capture.mjs 案（新旧文案共享前缀「隔离台」）落④ med
                 同样必报；夹具复刻纯重写形态走③ high 支路（见测试与场景）。
  S3 stale-ref   过时断言：守卫引用的文件路径不存在（已挪/已删）→ high；
                 引用的行号超出目标文件行数 → high（行号越界）。
  汇总          零发现=heartbeat true（全绿期=零发现票作心跳证明）。

输入面（全部可注入，供单测桩复现；畸形输入不崩，逐项降级记 meta/finding）：
  - 场景清单：integration/run_scenarios.py 的 SCENARIOS——用 ast 只取字面量，
    不 import 执行器（零副作用）；畸形元组 → S1 级 med finding 点名。
  - 守卫源码：integration/**/sc_*.py|.mjs|.ts|.tsx|.js（凡 sc_ 必登记的既有纪律）。
  - 生产方源码：PRODUCER_ROOTS 下文本源文件 + 守卫源码里引用到的现存文件。

CLI（运维/场景通道）：stdout 一律单行 JSON {ok, result|error}（与 client.py 同契约）。
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
DUP_JACCARD = 0.55          # S1 阈值（真仓标定记录见票报告；调阈值=改行为，须带用例）
_WINDOW_ALL = 1.0           # 组合片段：单行内全片段命中
STOPWORDS = {"the", "a", "an", "of", "for", "and", "with", "by", "to", "in", "on", "vs", "at", "is", "be"}
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PATH_RE = re.compile(r"(?:\.\./|\./)?[A-Za-z0-9_][A-Za-z0-9_\-./]*\.(?:py|mjs|ts|tsx|js|sh|md|ya?ml|json)\b")
_LINE_REF_RE = re.compile(r"\bL(\d{1,5})\b")
_PRODUCER_EXTS = {".py", ".mjs", ".ts", ".tsx", ".js", ".md", ".sh", ".yaml", ".yml", ".json"}
GUARD_EXTS = {".py", ".mjs", ".ts", ".tsx", ".js"}


class ScanError(Exception):
    """扫描无法开始（仓库根/清单缺位）——fail-closed 点名，不静默返回空。"""


@dataclass
class Finding:
    """一条发现（发现清单落票面的最小单元：分严重度带证据）。"""

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
    """确定性 id（sha1 短摘要）——同一发现跨期稳定，供修复票引用与去重。"""
    return "%s:%s" % (scan, hashlib.sha1(("%s|%s" % (scan, subject)).encode("utf-8")).hexdigest()[:10])


def summarize(findings: List[Finding]) -> Dict[str, Any]:
    counts = {"high": 0, "med": 0, "low": 0}
    by_id: Dict[str, Finding] = {}
    for f in findings:                       # 同一发现（同 id）跨锚点重复出现只记一条
        by_id.setdefault(finding_id(f.scan, f.subject), f)
    deduped = list(by_id.values())
    for f in deduped:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    ordered = sorted(deduped, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.scan, f.subject))
    return {"counts": counts, "total": len(deduped), "ordered": ordered}


# ========================================================================================
# S1 duplicate —— 重复场景检测（锚点/断言重叠度）
# ========================================================================================

def tokenize(text: str) -> set:
    """确定性分词：ascii 词 + CJK 二元组；停用词剔除。"""
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


def scan_duplicate_scenarios(entries: List[Dict[str, Any]]) -> Tuple[List[Finding], Dict[str, Any]]:
    """entries: [{name, intent, cmd}]（畸形入口由 parse_scenarios 保证形状后仍可带错）。
    返回 (findings, meta)。O(n²) 两两比对，n≤百级。"""
    meta: Dict[str, Any] = {"compared": 0}
    findings: List[Finding] = []
    norm = []
    for e in entries:
        text = "%s %s" % (e.get("name", ""), e.get("intent", ""))
        norm.append((str(e.get("name", "")), tokenize(text)))
    for i in range(len(norm)):
        for j in range(i + 1, len(norm)):
            name_a, tok_a = norm[i]
            name_b, tok_b = norm[j]
            meta["compared"] += 1
            score = jaccard(tok_a, tok_b)
            if score >= DUP_JACCARD:
                findings.append(Finding(
                    scan="duplicate", severity="med",
                    subject="dup:%s × %s" % (name_a, name_b),
                    evidence="intent/name 词重叠 Jaccard=%.2f（阈值 %.2f），共享词 %d 个"
                             % (score, DUP_JACCARD, len(tok_a & tok_b)),
                    suggestion="两场景意图近重——合并或显式分化意图描述（intent 级重复禁止是清单纪律）"))
    return findings, meta


# ========================================================================================
# 场景清单解析（ast 只取字面量，不 import 执行器）
# ========================================================================================

def parse_scenarios(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    """从 run_scenarios.py 抽 SCENARIOS 三元组/四元组；畸形项进 problems（不崩）。"""
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
            parts = [ast.literal_eval(x) for x in el.elts]  # 非元组/含非常量 → ValueError
            if not isinstance(el, ast.Tuple):
                raise ValueError("条目不是元组")
            if len(parts) < 3:
                raise ValueError("字段数 %d<3" % len(parts))
            entries.append({"name": str(parts[0]), "intent": str(parts[1]),
                            "cmd": " ".join(str(p) for p in parts[2:])})
        except Exception as e:  # noqa: BLE001——畸形清单条目逐条降级，不让单项毁全扫
            problems.append("SCENARIOS[%d] 畸形（%s）" % (idx, e))
    return entries, problems


# ========================================================================================
# 守卫锚提取 + S2/S3
# ========================================================================================

def extract_string_literals(source: str, ext: str) -> List[str]:
    """从守卫源码抽字符串字面量：.py 走 ast（语法错→ScanError 由上层逐文件降级）；
    其余扩展名走引号正则（mjs/ts/js 的模板串/单双引号）。"""
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
    """守卫断言的候选字面锚（判据收紧防误报满屏，真仓 260905 标定）：
    够长、含 ≥2 个 CJK 字符（UI 文案形态，本仓锚皆中文）；
    排除模板插值（${…}=守卫自身报错文案）、多行模板串、选择器/路径/URL 形态。"""
    s = s.strip()
    if len(s) < 6 or "\n" in s:
        return False
    if "${" in s or "://" in s or s.startswith(("./", "/", "#", ".")):
        return False
    if len(CJK_RE.findall(s)) < 2:
        return False
    if re.match(r"^[\w\-./: ]+$", s):   # 纯 ascii 选择器/路径带空格形态
        return False
    if re.search(r"%[sdrif]", s):        # 断言/日志格式串（守卫自身文案，非生产方锚）
        return False
    if re.search(r"\[\w+[=~^|]?", s):    # 属性选择器（DOM 定位器，非文案锚）
        return False
    return True


def anchor_fragments(anchor: str) -> List[str]:
    """锚 → 片段（组合片段策略）：按非 CJK/字母数字切分，保留长度≥2 的段。"""
    parts = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", anchor)
    return [p for p in parts if len(p) >= 2]


def _producer_hit(content: str, anchor: str, fragments: List[str]) -> Tuple[bool, float]:
    """在单个生产方文件内容里判定锚在场性：字面命中 → (True, 1.0)；
    组合片段单行全中 → (True, 1.0)；否则返回 (False, 核心片段覆盖率)。"""
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
        # 跨行覆盖率：核心片段任意出现在文件任何位置也算部分证据（悬置判定用）
        best_cov = max(best_cov, cov)
    any_cov = sum(1 for f in core if f in content) / len(core)
    return False, max(best_cov, any_cov)


def is_ui_guard(source: str) -> bool:
    """UI 捕获型守卫判定（S2 范围闸，真仓标定 260905）：源码含 DOM/页面捕获标记。
    非 UI 守卫（纯逻辑断言）没有文案生产方可索引——其字符串是场景自述/断言标签，
    混入即噪声（首扫 1300+ 条的教训）；这些守卫只进 S1/S3。"""
    return any(marker in (source or "") for marker in
               ("page.", "locator(", "getBy", "innerText", "textContent", "page(", "driver."))


def scan_guard_anchor_presence(
    guards: List[Tuple[str, str, List[str]]],
    producer_contents: Dict[str, str],
) -> Tuple[List[Finding], Dict[str, Any]]:
    """guards: [(rel_path, source, producer_rels)]——producer_rels=该守卫解析命中（state=ok）
    的生产方仓相对路径清单；producer_contents 为其内容。判据见头注 ①~④。
    返回 (findings, meta)。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"guards": len(guards), "anchors_checked": 0,
                            "anchors_skipped_no_producer": 0, "guards_no_producer": [],
                            "guards_non_ui": 0}
    for rel, source, producer_rels in guards:
        if not is_ui_guard(source):
            meta["guards_non_ui"] += 1
            continue
        producer_here = {p: c for p, c in producer_contents.items() if p in producer_rels}
        if not producer_here:
            meta["guards_no_producer"].append(rel)
            continue
        ext = Path(rel).suffix
        literals = extract_string_literals(source, ext)
        for lit in literals:
            if not is_anchor_literal(lit):
                continue
            meta["anchors_checked"] += 1
            frags = anchor_fragments(lit)
            hit_files = [p for p, c in producer_here.items() if _producer_hit(c, lit, frags)[0]]
            if hit_files:
                continue  # ①② 在场，零发现
            cov = max((_producer_hit(c, lit, frags)[1] for c in producer_here.values()), default=0.0)
            if cov <= 0.0:
                # ③ 确证漂移：生产方上下文在位、字面与组合片段双缺、核心片段全缺
                findings.append(Finding(
                    scan="guard-anchor", severity="high",
                    subject="%s ⇢ %s" % (rel, lit[:40]),
                    evidence="守卫字面锚在生产方源码字面与组合片段双缺（核心片段覆盖率 0；"
                             "生产方已定位：%s）——守卫锚 vs 生产方措辞漂移（KI-051 形态）"
                             % "、".join(sorted(producer_here)),
                    suggestion="改锚措辞兼容生产方现文案（锚语义不锚字面），或确认实现回退——修一律走 dev-lane 工单"))
            else:
                # ④ 相似度悬置：部分片段在场——交人审，不判绿不判红
                findings.append(Finding(
                    scan="guard-anchor", severity="med",
                    subject="%s ⇢ %s" % (rel, lit[:40]),
                    evidence="守卫字面锚组合片段未命中，但核心片段覆盖率 %.0f%%（相似度悬置）——"
                             "静态面无法确证，交人审" % (cov * 100),
                    suggestion="人审比对守卫锚与生产方现措辞；确认漂移则修守卫或修实现（dev-lane 工单）"))
    return findings, meta


# 仓顶目录词表：带路径引用以此开头才按「仓内绝对路径」判定缺失=high；
# 其余带路径缺失（~/ 凭据、宿主相对语境）语境不明 → med 交人审（不冤判）。
REPO_TOP_DIRS = ("integration", "server", "docs", "app", "bin", "notes", "tools")
# 环境依赖路径段：引用含这些段一律 external（装态相关，不是代码漂移）。
_ENV_PATH_SEGMENTS = ("node_modules", ".venv", "out/", "/out", "__pycache__")


def scan_stale_assertions(
    guards: List[Tuple[str, str, List[str], Dict[str, str]]],
    line_count: Callable[[str], Optional[int]],
) -> Tuple[List[Finding], Dict[str, Any]]:
    """S3 过时断言。引用解析已在外层完成（guards 第四元 ref→状态映射）：
      missing：仓顶目录开头的带路径引用或裸代码名全仓无命中 → high（已挪/已删）；
               其余语境的带路径缺失 → med 交人审；
      ok 且引用行号超出目标行数 → high（行号越界）；
      external（环境路径/配置文档裸名等）→ 不判，记 meta 防误报。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"refs_checked": 0, "refs_external": 0}
    for rel, source, _resolved, ref_states in guards:
        for line_no, line in enumerate(source.splitlines(), start=1):
            for ref in _path_refs(line):
                if is_self_ref(ref, rel):
                    continue  # 自引用（含 sc_ 前缀变体）
                if any(seg in ref for seg in _ENV_PATH_SEGMENTS):
                    meta["refs_external"] += 1
                    continue
                meta["refs_checked"] += 1
                state, target = ref_states.get(ref, ("external", None))
                if state == "external":
                    meta["refs_external"] += 1
                    continue
                if state == "missing":
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
    """路径引用提取。跳过紧邻前缀为 `.` 或 `~` 的命中：前者是点前缀目录名
    （.dsh/.git 等，正则表达不了），后者是 HOME 相对语境——都不是仓内路径引用。"""
    out = set()
    for m in _PATH_RE.finditer(source or ""):
        if m.start() > 0 and source[m.start() - 1] in (".", "~"):
            continue
        out.add(m.group(0))
    return out


def build_ref_resolver(repo_root: Path):
    """引用三态解析器（S2 生产方定位 / S3 存在性共用；判据真源）：
      ① ./ ../ 相对引用 → 守卫文件目录（出仓=external）；
      ② 带目录引用（含 /）→ 仓根相对（不在=missing）；
      ③ 裸文件名 → 全仓按名检索（代码扩展名；命中=ok 取稳定首序；
         零命中：代码扩展名=missing，配置/文档=external——常指仓外环境不误报）。
    返回 resolve(ref, guard_rel) -> (state, repo_rel_path|None)，state ∈ ok|missing|external。"""
    root = repo_root.resolve()
    basename_index: Dict[str, List[str]] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in _PRODUCER_EXTS:
            continue
        if any(seg in ("node_modules", ".git", "out", ".venv", "data") for seg in p.parts):
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
            if (root / ref).is_file():
                return "ok", ref
            # 命名法变体回退：-/ _互换、sc_ 前缀互变（场景文件名两代惯例并存）
            d, b = ref.rsplit("/", 1)
            variants = {b, "sc_" + b, b[3:] if b.startswith("sc_") else b,
                        b.replace("-", "_"), "sc_" + b.replace("-", "_")}
            for alt in sorted(variants):
                if alt and (root / d / alt).is_file():
                    return "ok", "%s/%s" % (d, alt)
            return "missing", ref
        name = Path(ref).name
        # 裸名变体解析：sc_ 前缀互变、-/ _互换（场景文件常以旧名被引用）
        bare_variants = {name, "sc_" + name, name[3:] if name.startswith("sc_") else name,
                         name.replace("-", "_"), "sc_" + name.replace("-", "_")}
        for cand in sorted(bare_variants):
            hits = basename_index.get(cand, [])
            if hits:
                return "ok", hits[0]
        if ref.rsplit(".", 1)[-1] in ("py", "mjs", "ts", "tsx", "js"):
            return "missing", ref
        return "external", None

    return resolve


def is_self_ref(ref: str, guard_rel: str) -> bool:
    """守卫自引用判定（含 sc_ 前缀变体：守卫头注常以不带 sc_ 的名指自己）；
    另滤通配碎片（如 `*.d.ts` 被截成 `d.ts`——词干≤1 字符）。"""
    stem = Path(ref).stem
    if len(stem) <= 1:
        return True
    guard_name = Path(guard_rel).name
    ref_name = Path(ref).name
    return ref_name in (guard_name, "sc_" + guard_name, guard_name[3:] if guard_name.startswith("sc_") else "")


# ========================================================================================
# 汇总入口（activity 消费；纯读）
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
            # 读不了（权限/编码毁损）=可观测降级：记 meta，不静默也不崩
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
            if "node_modules" in p.parts or "/out/" in p.as_posix():
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
    """测试面扫描主入口（activity 薄壳包它）。返回单行 JSON 的 result 形态。"""
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
            except (SyntaxError, ValueError) as e:  # ValueError=含空字节等毁损源
                bad_guards.append("%s (unparseable: %s)" % (rel, e))
                continue
        parsed_guards.append((rel, source))
    # 引用三态解析（S2 生产方定位 / S3 存在性共用一个判据真源）
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
    anchor_findings, anchor_meta = scan_guard_anchor_presence(
        [(rel, source, producer_rels) for rel, source, producer_rels, _ in guard_states], producers)
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
            "guards": anchor_meta.get("guards", 0),
            "guards_unparseable": bad_guards,
            "anchors_checked": anchor_meta.get("anchors_checked", 0),
            "anchors_skipped_no_producer_ctx": len(anchor_meta.get("guards_no_producer", [])),
            "guards_non_ui": anchor_meta.get("guards_non_ui", 0),
            "stale_refs_checked": stale_meta.get("refs_checked", 0),
            "stale_refs_external": stale_meta.get("refs_external", 0),
            "red_line": "巡检只出报告与开票建议，绝不直接改码",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="测试面扫描器（inspection 票①）")
    ap.add_argument("--repo-root", default=".", help="仓库根（缺省当前目录）")
    ap.add_argument("--scenarios-path", default=None, help="run_scenarios.py 路径（缺省 <repo>/integration/run_scenarios.py）")
    args = ap.parse_args()
    try:
        result = run_test_face_scan(Path(args.repo_root), Path(args.scenarios_path) if args.scenarios_path else None)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except ScanError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()

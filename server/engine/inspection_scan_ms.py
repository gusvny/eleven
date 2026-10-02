#!/usr/bin/env python3
"""inspection_scan_ms — the mechanism-face and simplify-face scanners (inspection epic
ticket 2, t260910-09).

------------------------------------------------------------------------
【退役留档（t260916-22，宿主令「不需要这个静态扫描，我们巡检要用 agent 来做」）】
本模块已从生产路径摘除：InspectionPeriodicWorkflow 新票走 inspect 段
（agent 审查，见 inspection_inspect.py / agent_activities.run_inspection_inspect）。
本文件保留一版只服务老在途票 replay（Temporal 重放历史里的 run_inspection_scan
调用必须仍能匹配）——新代码禁接线本模块；S1~S4 静态发现自此不再产出，274 条旧
发现整体作废不迁移（宿主裁定④）。deadman/suite 机械面不受影响。
------------------------------------------------------------------------

Red line (inherited from ticket 1, inspection_scan.py header): inspection only produces
reports and ticket-opening suggestions, it never modifies code — this module is a
pure-read static surface with zero write operations.

Face layout:
  mechanism face — S4 dead-mechanism (dead-man generalization, the KI-049 shape: a
    mechanism with zero hits across its whole life is found mechanically instead of by
    tripping over tickets). "Whole-life zero-hit" is mechanically approximated by a
    CURRENT-TREE TRIPLE ZERO-HIT CROSS (see D2 caveat in meta and the report discipline:
    the scan never claims history it did not inspect — C2: every count carries its
    denominator, an empty set is N/A, never a fake 0/0):
      (a) scenario zero-reference: the candidate name appears in no integration/**/sc_*
          source;
      (b) log-literal zero-hit: the log/print literal strings emitted by the defining
          module appear in no other module / scenario / docs source (KI-049's 「授权扩展
          日志 0 条」, mechanized). A module emitting no log literal = the log face is
          N/A (stated as such in evidence, not folded into 0);
      (c) zero reference reachability: no ast Name/Attribute reference to the name
          anywhere in the scanned call-domain — INCLUDING the defining module itself
          (same-module use counts: the ALL_WORKFLOWS/ALL_ACTIVITIES registration lists
          live in the defining module, and an internally-used helper is genuinely
          reachable; excluding them produced a day-one false-positive flood, see the
          calibration note in the ticket report).
    triple zero → med (dead-man suspicion, handed to human review — a static surface
    cannot prove runtime death, so never high, never a wrongful kill); two-zero → low.
    Dynamic-dispatch blind spot (getattr/string dispatch) is declared, not hidden:
    `dead-man-exempt: <name>` comment lines in any scanned module file exempt a name.
  mechanism face — S5 shadow-code: a defined-but-zero-external-reference name that
    forms an old/new shape pair with a live variant (`*_v2/_new` vs base, or
    `*_old/_legacy/_backup` vs base) → med「影子路径：疑似被绕过未删」.
  simplify face — S6 patch-retirement: thin wrapper/named-layer defenses
    (`*_patch/_compat/_legacy/_shim/_fallback` names, or 补丁/防御层/兼容层 marker
    comments) → retirement judgment; superseded evidence (an old/new pair exists, or the
    name has zero external references) → med, naming-only → low. Duplicate defensive
    layer: caller and callee both invoke the same guard-ish helper
    (normalize/sanitize/validate/ensure/check…) → med on the caller.
    EVERY S6 suggestion must carry the「删了会怎样」risk note (ticket-2 hard rule):
    the mechanical blast radius (who calls it — losing the defense there) + 修复走
    dev-lane 工单引用来源巡检票；人审可毙.
  simplify face — S7 long-function / deep-nesting roll call (low, human-review signals):
    > LONG_FUNC_LINES source lines or nesting depth > MAX_NEST_DEPTH
    (If/For/While/Try/With chains), evidence carries 文件:起-止 + 实测值.

C3 (review_plan conditional item): the SIMPLIFY scan domain and the MECHANISM candidate
domain are both injectable (`scan_roots`), default ("server/engine",) — agent_activities
and friends are full of long functions by nature; defaulting to the whole server/ would
be a screen-full of noise on day one. The call-domain of S4(c)/S5 (MECHANISM_CALL_ROOTS)
is wider by design (server/ + integration/ + bin/) because "zero callers" must search
where callers would plausibly live. Unit tests pin truth tables per domain.

========================================================================================
C1 故障模式取舍清单（review_plan 条件项：票① inspection_scan.py 已处理故障模式 13 项
逐项「带过来 / 不适用+理由」，承接从评审结论变成代码内可查声明）：
  1. 仓根缺失 fail-closed ScanError            → 带过来（run_*_face_scan 首行同判）。
  2. 条目/文件不可读逐项降级不株连             → 带过来（collect 阶段 OSError/Unicode→
     降级进 meta.unreadable，单项坏不毁整扫）。
  3. 坏 ast（含 NUL 等损坏源码）降级           → 带过来（ast.parse SyntaxError/ValueError
     逐文件降级进 meta.unparseable，不崩）。
  4. stdout 单行 JSON {ok, result|error}+错 exit 1 → 带过来（CLI 契约同 client.py）。
  5. 零发现 heartbeat=true                     → 带过来（心跳票语义逐字段同票①）。
  6. 纯读零写入                                → 带过来（本模块无任何 write/open-w）。
  7. ast 只取字面量/结构、不 import 被扫对象    → 带过来且更严：本模块连场景清单都不
     读，被扫仓全部经 ast.parse 静态取结构，零执行被扫代码。
  8. 误报洪泛闸                                 → 带过来并换形态：豁免清单（dead-man-
     exempt 注释声明）+ 候选只取模块级公有定义 + 域注入（C3）收窄误报体量。
  9. 静态面不确证 → med 交人审、不判 high       → 带过来（dead-man 三重零只给 med；
     动态分发盲区如实在 meta 声明）。
 10. 阈值常量置顶、改阈值必带用例              → 带过来（LONG_FUNC_LINES/MAX_NEST_DEPTH/
     命名特征正则全置顶）。
 11. 确定性排序                                 → 带过来（summarize 继承：severity→
     scan→subject 排序；rglob 先 sorted）。
 12. 稳定 finding_id 跨期 dedupe               → 带过来（复用 finding_id，subject 只由
     稳定名与文件:行构成，不带时间戳）。
 13. meta 记录口径局限                         → 带过来（meta.caveat=「全史≈当前树交叉
     零命中近似；跨期票史累积成史；git 考古留人审票」+ 动态分发盲区声明）。
  不适用项：票①的 SCENARIOS 清单解析/guard 锚提取——输入面不同（本模块不读场景清单，
  无对应故障模式可带）。

Input surface (all injectable for unit tests; malformed input degrades item by item,
never crashes). CLI (ops channel):
    python3 inspection_scan_ms.py --face mechanism|simplify --repo-root <repo>
               [--scan-roots server/engine[,…]]
stdout: single line JSON {ok, result|error} (same contract as inspection_scan.py).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from inspection_scan import Finding, ScanError, summarize

# ---- 阈值/特征常量（置顶；改任何一个都必须带真值表用例——票① DUP_JACCARD 惯例）----
LONG_FUNC_LINES = 80          # S7 过长函数阈值（源码行）
MAX_NEST_DEPTH = 5            # S7 过深嵌套阈值（If/For/While/Try/With 链深）
DEADMAN_SEVERITY = "med"      # 三重零命中=med（静态面不确证，交人审；永不 high）
TWOSCAN_SEVERITY = "low"      # 两重零命中=low（提示面）
OLD_SUFFIXES = ("_old", "_legacy", "_backup")
NEW_SUFFIXES = ("_v2", "_new")
PATCH_NAME_RE = re.compile(r"(?:_|^)(patch|compat|legacy|shim|fallback|old)$")
GUARDISH_NAME_RE = re.compile(r"^(normalize|sanitize|validate|ensure|check|guard)\w*$", re.IGNORECASE)
PATCH_MARKER_RE = re.compile(r"补丁|防御层|兼容层")
EXEMPT_RE = re.compile(r"#\s*dead-man-exempt:\s*([A-Za-z_][A-Za-z0-9_]*)")
NEST_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.AsyncFor, ast.AsyncWith)

# 扫描域（C3：可注入，缺省与 D2 同域=server/engine——首日即洪泛的域不是缺省）
DEFAULT_SCAN_ROOTS: Tuple[str, ...] = ("server/engine",)
# S4(c)/S5 的调用点搜索域：「零调用」必须在调用者可能在的地方搜（比候选域宽是有意的）
MECHANISM_CALL_ROOTS: Tuple[str, ...] = ("server", "integration", "bin")
DOC_ROOTS: Tuple[str, ...] = ("docs",)     # 日志字面零命中也要搜文档面
_SCENARIO_DIR = "integration"
_PY_EXTS = {".py"}


def is_testish(rel: str) -> bool:
    """Test/selfcheck/fixture file judgment（候选域排除口径，真值表有单测）：
    tests|fixtures 目录段、test_* / *_test.py / selfcheck_* / conftest.py 文件名。"""
    name = Path(rel).name
    parts = rel.split("/")
    return ("tests" in parts or "fixtures" in parts or name.startswith("test_")
            or name.startswith("selfcheck_") or name == "conftest.py" or name.endswith("_test.py"))


# ========================================================================================
# Collection（不可读/坏 ast 逐项降级——故障模式 2/3）
# ========================================================================================

@dataclass
class _FileUnit:
    """One collected python file: rel path, raw text, parsed tree (or degrade notes)."""

    rel: str
    text: str = ""
    tree: Optional[ast.AST] = None


def collect_py_units(repo_root: Path, roots: Tuple[str, ...]) -> Tuple[List[_FileUnit], List[str]]:
    """Collect .py files under `roots` (repo-relative). TEST/SELFCHECK/FIXTURE files are
    excluded from the candidate domain (误报洪泛闸：test_*、selfcheck_*、tests/、fixtures/
    是断言与桩的领地，把「只被本测试文件引用」判成 dead-man 是首日即满屏的洪泛形态) —
    production-code zero-reference is what this scan judges. Unreadable files degrade
    into the returned problem list (named, never fatal); parsing is deferred to
    _parse_units so unreadable and unparseable are separately observable."""
    units: List[_FileUnit] = []
    problems: List[str] = []
    seen: set = set()
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if not p.is_file():
                continue
            rel = p.relative_to(repo_root).as_posix()
            if rel in seen or any(seg in ("node_modules", ".git", ".venv", "__pycache__", "out") for seg in p.parts):
                continue
            if is_testish(rel):
                continue
            seen.add(rel)
            try:
                units.append(_FileUnit(rel=rel, text=p.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError) as e:
                problems.append("%s (unreadable: %s)" % (rel, e))
    return units, problems


def _parse_units(units: List[_FileUnit]) -> List[str]:
    """Parse in place; a corrupt source (SyntaxError / ValueError incl. NUL) degrades that
    one file into meta.unparseable and never ruins the whole scan."""
    problems: List[str] = []
    for u in units:
        try:
            u.tree = ast.parse(u.text, filename=u.rel)
        except (SyntaxError, ValueError) as e:
            u.tree = None
            problems.append("%s (unparseable: %s)" % (u.rel, e))
    return problems


def _exempt_names(repo_root: Path, roots: Tuple[str, ...]) -> set:
    """Two documented escape hatches (declaration is documentation; grep-able):
    (1) `dead-man-exempt: <name>` comment lines in any scanned module file;
    (2) registry lists — string elements of ALL_WORKFLOWS / ALL_ACTIVITIES assignments
        anywhere in the candidate domain (the dynamic-dispatch registers, the exact
        shape of ticket-1's wired entry tables; a name registered there is dispatched
        dynamically and must never be judged dead by a static surface)."""
    out: set = set()
    roots_all = set(roots) | set(MECHANISM_CALL_ROOTS)
    for root in sorted(roots_all):
        base = repo_root / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in EXEMPT_RE.finditer(text):
                out.add(m.group(1))
            try:
                tree = ast.parse(text, filename=str(p))
            except (SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Assign) and all(
                        isinstance(t, ast.Name) and
                        ("WORKFLOWS" in t.id or "ACTIVITIES" in t.id) for t in node.targets)):
                    continue
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for el in node.value.elts:
                        if isinstance(el, ast.Constant) and isinstance(el.value, str):
                            out.add(el.value)
    return out


def _module_defs(unit: _FileUnit) -> List[Tuple[str, ast.AST]]:
    """Module-level public definitions (candidates). Private (_x), dunders and `main`
    are excluded — entrypoints are not mechanisms; the ALL_WORKFLOWS/ALL_ACTIVITIES
    registration names appear as Name references in their modules anyway (so they fail
    the zero-reference test naturally)."""
    if unit.tree is None:
        return []
    out: List[Tuple[str, ast.AST]] = []
    for node in unit.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if name.startswith("_") or name == "main":
                continue
            out.append((name, node))
    return out


def _node_lineno(node: ast.AST) -> int:
    return getattr(node, "lineno", 0)


# ========================================================================================
# Reference indexes（S4 的三面命中统计——C2：每个计数都带分母）
# ========================================================================================

def build_name_ref_index(units: List[_FileUnit]) -> Dict[str, Dict[str, int]]:
    """name → {file_rel: count of ast Name(Load/alias-as-use) + Call references}, across
    the call-domain units. The defining module is excluded at query time, not here."""
    idx: Dict[str, Dict[str, int]] = {}
    for u in units:
        if u.tree is None:
            continue
        for node in ast.walk(u.tree):
            if isinstance(node, ast.Name):
                idx.setdefault(node.id, {}).setdefault(u.rel, 0)
                idx[node.id][u.rel] += 1
            elif isinstance(node, ast.Attribute):
                idx.setdefault(node.attr, {}).setdefault(u.rel, 0)
                idx[node.attr][u.rel] += 1
        for node in ast.walk(u.tree):
            # import 别名也是引用点（from m import name / import m as name）
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    key = a.asname or a.name.split(".")[0]
                    idx.setdefault(key, {}).setdefault(u.rel, 0)
                    idx[key][u.rel] += 1
                    if isinstance(node, ast.ImportFrom) and not a.asname:
                        idx.setdefault(a.name, {}).setdefault(u.rel, 0)
                        idx[a.name][u.rel] += 1
    return idx


def build_scenario_reference_index(repo_root: Path) -> Tuple[Dict[str, int], int]:
    """Text-level reference index over the scenario surface: integration/**/sc_* sources
    AND the scenario registry integration/run_scenarios.py (SCENARIOS names/intents are
    the project's own mechanism inventory — a mechanism mentioned only there is
    scenario-referenced). name → hit count; plus the number of scenario files searched
    (the denominator for the scenario face)."""
    hits: Dict[str, int] = {}
    files = 0
    base = repo_root / _SCENARIO_DIR
    if not base.is_dir():
        return hits, 0

    def _scan(p: Path) -> None:
        nonlocal files
        files += 1
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]{2,}", text):
            hits[m.group(0)] = hits.get(m.group(0), 0) + 1

    for p in sorted(base.rglob("sc_*")):
        if p.is_file():
            _scan(p)
    registry = base / "run_scenarios.py"
    if registry.is_file():
        _scan(registry)
    return hits, files


def module_log_literals(unit: _FileUnit) -> List[str]:
    """Log/print literal strings emitted by one module (ast: call to an attribute named
    info/warning/error/debug/exception/critical/log or print, first arg a str constant).
    ast-only — the module is never imported, never executed (故障模式 7)."""
    out: List[str] = []
    if unit.tree is None:
        return out
    for node in ast.walk(unit.tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_log = isinstance(fn, ast.Attribute) and fn.attr in (
            "info", "warning", "error", "debug", "exception", "critical", "log")
        is_print = isinstance(fn, ast.Name) and fn.id == "print"
        if not (is_log or is_print):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and len(arg.value) >= 4:
                out.append(arg.value)
    return out


_WIDE_SUFFIXES = {".py", ".mjs", ".ts", ".tsx", ".js", ".md"}


def _is_wide_file(p: Path) -> bool:
    return p.is_file() and p.suffix in _WIDE_SUFFIXES and not any(
        seg in ("node_modules", ".git", ".venv", "__pycache__", "out") for seg in p.parts)


def load_wide_texts(repo_root: Path) -> List[Tuple[str, str]]:
    """Call-domain + docs file contents loaded ONCE per scan (性能口径：字面检索全在内存，
    不逐字面 rglob)。Unreadable files are skipped — the log face then reports a smaller
    denominator honestly (the count is the searched count)."""
    out: List[Tuple[str, str]] = []
    for root in MECHANISM_CALL_ROOTS + DOC_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not _is_wide_file(p):
                continue
            try:
                out.append((p.relative_to(repo_root).as_posix(),
                            p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return out


def literal_hit_count(literal: str, wide_texts: List[Tuple[str, str]], exclude_rel: str) -> int:
    """Hits of one log literal outside its defining module: a literal fragment (first 3
    CJK/alnum runs, capped) searched text-level across the preloaded wide texts (a
    literal can only be evidence-searched textually). Returns -1 when the literal is too
    shapeless to search — the caller reports the log face N/A honestly (C2)."""
    frag = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", literal)
    probe = "".join(frag[:3])[:16]
    if len(probe) < 4:
        return -1
    return sum(1 for rel, text in wide_texts if rel != exclude_rel and probe in text)


def _searched_wide_file_count(repo_root: Path, wide_texts: List[Tuple[str, str]]) -> int:
    """Denominator for the log face: how many wide-domain files a literal was searched
    across (the preloaded list length — the actually searched count)."""
    return len(wide_texts)


# ========================================================================================
# S4 dead-mechanism + S5 shadow-code（mechanism 面）
# ========================================================================================

def scan_dead_mechanisms(
    repo_root: Path,
    wide_texts: List[Tuple[str, str]],
    candidate_units: List[_FileUnit],
    name_index: Dict[str, Dict[str, int]],
    scenario_hits: Dict[str, int],
    scenario_file_count: int,
    wide_file_count: int,
    exempt: set,
) -> Tuple[List[Finding], Dict[str, Any]]:
    """S4：三重零命中交叉（a 场景零引用 / b 日志字面零命中 / c 零外部调用）。三重零=med，
    两重零=low；任何一面非零即不报（不冤枉）。证据每面带分母（C2）：场景 0/N 文件、
    日志 0/M 文件或 N/A（模块 0 条 log 字面）、外部调用点 0 处。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"candidates": 0, "exempted": [], "log_literals_total": 0}
    for u in candidate_units:
        for name, node in _module_defs(u):
            if name in exempt:
                meta["exempted"].append("%s:%s" % (u.rel, name))
                continue
            meta["candidates"] += 1
            # (a) 场景零引用
            scen = scenario_hits.get(name, 0)
            # (c) 零引用可达（全仓含定义模块内——注册表/自用即可达；排除同模块即首日洪泛，已校准）
            ext_refs = sum(name_index.get(name, {}).values())
            # (b) 日志字面零命中
            lits = module_log_literals(u)
            meta["log_literals_total"] += len(lits)
            log_face: str
            log_zero = False
            if not lits:
                log_face = "日志面 N/A（模块 0 条 log 字面——空集不折算成 0/0）"
                log_zero = True   # N/A 不反对 dead-man 嫌疑，但证据里如实写 N/A（C2）
            else:
                hits_files = sum(1 for lit in lits if literal_hit_count(lit, wide_texts, u.rel) > 0)
                if hits_files == 0:
                    log_face = "日志字面 0/%d 条在外域文件（共搜 %d 个）命中" % (len(lits), wide_file_count)
                    log_zero = True
                else:
                    log_face = "日志字面 %d/%d 条在外域文件（共搜 %d 个）命中" % (hits_files, len(lits), wide_file_count)
            zero_count = (scen == 0) + (ext_refs == 0)
            if zero_count < 2:
                continue   # 结构面（场景/代码引用）任一非零即活——不报，不冤枉
            if log_zero:
                sev, verdict = DEADMAN_SEVERITY, "三面全零（KI-049 形态）"
            else:
                sev, verdict = TWOSCAN_SEVERITY, "两面零命中（场景 0 + 引用点 0，但日志字面在外域有命中——降 low 留观）"
            evidence = "%s:%d 定义「%s」；%s；场景引用 %d/%d 文件；引用点 %d 处（域 %s，含定义模块内使用）" % (
                u.rel, _node_lineno(node), name, log_face, scen, scenario_file_count,
                ext_refs, "+".join(MECHANISM_CALL_ROOTS))
            findings.append(Finding(
                scan="dead-mechanism", severity=sev,
                subject="dead:%s (%s)" % (name, u.rel),
                evidence="dead-man 嫌疑——%s。%s" % (verdict, evidence),
                suggestion="人审该机制是否已死：确认全史零生效则开 dev-lane 工单退役（引用来源巡检票），"
                           "或在定义模块加 dead-man-exempt 声明豁免；静态面无法确证运行期死，人审可毙"))
    return findings, meta


def name_base(name: str) -> str:
    """旧/新命名变体的公共 base：剥一个新旧/补丁后缀（fetch_payload_v2 / _legacy /
    _patch → fetch_payload）。"""
    for suf in NEW_SUFFIXES + OLD_SUFFIXES + ("_patch", "_compat", "_shim", "_fallback"):
        if name.endswith(suf) and len(name) > len(suf):
            return name[:-len(suf)]
    return name


def scan_shadow_code(
    candidate_units: List[_FileUnit],
    name_index: Dict[str, Dict[str, int]],
) -> Tuple[List[Finding], Dict[str, Any]]:
    """S5 影子代码（base 组语义）：零引用点的定义 × 同 base 组内有被引用的兄弟变体
    → med「疑似被绕过未删的旧路径」。证据点名兄弟变体的 文件:行 而不写其名——
    在役侧不得出现在任何 finding 文本里（场景契约：影子判旧不冤在役）。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"pairs_considered": 0}
    defined: Dict[str, Tuple[str, int]] = {}
    for u in candidate_units:
        for name, node in _module_defs(u):
            defined.setdefault(name, (u.rel, _node_lineno(node)))
    groups: Dict[str, List[str]] = {}
    for name in defined:
        groups.setdefault(name_base(name), []).append(name)
    for name, (rel, ln) in sorted(defined.items()):
        base_name = name_base(name)
        siblings = [s for s in groups.get(base_name, []) if s != name]
        if not siblings:
            continue
        meta["pairs_considered"] += 1
        refs = sum(name_index.get(name, {}).values())
        if refs > 0:
            continue                      # 仍有引用点（含模块内注册/自用）——不是影子
        live = [s for s in siblings if sum(name_index.get(s, {}).values()) > 0]
        if not live:
            continue                      # 整组全死——归 S4 统一判，不重复报
        partner = sorted(live)[0]
        p_rel, p_ln = defined[partner]
        findings.append(Finding(
            scan="shadow-code", severity="med",
            subject="shadow:%s (%s:%d)" % (name, rel, ln),
            evidence="%s:%d 定义「%s」引用点 0 处（全仓含定义模块内），同 base「%s*」组内存在"
                     "在役兄弟变体（%s:%d，引用点 %d 处）——疑似被绕过未删的旧路径"
                     % (rel, ln, name, base_name, p_rel, p_ln,
                        sum(name_index.get(partner, {}).values())),
            suggestion="人审旧路径是否可退役：引用点 0 处=直接删无调用方爆炸；"
                       "确认被绕过则开 dev-lane 工单删除（引用来源巡检票）；人审可毙"))
    return findings, meta


# ========================================================================================
# S6 patch-retirement + S7 long/nested（simplify 面；域=C3 注入）
# ========================================================================================

def _func_calls(tree: ast.AST) -> Dict[str, List[str]]:
    """函数名 → 其体内调用的函数名列表（ast Call 名，一层）。"""
    out: Dict[str, List[str]] = {}
    if tree is None:
        return out
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                 for n in ast.walk(node) if isinstance(n, ast.Call)]
        out[node.name] = [c for c in calls if c]
    return out


def scan_patch_retirement(candidate_units: List[_FileUnit],
                          name_index: Dict[str, Dict[str, int]]) -> Tuple[List[Finding], Dict[str, Any]]:
    """S6 补丁退役判定：命名特征（*_patch/_compat/_legacy/_shim/_fallback）或补丁标记
    注释 → 老化判定；被取代证据（同文件存在 base 变体）→ med，仅命名特征 → low。
    重复防御层：caller 与 callee 都调用同一 guard-ish 助手 → med（caller 点名）。
    每条 suggestion 必含「删了会怎样」机械爆炸半径（调用方清单计数）+ dev-lane 口径。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"patch_named": 0, "dup_defense_pairs": 0}
    defined: Dict[str, Tuple[str, int]] = {}
    call_graph: Dict[str, List[str]] = {}
    for u in candidate_units:
        if u.tree is None:
            continue
        call_graph.update(_func_calls(u.tree))
        for name, node in _module_defs(u):
            defined.setdefault(name, (u.rel, _node_lineno(node)))
    defined_group: Dict[str, List[str]] = {}
    for name in defined:
        defined_group.setdefault(name_base(name), []).append(name)
    # S6a 命名/标记特征
    for u in candidate_units:
        if u.tree is None:
            continue
        for name, node in _module_defs(u):
            named = bool(PATCH_NAME_RE.search(name))
            marked = any(PATCH_MARKER_RE.search(u.text.splitlines()[ln - 1] or "")
                         for ln in range(_node_lineno(node),
                                         min(getattr(node, "end_lineno", _node_lineno(node)) + 1,
                                             _node_lineno(node) + 3))
                         if 0 < ln <= len(u.text.splitlines()))
            if not (named or marked):
                continue
            meta["patch_named"] += 1
            base_name = name_base(name)
            superseded = any(
                s != name and sum(name_index.get(s, {}).values()) > 0
                for s in defined_group.get(base_name, []))
            callers = [rel2 for rel2, cnt in name_index.get(name, {}).items() if rel2 != u.rel]
            sev = "med" if superseded else "low"
            findings.append(Finding(
                scan="patch-retirement", severity=sev,
                subject="patch:%s (%s:%d)" % (name, u.rel, _node_lineno(node)),
                evidence="补丁层特征：%s（命名 %s / 标记注释 %s）；被取代证据=%s；外部引用文件 %d 个（%s）"
                         % (name, "有" if named else "无", "有" if marked else "无",
                            ("同 base「%s*」组内在役兄弟变体（引用点 %d 处）"
                             % (base_name, max(sum(name_index.get(s, {}).values()) for s in defined_group.get(base_name, []) if s != name)))
                            if superseded else "无（仅特征，不判退役）",
                            len(callers), "、".join(sorted(callers)[:3]) or "无"),
                suggestion="删了会怎样：%s。人审补丁是否可退役——确认宿主机制已取代补丁则开 dev-lane "
                           "工单删除（引用来源巡检票），并带防回退场景验证；人审可毙"
                           % ("删后 %d 个引用文件失去该补丁行为（需先核对其调用方是否已迁移）" % len(callers)
                              if callers else "直接删零外部引用方，爆炸半径=0（仍需防回退场景验证）")))
    # S6b 重复防御层：F 调 G，且 F、G 都调用同一 guard-ish H
    for fname, calls in sorted(call_graph.items()):
        fcalls = set(calls)
        for callee in sorted(fcalls & set(call_graph)):
            dup = {c for c in (fcalls & set(call_graph[callee]))
                   if c and GUARDISH_NAME_RE.match(c)}
            if not dup:
                continue
            meta["dup_defense_pairs"] += 1
            loc = defined.get(fname, ("?", 0))
            findings.append(Finding(
                scan="patch-retirement", severity="med",
                subject="dup-defense:%s→%s (%s:%d)" % (fname, callee, loc[0], loc[1]),
                evidence="重复防御层：%s 与其被调 %s 都调用同一防御助手 %s——同一防御在调用链两层重复"
                         % (fname, callee, "、".join(sorted(dup))),
                suggestion="删了会怎样：删 %s 层后其调用方失去第一道防御（%s 在 %s 内仍守第二道）——"
                           "先核调用方输入是否已可信。确认冗余则开 dev-lane 工单收敛为一层"
                           "（引用来源巡检票）；人审可毙" % (fname, callee, fname)))
    return findings, meta


def scan_long_nested(candidate_units: List[_FileUnit]) -> Tuple[List[Finding], Dict[str, Any]]:
    """S7 过长函数/过深嵌套点名（low——简化建议本就是人审信号，不判 high/med 冤枉）。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"functions": 0}
    for u in candidate_units:
        if u.tree is None:
            continue
        lines = u.text.splitlines()
        for node in ast.walk(u.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            meta["functions"] += 1
            start = _node_lineno(node)
            end = getattr(node, "end_lineno", start)
            length = end - start + 1
            if length > LONG_FUNC_LINES:
                findings.append(Finding(
                    scan="long-function", severity="low",
                    subject="long:%s (%s:%d-%d)" % (node.name, u.rel, start, end),
                    evidence="函数 %s 源码行数 %d > 阈值 %d（%s:%d-%d）"
                             % (node.name, length, LONG_FUNC_LINES, u.rel, start, end),
                    suggestion="过长点名（low）：人审能否拆分——拆分属改码，一律走 dev-lane 工单"
                               "（引用来源巡检票）；删了会怎样：不删无行为风险，仅可读性/维护面成本"))
            depth = _nest_depth(node)
            if depth > MAX_NEST_DEPTH:
                findings.append(Finding(
                    scan="deep-nesting", severity="low",
                    subject="deep:%s (%s:%d)" % (node.name, u.rel, start),
                    evidence="函数 %s 嵌套深度 %d > 阈值 %d（%s:%d，总 %d 行）"
                             % (node.name, depth, MAX_NEST_DEPTH, u.rel, start, length),
                    suggestion="过深嵌套点名（low）：人审能否早返回/提取函数——改码走 dev-lane 工单；"
                               "删了会怎样：不删无行为风险，仅分支不可读成本"))
    return findings, meta


def _nest_depth(func_node: ast.AST) -> int:
    """Max nesting depth of If/For/While/Try/With chains inside one function (1-based)."""
    best = 0

    def visit(node: ast.AST, d: int) -> None:
        nonlocal best
        if isinstance(node, NEST_NODES):
            d += 1
            best = max(best, d)
        for child in ast.iter_child_nodes(node):
            visit(child, d)

    visit(func_node, 0)
    return best


# ========================================================================================
# Face entries + dispatch（activities 的 run_inspection_scan 按此分派；face 缺省 test）
# ========================================================================================

SCAN_NAMES_MS = ("dead-mechanism", "shadow-code", "patch-retirement", "long-function", "deep-nesting")


def _prepare(repo_root: Path, scan_roots: Optional[Tuple[str, ...]]) -> Tuple[
        Path, Tuple[str, ...], List[_FileUnit], List[str]]:
    repo_root = Path(repo_root)
    if not repo_root.is_dir():
        raise ScanError("仓库根不存在：%s" % repo_root)          # 故障模式 1
    roots = tuple(scan_roots) if scan_roots else DEFAULT_SCAN_ROOTS
    units, unreadable = collect_py_units(repo_root, roots)
    unparseable = _parse_units(units)
    return repo_root, roots, units, unreadable + unparseable


def _finish(face: str, findings: List[Finding], meta: Dict[str, Any]) -> Dict[str, Any]:
    summary = summarize(findings)
    return {
        "face": face,
        "findings": [f.to_dict() for f in summary["ordered"]],
        "summary": summary["counts"],
        "heartbeat": len(summary["ordered"]) == 0,            # 故障模式 5：零发现=心跳
        "meta": dict(meta, red_line="巡检只出报告与开票建议，绝不直接改码",
                     caveat="「全史零命中」=当前树交叉零命中近似：跨期巡检票史累积构成史，"
                            "git 考古留人审票；动态分发（getattr/字符串派发）有盲区，"
                            "豁免走 dead-man-exempt 声明"),
    }


def run_mechanism_face_scan(repo_root: Path,
                            scan_roots: Optional[Tuple[str, ...]] = None) -> Dict[str, Any]:
    """Mechanism-face main entry（S4 dead-mechanism + S5 shadow-code）。"""
    repo_root, roots, units, degrade = _prepare(repo_root, scan_roots)
    candidates = [u for u in units if u.tree is not None and u.rel.startswith(tuple(r + "/" for r in roots))]
    call_units, call_degrade = collect_py_units(repo_root, MECHANISM_CALL_ROOTS)
    degrade += call_degrade
    _parse_units(call_units)
    name_index = build_name_ref_index(call_units)
    scenario_hits, scenario_files = build_scenario_reference_index(repo_root)
    exempt = _exempt_names(repo_root, roots)
    wide_texts = load_wide_texts(repo_root)
    s4_findings, s4_meta = scan_dead_mechanisms(
        repo_root, wide_texts, candidates, name_index, scenario_hits, scenario_files,
        _searched_wide_file_count(repo_root, wide_texts), exempt)
    s5_findings, s5_meta = scan_shadow_code(candidates, name_index)
    findings = s4_findings + s5_findings
    meta = {"scan_roots": list(roots), "call_roots": list(MECHANISM_CALL_ROOTS),
            "candidates": s4_meta["candidates"], "exempted": s4_meta["exempted"],
            "shadow_pairs": s5_meta["pairs_considered"], "degraded": degrade}
    return _finish("mechanism", findings, meta)


def run_simplify_face_scan(repo_root: Path,
                           scan_roots: Optional[Tuple[str, ...]] = None) -> Dict[str, Any]:
    """Simplify-face main entry（S6 patch-retirement + S7 long/nested；域=C3 注入）。"""
    repo_root, roots, units, degrade = _prepare(repo_root, scan_roots)
    candidates = [u for u in units if u.tree is not None]
    call_units, call_degrade = collect_py_units(repo_root, MECHANISM_CALL_ROOTS)
    _parse_units(call_units)
    name_index = build_name_ref_index(call_units)
    s6_findings, s6_meta = scan_patch_retirement(candidates, name_index)
    s7_findings, s7_meta = scan_long_nested(candidates)
    findings = s6_findings + s7_findings
    meta = {"scan_roots": list(roots), "patch_named": s6_meta["patch_named"],
            "dup_defense_pairs": s6_meta["dup_defense_pairs"],
            "functions": s7_meta["functions"], "degraded": degrade,
            "thresholds": {"long_func_lines": LONG_FUNC_LINES, "max_nest_depth": MAX_NEST_DEPTH}}
    return _finish("simplify", findings, meta)


FACE_RUNNERS = {
    "mechanism": run_mechanism_face_scan,
    "simplify": run_simplify_face_scan,
}


def run_face_scan(face: str, repo_root: Path,
                  scan_roots: Optional[Tuple[str, ...]] = None) -> Dict[str, Any]:
    """Face dispatch used by the activity layer（fail-closed：未知面点名已知面清单，不猜）。"""
    runner = FACE_RUNNERS.get(face)
    if runner is None:
        raise ScanError("未知巡检面 %r（已接线：test[缺省]、mechanism、simplify）" % face)
    return runner(repo_root, scan_roots)


def main() -> None:
    ap = argparse.ArgumentParser(description="机制面/简化面扫描器（inspection 票②）")
    ap.add_argument("--face", required=True, choices=sorted(FACE_RUNNERS), help="扫描面")
    ap.add_argument("--repo-root", default=".", help="仓库根（缺省当前目录）")
    ap.add_argument("--scan-roots", default=None,
                    help="逗号分隔扫描域（repo-relative，缺省 server/engine——C3）")
    args = ap.parse_args()
    roots = tuple(s.strip() for s in args.scan_roots.split(",") if s.strip()) if args.scan_roots else None
    try:
        result = run_face_scan(args.face, Path(args.repo_root), roots)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
    except ScanError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
        sys.exit(1)


if __name__ == "__main__":
    main()

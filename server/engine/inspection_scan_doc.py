#!/usr/bin/env python3
"""inspection_scan_doc — the docs-face scanner (inspection epic instance 2, docs-sync,
t260911-02).

------------------------------------------------------------------------
【退役留档（t260916-22，宿主令「不需要这个静态扫描，我们巡检要用 agent 来做」）】
本模块已从生产路径摘除：InspectionPeriodicWorkflow 新票走 inspect 段
（agent 审查，见 inspection_inspect.py / agent_activities.run_inspection_inspect）。
本文件保留一版只服务老在途票 replay（Temporal 重放历史里的 run_inspection_scan
调用必须仍能匹配）——新代码禁接线本模块；S1~S4 静态发现自此不再产出，274 条旧
发现整体作废不迁移（宿主裁定④）。deadman/suite 机械面不受影响。
------------------------------------------------------------------------

Red line: inspection only produces reports and ticket-opening suggestions, it never
modifies anything — this module is a pure-read static surface over the docs knowledge
base (docs/ 定稿库只读；写路径只存在于 out/ 巡检落账，由 flow 层负责，本模块零写入).

Three scans (severity: static surfaces never certify high — C1 item 9, all med):
  S8 index-consistency  docs/index.json `docs[].path` ↔ docs/ 实际 *.md 文件，双向点名：
                        缺登记（文件在索引无）与幽灵条目（索引有文件无）。README 人工目录
                        与 index.json 的双口径漂移如实进 meta（不裁谁对——口径局限声明）。
  S9 frontmatter        每篇头部 YAML frontmatter 五字段合法：title（非空）/category
                        （design|content|ops|reference）/tags（非空）/status（active|
                        draft|deprecated）/updated（YYYY-MM-DD）。规则真源=本文件置顶
                        常量（不引 README 行号——README 自身已实测漂移，锚字面漂移即
                        KI-051 同族病）。
  S10 referenced-path   文档引用的仓内路径存在（KI-051 族守卫的 doc 版锚点，常驻化）：
                        只认显式形态——markdown 链接 `](path)` 与反引号 `path`（含 / 且
                        带已知后缀、非 URL）——不全文猜路径（模板感知盲区=KI-051 教训）。
                        相对路径按仓根解析（`./`、`../` 开头按文档所在目录解析）；解析后
                        越出仓根=点名（`../` 逃逸）；目标不存在=点名。只验「存在」不验
                        「语义相符」（meta.caveat 如实声明）。

C1 故障模式取舍清单（承 inspection_scan_ms.py 十三项，逐项「带过来 / 不适用+理由」）：
  1. 仓根缺失 fail-closed ScanError       → 带过来（run_doc_face_scan 首行同判）。
  2. 条目/文件不可读逐项降级不株连         → 带过来（单篇 OSError/Unicode → 降级进
     meta.unreadable，单篇坏不毁整扫）。
  3. 坏 ast 降级                          → 不适用（不 parse python）；换形态：index.json
     坏 JSON / frontmatter 坏子集解析失败 → 逐条降级点名，不假绿不崩。
  4. stdout 单行 JSON {ok, result|error}   → 带过来（CLI 契约同 client.py/scan_ms）。
  5. 零发现 heartbeat=true                → 带过来（心跳票语义逐字段同票①）。
  6. 纯读零写入                           → 带过来（本模块无任何 write/open-w）。
  7. 静态不执行被扫对象                   → 带过来且更强（docs=纯文本+JSON，零执行面）。
  8. 误报洪泛闸                           → 带过来并换形态：豁免清单 `doc-exempt: <规则id>`
     注释声明（承接 dead-man-exempt 先例；md 形态 `<!-- doc-exempt: doc-s9 -->`）+
     S10 只认显式路径形态（见上）。
  9. 静态面不确证 → med 交人审、不判 high  → 带过来（S8/S9/S10 全 med）。
 10. 阈值/词法常量置顶、改必带用例         → 带过来（REQUIRED_FIELDS/CATEGORIES/STATUSES/
     路径引用正则全置顶）。
 11. 确定性排序                           → 带过来（severity→scan→subject；rglob 先 sorted）。
 12. 稳定 finding_id 跨期 dedupe          → 带过来（id 由 规则:文件:路径构成，不带时间戳）。
 13. meta 记录口径局限                    → 带过来（meta.caveat：S10 只验存在；README 人工
     目录与 index.json 双口径漂移如实进 meta）。

Input surface (all injectable; malformed input degrades item by item, never crashes).
CLI (ops channel): python3 inspection_scan_doc.py --repo-root <repo>
stdout: single line JSON {ok, result|error} (same contract as inspection_scan.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inspection_scan import Finding, ScanError, summarize  # noqa: E402

# ---- 规则词法/词表（置顶；改任何一个都必须带真值表用例——票① DUP_JACCARD 惯例）----
DOC_ROOT = "docs"
INDEX_REL = "docs/index.json"
REQUIRED_FIELDS = ("title", "category", "tags", "status", "updated")   # 五字段（R6 修正）
CATEGORIES = ("design", "content", "ops", "reference")
STATUSES = ("active", "draft", "deprecated")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RULE_S8_MISSING = "doc-s8-missing"      # 文件在、索引无（缺登记）
RULE_S8_GHOST = "doc-s8-ghost"          # 索引有、文件无（幽灵条目）
RULE_S9_FRONTMATTER = "doc-s9-frontmatter"
RULE_S10_MISSING = "doc-s10-missing"
RULE_S10_ESCAPE = "doc-s10-escape"
SEVERITY = "med"                        # 静态面全 med（C1 item 9）
# S10 显式路径形态：反引号或 markdown 链接内，含 / 且带已知后缀；排除 URL/锚点/邮箱。
_PATHISH_RE = re.compile(
    r"(?<![\w/\-.])(?:\.\./|\./|/)?"
    r"[A-Za-z0-9_\u4e00-\u9fff][\w\u4e00-\u9fff\-./]*?"
    r"\.(?:py|mjs|ts|tsx|js|sh|md|ya?ml|json)\b")
_MD_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
_EXEMPT_RE = re.compile(r"doc-exempt:\s*([A-Za-z0-9\-_, ]+)")
_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*:|^//|^#")


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./")


def findings_to_dicts(finds: List[Finding]) -> List[Dict[str, Any]]:
    return [f.to_dict() for f in finds]


def _sorted(findings: List[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: (f.severity, f.scan, f.subject))


def exempt_rules(text: str) -> set:
    """`doc-exempt: <规则id…>` 豁免集合（C1 item 8：误报洪泛闸的声明形态）。
    语义=规则族前缀豁免：`doc-exempt: doc-s9` 抑制该文件全部 doc-s9-* 发现。"""
    out: set = set()
    for m in _EXEMPT_RE.finditer(text):
        for tok in m.group(1).replace(",", " ").split():
            out.add(tok.strip())
    return out


def _exempted(text: str, *rules: str) -> bool:
    ex = exempt_rules(text)
    return any(rule.startswith(tok) or tok.startswith(rule) for tok in ex for rule in rules)


def parse_frontmatter(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """头部 frontmatter 子集解析（零依赖；只认 `---` 围栏 + `key: value` / tags 块列表）。
    返回 (mapping|None, err)。无围栏=(None, "缺 frontmatter 围栏")。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "缺 frontmatter 围栏"
    end = None
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, "frontmatter 围栏未闭合"
    fm: Dict[str, Any] = {}
    key = ""
    for ln in lines[1:end]:
        if not ln.strip() or ln.strip().startswith("#"):
            continue
        if ln.lstrip().startswith("- ") and key:
            if not isinstance(fm.get(key), list):
                fm[key] = []          # `key:` 空标量后跟块列表（tags 形态）——收编为列表
            fm[key].append(ln.lstrip()[2:].strip().strip('"'))
            continue
        if ":" not in ln:
            return None, "frontmatter 行无法解析：%r" % ln.strip()
        # 缩进行=上一层键的嵌套块（related 段落形态：`- mode: …` / `  target: …`）。
        # 260928：以前逐行当平铺映射读，嵌套块里的 `target:` 会被误判「键重复」——
        # 见 docs/design/failure-classification-protocol-v1.md 的 related 段。
        # 只跳过嵌套行，不改变顶层判据（顶层重复键仍红）。
        if ln[:1].isspace():
            continue
        k, _, v = ln.partition(":")
        key = k.strip()
        val = v.strip()
        if key in fm:
            return None, "frontmatter 键重复：%s" % key
        fm[key] = val
    return fm, ""


def scan_frontmatter(rel: str, text: str) -> List[Finding]:
    """S9：一篇文档的 frontmatter 合法性（单篇全判，逐项点名缺什么）。"""
    fm, err = parse_frontmatter(text)
    problems: List[str] = []
    if fm is None:
        problems.append(err)
    else:
        for k in REQUIRED_FIELDS:
            v = fm.get(k)
            if k == "tags":
                if not v or (isinstance(v, str) and not v.strip()):
                    problems.append("缺 tags")
                continue
            if isinstance(v, list):
                v = v[0] if v else ""
            v = str(v or "").strip().strip('"')
            if not v:
                problems.append("缺 %s" % k)
            elif k == "category" and v not in CATEGORIES:
                problems.append("category 非法 %r（合法：%s）" % (v, "|".join(CATEGORIES)))
            elif k == "status" and v not in STATUSES:
                problems.append("status 非法 %r（合法：%s）" % (v, "|".join(STATUSES)))
            elif k == "updated" and not DATE_RE.match(v):
                problems.append("updated 非日期形态 %r（须 YYYY-MM-DD）" % v)
    if not problems or _exempted(text, RULE_S9_FRONTMATTER):
        return []
    return [Finding(scan=RULE_S9_FRONTMATTER, severity=SEVERITY,
                    subject="%s：%s" % (rel, "；".join(problems)),
                    evidence="头部 frontmatter 校验（规则真源=常量 REQUIRED_FIELDS）",
                    suggestion="补齐/修正 frontmatter 五字段（维护约定）后重扫")]


def scan_index_consistency(docs_root: Path) -> Tuple[List[Finding], Dict[str, Any]]:
    """S8：index.json ↔ 实际文件双向核对（index 坏 JSON=逐条降级点名，不崩不假绿）。"""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {}
    index_path = docs_root.parent / INDEX_REL
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [Finding(scan=RULE_S8_GHOST, severity=SEVERITY,
                        subject="%s 缺失（机器索引不存在）" % INDEX_REL,
                        evidence=str(index_path), suggestion="跑 docs/scripts/build_index.py")], meta
    except (OSError, ValueError) as e:
        return [Finding(scan=RULE_S8_GHOST, severity=SEVERITY,
                        subject="%s 不可解析（%s: %s）" % (INDEX_REL, type(e).__name__, e),
                        evidence=str(index_path), suggestion="重建 index.json 后重扫")], meta
    entries = data.get("docs") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [Finding(scan=RULE_S8_GHOST, severity=SEVERITY,
                        subject="%s 缺 docs 列表（畸形索引）" % INDEX_REL,
                        evidence=str(index_path), suggestion="重建 index.json 后重扫")], meta
    indexed = sorted({_norm(str(e.get("path") or "")) for e in entries
                      if isinstance(e, dict) and e.get("path")})
    # 口径：索引条目与实际文件都以 docs/ 为根（index.json 的 path 形态=design/x.md）
    actual = sorted(_norm(str(p.relative_to(docs_root)))
                    for p in docs_root.rglob("*.md") if p.is_file())
    meta["indexed"] = len(indexed)
    meta["actual_files"] = len(actual)
    ghost = [p for p in indexed if p not in set(actual)]
    missing = [p for p in actual if p not in set(indexed)]
    for p in ghost:
        findings.append(Finding(scan=RULE_S8_GHOST, severity=SEVERITY,
                                subject="索引幽灵条目：%s（文件不存在）" % p,
                                evidence=index_path.name, suggestion="登记或移除索引条目"))
    for p in missing:
        findings.append(Finding(scan=RULE_S8_MISSING, severity=SEVERITY,
                                subject="文档缺登记：%s（不在 %s）" % (p, INDEX_REL),
                                evidence=index_path.name, suggestion="补进索引（build_index.py）"))
    return _sorted(findings), meta


def _extract_refs(text: str) -> List[str]:
    """S10 显式路径形态提取：反引号路径 + markdown 链接（URL/锚点/纯文件名排除——
    不全文猜路径，防模板感知盲区）。"""
    out: List[str] = []
    for m in _PATHISH_RE.finditer(text):
        out.append(m.group(0))
    for m in _MD_LINK_RE.finditer(text):
        target = m.group(1).split("#", 1)[0]
        if target and not _URL_RE.match(target) and "/" in target:
            out.append(target)
    # 去重保序
    seen: set = set()
    uniq = []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def _name_index(repo_root: Path) -> frozenset:
    """仓内文件路径后缀集（建一次、查千次）。

    逐后缀入集：`server/engine/shared.py` 贡献 `server/engine/shared.py`、
    `engine/shared.py`、`shared.py` 三个后缀。查询 O(1)。
    跳过重目录（node_modules/.git/venv/临时件）——文档引用不会指向它们，扫它们
    只会把一次巡检拖成分钟级（实测：逐条 rglob 直接跑不出结果）。
    """
    skip_dirs = {"node_modules", ".git", ".venv", "venv", "__pycache__",
                 ".mypy_cache", ".pytest_cache", "dist", "build", ".next"}
    suffixes = set()
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            try:
                rel = Path(dirpath, fn).relative_to(repo_root).as_posix()
            except ValueError:
                continue
            parts = rel.split("/")
            for i in range(len(parts)):
                suffixes.add("/".join(parts[i:]))
    return frozenset(suffixes)


def scan_referenced_paths(rel: str, text: str, repo_root: Path, name_index=None) -> List[Finding]:
    """S10：单篇文档的仓内路径引用存在性（`../` 逃逸与不存在逐条点名）。

    `name_index` = `_name_index(repo_root)` 后缀集（调用方建一次复用）；不给则单篇自建
    （直接调用本函数的单测/工具面仍然工作）。
    """
    if _exempted(text, RULE_S10_MISSING, RULE_S10_ESCAPE):
        return []
    if name_index is None:
        name_index = _name_index(repo_root)
    findings: List[Finding] = []
    doc_dir = (repo_root / rel).parent
    for ref in _extract_refs(text):
        if ref.startswith("/"):
            # 根绝对形态（/.sandbar/… 等）多是契约字面而非仓内引用——不判越界（防误报
            # 洪水），如实进 meta.caveat（见 run_doc_face_scan）
            continue
        explicit_rel = ref.startswith(("./", "../"))
        base = doc_dir if explicit_rel else repo_root
        resolved = (base / ref).resolve()
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            findings.append(Finding(scan=RULE_S10_ESCAPE, severity=SEVERITY,
                                    subject="%s 引用越界：%s（解析出仓根）" % (rel, ref),
                                    evidence=ref, suggestion="改为仓内相对路径"))
            continue
        if resolved.exists():
            continue
        # 名称形态引用（`node.ts` / `client.py` / `merge-checks.yaml`）按仓内后缀命中；
        # 显式相对路径不做后缀兜底（它写死了目录主张，解析不到就是真断）。
        if not explicit_rel:
            parts = [p for p in ref.replace("\\", "/").split("/") if p not in ("", ".")]
            if parts and "/".join(parts) in name_index:
                continue
        findings.append(Finding(scan=RULE_S10_MISSING, severity=SEVERITY,
                                subject="%s 引用缺失：%s" % (rel, ref),
                                evidence=ref, suggestion="修引用或恢复目标文件"))
    return findings


def run_doc_face_scan(repo_root: Path, docs_root: Optional[Path] = None) -> Dict[str, Any]:
    """docs 面主入口（activities.run_inspection_scan face=doc 分派 + CLI 共用）。
    仓根缺失 fail-closed；单篇不可读逐项降级；零发现=heartbeat。"""
    repo_root = Path(repo_root)
    if not repo_root.is_dir():
        raise ScanError("仓根缺失：%s 不存在（fail-closed）" % repo_root)
    docs = docs_root if docs_root is not None else repo_root / DOC_ROOT
    if not docs.is_dir():
        raise ScanError("docs 目录缺失：%s 不存在（fail-closed）" % docs)
    findings: List[Finding] = []
    s8, index_meta = scan_index_consistency(docs)
    findings.extend(s8)
    unreadable: List[str] = []
    scanned = 0
    ref_scanned = 0
    name_index = _name_index(repo_root)   # 260928：S10 后缀命中表，建一次全篇复用
    for p in sorted(docs.rglob("*.md")):
        rel = _norm(str(p.relative_to(repo_root)))
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            unreadable.append("%s（%s）" % (rel, type(e).__name__))
            continue
        scanned += 1
        findings.extend(scan_frontmatter(rel, text))
        refs = scan_referenced_paths(rel, text, repo_root, name_index)
        ref_scanned += len(_extract_refs(text))
        findings.extend(refs)
    findings = _sorted(findings)
    summary = summarize(findings)
    counts = summary["counts"]
    return {
        "face": "doc",
        "findings": findings_to_dicts(findings),
        "summary": counts,
        "heartbeat": len(findings) == 0,
        "meta": {
            "scanned_files": scanned,
            "unreadable": unreadable,
            "paths_checked": ref_scanned,
            "index": index_meta,
            # 依赖占位（工单②依赖说明，不得静默空转）：以下扫描项属 doc-lifecycle epic
            # 的文档同步面（沉淀触发器与反向同步闸），本面显式标注不覆盖，待该 epic 落地接入
            "deferred": "doc-lifecycle 依赖占位：沉淀触发器/反向同步闸扫描未覆盖（属 "
                        "doc-lifecycle epic，本面不静默空转）",
            "caveat": "S10 只验「路径存在」不验语义相符，根绝对形态（/ 开头）不判越界"
                      "（契约字面豁免，防误报洪水）；README 人工目录与 index.json 双口径"
                      "漂移如实进 index 元数据，本扫描不裁谁对；静态面全 med 交人审",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="docs 面巡检扫描器（纯读，单行 JSON 回执）")
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--docs-root", default=None, help="夹具注入用；缺省=<repo-root>/docs")
    args = ap.parse_args()
    try:
        result = run_doc_face_scan(
            Path(args.repo_root), Path(args.docs_root) if args.docs_root else None)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
    except ScanError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""inspection_produce — 产出型巡检（produce mode）纯函数契约层（t260925-01）。

定位（与 inspection_inspect 同纪律）：零 temporalio 依赖的**纯函数层**——场景/UT/
活动壳都可直接 import；活动壳在 agent_activities.run_inspection_produce；workflow
在 inspection_flow.InspectionProduceWorkflow（与 dev-lane 分链，段序=setup → produce
→ 自检 → 报告(含 diff) → 人审门 approve=merge / reject=discard）。

红线分化（260924 设计稿附一§1）：test（integration）面保持「只出报告」且只读 pin
零改动（A4）；produce 面 agent 在**自有泳道**内受限可写（写面口径见
produce_write_pin_patch 注），改动的**落盘权在人审**——approve 走既有 merge 机械
（squash、一票一 commit），reject 丢弃本期（报告先行落账，diff 留痕可追溯）。

强 schema（fail-closed）：agent 最终消息**末尾恰一块** ```json 围栏
  {"changes": [{"path": "...", "action": "add|modify|delete", "summary": "..."}],
   "zero_change": false, "evidence": ["..."]}
id 不由 agent 提供——机械侧按「路径+动作」指纹铸（mint_change_ids：同一文件
同一动作跨期同 id；不含内容哈希——解析层无文件内容可哈希，措辞与实现一致）。
畸形输入（坏 JSON / 多围栏 / 缺围栏 / changes 非列表 / path 畸形 / action 词表外 /
zero_change 非布尔）一律 ProduceParseError 点名——不猜、不静默丢。

机械自检四闸（方案步2；全部纯函数，报告段在活动内消费）：
  ①写集闸 check_write_set：diff 路径全部 ∈ 声明 docs_root；越界=fail-closed 拒收
    并逐条**点名越界路径**（A2）。绝对路径与 .. 逃逸形态同样点名。
  ②保护面闸 check_protected_overlap：diff ∩ path_gates.PROTECTED_PATHS（真源沿用，
    票3 随项目声明化）＝不跳过、不硬失败——产出 protected_overlap 清单进报告
    （file + 见报告 diff），人审可在**同一期票**内签 produce-protect-authorize 放行
    （A3；授权清单随 merge payload 作窄通旁路标记，path_gates 本体零改动）。
  ③zero-change gate check_zero_change (A5): a zero_change=true claim needs evidence and
    an empty changes list; changes declared as zero-change, or a zero-change claim with
    no evidence, are both red (no empty shell, no invented work). Interaction with a red
    document self-check (review v2 condition ②): a period with no substantive change but
    a red self-check still carries an explicit conclusion (the named red list) -- the
    whole self-check result, green or red, goes into the report, and this gate judges
    only whether the zero-change claim itself is true.
  ④doc self-check doc_selfcheck (t261103-21): what a produced documentation change
    must not break -- the frontmatter lexical fields, and explicit path references
    (an escape out of the tree is named). The INDEX leg is gone on purpose. The
    documentation index is a derived artefact that lives in the project's own data
    directory (design docs/design/project-docs-roots-v1.md goal 5): an
    in-repository copy has no consumer and drifts, and the project-level derived
    index describes a DIFFERENT tree than the lane worktree this self-check judges
    -- reading either here would judge the wrong tree. Index consistency (derived
    index <-> README <-> files, plus the absent/stale/failed states) is owned by
    the doc-face mechanical layer M1 (inspection_doc_mech.py, doc-m1-*) on the
    project tree, after the produced change is merged. The rule set stays
    declarable (DocCheckRules; the engine never hard-codes one project's
    documentation conventions), and a self-check that judged nothing says so by
    name (doc_selfcheck_verdict's `not_judged`), never a bare empty list. Relation
    to the retired module inspection_scan_doc: the body is never wired in
    (t260916-22's retirement note), its top-of-file rule constants are copied by
    value and cross-linked, and the same-set property is locked by UT fixtures.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ========================================================================================
# 词表与常量（置顶；改任何一个都必须带真值表用例——票① DUP_JACCARD 惯例）
# ========================================================================================

#: 产出型巡检的两个人审门 id（与报告面 CLOSE_GATE_ID 字面不同——防两类票信号串门，
#: 方案 C1 第 3 条）
PRODUCE_CLOSE_GATE_ID = "inspection-produce-close"
PRODUCE_AUTHORIZE_GATE_ID = "inspection-produce-protect-authorize"

#: 活动内 deadline margin（活动 deadline=预算−本余量，须 < workflow 侧
#: start_to_close；inspect.INSPECT_DEADLINE_MARGIN_SEC 同值同纪律，独立常量防环）
PRODUCE_DEADLINE_MARGIN_SEC = 60

#: change 动作词表（agent 围栏 schema 的一部分；词表外 fail-closed）
CHANGE_ACTIONS: Tuple[str, ...] = ("add", "modify", "delete")

#: 末尾围栏抽取（与 inspection_inspect.parse_agent_findings 同形态：末尾恰一块围栏）
_FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)

#: 显式路径引用形态（S10 同款口径，见 inspection_scan_doc._REF_RE）：markdown 链接
#: 与反引号内、含 / 且带已知后缀、非 URL/锚点/邮箱。只验「存在」不验语义（meta 局限）。
_REF_RE = re.compile(
    r"`([^`]+)`"                       # 反引号
    r"|\]\(([^)\s]+)\)"                # markdown 链接
)
_REF_SUFFIXES = (".md", ".json", ".yaml", ".yml", ".py", ".txt", ".html", ".mjs")
_REF_EXCLUDE_RE = re.compile(r"^(https?:|mailto:|#|data:)")


class ProduceParseError(ValueError):
    """agent 产出围栏不满足强 schema——fail-closed，报错点名形态。"""


class SelfcheckError(ValueError):
    """机械自检输入畸形（如 diff 路径清单非列表）——闭式点名，不假绿。"""


# ========================================================================================
# 围栏解析与 id 铸造
# ========================================================================================

def extract_last_fence(text: str) -> str:
    """取**末尾恰一块** ```json 围栏体；零块/多块容忍但末尾判定按最后一块（与
    inspect 同口径——围栏缺/多块的红判定在 parse 阶段做，这里只取体）。"""
    blocks = _FENCE_RE.findall(text or "")
    if not blocks:
        raise ProduceParseError("产出缺少 ```json 围栏（末尾恰一块的强 schema）")
    return blocks[-1]


def parse_agent_changes(text: str) -> Dict[str, Any]:
    """围栏 → 结构化产出（fail-closed）。返回
    {"changes": [{path, action, summary}], "zero_change": bool, "evidence": [str]}。"""
    body = extract_last_fence(text)
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as e:
        raise ProduceParseError("围栏 JSON 解析失败：%s" % e) from e
    if not isinstance(raw, dict):
        raise ProduceParseError("围栏顶层必须是映射（got %s）" % type(raw).__name__)
    changes = raw.get("changes")
    if not isinstance(changes, list):
        raise ProduceParseError("changes 缺失或非列表（强 schema：changes=[…]）")
    norm: List[Dict[str, str]] = []
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict):
            raise ProduceParseError("changes[%d] 非映射（got %s）" % (i, type(ch).__name__))
        path = str(ch.get("path") or "").strip()
        action = str(ch.get("action") or "").strip()
        summary = str(ch.get("summary") or "").strip()
        if not path or path.startswith("/") or "\\" in path:
            raise ProduceParseError(
                "changes[%d].path 畸形 %r（仓内相对 posix 路径，非空非绝对）" % (i, path))
        if any(seg == ".." for seg in path.split("/")):
            raise ProduceParseError("changes[%d].path %r 含 .. 段（越根逃逸禁入）" % (i, path))
        if action not in CHANGE_ACTIONS:
            raise ProduceParseError(
                "changes[%d].action %r 词表外（可指名：%s）"
                % (i, action, "、".join(CHANGE_ACTIONS)))
        if not summary:
            raise ProduceParseError("changes[%d].summary 缺空（每条 change 须人读摘要）" % i)
        norm.append({"path": path, "action": action, "summary": summary})
    zero_change = raw.get("zero_change")
    if not isinstance(zero_change, bool):
        raise ProduceParseError("zero_change 缺失或非布尔（强 schema：true/false）")
    evidence = raw.get("evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list) or any(not isinstance(e, str) for e in evidence):
        raise ProduceParseError("evidence 缺失或非字符串列表")
    return {"changes": norm, "zero_change": zero_change, "evidence": [str(e) for e in evidence]}


def mint_change_ids(changes: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """id 机械侧铸：种子=路径\x00动作（不含时间戳/内容——解析层无内容可哈希）。
    同一文件同一动作跨期同 id（去重面）；内容级区分属 diff 复核职责，不在此。"""
    out = []
    for ch in changes:
        seed = "%s\x00%s" % (ch.get("path", ""), ch.get("action", ""))
        out.append(dict(ch, id=hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]))
    return out


#: 模块公开契约别名（integration/t260925-01 场景锁定名——validate_output_schema=
#: parse_agent_changes 的同一实现；单点真源不复制）
validate_output_schema = parse_agent_changes


# ========================================================================================
# 机械自检四闸
# ========================================================================================

def _check_path_shape(p: str) -> Optional[str]:
    """路径形态守卫：畸形返回人读原因（绝对/反斜杠/../空），合法返回 None。"""
    if not p or p.startswith("/") or "\\" in p:
        return "绝对/畸形路径"
    if any(seg == ".." for seg in p.split("/")):
        return ".. 越根逃逸"
    return None


def _path_of(item: Any) -> str:
    """写集条目归一：str 直用；dict（agent 围栏 change 形状）取其 path。"""
    if isinstance(item, dict):
        return str(item.get("path") or "")
    return str(item or "")


def check_write_set(paths: Iterable[Any], docs_root: str = "") -> List[Dict[str, str]]:
    """写集闸（A2）：路径全部 ∈ docs_root；越界逐条点名返回
    [{path, reason}]——空列表=全过。条目接受 str 或 {path:...} dict。"""
    root = (docs_root or "").strip().rstrip("/")
    if not root:
        raise SelfcheckError("docs_root 为空——写集闸无法判定（fail-closed）")
    out: List[Dict[str, str]] = []
    for item in paths:
        p = _path_of(item)
        reason = _check_path_shape(p)
        if reason:
            out.append({"path": p, "reason": reason})
            continue
        if p != root and not p.startswith(root + "/"):
            out.append({"path": p, "reason": "outside doc root %s (doc change is limited to the doc root; "
                                             "code/comments/integration/notes are never in the write set)" % root})
    return out


def check_protected_overlap(paths: Iterable[Any],
                            protected: Optional[Iterable[str]] = None) -> List[str]:
    """保护面闸（A3）：diff ∩ 保护名单＝**点名进报告**，不跳过不硬失败。
    protected 缺省=path_gates.PROTECTED_PATHS（引擎保护名单真源；票3 随项目声明化）。
    返回命中的保护路径清单（去重排序）。"""
    if protected is None:
        from path_gates import PROTECTED_PATHS  # 懒 import（防环）
        protected = PROTECTED_PATHS
    prot = [p.rstrip("/") for p in (protected or []) if p]
    hits = set()
    for item in paths:
        p = _path_of(item)
        for q in prot:
            if p == q or p.startswith(q + "/") or q.startswith(p + "/"):
                hits.add(q)
                hits.add(p)
    return sorted(hits)


def check_zero_change(changes: Optional[List[Dict[str, Any]]] = None,
                      zero_change: bool = False,
                      evidence: Optional[List[str]] = None) -> str:
    """零 change 闸（A5）：返回 ""=过；非空=红（人读点名）。
      - zero_change=true：changes 必须为空 **且** evidence 非空（显式证据，非空壳）；
      - zero_change=false：changes 必须非空（不许「自称有改动却零条目」）；
    有 changes 却声明零 change=造假改动嫌疑，判红。文档自检红不在此判（见头注③）。"""
    changes = changes or []
    evidence = evidence or []
    if zero_change:
        if changes:
            return "零 change 声明与 %d 条 changes 并存（造假改动嫌疑，A5 判红）" % len(changes)
        if not evidence:
            return "零 change 声明缺证据（evidence 空=空壳报告，A5 判红）"
        return ""
    if not changes:
        return "zero_change=false 但 changes 为空（既非零 change 又无条目——形态非法）"
    return ""


# ========================================================================================
# 文档自检（doc_selfcheck；规则集可声明——review v2 附条件①）
# ========================================================================================

#: t261103-21: who judges documentation-index consistency now, and why it is not judged
#: here. Named in the code (and reported in every verdict) so the dropped coverage cannot
#: go quiet and announce itself as a pass.
INDEX_CHECK_OWNER = "inspection_doc_mech.py M1 (doc-m1-*)"
INDEX_CHECK_REASON = (
    "the documentation index is a derived artefact in the project's own data directory, "
    "outside every repository; the self-check judges the lane worktree it writes into, so "
    "neither an in-repository copy nor the project-level index describes this tree. "
    "Index consistency is judged by %s on the project tree after the change is merged."
    % INDEX_CHECK_OWNER)


@dataclass
class DocCheckRules:
    """The document self-check's rule set. The default values are the documentation
    conventions of this project; a project declares its own (review v2 condition ①: the
    engine never hard-codes one project's conventions). The frontmatter vocabulary is the
    same set the retired module inspection_scan_doc kept at the top of its file (copied by
    value and cross-linked; a UT fixture locks the same-set property). There is no index
    rule field: see INDEX_CHECK_REASON (t261103-21)."""
    require_frontmatter: bool = True        # 是否查 frontmatter（非 md 约定项目可关）
    required_fields: Tuple[str, ...] = ("title", "category", "tags", "status", "updated")
    categories: Tuple[str, ...] = ("design", "content", "ops", "reference")
    statuses: Tuple[str, ...] = ("active", "draft", "deprecated")
    updated_re: str = r"^\d{4}-\d{2}-\d{2}$"
    ref_suffixes: Tuple[str, ...] = _REF_SUFFIXES


#: A self-check finding's shape: {check, path, detail}; check in root|frontmatter|ref
def _findings_add(out: List[Dict[str, str]], check: str, path: str, detail: str) -> None:
    out.append({"check": check, "path": path, "detail": detail})


def _parse_frontmatter(text: str) -> Optional[Dict[str, str]]:
    """极简 frontmatter 解析（首 --- 块内 key: value 平铺；解析不出=None，由调用方
    点名——不崩不假绿）。"""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    block = text[3:end]
    out: Dict[str, str] = {}
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        out[k.strip()] = v.strip()
    return out


def _extract_refs(text: str) -> List[str]:
    """显式路径引用提取（S10 同口径：反引号/markdown 链接、含 /、带已知后缀、
    排除 URL/锚点）。"""
    refs: List[str] = []
    for m in _REF_RE.finditer(text or ""):
        cand = (m.group(1) or m.group(2) or "").strip()
        if not cand or _REF_EXCLUDE_RE.match(cand) or "#" in cand:
            continue
        if "/" not in cand or not cand.lower().endswith(_REF_SUFFIXES):
            continue
        refs.append(cand)
    return refs


def _doc_selfcheck_run(repo_root: Path, docs_root: str,
                       rules: Optional[DocCheckRules] = None):
    """The self-check proper: (findings, pages judged). Two checks, both judged against
    the tree's OWN files (t261103-21 dropped the index leg -- INDEX_CHECK_REASON says
    where that coverage went):
      ① frontmatter (when rules.require_frontmatter);
      ② explicit path references, including the escape out of the tree (named).
    An IO fault degrades item by item with a named finding: never a crash, never a
    silent pass."""
    rules = rules or DocCheckRules()
    root = Path(repo_root)
    out: List[Dict[str, str]] = []
    docs = root / docs_root.rstrip("/")
    # The tree's own markdown pages under the declared root (rglob, sorted = deterministic)
    actual: List[str] = []
    if docs.is_dir():
        actual = sorted(
            (f"{docs_root.rstrip('/')}/{p.relative_to(docs).as_posix()}"
             for p in docs.rglob("*.md") if p.is_file()))
    elif not docs.exists():
        _findings_add(out, "root", docs_root, "documentation root absent: %s" % docs_root)
    # ---- ①②: per page, the frontmatter fields and the explicit references ----
    for rel in actual:
        f = root / rel
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            _findings_add(out, "frontmatter", rel,
                          "不可读：%s: %s" % (type(e).__name__, e))
            continue
        if rules.require_frontmatter:
            fm = _parse_frontmatter(text)
            if fm is None:
                _findings_add(out, "frontmatter", rel, "frontmatter 缺失或形态畸形")
            else:
                for k in rules.required_fields:
                    if not fm.get(k):
                        _findings_add(out, "frontmatter", rel,
                                      "frontmatter 字段 %s 缺空" % k)
                if fm.get("category") and fm["category"] not in rules.categories:
                    _findings_add(out, "frontmatter", rel,
                                  "category %r 词表外（%s）"
                                  % (fm["category"], "、".join(rules.categories)))
                if fm.get("status") and fm["status"] not in rules.statuses:
                    _findings_add(out, "frontmatter", rel,
                                  "status %r 词表外（%s）"
                                  % (fm["status"], "、".join(rules.statuses)))
                if fm.get("updated") and not re.match(rules.updated_re, fm["updated"]):
                    _findings_add(out, "frontmatter", rel,
                                  "updated %r 非 YYYY-MM-DD" % fm["updated"])
        for ref in _extract_refs(text):
            reason = _check_path_shape(ref)
            if reason:
                _findings_add(out, "ref", rel, "引用形态非法 %r（%s）" % (ref, reason))
                continue
            target = (root / rel).parent / ref if ref.startswith(("./", "../")) \
                else root / ref
            try:
                resolved = target.resolve()
                if not str(resolved).startswith(str(root.resolve())):
                    _findings_add(out, "ref", rel, "引用 %r 越出仓根" % ref)
                elif not resolved.exists():
                    _findings_add(out, "ref", rel, "引用 %r 目标不存在" % ref)
            except OSError as e:
                _findings_add(out, "ref", rel, "引用 %r 解析失败：%s" % (ref, e))
    return out, len(actual)


def doc_selfcheck(repo_root: Path, docs_root: str,
                  rules: Optional[DocCheckRules] = None) -> List[Dict[str, str]]:
    """The document self-check's findings (empty = pass). Runs on the LANE WORKTREE it
    judges; every check is against that tree's own files. Kept as the findings-only face
    for callers that only report a list; the full statement of what was and was not
    judged is doc_selfcheck_verdict."""
    return _doc_selfcheck_run(repo_root, docs_root, rules)[0]


def doc_selfcheck_verdict(repo_root: Path, docs_root: str,
                          rules: Optional[DocCheckRules] = None) -> Dict[str, Any]:
    """The self-check's full statement: the findings, what was judged, and what was not.

    Why a verdict and not a bare list (t261103-21): the index leg is gone, so a tree that
    holds no page -- or any tree at all -- can produce zero findings while judging little.
    An empty list would then read as "all clear". `not_judged` names the missing coverage
    and its owner instead, so the report never claims more than the checks did.
    """
    root = Path(repo_root)
    findings, pages = _doc_selfcheck_run(root, docs_root, rules)
    judged = {"tree": str(root), "docs_root": docs_root.rstrip("/"),
              "pages": pages, "checks": ["frontmatter", "ref"]}
    if not (rules or DocCheckRules()).require_frontmatter:
        judged["checks"] = ["ref"]
    not_judged: List[Dict[str, str]] = [
        {"check": "index", "owner": INDEX_CHECK_OWNER, "reason": INDEX_CHECK_REASON}]
    if pages == 0:
        not_judged.append({
            "check": "docs", "owner": "doc_selfcheck",
            "reason": ("no markdown page under %r in this tree: the frontmatter and "
                       "reference checks had nothing to judge" % (docs_root.rstrip("/")))})
    return {"findings": findings, "judged": judged, "not_judged": not_judged}


# ========================================================================================
# 受限可写 pin（produce 面；对比 readonly_pin_patch 只读钉）
# ========================================================================================

def produce_write_pin_patch(docs_root: str) -> str:
    """produce agent 的受限可写 pin patch（晚于既有 pin 追加=覆盖生效）。

    两层口径（如实声明，不静默降级）：
      - **沙箱层**：sandbox-policy mode=workspace-write（泳道工作区可写——不是只读钉，
        也不是 danger-full-access）；dsh 的 workspace-write 沙箱把写面钉在**工作区**
        粒度，「仅 docs_root 子树」的文件系统级收窄受当前 dsh 预设词表所限（预设
        不携带路径参数，readonly_pin_patch 260920 修正同源实证）。
      - **机械层**：docs_root 粒度的写集闸在本模块 check_write_set——越界改动在自检
        段 fail-closed 拒收并逐条点名（A2），泳道是一次性工作副本、落盘权在人审，
        越界写不进 main。两层合起来=「受限可写、越界必拒、路径必点名」。
    复用 readonly_pin_patch 的预设表形态（260920 修正：表内自带预设，不引用缺省表）。"""
    return (
        "# 本文件由 run_inspection_produce 每次 spawn 生成（t260925-01 产出型巡检"
        "受限可写 pin；写集口径=声明 docs_root=%s，机械闸=check_write_set fail-closed）。\n"
        "- id: sandbox-policy\n"
        "  disabled: false\n"
        "  config:\n"
        "    mode: 'workspace-write'\n"
        "- id: permission\n"
        "  disabled: false\n"
        "  config:\n"
        "    presets:\n"
        "      produce-doc-write:\n"
        "        sandbox: 'workspace-write'\n"
        "        approval: 'ask'\n"
        "        name: 'produce-doc-write'\n"
        "        description: 'Inspection produce mode: write within the lane workspace;"
        " declared docs root = %s (out-of-root changes are refused by the mechanical"
        " self-check and named)'\n"
        "    defaultPreset: 'produce-doc-write'\n" % (docs_root, docs_root))


# ========================================================================================
# prompt 构建（纯字符串函数，零 IO）
# ========================================================================================

def build_produce_prompt(instance_id: str, period: str, docs_root: str,
                         base_dir: str, base_ref: str) -> str:
    """produce 段 agent prompt：写面=声明 docs_root；零 change 须显式带证据；
    输出=末尾恰一块 ```json 围栏（强 schema 见模块头注）。"""
    return (
        "你是产出型巡检（inspection produce mode）的文档巡检员。实例=%s 期=%s。\n"
        "工作副本（你的泳道）：%s（基点 %s）。\n\n"
        "任务：审查 %s 目录下的文档，找出该修的地方（漂移、烂链接、索引不一致、"
        "frontmatter 缺漏、内容过时），并**直接把修好的文件写进泳道**。\n"
        "写面红线：只许改 %s 下的文件；代码、代码注释、integration/、notes/ 一律"
        "不在写集——越界改动会被机械自检拒收并逐条点名，等于白做。不派生子代理。\n\n"
        "零 change 纪律：本期确实无可改，就一处都不许动（不许为凑数造假改动），"
        "并在围栏里 zero_change=true 且 evidence 给出「为什么无可改」的核查证据。\n\n"
        "完成后，最终消息末尾恰一块 ```json 围栏：\n"
        '```json\n{"changes": [{"path": "%s/xxx.md", "action": "modify",'
        ' "summary": "人读摘要"}], "zero_change": false, "evidence": []}\n'
        "```\n"
        "changes 列出你实际写动的每个文件（action: add|modify|delete）；"
        "path 用仓内相对 posix 路径。\n"
        % (instance_id, period, base_dir, base_ref or "main HEAD",
           docs_root, docs_root, docs_root))


# ========================================================================================
# 人审门载荷校验（纯函数；workflow signal 面消费）
# ----------------------------------------------------------------------------------------
# close 门签字校验单一真源=inspection_flow.validate_close_signature（expected_gate
# 传 PRODUCE_CLOSE_GATE_ID）——本模块不再复制第二份（验收 gen0 遗留1：语义重复收敛）。
# ========================================================================================

def validate_authorize_payload(sig: Any, protected_overlap: List[str],
                               expected_gate: str = PRODUCE_AUTHORIZE_GATE_ID) -> Tuple[Dict[str, Any], str]:
    """保护面授权载荷校验（A3 同票窄通）：who 是人 + gate 匹配 + paths 必须是本期
    报告 protected_overlap 的**子集**（清单外保护文件不因一次授权被一并放行）。"""
    if isinstance(sig, dict):
        raw = {"who": str(sig.get("who") or ""),
               "note": str(sig.get("note") or ""),
               "gate": str(sig.get("gate") or ""),
               "paths": sig.get("paths")}
    else:
        raw = {"who": str(getattr(sig, "who", "") or ""),
               "note": str(getattr(sig, "note", "") or ""),
               "gate": str(getattr(sig, "gate", "") or ""),
               "paths": getattr(sig, "paths", None)}
    if not raw["who"].strip():
        return {}, "授权缺 who（授权身份由调用方注入）"
    if raw["gate"] != expected_gate:
        return {}, "授权 gate 不匹配：%r（本门=%r）" % (raw["gate"], expected_gate)
    paths = raw["paths"]
    if not isinstance(paths, list) or not paths or \
            any(not isinstance(p, str) or not p.strip() for p in paths):
        return {}, "授权 paths 缺空或含非字符串（逐文件显式授权，不整批放行）"
    paths = [p.strip() for p in paths]
    overlap = set(protected_overlap or [])
    outside = [p for p in paths if p not in overlap]
    if outside:
        return {}, "授权清单超出本期 protected_overlap：%s（窄通只对报告点名过的文件）" \
            % "、".join(sorted(outside))
    return {"who": raw["who"], "note": raw["note"], "gate": raw["gate"],
            "paths": paths}, ""

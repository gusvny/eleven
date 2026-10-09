"""inspection_decl — inspection declaration reader/validator (inspection epic
ticket 1, t260905-03).

The mechanism lives in the engine, the scheduling face lives in the project declaration: this
module does exactly one thing, "declaration file → structured instance table", which
the scheduling and ticket-opening machinery (inspection_trigger.py /
InspectionPeriodicWorkflow) consumes.

Settled design (preconditions from review_plan conditional-pass comments C1-C3 + M2/M4):
  - Location: a standalone inspection.yaml (not inside verify.yaml — that is the
    per-ticket re-verification gate; inspection scheduling belongs to the timer domain,
    and stuffing it in means semantic drift plus a wider engine whitelist. What
    "same family as ui_evidence" really means is the "mechanism in the engine, scheduling
    face in the project declaration" principle, not the same file).
  - Parser: a **zero-dependency YAML subset parser** (runs in the docker test image /
    scenario lane / locally, stdlib only). It accepts only the subset declared in this
    header; anything outside the subset fails closed with an error naming the line
    number — no guessing, no silent degradation. Two parsers would inevitably drift, so
    no pyyaml dual track.
  - Unwired kinds (M2): KNOWN_KINDS holds every "documented kind", WIRED_KINDS only the
    wired ones. An **enabled instance** declaring an unwired kind → explicit error
    naming the wired list; disabled instances are allowed (disabled = pure placeholder,
    never triggers; the declaration is documentation). "Parses fine but silently never
    triggers at runtime" is never acceptable.
  - Path (t260916-02 声明落位迁移A 后的三层): **生产面=每项目仓内单文件**——默认
    `<注册条目主目录 dirs[0]>/inspection.yaml`，`project.yaml` 的 `paths.inspection_decl`
    可指路（绝对/机器级 `~/…`/相对皆可，校验同 paths.model_routes 放宽口径）；聚合消费面
    遍历注册项目读各自声明（iter_project_decls / load_decl_for_instance）。**测试覆盖层=env
    SANDBAR_INSPECTION_DECL**（单文件整体替代聚合；巡检场景族夹具全靠它，语义仅限测试——
    生产禁用，降级路径写进 README §13）；显式 --decl-path（夹具注入）优先级最高。旧「引擎仓
    单文件缺省」已退役（server/engine/inspection.yaml 迁至 sandbar 项目仓根，样例模板=
    docs/inspection-sample.yaml）。

YAML subset grammar (each rule pinned by a unit test):
  - Indentation is spaces only, tabs forbidden; fixed levels: root mapping (0) →
    instance list item (- at 2) → instance keys (4) → schedule mapping (6) →
    schedule keys (8).
  - Only five line shapes: blank / full-line comment (starting with #,
    leading spaces allowed) / `key: scalar` / `key:` (opens a sub-structure) /
    `- key: scalar` (a list item's first key; continuation keys use same-level
    `key: scalar`).
  - Scalars are taken as strings verbatim (no type inference); booleans accept only the
    true/false literals; trailing whitespace is stripped; `#` is never truncated
    mid-line (cron `*` and friends stay safe).
  - Duplicate keys / a key with two shapes (both a scalar and an open sub-structure) /
    a list item inside a sub-structure → error.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from inspection_inspect import (DEFAULT_INSPECT_TIMEOUT_MIN, DEFAULT_MAX_FINDINGS,
                                DEFAULT_MAX_FILES_PER_SHARD, DEFAULT_MAX_SHARDS,
                                PROFILE_FACES)
# lane/watchdog 面阈值（260926，KI-122 追加面）：**单源**在 inspection_lane_watchdog
# （纯函数模块，零 IO）——声明解析件只做词法/范围校验，值语义与运行期回落规则同源，
# 绝不在这里另造一份缺省（两套默认值必然漂移）。第四判据（测试夹具临时目录水位，
# 260926 同批）走同一份合并字典 WATCHDOG_ALL_*（票级三键 + 水位两键）。
from inspection_lane_watchdog import (WATCHDOG_ALL_DEFAULTS, WATCHDOG_ALL_KEYS,
                                      WATCHDOG_ALL_RANGES, WATCHDOG_DEFAULTS,
                                      WATCHDOG_KEYS, WATCHDOG_RANGES)
# t261006-13 shared-surface vocabulary: single source in inspection_surface (pure
# module) — same no-duplicate-defaults discipline as the watchdog keys above.
from inspection_surface import (DEFAULT_MIN_NEW_SCENARIOS, DEFAULT_MIN_SURFACE_FILES,
                                DEFAULT_SHARED_SCAN_OWNER, SHARED_SCAN_NAMES,
                                SURFACE_THRESHOLD_KEYS)

DECL_FILE_NAME = "inspection.yaml"

# kind vocabulary: KNOWN = the full documented set (legal to appear in a declaration),
# WIRED = the subset the engine has actually wired (the whitelist for enabled instances).
KNOWN_KINDS = ("cron", "every-n-tickets", "race-first")
# t260911-02：every-n-tickets / race-first 接线（计数真源=归档目录，见
# inspection_ticket_count.py 头注）。未知 kind 仍 fail-closed（KNOWN 之外的启用/禁用
# 声明一律报错点名）——接线只扩白名单，不扩词法。
WIRED_KINDS = ("cron", "every-n-tickets", "race-first")
# Whitelist of inspection workflow type names the engine has wired and a declaration may
# name (fail-closed so a declaration cannot point at a nonexistent workflow and then
# silently never trigger — same spirit as M2).
WIRED_WORKFLOWS = ("InspectionPeriodicWorkflow", "InspectionProduceWorkflow")
# 计数源词表（t260911-02）：现在只接了归档目录一源；扩源必须先扩此表+计数模块。
TICKET_COUNT_SOURCES = ("archive-dir",)
# 扫描面词表（t260911-02）：实例可声明 scan_face 指定跑哪个扫描器（「跑哪个巡检面」
# 由项目声明决定——拍板③原文）；缺省 test（票① 行为兼容，零声明实例不回退不报错）。
# stage 面接线（t260915-18）：台面容量可见性（stage_docker inventory 只读清点）。
# t260916-22：静态扫描器退役后，本表语义延续为「巡检面」词表（scan_face 声明键保留，
# inspect_profile 缺省回落它）；与 inspect 分面词表 PROFILE_FACES 的同集锁在下方。
WIRED_FACES = ("test", "doc", "stage", "mechanism", "simplify")
# 同集锁（t260916-22）：WIRED_FACES（声明侧面词表）与 PROFILE_FACES（prompt 分面清单
# 键集，真源=inspection_inspect）此刻必须同集——扩面两表同扩，漂移=import 即炸
# （t260916-05 双真源锁同款纪律；这里是纯模块级断言，零成本）。
if set(WIRED_FACES) != set(PROFILE_FACES):
    raise AssertionError("WIRED_FACES %s 与 inspect 分面词表 PROFILE_FACES %s 漂移——"
                         "扩面须两表同扩（t260916-22）" % (WIRED_FACES, PROFILE_FACES))
# 套件词表（t260913-02）：实例可声明 suite 指定「本期是否在自己的泳道里跑集成全集」。
# 现在只接 full 一档——全集就是全集，不接受任何「抽稀/跳场景」的值（红线：不得以
# 跳过或删减场景换取跑通）；缺省空=不跑套件（票① 行为兼容，零声明实例不报错不回退）。
# 词表外值一律 fail-closed 点名，不静默降级成 no-suite。
WIRED_SUITES = ("full",)
# 时区词法（t260913-02 实现段）：Temporal Schedule 的 cron 默认按 **UTC** 求值——声明
# 里的人读钟点（07:30=本地）必须显式带 tz 才成立，否则「每天 07:30」实际落在本地 15:30。
# 引擎只做词法闸（IANA 名的保守字面），真正的时区存在性由 Temporal 拒绝并点名。
TZ_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-/]{0,63}$")
SCHEMA = "v1"
INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Five-field cron lexicon: `*` `*/n` `n` `n-m` `n-m/n` `n,m` (comma lists); the month and
# weekday fields also allow three-letter names.
_CRON_ATOM = r"(?:\*|\*/\d+|\d+|\d+-\d+(?:/\d+)?|[a-z]{3}(?:-[a-z]{3})?)"
_CRON_FIELD_RE = re.compile(r"^%s(?:,%s)*$" % (_CRON_ATOM, _CRON_ATOM))
BOOL_RE = re.compile(r"^(true|false)$")

# ---- 巡检模式两键（t260925-01 产出型巡检底座）----
# mode：report=只报告（现状，缺省=未声明零行为变化，A6）；produce=产出型（agent 在
# 自有泳道内产 change，机械自检后交人审 merge/discard）。词表外 fail-closed 点名。
WIRED_MODES = ("report", "produce")
DEFAULT_MODE = "report"
# docs_root：产出型实例的文档根（A6：引擎缺省 docs/，无 sandbar 专属路径硬编码）。
# 词法=仓内相对 posix 路径：禁绝对路径、禁 .. 段（防越根逃逸）、禁空/尾斜杠。
DEFAULT_DOCS_ROOT = "docs"
DOCS_ROOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]*$")


def validate_docs_root(where: str, value: str) -> str:
    """docs_root 词法闸（纯函数便于 UT）：非法一律 DeclError 点名。"""
    if not DOCS_ROOT_RE.match(value) or value.endswith("/"):
        raise DeclError("%s：docs_root %r 非法（仓内相对 posix 路径，如 docs；"
                        "禁绝对路径/空/尾斜杠）" % (where, value))
    if any(seg == ".." for seg in value.split("/")):
        raise DeclError("%s：docs_root %r 含 .. 段（越根逃逸禁入）" % (where, value))
    return value


class DeclError(Exception):
    """Malformed or out-of-scope declaration — fail-closed; the message names the problem
    and its location, never a default fallback."""


@dataclass
class InstanceSpec:
    """One inspection instance (the anchor for everything declaration-driven).

    项目身份两字段分工（t260915-20，全案统一口径）：
      - instance_project_key = **实例级身份**：本实例巡检票归属哪个项目（声明实例键
        `project_key`，解析后落本字段；驱动起票 ProjectKey SA 与 repo_root 注册表解析）；
      - project_key = **schedule 级计数源**（仅计数 kind，schedule 作用域下的
        `project_key`）：every-n-tickets/race-first 数谁家的票。
      二者作用域不同不撞键，且绝不互串（串键=静默错挂，t260915-20 R2 的教训）。
    """

    id: str
    enabled: bool
    kind: str
    cron: str = ""
    n: int = 0
    source: str = ""
    project_key: str = ""
    # 实例级项目身份（t260915-20）：声明实例键 project_key → 本字段；所有实例必填
    # （enabled 与否——身份不是调度细节，无身份的占位实例=无主票预定席）。
    instance_project_key: str = ""
    scan_face: str = "test"
    # 巡检模式两键（t260925-01）：mode=report（缺省，只报告）| produce（产出型）；
    # docs_root=产出型实例的文档根（引擎缺省 docs/，A6 无项目硬编码）。
    mode: str = DEFAULT_MODE
    docs_root: str = DEFAULT_DOCS_ROOT
    # 套件档（t260913-02）：空=不跑套件；"full"=本期在巡检自有泳道里跑集成全集。
    suite: str = ""
    # 巡检预算三键（t260916-22，宿主裁定③：预算可配置起步 40 条/30 分钟 + 分面清单）：
    #   - max_findings：本期新发现条数上限（超截并注明，recurring/压制不占预算）；
    #   - inspect_timeout_min：inspect 段 agent 预算（分钟；超时=「agent 未完成」不假绿）；
    #   - inspect_profile：prompt 分面清单（PROFILE_FACES 词表；空=回落 scan_face）。
    max_findings: int = DEFAULT_MAX_FINDINGS
    inspect_timeout_min: int = DEFAULT_INSPECT_TIMEOUT_MIN
    inspect_profile: str = ""
    # 缩面硬上限两键（t260924-06）：inspect 分片（子代理）数与每片文件数机械封顶——
    # 防「7 子代理审 368 个场景文件」式无界扇出复发。
    inspect_max_shards: int = DEFAULT_MAX_SHARDS
    inspect_max_files_per_shard: int = DEFAULT_MAX_FILES_PER_SHARD
    # Review-ledger rotation slice (t261006-12): review_slice=None = not set in
    # the declaration (the activity side applies the profile default: simplify
    # on, the other faces off); slice_min/max=0 = activity-side default 40/60.
    review_slice: Optional[bool] = None
    slice_min: int = 0
    slice_max: int = 0
    # lane/watchdog 面阈值档（260926，KI-122 追加面）：声明原值（YAML 子集无类型推断，
    # 逐字 str）——解析期已过词法/范围校验；运行期由 inspection_lane_watchdog.
    # resolve_thresholds 归一并在面/回执上点名来源（declaration|default）。空=全缺省。
    watchdog: Dict[str, str] = field(default_factory=dict)
    # t261006-13 shared-surface keys:
    #   shared_scans: {scan-name → owner instance id} — the public scan (only
    #     "lane-watchdog" is wired) lands in the OWNER face; other faces keep a
    #     reference line (design 261004 §5 discipline 2). Unwired scan name or empty
    #     owner id → fail-closed.
    #   surface_thresholds: {min_surface_files, min_new_scenarios} — B3 coverage
    #     self-check bar; positive ints; missing keys fall back to the engine defaults
    #     in inspection_surface (the front page always prints the bar actually used).
    shared_scans: Dict[str, str] = field(default_factory=dict)
    surface_thresholds: Dict[str, str] = field(default_factory=dict)
    # 无新变更则空转（260929 宿主令，simplify-face）：true=起票前比对「上次运行的基点 sha
    # 与当前 main HEAD」，相同则本期不铸票不跑（仍落一行裁决记录，漏跑核查据此不误报）；
    # 读不出/形态不合=不跳（宁可多跑一次，绝不假跳）。
    skip_when_unchanged: bool = False
    # 调度时区（t260913-02 实现段）：空=Temporal 缺省（UTC）；填 IANA 名（如 Asia/Shanghai）
    tz: str = ""
    workflow: str = ""
    template: str = ""


@dataclass
class InspectionDecl:
    """The structured form of a whole declaration."""

    schema: str
    instances: List[InstanceSpec] = field(default_factory=list)
    source: str = ""

    def instance(self, instance_id: str) -> Optional[InstanceSpec]:
        for it in self.instances:
            if it.id == instance_id:
                return it
        return None

    def enabled_instances(self) -> List[InstanceSpec]:
        return [it for it in self.instances if it.enabled]


def default_decl_path() -> Path:
    """**历史兼容缺省路径**（t260916-02 起）：env 覆盖层路径；env 未设=引擎仓旧位（该文件
    已迁往项目仓根，此缺省仅服务历史调用点/报错信息——生产消费面一律走聚合
    iter_project_decls / load_decl_for_instance，绝不把本缺省当真源）。"""
    env = os.environ.get("SANDBAR_INSPECTION_DECL")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / DECL_FILE_NAME


def coverage_decl_path() -> str:
    """测试覆盖层单点（t260916-02）：env `SANDBAR_INSPECTION_DECL` 非空（strip 后）=单文件
    整体替代聚合遍历——巡检场景族夹具的兼容缝。**仅测试语义**：它让「面」脱离项目注册表
    落位，生产环境设置它=配置事故（聚合被静默短路成单文件），消费方回执必须带 coverage
    标记让人看见（见 iter_project_decls）。"""
    return (os.environ.get("SANDBAR_INSPECTION_DECL") or "").strip()


# ========================================================================================
# YAML subset parser (accepts only the header-declared grammar; every excursion = fail-closed)
# ========================================================================================

class _Line:
    __slots__ = ("no", "indent", "text", "kind")

    def __init__(self, no: int, indent: int, text: str, kind: str) -> None:
        self.no = no            # 1-based line number (for naming in error messages)
        self.indent = indent
        self.text = text        # the effective content after de-indenting (comments stripped)
        self.kind = kind        # blank | comment | kv | open | item


def _tokenize(text: str) -> List[_Line]:
    lines: List[_Line] = []
    for no, raw in enumerate(text.splitlines(), start=1):
        lead = re.match(r"[\t ]*", raw).group()
        if "\t" in lead:
            raise DeclError("第 %d 行：缩进含 tab（子集只允许空格缩进）" % no)
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        body = raw[indent:].rstrip()
        if body.startswith("- "):
            lines.append(_Line(no, indent, body[2:].strip(), "item"))
            continue
        if ":" not in body:
            raise DeclError("第 %d 行：无法识别的行形态（子集只允许 key: 标量 / key: / - key: 标量）：%r"
                            % (no, body))
        key, _, val = body.partition(":")
        key = key.strip()
        val = val.strip()
        if not key or (" " in key) or ("-" == key[:1]):
            raise DeclError("第 %d 行：键非法：%r" % (no, key))
        if val == "":
            lines.append(_Line(no, indent, key, "open"))
        else:
            lines.append(_Line(no, indent, "%s\x00%s" % (key, val), "kv"))
    return lines


def _split_kv(text: str) -> tuple:
    key, _, val = text.partition("\x00")
    return key, val


def _parse_mapping(lines: List[_Line], pos: int, indent: int, ctx: str) -> tuple:
    """Parse one mapping level (consecutive kv/open at the same indent); returns
    (mapping, next_pos)."""
    out: Dict[str, Any] = {}
    i = pos
    while i < len(lines):
        ln = lines[i]
        if ln.indent < indent:
            break
        if ln.indent > indent:
            raise DeclError("第 %d 行：意外加深缩进（子集层级固定，%s 处）" % (ln.no, ctx))
        if ln.kind == "item":
            raise DeclError("第 %d 行：映射层出现列表项（- 只允许实例列表首键）：%r" % (ln.no, ln.text))
        if ln.kind == "open":
            if ln.text in out:
                raise DeclError("第 %d 行：键重复：%s" % (ln.no, ln.text))
            child, i2 = _parse_child(lines, i + 1, indent, ln.text)
            out[ln.text] = child
            i = i2
            continue
        key, val = _split_kv(ln.text)
        if key in out:
            raise DeclError("第 %d 行：键重复：%s" % (ln.no, key))
        out[key] = val
        i += 1
    return out, i


def _parse_child(lines: List[_Line], pos: int, parent_indent: int, ctx: str) -> tuple:
    """Parse an open key's sub-structure: a deeper mapping, or a sequence of list items
    (the instance table). List items may sit deeper than their opening key (the YAML
    convention); the first list item's indent becomes the list's base level."""
    if pos >= len(lines) or lines[pos].indent <= parent_indent:
        raise DeclError("第 %d 行：%s 开了子结构但无内容" % (lines[pos - 1].no if pos else 0, ctx))
    if lines[pos].kind == "item":
        return _parse_item_list(lines, pos, lines[pos].indent, ctx)
    return _parse_mapping(lines, pos, lines[pos].indent, ctx)


def _parse_item_list(lines: List[_Line], pos: int, indent: int, ctx: str) -> tuple:
    """Instance list: starts with `- key: scalar` (all at the same base indent);
    continuation keys are kv/open at indent+2."""
    items: List[Dict[str, Any]] = []
    i = pos
    while i < len(lines):
        ln = lines[i]
        if ln.indent < indent or (ln.indent == indent and ln.kind != "item"):
            break
        if ln.kind != "item" or ln.indent != indent:
            raise DeclError("第 %d 行：列表项形态/缩进非法：%r" % (ln.no, ln.text))
        item: Dict[str, Any] = {}
        # The item line is raw text (not tokenized as kv), so split key: scalar here
        ikey, _, ival = ln.text.partition(":")
        ikey = ikey.strip()
        if not ikey or not ival.strip():
            raise DeclError("第 %d 行：列表项首键必须 key: 标量形态：%r" % (ln.no, ln.text))
        item[ikey] = ival.strip()
        i += 1
        # Continuation keys: kv/open at indent+2
        while i < len(lines) and lines[i].indent == indent + 2:
            cont = lines[i]
            if cont.kind in ("item", "comment"):
                break
            if cont.kind == "open":
                if cont.text in item:
                    raise DeclError("第 %d 行：键重复：%s" % (cont.no, cont.text))
                child, i2 = _parse_child(lines, i + 1, cont.indent, cont.text)
                item[cont.text] = child
                i = i2
                continue
            key2, val2 = _split_kv(cont.text)
            if key2 in item:
                raise DeclError("第 %d 行：键重复：%s" % (cont.no, key2))
            item[key2] = val2
            i += 1
        items.append(item)
    return items, i


def parse_decl_text(text: str, source: str = "<text>") -> InspectionDecl:
    """Text entry point: subset-grammar parsing + structural validation (fail-closed)."""
    lines = _tokenize(text)
    if not lines:
        raise DeclError("%s：声明为空" % source)
    root, _ = _parse_mapping(lines, 0, 0, "根")
    return decl_from_mapping(root, source=source)


def load_inspection_decl(path: Optional[Path] = None) -> InspectionDecl:
    """File entry point (the env path single point is default_decl_path). A failed read
    is an explicit error."""
    p = Path(path) if path else default_decl_path()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise DeclError("声明文件不可读：%s（%s）" % (p, e)) from e
    return parse_decl_text(text, source=str(p))


# ========================================================================================
# Structural validation (every malformed input is named in a DeclError)
# ========================================================================================

def _req_str(where: str, data: Dict[str, Any], key: str, no: str = "") -> str:
    val = data.get(key)
    if val is None:
        raise DeclError("%s：缺必填字段 %s%s" % (where, key, no))
    if not isinstance(val, str) or not val.strip():
        raise DeclError("%s：%s 必须是非空标量（got %r）" % (where, key, val))
    return val.strip()


def _validate_watchdog(where: str, raw: Any) -> Dict[str, str]:
    """lane/watchdog 阈值档校验（260926，KI-122 追加面 + 第四判据水位档 t260926 同批）：
    缺省段=空档（全缺省值）；非映射/未知键/非正整数或越界 → DeclError 点名（与 inspect 预算键
    同款 fail-closed 纪律）。范围与缺省**同源**自 inspection_lane_watchdog（票级三键 +
    水位两键的合并字典 WATCHDOG_ALL_RANGES/DEFAULTS）——本函数只做词法闸，值语义单点在
    runtime resolve_thresholds / resolve_tmp_thresholds /
    resolve_suite_duration_thresholds (the t261008-43 suite-duration pair)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DeclError("%s：watchdog 必须是映射（got %r；合法键：%s）"
                        % (where, raw, "/".join(WATCHDOG_ALL_KEYS)))
    unknown = sorted(set(raw) - set(WATCHDOG_ALL_KEYS))
    if unknown:
        raise DeclError("%s：watchdog 未知字段 %s（合法：%s）"
                        % (where, unknown, "/".join(WATCHDOG_ALL_KEYS)))
    what = {"rerun_rounds": "同票重跑轮次阈值",
            "fault_loop_min": "tests-fault 回路停留阈值（分钟）",
            "inflight_silent_min": "在飞静默阈值（分钟）",
            "tmp_fixture_max_dirs": "测试夹具临时目录数水位（第四判据；目录数上界）",
            "tmp_fixture_max_age_h": "fixture tmp water-level: oldest dir age (4th criterion, hours)",
            "suite_slow_round_min": "suite whole-round duration threshold (minutes; t261008-43 slow-round finding)",
            "suite_slow_scenario_sec": "suite per-scenario duration outlier threshold (seconds; t261008-43)"}
    out: Dict[str, str] = {}
    for k in WATCHDOG_ALL_KEYS:
        if k not in raw:
            continue
        v = raw[k]
        lo, hi = WATCHDOG_ALL_RANGES[k]
        if not isinstance(v, str) or not re.match(r"^\d+$", v) or not (lo <= int(v) <= hi):
            raise DeclError("%s：watchdog.%s %r 非法（正整数 %d~%d；缺省 %d——本项=%s）"
                            % (where, k, v, lo, hi, WATCHDOG_ALL_DEFAULTS[k], what[k]))
        out[k] = v
    return out


def _validate_shared_scans(where: str, raw: Any) -> Dict[str, str]:
    """shared_scans validation (t261006-13, B4 public-scan cross-face ownership): the
    scan name must be in the wired vocabulary and the owner instance id a non-empty
    lowercase slug (same lexicon as instance ids) — anything else fails closed with a
    named error ("who owns it" written wrong = the whole dedupe is dead; never guess).
    Missing section = empty (engine default owner inspection_surface.DEFAULT_SHARED_SCAN_OWNER)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DeclError("%s：shared_scans must be a mapping {scan-name: owner-instance-id} "
                        "(got %r; wired scan names: %s)"
                        % (where, raw, "/".join(SHARED_SCAN_NAMES)))
    out: Dict[str, str] = {}
    for scan, owner in raw.items():
        if scan not in SHARED_SCAN_NAMES:
            raise DeclError("%s：shared_scans scan name %r is not wired (valid: %s)"
                            % (where, scan, "/".join(SHARED_SCAN_NAMES)))
        if not isinstance(owner, str) or not INSTANCE_ID_RE.match(owner.strip()):
            raise DeclError("%s：shared_scans.%s owner instance id invalid %r (lowercase "
                            "slug, same lexicon as instance ids)" % (where, scan, owner))
        out[scan] = owner.strip()
    return out


def _validate_surface_thresholds(where: str, raw: Any) -> Dict[str, str]:
    """surface_thresholds validation (t261006-13, B3 coverage self-check bar): the two
    documented keys, non-negative integer literals (0 is legal = "any surface counts as
    reviewable"); unknown keys / malformed values fail closed with a named error.
    Missing section = engine defaults (inspection_surface.DEFAULT_*); the front-page
    coverage block always prints the thresholds actually used."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DeclError("%s：surface_thresholds must be a mapping (got %r; valid keys: %s)"
                        % (where, raw, "/".join(SURFACE_THRESHOLD_KEYS)))
    unknown = sorted(set(raw) - set(SURFACE_THRESHOLD_KEYS))
    if unknown:
        raise DeclError("%s：surface_thresholds unknown keys %s (valid: %s)"
                        % (where, unknown, "/".join(SURFACE_THRESHOLD_KEYS)))
    out: Dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(v, str) or not re.match(r"^\d+$", v):
            raise DeclError("%s：surface_thresholds.%s %r invalid (non-negative integer "
                            "literal; defaults min_surface_files=%d / min_new_scenarios=%d)"
                            % (where, k, v, DEFAULT_MIN_SURFACE_FILES,
                               DEFAULT_MIN_NEW_SCENARIOS))
        out[k] = v
    return out


def _validate_schedule(where: str, sched: Any, enabled: bool) -> tuple:
    if not isinstance(sched, dict):
        raise DeclError("%s：schedule 必须是映射（got %r）" % (where, sched))
    unknown = sorted(set(sched) - {"kind", "cron", "n", "source", "project_key"})
    if unknown:
        raise DeclError("%s：schedule 未知字段 %s（合法：cron/n/kind）" % (where, unknown))
    kind = _req_str(where, sched, "kind")
    if kind not in KNOWN_KINDS:
        raise DeclError("%s：schedule.kind 未知 %r（文档化 kind：%s）"
                        % (where, kind, "、".join(KNOWN_KINDS)))
    if enabled and kind not in WIRED_KINDS:
        raise DeclError("%s：schedule.kind %r 未接线（已接线：%s）——启用实例只允许已接线"
                        " kind，禁用实例才可作占位声明"
                        % (where, kind, "、".join(WIRED_KINDS)))
    cron = ""
    n = 0
    if kind in ("cron", "race-first"):   # race-first 的 cron 侧与 cron kind 同词法
        if kind == "cron" and sched.get("n") is not None:
            raise DeclError("%s：n 只属于计数 kind（every-n-tickets/race-first），cron 实例"
                            "声明了 n——多余字段 fail-closed" % where)
        if kind == "race-first" and not enabled and not sched.get("cron"):
            # race-first 禁用占位允许缺 cron（占位=纯声明文档，同 source 的占位豁免口径）
            cron = ""
        else:
            cron = _req_str(where, sched, "cron")
        if cron:
            fields = cron.split()
            if len(fields) != 5 or any(not _CRON_FIELD_RE.match(f) for f in fields):
                raise DeclError("%s：cron 非法 %r（需五字段，词法 * */n n n-m n-m/n 名称/逗号列表）"
                                % (where, cron))
            # Numeric fields (per-field validation of bare values; fields containing */ranges/
            # lists are left to the scheduler's semantics — here we only stop a bare value
            # out of range)
            _CRON_MAX = (59, 23, 31, 12, 7)
            for pos, (f, top) in enumerate(zip(fields, _CRON_MAX)):
                if f.isdigit() and int(f) > top:
                    raise DeclError("%s：cron 第 %d 域 %s 超出数值域（≤%d）" % (where, pos + 1, f, top))
    source = ""
    project_key = ""
    if kind in ("every-n-tickets", "race-first"):
        n_raw = sched.get("n")
        try:
            n = int(str(n_raw))
        except (TypeError, ValueError):
            raise DeclError("%s：n 必须是整数（got %r）" % (where, n_raw)) from None
        if n < 1 or n > 10000:
            raise DeclError("%s：n 超出合理区间（1–10000）：%d" % (where, n))
        # 计数源必须显式声明且在已接线词表内（fail-closed：不猜默认源——「取数面可配置
        # 且确定」是本票验收前提，缺声明=报错点名，绝不静默回退）。enabled=false 占位
        # 豁免必填（占位=纯声明文档，不调度不触发；但给了就照词法校验，不因禁用放行坏值）。
        source = str(sched.get("source") or "")
        project_key = str(sched.get("project_key") or "")
        if enabled:
            if not source:
                raise DeclError("%s：缺必填字段 source（计数源词表：%s）"
                                % (where, "、".join(TICKET_COUNT_SOURCES)))
            if not project_key:
                raise DeclError("%s：缺必填字段 project_key（计数取数面的项目 key）" % where)
        if source:
            if source not in TICKET_COUNT_SOURCES:
                raise DeclError("%s：ticket 计数源 %r 未接线（已接线：%s）"
                                % (where, source, "、".join(TICKET_COUNT_SOURCES)))
            if not INSTANCE_ID_RE.match(project_key):
                raise DeclError("%s：project_key 非法 %r（小写 slug，同实例 id 词法）"
                                % (where, project_key))
    elif sched.get("source") or sched.get("project_key"):
        raise DeclError("%s：source/project_key 只属于计数 kind（every-n-tickets/race-first），"
                        "cron 实例声明了 %s——多余字段 fail-closed"
                        % (where, "、".join(k for k in ("source", "project_key") if sched.get(k))))
    return kind, cron, n, source, project_key


def decl_from_mapping(data: Any, source: str = "<mapping>") -> InspectionDecl:
    """Mapping entry validation (the common narrow gate after text parsing; unit tests
    feed dicts directly to reproduce malformed shapes)."""
    if not isinstance(data, dict):
        raise DeclError("%s：声明根必须是映射（got %s）" % (source, type(data).__name__))
    unknown_top = sorted(set(data) - {"schema", "instances"})
    if unknown_top:
        raise DeclError("%s：未知顶层键 %s（引擎按未知键 fail-closed；合法：schema/instances）"
                        % (source, unknown_top))
    schema = data.get("schema")
    if schema != SCHEMA:
        raise DeclError("%s：schema 必须 %r（got %r）" % (source, SCHEMA, schema))
    inst_raw = data.get("instances")
    if not isinstance(inst_raw, list) or not inst_raw:
        raise DeclError("%s：instances 必须是非空列表" % source)
    seen_ids = set()
    instances: List[InstanceSpec] = []
    for idx, item in enumerate(inst_raw):
        where = "%s instances[%d]" % (source, idx)
        if not isinstance(item, dict):
            raise DeclError("%s：实例必须是映射（got %s）" % (where, type(item).__name__))
        unknown = sorted(set(item) - {"id", "enabled", "schedule", "workflow", "template",
                                      "scan_face", "suite", "tz", "project_key",
                                      "max_findings", "inspect_timeout_min",
                                      "inspect_profile", "inspect_max_shards",
                                      "inspect_max_files_per_shard",
                                      "mode", "docs_root", "watchdog",
                                      "skip_when_unchanged",
                                      "review_slice", "slice_min", "slice_max",
                                      "shared_scans", "surface_thresholds"})
        if unknown:
            raise DeclError("%s：未知实例字段 %s（合法：id/enabled/schedule/workflow/template/"
                            "scan_face/suite/tz/project_key（实例级项目身份，t260915-20）/"
                            "max_findings/inspect_timeout_min/inspect_profile（inspect 段预算三键，"
                            "t260916-22）/inspect_max_shards/inspect_max_files_per_shard"
                            "（缩面分片硬上限两键，t260924-06）/mode/docs_root（巡检模式两键，"
                            "t260925-01）/watchdog（lane 巡检面阈值档三键，260926）/"
                            "skip_when_unchanged (idle when nothing changed, host order "
                            "260929)/review_slice, slice_min, slice_max (review-ledger "
                            "rotation slice, t261006-12)/shared_scans, surface_thresholds "
                            "(t261006-13: public-scan ownership / coverage self-check "
                            "thresholds); "
                            "face 已于 260910 巡检校准票 t260910-11 除名——零消费者，旧声明含 face 一律拒收点名）"
                            % (where, unknown))
        inst_id = _req_str(where, item, "id")
        if not INSTANCE_ID_RE.match(inst_id):
            raise DeclError("%s：id 非法 %r（小写 slug：^[a-z0-9][a-z0-9-]{0,63}$）" % (where, inst_id))
        if inst_id in seen_ids:
            raise DeclError("%s：实例 id 重复：%s" % (where, inst_id))
        seen_ids.add(inst_id)
        enabled_raw = item.get("enabled")
        if not isinstance(enabled_raw, str) or not BOOL_RE.match(enabled_raw):
            raise DeclError("%s：enabled 只认 true/false 字面（got %r）" % (where, enabled_raw))
        enabled = enabled_raw == "true"
        workflow_name = _req_str(where, item, "workflow")
        if workflow_name not in WIRED_WORKFLOWS:
            raise DeclError("%s：workflow %r 未接线（可指名：%s）——防声明指空后静默不触发"
                            % (where, workflow_name, "、".join(WIRED_WORKFLOWS)))
        template = _req_str(where, item, "template")
        scan_face = "test"
        if item.get("scan_face") is not None:
            scan_face = _req_str(where, item, "scan_face")
            if scan_face not in WIRED_FACES:
                raise DeclError("%s：scan_face %r 未接线（可指名：%s）——面在项目声明，"
                                "引擎只提供已接线的扫描器" % (where, scan_face, "、".join(WIRED_FACES)))
        # 巡检模式两键（t260925-01）：mode 缺省 report=现状零行为（A6）；produce 实例
        # 由产出型 workflow 消费 docs_root。词表/词法外 fail-closed 点名。
        mode = DEFAULT_MODE
        if item.get("mode") is not None:
            mode = _req_str(where, item, "mode")
            if mode not in WIRED_MODES:
                raise DeclError("%s：mode %r 未接线（可指名：%s）——report=只报告（现状），"
                                "produce=产出型（泳道产 change 交人审）"
                                % (where, mode, "、".join(WIRED_MODES)))
        docs_root = DEFAULT_DOCS_ROOT
        if item.get("docs_root") is not None:
            docs_root = validate_docs_root(where, _req_str(where, item, "docs_root"))
        suite = ""
        if item.get("suite") is not None:
            suite = _req_str(where, item, "suite")
            if suite not in WIRED_SUITES:
                raise DeclError("%s：suite %r 未接线（可指名：%s）——套件只有全集一档，"
                                "没有「抽稀/跳场景」的值" % (where, suite, "、".join(WIRED_SUITES)))
        tz = ""
        if item.get("tz") is not None:
            tz = _req_str(where, item, "tz")
            if not TZ_RE.match(tz):
                raise DeclError("%s：tz %r 形态非法（IANA 名，如 Asia/Shanghai）" % (where, tz))
        # inspect 段预算三键（t260916-22）。YAML subset 无类型推断（scalar 逐字取 str），
        # 数字键走词法+范围校验（bool 是 int 子类，一并排除）。
        max_findings = DEFAULT_MAX_FINDINGS
        if item.get("max_findings") is not None:
            raw_mf = _req_str(where, item, "max_findings")
            if not re.match(r"^\d+$", raw_mf) or not (1 <= int(raw_mf) <= 10000):
                raise DeclError("%s：max_findings %r 非法（正整数 1~10000；本项=本期新发现"
                                "条数上限，超出按 severity 截断并注明）" % (where, raw_mf))
            max_findings = int(raw_mf)
        inspect_timeout_min = DEFAULT_INSPECT_TIMEOUT_MIN
        if item.get("inspect_timeout_min") is not None:
            raw_to = _req_str(where, item, "inspect_timeout_min")
            if not re.match(r"^\d+$", raw_to) or not (1 <= int(raw_to) <= 720):
                raise DeclError("%s：inspect_timeout_min %r 非法（分钟，1~720；本项=inspect"
                                " 段 agent 预算，超时=「agent 未完成」不假绿）" % (where, raw_to))
            inspect_timeout_min = int(raw_to)
        inspect_profile = ""
        if item.get("inspect_profile") is not None:
            inspect_profile = _req_str(where, item, "inspect_profile")
            if inspect_profile not in PROFILE_FACES:
                raise DeclError("%s：inspect_profile %r 未接线（可指名：%s）——分面清单真源"
                                "在引擎（inspection_inspect.PROFILE_TEXTS）" %
                                (where, inspect_profile, "、".join(PROFILE_FACES)))
        # 缩面硬上限两键（t260924-06）：数字键词法+范围校验（同 max_findings 纪律）。
        inspect_max_shards = DEFAULT_MAX_SHARDS
        if item.get("inspect_max_shards") is not None:
            raw_ms = _req_str(where, item, "inspect_max_shards")
            if not re.match(r"^\d+$", raw_ms) or not (1 <= int(raw_ms) <= 64):
                raise DeclError("%s：inspect_max_shards %r 非法（正整数 1~64；本项=inspect"
                                " 段子代理分片数硬上限，缩面纪律 t260924-06）" % (where, raw_ms))
            inspect_max_shards = int(raw_ms)
        inspect_max_files_per_shard = DEFAULT_MAX_FILES_PER_SHARD
        if item.get("inspect_max_files_per_shard") is not None:
            raw_mp = _req_str(where, item, "inspect_max_files_per_shard")
            if not re.match(r"^\d+$", raw_mp) or not (1 <= int(raw_mp) <= 10000):
                raise DeclError("%s：inspect_max_files_per_shard %r 非法（正整数 1~10000；"
                                "本项=每片文件数硬上限，缩面纪律 t260924-06）" % (where, raw_mp))
            inspect_max_files_per_shard = int(raw_mp)
        watchdog = _validate_watchdog(where, item.get("watchdog"))
        shared_scans = _validate_shared_scans(where, item.get("shared_scans"))
        surface_thresholds = _validate_surface_thresholds(where, item.get("surface_thresholds"))
        # 布尔口径与 enabled 逐字同规（本 YAML 子集无类型推断，标量恒为 str：只认
        # true/false 字面，其他一律 fail-closed 点名——不许 'yes'/1/True 混进来）。
        skip_when_unchanged = False
        if item.get("skip_when_unchanged") is not None:
            raw_skip = item.get("skip_when_unchanged")
            if not isinstance(raw_skip, str) or not BOOL_RE.match(raw_skip):
                raise DeclError("%s：skip_when_unchanged 只认 true/false 字面（got %r；"
                                "本项=「无新变更则空转」，260929 宿主令）" % (where, raw_skip))
            skip_when_unchanged = raw_skip == "true"
        # Review-ledger rotation slice (t261006-12): review_slice accepts the
        # true/false literals only (None = not set -> the activity side applies
        # the profile default); min/max are positive integers (no invented upper
        # bound, non-positive rejected; min>max is clamped with a note at the
        # use site). Same lexical discipline as max_findings.
        review_slice: Optional[bool] = None
        if item.get("review_slice") is not None:
            raw_rs = item.get("review_slice")
            if not isinstance(raw_rs, str) or not BOOL_RE.match(raw_rs):
                raise DeclError("%s：review_slice only accepts the true/false literals "
                                "(got %r; review-ledger rotation slice switch, t261006-12)"
                                % (where, raw_rs))
            review_slice = raw_rs == "true"
        slice_min = 0
        if item.get("slice_min") is not None:
            raw_smin = _req_str(where, item, "slice_min")
            if not re.match(r"^\d+$", raw_smin) or int(raw_smin) <= 0:
                raise DeclError("%s：slice_min %r is invalid (a positive integer; the "
                                "lower bound of the per-period least-recently-reviewed "
                                "slice, default 40, t261006-12)" % (where, raw_smin))
            slice_min = int(raw_smin)
        slice_max = 0
        if item.get("slice_max") is not None:
            raw_smax = _req_str(where, item, "slice_max")
            if not re.match(r"^\d+$", raw_smax) or int(raw_smax) <= 0:
                raise DeclError("%s：slice_max %r is invalid (a positive integer; the "
                                "upper bound of the per-period least-recently-reviewed "
                                "slice, default 60, t261006-12)" % (where, raw_smax))
            slice_max = int(raw_smax)
        kind, cron, n, source, project_key = _validate_schedule(where, item.get("schedule"), enabled)
        # 实例级项目身份必填（t260915-20）：校验放字段链**最后**——既有反用例事由
        # （缺 source、未知 kind、face 除名、cron 非法…）照旧先爆，断言语义零偷换；
        # 「其余全对但缺身份」的正形声明在此点名。占位豁免惯例（schedule.source/n 只在
        # enabled 必填）不适用：身份不是调度细节，无身份的占位实例=无主票预定席。
        identity_key = str(item.get("project_key") or "").strip()
        if not identity_key:
            raise DeclError("%s：实例 %s 缺必填字段 project_key（实例级项目身份=巡检票归属；"
                            "无项目身份的巡检=无主票，绝不静默归属引擎仓）" % (where, inst_id))
        if not INSTANCE_ID_RE.match(identity_key):
            raise DeclError("%s：实例 %s 的 project_key 非法 %r（实例级项目身份；"
                            "小写 slug，同实例 id 词法）" % (where, inst_id, identity_key))
        instances.append(InstanceSpec(
            id=inst_id, enabled=enabled, kind=kind, cron=cron, n=n,
            source=source, project_key=project_key,
            instance_project_key=identity_key, scan_face=scan_face,
            mode=mode, docs_root=docs_root,
            suite=suite, tz=tz, skip_when_unchanged=skip_when_unchanged,
            workflow=workflow_name, template=template,
            max_findings=max_findings, inspect_timeout_min=inspect_timeout_min,
            inspect_profile=inspect_profile,
            inspect_max_shards=inspect_max_shards,
            inspect_max_files_per_shard=inspect_max_files_per_shard,
            review_slice=review_slice, slice_min=slice_min, slice_max=slice_max,
            watchdog=watchdog, shared_scans=shared_scans,
            surface_thresholds=surface_thresholds))
    return InspectionDecl(schema=SCHEMA, instances=instances, source=source)


def build_schedule_specs(decl: InspectionDecl) -> List[Dict[str, Any]]:
    """The behavior-level declaration consumption point (M1 acceptance 3): outputs the
    scheduling intent of **enabled** instances only.
    Disabled instances produce nothing — "enabled=false does not run" takes shape here,
    and the trigger surface trusts only this function's output."""
    specs: List[Dict[str, Any]] = []
    for it in decl.instances:
        if not it.enabled:
            continue
        specs.append({
            "instance_id": it.id,
            "kind": it.kind,
            "cron": it.cron,
            "n": it.n,
            "source": it.source,
            # 实例级身份键（t260915-20）：巡检票归属——起票 SA 与 repo_root 注册表解析
            # 的真源。**不占用/不改**下方 "project_key" 键的计数源语义（下游消费者零惊变）。
            "instance_project_key": it.instance_project_key,
            "project_key": it.project_key,
            "scan_face": it.scan_face,
            # 巡检模式两键（t260925-01）：additive 键——老消费者忽略，A6 零行为。
            "mode": it.mode, "docs_root": it.docs_root,
            "suite": it.suite,
            "tz": it.tz,
            # 无新变更则空转（260929，additive 键）：老消费者忽略零行为；spawn 活动读它
            # 决定「起票前先比基点 sha」。
            "skip_when_unchanged": bool(it.skip_when_unchanged),
            "workflow": it.workflow,
            "template": it.template,
            # overlap semantics (borrowed from trade-off list item 1): repeated triggers of
            # the same instance in the same period merge into one ticket (one ticket per
            # period), no extra ticket on collision — SKIP at the schedule layer, with the
            # workflow id's idempotency as the backstop (see inspection_trigger.py).
            "overlap": "SKIP",
        })
    return specs


def _plan_from_decl(decl: "InspectionDecl", instance_id: str) -> Dict[str, Any]:
    """decl + 实例 → plan（resolve_instance_plan 的三态闭式核，纯函数）。"""
    it = decl.instance(instance_id)
    if it is None:
        return {"ok": False, "instance_id": instance_id,
                "error": "实例 %r 不在声明中（在册：%s）——调度器还在触发但声明已除名，"
                         "配置漂移，人工处置" % (instance_id,
                                             "、".join(i.id for i in decl.instances) or "无")}
    if not it.enabled:
        return {"ok": False, "instance_id": instance_id, "enabled": False,
                "suite": it.suite,
                "error": "实例 %r 在声明中已停用（enabled=false），但调度/触发仍在——配置漂移，"
                         "人工处置（删调度或改回声明）" % instance_id}
    return {"ok": True, "instance_id": it.id, "enabled": True, "suite": it.suite,
            "run_suite": bool(it.suite), "scan_face": it.scan_face, "cron": it.cron,
            "mode": it.mode, "docs_root": it.docs_root,
            "tz": it.tz,
            # 无新变更则空转（260929）：spawn 活动据本键决定是否「先比基点 sha 再起票」。
            "skip_when_unchanged": bool(it.skip_when_unchanged),
            # inspect 段预算三键（t260916-22）：profile 空=回落 scan_face（consume 侧
            # workflow 定，声明零重复）。
            "inspect": {"max_findings": it.max_findings,
                        "timeout_min": it.inspect_timeout_min,
                        "profile": it.inspect_profile,
                        "max_shards": it.inspect_max_shards,
                        "max_files_per_shard": it.inspect_max_files_per_shard,
                        # Review-ledger rotation slice (t261006-12): review_slice
                        # None = not set in the declaration (activity-side profile
                        # default); min/max 0 = activity-side default 40/60.
                        "review_slice": it.review_slice,
                        "slice_min": it.slice_min,
                        "slice_max": it.slice_max},
            # lane/watchdog 阈值档（260926）：additive 键，声明原值透传——运行期活动
            # 归一并在面/回执上点名来源（declaration|default）；旧消费者忽略本键零行为。
            "watchdog": dict(it.watchdog),
            # t261006-13: shared public scan ownership + B3 coverage thresholds
            # (additive keys; declaration raw values, engine-side normalization).
            "shared_scans": dict(it.shared_scans),
            "surface_thresholds": dict(it.surface_thresholds),
            "kind": it.kind, "workflow": it.workflow, "template": it.template,
            # t260917-02（R2 身份回退链）：实例级项目身份随 plan 出——旧调度 payload 缺
            # project_key 时（260917 实况），spawn 活动按本键回退决议归属，起票 SA
            # 三件套在生产过渡窗也齐。键名沿用 decl 本名（防与 schedule 级 project_key
            # 计数源语义混串，见本文件 :104 注）。
            "instance_project_key": it.instance_project_key, "error": ""}


def resolve_instance_plan(instance_id: str, decl_path: Any = None) -> Dict[str, Any]:
    """运行期「本期怎么跑」的单一决议点（t260913-02；t260916-02 接声明落位聚合）：workflow
    启动时经 activity 读当前声明，决定是否进 setup/suite 阶段——**开关不进 workflow 输入
    payload**（老 worker 解新字段的反向兼容面为零；改声明即改行为，不必重跑 schedule-up）。

    声明来源（覆盖层优先级，t260916-02）：显式 decl_path（场景注入，绝对路径）> env 测试
    覆盖层（单文件）> 项目注册表聚合（生产路径——遍历注册项目找到定义本实例的那份声明）。

    三态，逐态闭式（C4）：ok=True 的两种形态也显式区分——
      - suite 非空（现只认 "full"）：跑套件（setup → scan → suite → report → close）；
      - suite 空：不跑套件（scan → report → close，票① 行为）；
      - enabled=false / 实例不在任何项目声明中 / 声明不可解析 → ok=False + 点名 error（**绝不**
        与「启用但没声明 suite」同形放过：调度器还在触发却声明已停用，是配置漂移事故，
        必须显式 blocked 让人看见——dead-man 纪律的同一族）。"""
    explicit = str(decl_path or "").strip() or coverage_decl_path()
    if explicit:
        try:
            decl = load_inspection_decl(Path(explicit))
        except Exception as e:  # noqa: BLE001——解析/IO 一律闭式点名，不静默当 no-suite
            return {"ok": False, "instance_id": instance_id,
                    "error": "声明不可用（%s）：%s" % (type(e).__name__, e)}
        return _plan_from_decl(decl, instance_id)
    try:
        decl, _project_key = load_decl_for_instance(instance_id)
    except Exception as e:  # noqa: BLE001——聚合解析失败同样闭式点名（含逐项目状态）
        return {"ok": False, "instance_id": instance_id,
                "error": "声明聚合解析失败：%s" % e}
    return _plan_from_decl(decl, instance_id)


# ========================================================================================
# 声明落位（t260916-02 迁移A）：每项目仓内单文件 + paths.inspection_decl 指路 + 聚合遍历
#   - 生产面：默认 <注册条目主目录 dirs[0]>/inspection.yaml；指路键可落仓外（机器级）。
#   - 三态逐项目闭式：ok / absent（无声明文件=该项目无巡检面，响应但不报错）/
#     error（不可读/坏形态——显式点名项目 key+路径+事由，绝不静默吞）。
#   - 覆盖层：env SANDBAR_INSPECTION_DECL 单文件整体替代聚合（仅测试语义）。
#   - 跨项目实例 id 重复 = 配置事故 fail-closed（绝不猜）。
# ========================================================================================

class ProjectDeclState:
    """一个注册项目的声明装载状态（聚合遍历的逐项目结果，三态闭式可观测）。"""

    __slots__ = ("project_key", "state", "path", "decl", "error", "coverage")

    def __init__(self, project_key: str, state: str, path: str = "",
                 decl: Optional[InspectionDecl] = None, error: str = "",
                 coverage: bool = False) -> None:
        self.project_key = project_key
        self.state = state          # "ok" | "absent" | "error"
        self.path = path            # 已解析的声明路径（absent 时=默认落位路径，供点名）
        self.decl = decl
        self.error = error          # state=error 时的人读事由
        self.coverage = coverage    # True=env 测试覆盖层（单文件模式）

    def as_dict(self) -> Dict[str, Any]:
        return {"project_key": self.project_key, "state": self.state, "path": self.path,
                "error": self.error, "coverage": self.coverage,
                "instances": [i.id for i in (self.decl.instances if self.decl else [])]}


def resolve_project_decl_path(project_key: str) -> Path:
    """项目 → 声明路径解析链（三分支，t260916-02）：
      ① paths.inspection_decl 已声明 → 用之（绝对/`~/…` 原样，相对拼 dirs[0]）；
         declared 锚点缺失/类型错位 fail-closed（契约①d 四态表同款——**声明了就必须在**）；
      ② 未声明 → <dirs[0]>/inspection.yaml（默认落位；文件在不在=absent 与否，此处不判）；
      ③ 注册条目不可用（未知 key/主目录缺失/条目文件坏）→ ProjectPathsError/DeclError 语境点名。
    """
    from shared import project_paths
    key = str(project_key or "").strip()
    info = project_paths(key)
    main_dir = info.get("main_dir")
    declared = info.get("inspection_decl")
    if declared is not None:
        p = Path(str(declared))
        if not p.exists():
            raise DeclError("paths.inspection_decl 声明锚点不存在（fail-closed，契约①d）：%s（项目 %s）"
                            % (p, key))
        if not p.is_file():
            raise DeclError("paths.inspection_decl 声明锚点不是文件（类型错位，fail-closed）：%s（项目 %s）"
                            % (p, key))
        return p
    if not main_dir:
        raise DeclError("项目 %r 无可用注册条目主目录（dirs[0] 缺失）——巡检声明落位无法解析" % key)
    return Path(str(main_dir)) / DECL_FILE_NAME


def iter_project_decls() -> List[ProjectDeclState]:
    """遍历注册项目读各自声明（聚合真源，t260916-02 口径④）。

    - 项目清单=shared.list_registered_projects（唯一装载器薄壳：跳过/隔离语义逐字同源）；
      隔离条目（装载失败）→ error 态点名（目录+事由），绝不静默吞。
    - env 测试覆盖层生效 → 单文件模式：只出一条 coverage=True 的 ok/absent 态（absent=
      env 指向的文件不存在——显式点名，不回落聚合）。
    - 每项目三态：ok（解析成功）/ absent（无声明文件=无巡检面）/ error（点名 key+路径+事由）。"""
    cov = coverage_decl_path()
    if cov:
        p = Path(cov)
        if not p.is_file():
            return [ProjectDeclState(project_key="", state="error", path=str(p), coverage=True,
                                     error="测试覆盖层声明不可读（SANDBAR_INSPECTION_DECL=%s）——"
                                           "该 env 仅测试语义，生产误设=配置事故" % cov)]
        try:
            decl = load_inspection_decl(p)
        except Exception as e:  # noqa: BLE001——覆盖层坏形态同样显式点名
            return [ProjectDeclState(project_key="", state="error", path=str(p), coverage=True,
                                     error="测试覆盖层声明不可解析：%s: %s" % (type(e).__name__, e))]
        return [ProjectDeclState(project_key="", state="ok", path=str(p), decl=decl, coverage=True)]
    from shared import list_registered_projects
    projects, quarantined = list_registered_projects()
    out: List[ProjectDeclState] = []
    for q in (quarantined or []):
        qdir = str((q or {}).get("dir") or "")
        out.append(ProjectDeclState(
            project_key=Path(qdir).name if qdir else "",
            state="error",
            error="注册条目被隔离（%s）：%s" % (qdir, str((q or {}).get("error") or "未知")))
        )
    for proj in (projects or []):
        key = str((proj or {}).get("key") or "")
        try:
            p = resolve_project_decl_path(key)
        except Exception as e:  # noqa: BLE001——指路坏形/锚点错位/条目不可用 → error 态点名
            out.append(ProjectDeclState(project_key=key, state="error",
                                        error="%s: %s" % (type(e).__name__, e)))
            continue
        if not p.is_file():
            out.append(ProjectDeclState(project_key=key, state="absent", path=str(p)))
            continue
        try:
            decl = load_inspection_decl(p)
        except Exception as e:  # noqa: BLE001——坏形态逐项目点名（不静默、不拖垮他项目）
            out.append(ProjectDeclState(project_key=key, state="error", path=str(p),
                                        error="声明不可解析：%s: %s" % (type(e).__name__, e)))
            continue
        out.append(ProjectDeclState(project_key=key, state="ok", path=str(p), decl=decl))
    return out


def load_decl_for_instance(instance_id: str):
    """实例 → (decl, project_key) 聚合解析（t260916-02）。

    覆盖层优先：env 生效 → 只在覆盖层文件里找（absent/error=显式点名，不回落聚合）。
    生产聚合：遍历各项目声明找实例；命中唯一 → 返回；命中多个 → fail-closed 点名两处
    （跨项目实例 id 重复=配置事故）；全无 → 显式报错并列出逐项目状态（含 error 项目点名）——
    **绝不回落他项目声明、绝不回落引擎样例**（口径④ fail-closed 分支）。"""
    iid = str(instance_id or "").strip()
    states = iter_project_decls()
    cov = coverage_decl_path()
    if cov:
        st = states[0]
        if st.state == "ok" and st.decl is not None and st.decl.instance(iid) is not None:
            return st.decl, ""
        if st.state != "ok":
            raise DeclError("实例 %r 不可解析：%s" % (iid, st.error))
        raise DeclError("实例 %r 不在测试覆盖层声明中（%s，在册：%s）"
                        % (iid, st.path, "、".join(i.id for i in st.decl.instances) or "无"))
    hits: List[ProjectDeclState] = []
    for st in states:
        if st.state == "ok" and st.decl is not None and st.decl.instance(iid) is not None:
            hits.append(st)
    if len(hits) > 1:
        raise DeclError("实例 %r 在多个项目声明中重复（%s）——跨项目实例 id 重复是配置事故，"
                        "绝不猜（t260916-02 聚合 fail-closed）"
                        % (iid, "、".join(st.project_key for st in hits)))
    if hits:
        return hits[0].decl, hits[0].project_key
    scanned = "；".join(
        "%s=%s%s" % (st.project_key or "（隔离）", st.state,
                     ("（%s）" % st.error) if st.error else ("（%s）" % st.path if st.path else ""))
        for st in states) or "注册表为空（无任何注册项目）"
    raise DeclError("实例 %r 未在任何项目声明中——各项目仓根无 inspection.yaml=该项目无巡检面"
                    "（逐项目：%s）；绝不回落他项目声明或引擎样例" % (iid, scanned))


def enabled_instance_whitelist():
    """工单板白名单聚合面（t260915-08 的 `_inspection_enabled_instances` 消费；t260916-02
    改遍历）。返回 (instances, degraded_projects, coverage)：
      instances = 全项目 enabled 实例 id 并集（排序去重）；
      degraded_projects = [(project_key, path, error), …]——error 项目实例不收（其声明读不出，
        收了才是静默编造），但**显式点名**让板面 note 可见；
      coverage = env 覆盖层是否生效（单文件模式）。"""
    states = iter_project_decls()
    ids: Dict[str, list] = {}
    degraded = []
    for st in states:
        if st.state == "ok" and st.decl is not None:
            for i in st.decl.enabled_instances():
                ids.setdefault(i.id, []).append((st.project_key, st.path))
        elif st.state == "error":
            degraded.append((st.project_key, st.path, st.error))
    # 跨项目实例 id 重复=身份歧义配置事故（t260916-02 口径①fail-closed 半边）：绝不猜
    # 归属——歧义实例从并集剔除，degraded 点名两处（项目+声明路径），板面/聚合回执
    # 可见；trigger 面（load_decl_for_instance）多命中显式报错，两路口径一致。
    for iid, owners in sorted((k, v) for k, v in ids.items() if len(v) > 1):
        degraded.append((
            ",".join(sorted(k for k, _ in owners)),
            ";".join(str(p) for _, p in owners),
            "实例 id '%s' 被多个项目声明（跨项目撞名）：%s——身份歧义，从聚合白名单剔除"
            "（配置事故，人工处置）"
            % (iid, "、".join("%s@%s" % (k, p) for k, p in owners))))
    clean = tuple(sorted(k for k, v in ids.items() if len(v) == 1))
    return clean, degraded, bool(coverage_decl_path())

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
  - Path: the SANDBAR_INSPECTION_DECL env var overrides the default declaration path
    (test isolation; the path constant has its single point in default_decl_path, M4).

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
WIRED_WORKFLOWS = ("InspectionPeriodicWorkflow",)
# 计数源词表（t260911-02）：现在只接了归档目录一源；扩源必须先扩此表+计数模块。
TICKET_COUNT_SOURCES = ("archive-dir",)
# 扫描面词表（t260911-02）：实例可声明 scan_face 指定跑哪个扫描器（「跑哪个巡检面」
# 由项目声明决定——拍板③原文）；缺省 test（票① 行为兼容，零声明实例不回退不报错）。
WIRED_FACES = ("test", "doc", "mechanism", "simplify")
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


class DeclError(Exception):
    """Malformed or out-of-scope declaration — fail-closed; the message names the problem
    and its location, never a default fallback."""


@dataclass
class InstanceSpec:
    """One inspection instance (the anchor for everything declaration-driven)."""

    id: str
    enabled: bool
    kind: str
    cron: str = ""
    n: int = 0
    source: str = ""
    project_key: str = ""
    scan_face: str = "test"
    # 套件档（t260913-02）：空=不跑套件；"full"=本期在巡检自有泳道里跑集成全集。
    suite: str = ""
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
    """Single point for the declaration path (env-overridable; default = inspection.yaml
    next to this module)."""
    env = os.environ.get("SANDBAR_INSPECTION_DECL")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / DECL_FILE_NAME


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
                                      "scan_face", "suite", "tz"})
        if unknown:
            raise DeclError("%s：未知实例字段 %s（合法：id/enabled/schedule/workflow/template/"
                            "scan_face/suite/tz；"
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
        kind, cron, n, source, project_key = _validate_schedule(where, item.get("schedule"), enabled)
        instances.append(InstanceSpec(
            id=inst_id, enabled=enabled, kind=kind, cron=cron, n=n,
            source=source, project_key=project_key, scan_face=scan_face,
            suite=suite, tz=tz, workflow=workflow_name, template=template))
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
            "project_key": it.project_key,
            "scan_face": it.scan_face,
            "suite": it.suite,
            "tz": it.tz,
            "workflow": it.workflow,
            "template": it.template,
            # overlap semantics (borrowed from trade-off list item 1): repeated triggers of
            # the same instance in the same period merge into one ticket (one ticket per
            # period), no extra ticket on collision — SKIP at the schedule layer, with the
            # workflow id's idempotency as the backstop (see inspection_trigger.py).
            "overlap": "SKIP",
        })
    return specs


def resolve_instance_plan(instance_id: str, decl_path: Any = None) -> Dict[str, Any]:
    """运行期「本期怎么跑」的单一决议点（t260913-02）：workflow 启动时经 activity 读当前
    声明，决定是否进 setup/suite 阶段——**开关不进 workflow 输入 payload**（老 worker
    解新字段的反向兼容面为零；改声明即改行为，不必重跑 schedule-up）。

    三态，逐态闭式（C4）：ok=True 的两种形态也显式区分——
      - suite 非空（现只认 "full"）：跑套件（setup → scan → suite → report → close）；
      - suite 空：不跑套件（scan → report → close，票① 行为）；
      - enabled=false / 实例不在册 / 声明不可解析 → ok=False + 点名 error（**绝不**
        与「启用但没声明 suite」同形放过：调度器还在触发却声明已停用，是配置漂移
        事故，必须显式 blocked 让人看见——dead-man 纪律的同一族）。
    纯函数（IO 只有一次声明读，路径由 decl_path / env / 默认单点决定）。"""
    try:
        decl = load_inspection_decl(decl_path)
    except Exception as e:  # noqa: BLE001——解析/IO 一律闭式点名，不静默当 no-suite
        return {"ok": False, "instance_id": instance_id,
                "error": "声明不可用（%s）：%s" % (type(e).__name__, e)}
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
            "tz": it.tz,
            "kind": it.kind, "workflow": it.workflow, "template": it.template, "error": ""}

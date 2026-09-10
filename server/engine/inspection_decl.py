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
WIRED_KINDS = ("cron",)
# Whitelist of inspection workflow type names the engine has wired and a declaration may
# name (fail-closed so a declaration cannot point at a nonexistent workflow and then
# silently never trigger — same spirit as M2).
WIRED_WORKFLOWS = ("InspectionPeriodicWorkflow",)
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
    unknown = sorted(set(sched) - {"kind", "cron", "n"})
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
    if kind == "cron":
        cron = _req_str(where, sched, "cron")
        fields = cron.split()
        if len(fields) != 5 or any(not _CRON_FIELD_RE.match(f) for f in fields):
            raise DeclError("%s：cron 非法 %r（需五字段，词法 * */n n n-m n-m/n 名称/逗号列表）"
                            % (where, cron))
        # Numeric fields (per-field validation of bare values; fields containing */ranges/
        # lists are left to the scheduler's semantics — here we only stop a bare value out
        # of range)
        _CRON_MAX = (59, 23, 31, 12, 7)
        for pos, (f, top) in enumerate(zip(fields, _CRON_MAX)):
            if f.isdigit() and int(f) > top:
                raise DeclError("%s：cron 第 %d 域 %s 超出数值域（≤%d）" % (where, pos + 1, f, top))
    if kind in ("every-n-tickets", "race-first"):
        n_raw = sched.get("n")
        try:
            n = int(str(n_raw))
        except (TypeError, ValueError):
            raise DeclError("%s：n 必须是整数（got %r）" % (where, n_raw)) from None
        if n < 1 or n > 10000:
            raise DeclError("%s：n 超出合理区间（1–10000）：%d" % (where, n))
    return kind, cron, n


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
        unknown = sorted(set(item) - {"id", "enabled", "schedule", "workflow", "template"})
        if unknown:
            raise DeclError("%s：未知实例字段 %s（合法：id/enabled/schedule/workflow/template；"
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
        kind, cron, n = _validate_schedule(where, item.get("schedule"), enabled)
        instances.append(InstanceSpec(
            id=inst_id, enabled=enabled, kind=kind, cron=cron, n=n,
            workflow=workflow_name, template=template))
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
            "workflow": it.workflow,
            "template": it.template,
            # overlap semantics (borrowed from trade-off list item 1): repeated triggers of
            # the same instance in the same period merge into one ticket (one ticket per
            # period), no extra ticket on collision — SKIP at the schedule layer, with the
            # workflow id's idempotency as the backstop (see inspection_trigger.py).
            "overlap": "SKIP",
        })
    return specs

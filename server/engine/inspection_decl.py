"""inspection_decl —— 巡检声明读取/校验器（inspection epic 票①，t260905-03）。

机制在引擎，面在项目声明：本模块只做「声明文件 → 结构化实例表」的一件事，
调度与开票机制（inspection_trigger.py / InspectionPeriodicWorkflow）消费它的输出。

设计定稿（review_plan 附条件放行意见 C1~C3 前置约束 + M2/M4）：
  - 落位：独立 inspection.yaml（不进 verify.yaml——那是每票跑的复验闸，巡检调度是
    定时器域，塞入=语义漂移+引擎白名单扩围；「同 ui_evidence 一族」的本质是
    「机制在引擎、面在项目声明」原则，不是同文件）。
  - 解析器：**零依赖 YAML 子集解析器**（docker 测试镜像 / 场景道 / 本机全可跑，
    只用标准库）。只认本头注声明的子集，子集外形态一律 fail-closed 报错点名行号
    ——不猜、不静默降级。两套解析器必漂移，故不用 pyyaml 双轨。
  - 未接线 kind（M2）：KNOWN_KINDS 收录全部「文档化 kind」，WIRED_KINDS 只收已接线
    的。**启用实例**声明未接线 kind → 显式报错并点名已接线清单；禁用实例允许
    （禁用=纯占位不触发，声明即文档）。绝不允许「解析通过、运行时静默不触发」。
  - 路径：环境变量 SANDBAR_INSPECTION_DECL 可覆盖缺省声明路径（测试隔离；路径常量
    单点在本函数，M4）。

YAML 子集文法（逐条由单测钉死）：
  - 缩进只允许空格，禁 tab；层级固定：根映射(0) → 实例列表项(- 于 2) → 实例键(4)
    → schedule 映射(6) → schedule 键(8)。
  - 行形态只有五种：空行 / 全行注释(# 起头，含前导空格) / `key: 标量` /
    `key:`(开子结构) / `- key: 标量`(列表项首键，续键用同层级 `key: 标量`)。
  - 标量原样取字符串（不做类型推断），bool 只认 true/false 字面，strip 尾随空白；
    `#` 不在行内截断（cron `*` 等字符安全）。
  - 键重复 / 同键双形态（既有标量又开子结构）/ 子结构内出现列表项 → 报错。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DECL_FILE_NAME = "inspection.yaml"

# kind 词表：KNOWN=文档化全量（声明里出现合法），WIRED=引擎已接线全量（启用实例白名单）。
KNOWN_KINDS = ("cron", "every-n-tickets", "race-first")
WIRED_KINDS = ("cron",)
# 引擎已接线可被声明指名的巡检 workflow 类型名白名单（fail-closed 防声明指到不存在的
# workflow 后运行期静默不触发——同 M2 精神）。
WIRED_WORKFLOWS = ("InspectionPeriodicWorkflow",)
SCHEMA = "v1"
INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# cron 五字段词法：`*` `*/n` `n` `n-m` `n-m/n` `n,m`（逗号列表），月/星域放宽三字母名。
_CRON_ATOM = r"(?:\*|\*/\d+|\d+|\d+-\d+(?:/\d+)?|[a-z]{3}(?:-[a-z]{3})?)"
_CRON_FIELD_RE = re.compile(r"^%s(?:,%s)*$" % (_CRON_ATOM, _CRON_ATOM))
BOOL_RE = re.compile(r"^(true|false)$")


class DeclError(Exception):
    """声明畸形/越权——fail-closed，消息点名问题与位置，绝无缺省回落。"""


@dataclass
class InstanceSpec:
    """一个巡检实例（声明驱动的一切行为的锚）。"""

    id: str
    face: str
    enabled: bool
    kind: str
    cron: str = ""
    n: int = 0
    workflow: str = ""
    template: str = ""


@dataclass
class InspectionDecl:
    """整份声明的结构化形态。"""

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
    """声明路径单点（env 可覆盖；缺省=本模块同目录 inspection.yaml）。"""
    env = os.environ.get("SANDBAR_INSPECTION_DECL")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / DECL_FILE_NAME


# ========================================================================================
# YAML 子集解析器（只认头注文法；一切越界=fail-closed）
# ========================================================================================

class _Line:
    __slots__ = ("no", "indent", "text", "kind")

    def __init__(self, no: int, indent: int, text: str, kind: str) -> None:
        self.no = no            # 1-based 行号（报错点名用）
        self.indent = indent
        self.text = text        # 去缩进后的有效内容（注释已剥）
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
    """解析一层映射（同缩进连续 kv/open），返回 (mapping, next_pos)。"""
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
    """解析 open 键的子结构：更深层映射，或列表项序列（实例表）。
    列表项允许比开键更深（YAML 惯例），以首个列表项缩进为列表基准层。"""
    if pos >= len(lines) or lines[pos].indent <= parent_indent:
        raise DeclError("第 %d 行：%s 开了子结构但无内容" % (lines[pos - 1].no if pos else 0, ctx))
    if lines[pos].kind == "item":
        return _parse_item_list(lines, pos, lines[pos].indent, ctx)
    return _parse_mapping(lines, pos, lines[pos].indent, ctx)


def _parse_item_list(lines: List[_Line], pos: int, indent: int, ctx: str) -> tuple:
    """实例列表：`- key: 标量` 起头（同一基准缩进），续键为 +2 缩进的 kv / open。"""
    items: List[Dict[str, Any]] = []
    i = pos
    while i < len(lines):
        ln = lines[i]
        if ln.indent < indent or (ln.indent == indent and ln.kind != "item"):
            break
        if ln.kind != "item" or ln.indent != indent:
            raise DeclError("第 %d 行：列表项形态/缩进非法：%r" % (ln.no, ln.text))
        item: Dict[str, Any] = {}
        # item 行是原文（未经 kv 标记化），在此切 key: 标量
        ikey, _, ival = ln.text.partition(":")
        ikey = ikey.strip()
        if not ikey or not ival.strip():
            raise DeclError("第 %d 行：列表项首键必须 key: 标量形态：%r" % (ln.no, ln.text))
        item[ikey] = ival.strip()
        i += 1
        # 续键：缩进 = indent+2 的 kv / open
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
    """子集文法解析 + 结构校验（fail-closed），文本入口。"""
    lines = _tokenize(text)
    if not lines:
        raise DeclError("%s：声明为空" % source)
    root, _ = _parse_mapping(lines, 0, 0, "根")
    return decl_from_mapping(root, source=source)


def load_inspection_decl(path: Optional[Path] = None) -> InspectionDecl:
    """文件入口（env 路径单点见 default_decl_path）。读文件失败=显式报错。"""
    p = Path(path) if path else default_decl_path()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise DeclError("声明文件不可读：%s（%s）" % (p, e)) from e
    return parse_decl_text(text, source=str(p))


# ========================================================================================
# 结构校验（畸形输入一律 DeclError 点名）
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
        # 数值域（单值逐域校验；含 */区间/列表的域交调度器语义，这里只拦单值越域）
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
    """映射入口校验（文本解析后的公共窄口；单测直接喂 dict 复现畸形）。"""
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
        unknown = sorted(set(item) - {"id", "face", "enabled", "schedule", "workflow", "template"})
        if unknown:
            raise DeclError("%s：未知实例字段 %s（合法：id/face/enabled/schedule/workflow/template）"
                            % (where, unknown))
        inst_id = _req_str(where, item, "id")
        if not INSTANCE_ID_RE.match(inst_id):
            raise DeclError("%s：id 非法 %r（小写 slug：^[a-z0-9][a-z0-9-]{0,63}$）" % (where, inst_id))
        if inst_id in seen_ids:
            raise DeclError("%s：实例 id 重复：%s" % (where, inst_id))
        seen_ids.add(inst_id)
        face = _req_str(where, item, "face")
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
            id=inst_id, face=face, enabled=enabled, kind=kind, cron=cron, n=n,
            workflow=workflow_name, template=template))
    return InspectionDecl(schema=SCHEMA, instances=instances, source=source)


def build_schedule_specs(decl: InspectionDecl) -> List[Dict[str, Any]]:
    """行为级声明消费点（M1 验收③）：只输出**启用**实例的调度意图。
    禁用实例产出为零——「enabled=false 不跑」在这里成形，触发面只认本函数输出。"""
    specs: List[Dict[str, Any]] = []
    for it in decl.instances:
        if not it.enabled:
            continue
        specs.append({
            "instance_id": it.id,
            "face": it.face,
            "kind": it.kind,
            "cron": it.cron,
            "n": it.n,
            "workflow": it.workflow,
            "template": it.template,
            # overlap 语义（照搬取舍清单①）：同实例同期重复触发合并为一张票（每期一票），
            # 撞期不另开——schedule 层 SKIP，workflow id 幂等兜底（见 inspection_trigger.py）。
            "overlap": "SKIP",
        })
    return specs

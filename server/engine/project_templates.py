"""project_templates —— 项目外置工作流模板加载口（工单 t260924-04，票 1）。

为什么存在：引擎的「模板即代码」注册表（shared.TEMPLATE_CLASS_NAMES /
workflows_v2.TEMPLATE_CLASSES）此前只从引擎包内加载。本模块开放「按项目登记、
启动时合并」的一扇门：项目在注册条目 paths 节声明 `workflow_modules`（`,` 分隔的
模块清单，每项相对项目主目录 dirs[0]），引擎启动时逐模块加载、逐模板过检查，与
内置模板合并进同一张注册表。不声明 = 契约①d 四类回退，零行为变化。

三态拒收（fail-closed 且精确点名，不静默改名、不后到覆盖、不装死）：
  - 撞名 id：模板 id 与内置/夹具/其他项目已接受 id 撞名 → 拒收并点名双方；
  - 畸形：模块缺 TEMPLATE_ID / TEMPLATE_ID 多值 / 类缺 STAGES / 段形态不合 /
    源码声明与类属性不一致 → 拒收并点名缺什么、哪一层检查失败；
  - 加载失败：声明锚点缺失 / 模块不可读 / import 抛错 → 拒收并点名文件与异常。
每条拒收都是结构化 dict（project/module/check/detail），汇入 rejections 列表，
由 shared.project_template_rejection_note 暴露到建票文案面——「拒收≠装死」。
隔离语义：逐模块逐项目独立判定，坏模块只拒自己，同项目其他模块与别项目照常。

同门同源：shared（名面，stdlib-only 源码扫描——ticket.py 以 '_poc_shared' 别名
spec 装载 shared，故本模块**绝不 import shared**，一切依赖以参数注入）与
workflows_v2（类面，引擎 venv importlib 全量加载）都从 scan() 同一份结果合并。
深检（类面）可能拒掉名面已接受的 id：workflows_v2 合并时经
shared.project_template_classes_merged 回写 shared 两表，引擎进程内两表恒一致。

clean-module 约束（fixture_two_step 头注同款）：外置模板模块只允许 import + 类
定义，零模块级 IO——temporalio sandbox 会重执行定义模块。演进纪律（加载口文档
明示）：段序/拓扑变更走新模板 id 并存；分支逻辑变更走 workflow.patched() 且
PATCH_ID 带 `<项目key>-` 前缀——本加载器静态扫描引擎面 `*_PATCH_ID` 字面量集，
项目模板补丁标识撞引擎面 → 拒收点名（兜底防线；主防线是前缀纪律本身）。

补丁标识集采集手段取舍（t260924-04 方案 C4）：选**源码静态扫描**而非 import 后
内省——CLI/stdlib 进程 import 不起 temporalio，内省不可行；扫描只覆盖引擎目录
`*_PATCH_ID = "…"` 命名惯例（grep 实证 base/dev_lane/inspection_flow/shared 均守
此惯例），未守惯例的新补丁可能漏报——可接受：workflow.patched() 分支判等发生在
同一模板类自己的历史上，漏报后果有限；引擎集每次加载动态收集，不写死列举。
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

# 名面/类面共用的源码扫描锚（行首允许缩进=类属性；值限单引号/双引号标量）
RE_TEMPLATE_ID = re.compile(r'^[ \t]*TEMPLATE_ID[ \t]*=[ \t]*["\']([^"\']+)["\']', re.M)
RE_TEMPLATE_NAME = re.compile(r'^[ \t]*TEMPLATE_NAME[ \t]*=[ \t]*["\']([^"\']+)["\']', re.M)
RE_PATCH_ID = re.compile(r'^[ \t]*(?:[A-Z0-9_]+_)?PATCH_ID[ \t]*=[ \t]*["\']([^"\']+)["\']', re.M)
RE_DEFN_CLASS = re.compile(r'@workflow\.defn[ \t]*\n(?:[ \t]*@[^\n]*\n)*[ \t]*class[ \t]+(\w+)', re.M)
# 引擎面补丁标识集锚（仅模块级、零缩进的赋值行，注释/字符串不误报）
RE_ENGINE_PATCH = re.compile(r'^[A-Z0-9_]*PATCH_ID[ \t]*=[ \t]*["\']([^"\']+)["\']', re.M)

# 注册顺序（t260924-04 方案 C1 钉死）：内置∪夹具（调用方 builtin 表）先占，
# 项目模板后到——后到撞名即拒收点名双方，不覆盖。
_BUILTIN_ORIGIN = {"dev-lane": "内置模板", "fixture-two-step": "夹具模板（SANDBAR_FIXTURE_TEMPLATES 门）"}

# KI-124（t260925-23）：外置模板段路径闸可声明的允许面 kind 白名单（弱面子集——
# 外置模板是跨项目收件面，self_heal/test_face 等强 kind 缺省就关）。本模块零
# shared/path_gates import（依赖注入纪律），故本地常量；与 path_gates.TEMPLATE_WEAK_KINDS
# 的漂移由单测交叉锁（两表相等）。
_PATH_GATE_KINDS = ("result_files", "write_set", "join", "prefixes")


def _rej(project: str, module: str, check: str, detail: str) -> Dict[str, str]:
    return {"project": project, "module": module, "check": check, "detail": detail}


def collect_engine_patch_ids(engine_dir: pathlib.Path) -> set:
    """引擎面补丁标识集：动态收集、不写死（方案 C4；样例见注释——ki003-breathe-v1、
    ticket-update-receipt-v1、dev-lane-ui-evidence 等）。"""
    ids: set = set()
    if not engine_dir.is_dir():
        return ids
    for p in sorted(engine_dir.glob("*.py")):
        try:
            text = p.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        ids |= set(RE_ENGINE_PATCH.findall(text))
    return ids


class ScanResult:
    """一次扫描的结构化结果：accepted（id → 名面登记项）/ classes（id → 类，仅类面）/
    rejections（结构化拒收清单）。"""

    def __init__(self) -> None:
        self.accepted: Dict[str, Dict[str, str]] = {}
        self.classes: Dict[str, Any] = {}
        self.module_names: Dict[str, str] = {}   # id → sandbox 装载模块名（worker passthrough 面）
        self.module_deps: Dict[str, frozenset] = {}  # id → 引擎依赖顶层名（D6 decode 面放行）
        self.rejections: List[Dict[str, str]] = []

    def merged_names(self, names: Dict[str, str], displays: Dict[str, str]) -> None:
        """把已接受 id 并入调用方两表（内置在前、项目后到；后到撞名已在 scan 拒）。"""
        for tid, item in self.accepted.items():
            names[tid] = item["class_name"]
            if item.get("display"):
                displays[tid] = item["display"]

    def reconcile(self, names: Dict[str, str], displays: Dict[str, str],
                  builtin_keys: set) -> None:
        """类面回写（workflows_v2 合并时调用）：名面此前并入、但类面深检拒掉的 id 从
        两表撤下；类面新接受的补上——引擎进程内 shared 名面与 workflows_v2 类面恒
        一致，两表交叉自检不破。builtin_keys（内置∪夹具）永不被撤。"""
        for tid in [t for t in names if t not in builtin_keys and t not in self.accepted]:
            names.pop(tid, None)
            displays.pop(tid, None)
        self.merged_names(names, displays)


def _scan_source(path: pathlib.Path) -> Tuple[Optional[str], Optional[str], List[str], Optional[str]]:
    """读模块源码并提取（TEMPLATE_ID / TEMPLATE_NAME / PATCH_ID 列表 / defn 类名）。
    TEMPLATE_ID 多值/缺失 = _SourceShape（硬前提）；defn 类不可辨 = 返回 None（由调用
    方按检查优先级判——撞名等更决定性的检查先行，类不可辨本身也是「畸形」拒收）。
    文件不可读 = OSError/UnicodeDecodeError 向上抛（由调用方转「加载失败」拒收）。"""
    text = path.read_text("utf-8")
    ids = RE_TEMPLATE_ID.findall(text)
    tid = ids[0] if len(set(ids)) == 1 else None
    multi = len(set(ids)) > 1
    names = RE_TEMPLATE_NAME.findall(text)
    patches = RE_PATCH_ID.findall(text)
    defn = RE_DEFN_CLASS.findall(text)
    if multi:
        raise _SourceShape("TEMPLATE_ID 多值（一模块一模板约定，见 %s 个不同声明：%s）"
                           % (len(set(ids)), "、".join(sorted(set(ids))[:4])))
    if not tid:
        raise _SourceShape("TEMPLATE_ID 缺失或不可辨（须模块级 TEMPLATE_ID = \"<id>\" 单值声明）")
    cls = defn[0] if len(set(defn)) == 1 else None
    return tid, (names[0] if names else ""), patches, cls


class _SourceShape(Exception):
    """名面（源码扫描层）畸形：raise→调用方转结构化拒收。"""


def scan(perkey_root: Callable[[], pathlib.Path],
         project_keys: Callable[[], List[str]],
         resolve_decl: Callable[[str], Dict[str, Any]],
         engine_dir: pathlib.Path,
         builtin_names: Dict[str, str],
         builtin_displays: Dict[str, str],
         part_kinds: Tuple[str, ...] = (),
         import_classes: bool = False) -> ScanResult:
    """单一真源扫描。参数全部注入（本模块零 shared import——ticket.py 以别名 spec
    装载 shared，双装载下 import shared 会裂出第二套表）：
      perkey_root   → shared.perkey_projects_root（可注入测试根）
      project_keys  → shared.load_projects_registry 的 key 清单（畸形项目已被其隔离）
      resolve_decl  → shared.project_paths（①d 解析；ProjectPathsError 向上抛）
      builtin_*     → 当前 env 下的内置∪夹具两表（先占方）
    import_classes=False：名面（stdlib 源码扫描）；True：类面（importlib 全量加载＋
    形状深检）。"""
    res = ScanResult()
    taken = {tid: (_BUILTIN_ORIGIN.get(tid, "已注册模板")) for tid in builtin_names}
    engine_patches = collect_engine_patch_ids(engine_dir)
    try:
        keys = sorted(project_keys())
    except Exception as e:  # 注册表枚举本身故障：高声记名，不静默当空
        res.rejections.append(_rej("", "", "注册表枚举失败", str(e)[:200]))
        return res
    for key in keys:
        try:
            info = resolve_decl(key)
        except Exception as e:  # ①d ProjectPathsError 族：声明面红 → 结构化拒收
            res.rejections.append(_rej(key, "project.yaml", "声明解析失败", str(e)[:240]))
            continue
        rel = info.get("workflow_modules_rel")
        if not rel:
            continue  # 不声明 = 零行为变化（契约①d 四类回退）
        base = info.get("main_dir")
        for item in str(rel).split(","):
            rel_item = item.strip()
            mod_path = pathlib.Path(base) / rel_item if base else pathlib.Path(rel_item)
            origin = "%s/%s" % (key, rel_item)
            try:
                tid, disp, patches, cls_name = _scan_source(mod_path)
            except _SourceShape as e:
                res.rejections.append(_rej(key, rel_item, "畸形", str(e)[:240]))
                continue
            except (OSError, UnicodeDecodeError) as e:
                res.rejections.append(_rej(key, rel_item, "加载失败",
                                           "模块不可读 %s：%s" % (mod_path, str(e)[:160])))
                continue
            hit = engine_patches & set(patches)
            if hit:
                res.rejections.append(_rej(key, rel_item, "补丁标识撞引擎面",
                                           "双方=%s（项目侧）× %s（引擎面集）；"
                                           "分支变更须走 <项目key>- 前缀补丁标识"
                                           % ("、".join(sorted(hit)), "引擎动态收集集")))
                continue
            if tid in taken:
                res.rejections.append(_rej(key, rel_item, "撞名 id",
                                           "检查=模板 id 全局唯一；占用方=%s（%s）；"
                                           "来件方=%s" % (tid, taken[tid], origin)))
                continue
            if cls_name is None:
                res.rejections.append(_rej(key, rel_item, "畸形",
                                           "模板类不可辨（须恰一个 @workflow.defn 类）"))
                continue
            cls = None
            mod_name = _module_name(key, mod_path)
            if import_classes:
                ok, cls = _load_class(mod_path, key, rel_item, tid, cls_name,
                                      mod_name, part_kinds, res.rejections)
                if not ok:
                    continue
            taken[tid] = origin
            res.accepted[tid] = {"class_name": cls_name, "display": disp,
                                 "project": key, "module": rel_item}
            if cls is not None:
                res.classes[tid] = cls
                res.module_names[tid] = mod_name
                res.module_deps[tid] = frozenset(_module_deps(mod_name) | {mod_name})
    return res


def _module_name(key: str, mod_path: pathlib.Path) -> str:
    """外置模块的 sandbox 装载名（worker passthrough 面同名注入，见 worker.py）。"""
    return "sandbar_ext_%s_%s" % (re.sub(r"\W", "_", key),
                                  re.sub(r"\W", "_", mod_path.stem))


def _sandbox_validate(cls) -> Optional[str]:
    """temporalio sandbox 预校验（D3 隔离兜底，t260924-04 第 2 轮打回）：用与 worker
    同款 restrictions（本模块名＋其引擎依赖顶层名 passthrough，D6）跑 prepare_workflow
    ——校验失败的模板在加载口即「模板级隔离拒收」，永不进 worker 注册表，坏模板炸
    不垮工人进程。temporalio 缺席（纯 CLI 名面不走到这）= 跳过预校验（返回 None）。"""
    try:
        from temporalio import workflow as _tworkflow
        from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner
    except ImportError:
        return None
    restrictions = SandboxedWorkflowRunner.restrictions.default
    try:
        import asyncio
        # D6（第 4 轮打回）：依赖顶层名与装载名一并放行——「预校验过了＝worker 能跑」。
        restrictions = restrictions.with_passthrough_modules(
            cls.__module__, *sorted(_module_deps(cls.__module__)))
        runner = SandboxedWorkflowRunner(restrictions=restrictions)
        # prepare_workflow 内部断言运行中事件循环——worker 侧天然在 loop 内，加载口
        # 是同步上下文，套一层临时 loop 供给同款环境。
        asyncio.new_event_loop().run_until_complete(_prepare(runner, cls))
    except Exception as e:
        return "%s: %s" % (type(e).__name__, str(e)[:200])
    return None


def _module_deps(mod_name: str) -> set:
    """外置模块的引擎依赖顶层模块名（动态收集，D6）：activate 期 payload 解码要
    typing.get_type_hints 按 `sys.modules[<所属模块>]` 查类型所属模块——sandbox 受限
    importer 对非 passthrough 名即 KeyError（'shared' 实录）。这里不做 sys.modules
    全量差集（外层进程面太宽），按引擎 workflow 面已知顶层名收（shared/base/
    activities/agent_activities/workflows/workflows_v2/dev_lane + 同族外置装载名）。
    temporalio 自身已在 default minimum passthrough 集，无需重复。"""
    deps = {"shared", "base", "activities", "agent_activities",
            "workflows", "workflows_v2", "dev_lane"}
    deps.discard(mod_name)
    for name in list(sys.modules):
        top = name.split(".")[0]
        if top.startswith("sandbar_ext_") and top != mod_name:
            deps.add(top)
    return deps


async def _prepare(runner, cls) -> None:
    from temporalio import workflow as _tworkflow
    runner.prepare_workflow(_tworkflow._Definition.must_from_class(cls))


def _load_class(mod_path: pathlib.Path, key: str, rel_item: str, tid: str,
                cls_name: str, mod_name: str, part_kinds: Tuple[str, ...],
                rejections: List[Dict[str, str]]) -> Tuple[bool, Any]:
    """类面深检：importlib 全量加载 → 找 @workflow.defn 类 → 形状校验 → sandbox 预
    校验。失败路径全部结构化拒收并点名检查项；返回 (是否接受, 类)。"""
    if not mod_path.is_file():
        rejections.append(_rej(key, rel_item, "加载失败",
                               "声明锚点缺失（不是文件）：%s" % mod_path))
        return False, None
    mod_name = _module_name(key, mod_path)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod  # dataclasses/temporalio 反查 __module__ 需要
        spec.loader.exec_module(mod)
    except Exception as e:
        rejections.append(_rej(key, rel_item, "加载失败",
                               "模块 import 抛错 %s：%s: %s"
                               % (mod_path, type(e).__name__, str(e)[:160])))
        return False, None
    cls = getattr(mod, cls_name, None)
    if cls is None:
        rejections.append(_rej(key, rel_item, "畸形",
                               "源码声明类 %s 不可加载（模块内找不到该名）" % cls_name))
        return False, None
    # 检查顺序：段定义先于 id 一致性——「缺 STAGES」是更基础的形状缺陷，优先点名
    stages = getattr(cls, "STAGES", None)
    if stages is None:
        rejections.append(_rej(key, rel_item, "畸形", "缺 STAGES（段定义缺失，无法驱动）"))
        return False, None
    if getattr(cls, "TEMPLATE_ID", None) != tid:
        rejections.append(_rej(key, rel_item, "畸形",
                               "TEMPLATE_ID 源码声明与类属性不一致：双方=%s（源码）× %s（类属性）"
                               % (tid, getattr(cls, "TEMPLATE_ID", None))))
        return False, None
    if not isinstance(stages, tuple) or not stages:
        rejections.append(_rej(key, rel_item, "畸形",
                               "STAGES 须为非空 tuple（实得 %s）" % type(stages).__name__))
        return False, None
    for i, st in enumerate(stages):
        for attr in ("id", "name", "role"):
            if not isinstance(getattr(st, attr, None), str) or not getattr(st, attr):
                rejections.append(_rej(key, rel_item, "畸形",
                                       "段形态不合：第 %d 段缺 %s（须非空字符串）" % (i + 1, attr)))
                return False, None
        parts = getattr(st, "parts", ())
        if part_kinds and not set(parts) <= set(part_kinds):
            rejections.append(_rej(key, rel_item, "畸形",
                                   "段形态不合：段 %s parts 含非法值 %r（合法集 %s）"
                                   % (getattr(st, "id", i + 1), tuple(parts), part_kinds)))
            return False, None
    # KI-124（t260925-23）：段路径闸声明深检（PATH_GATE / PATH_GATE_RULES）。声明面
    # fail-closed 且精确点名：键 ⊆ STAGES id 全集（子集纪律的模板侧机械锁）、kind ∈
    # 弱面白名单（外置模板是跨项目收件面，self_heal/test_face 等强 kind 缺省就关）、
    # 声明了规则却不开闸=死配置拒收。白名单本地常量（本模块零 shared/path_gates
    # import 的依赖注入纪律），两表漂移由单测交叉锁（TEMPLATE_WEAK_KINDS ⊆
    # STAGE_PATH_RULES 全词表）。
    pg_decl = getattr(cls, "PATH_GATE", False)
    pg_rules = getattr(cls, "PATH_GATE_RULES", None)
    if pg_rules not in (None, {}) and not pg_decl:
        rejections.append(_rej(key, rel_item, "畸形",
                               "路径闸声明不合：声明了 PATH_GATE_RULES 但 PATH_GATE "
                               "非 True（死配置，声明即开闸或整体不声明）："
                               "PATH_GATE=%r" % (pg_decl,)))
        return False, None
    if pg_decl:
        if not isinstance(pg_rules, dict) or not pg_rules:
            rejections.append(_rej(key, rel_item, "畸形",
                                   "路径闸声明不合：PATH_GATE=True 须配套非空 "
                                   "PATH_GATE_RULES dict（键=段 id；实得 %s）"
                                   % type(pg_rules).__name__))
            return False, None
        stage_ids = {getattr(st, "id", None) for st in stages}
        bad_keys = sorted(str(k) for k in pg_rules if k not in stage_ids)
        if bad_keys:
            rejections.append(_rej(key, rel_item, "畸形",
                                   "路径闸声明不合：PATH_GATE_RULES 键 ⊄ STAGES id 全集"
                                   "（fail-closed：未声明段会被闸拦成 unknown_stage）——"
                                   "越界键=%s；段集=%s" % (bad_keys, sorted(map(str, stage_ids)))))
            return False, None
        for k, v in sorted(pg_rules.items(), key=lambda x: str(x[0])):
            kind = v.get("kind") if isinstance(v, dict) else v
            if not isinstance(kind, str) or kind not in _PATH_GATE_KINDS:
                rejections.append(_rej(key, rel_item, "畸形",
                                       "路径闸声明不合：段 %s 规则 kind 非法 %r"
                                       "（外置模板弱面白名单=%s；强 kind 走建票把需求"
                                       "带进引擎侧）" % (k, v, list(_PATH_GATE_KINDS))))
                return False, None
            if kind == "prefixes":
                pfs = v.get("prefixes") if isinstance(v, dict) else None
                if not isinstance(pfs, (list, tuple)) or not pfs or \
                        not all(isinstance(x, str) and x.strip() for x in pfs):
                    rejections.append(_rej(key, rel_item, "畸形",
                                           "路径闸声明不合：段 %s kind=prefixes 须配套"
                                           "非空前缀表 prefixes（字符串列表）" % (k,)))
                    return False, None
    # sandbox 预校验（D3 兜底）：校验失败=模板级拒收点名，永不进 worker 注册表
    sandbox_err = _sandbox_validate(cls)
    if sandbox_err:
        rejections.append(_rej(key, rel_item, "sandbox 校验失败",
                               "temporalio workflow sandbox 拒绝该模板（不注册、不进"
                               " worker——坏模板不许炸工人进程）：%s" % sandbox_err))
        return False, None
    return True, cls

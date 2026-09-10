"""path_gates — 阶段路径闸 + 受保护路径闸（工单 t260911-03）。

宿主令 260910：仲裁、走查，凡事不应该有代码变化的阶段，不允许改代码，要有机械闸门
检查。两道闸都在 worker 代落盘（settle）时刻判定——此时引擎已确知段 id 与本批改动
文件清单，判定是纯路径白名单、零猜测：

①【阶段路径闸】按「段 × 允许改动面」判路径白名单：做方案/审方案＝零代码改动（仅
  结果文件）；实现＝写集内；设计集成测试＝仅 integration/；仲裁＝仅测试面 + 本票
  场景（tests-fault 修测试属设计内，碰产品代码一律拒）；验收走查/合并检查/合并＝
  零代码改动。违规＝拒绝落盘（不 commit）+ 回执点名「段 X 不允许改 Y」+ 合法出路。

②【受保护路径闸】「真源与期望值文件」任何泳道不得改：共享守卫脚本、共享电池期望
  值/阈值档、配置真源（verify.yaml/model-routes.yaml/merge-checks.yaml/projects.yaml/
  project-registry.ts/roles/）、契约文档（docs/design/ 整目录）、以及闸自身
  （path_gates.py，防「各票改闸给自己发免红令」）。语义=「存在才拦」：以泳道分叉点
  （base_ref，非 HEAD——HEAD 会把本票早段 commit 里的文件误判为已存在，票内 rework
  死锁）为锚，base 已存在的名单内文件改动即红；新建（base 不存在）放行，落地后即受
  保护——闸不挡自己的出生，但挡后续任何泳道改它。出路：人审放行或回 main 侧走票。

③协议联动（t260910-13）：拒绝回执内嵌机器可辨键值 path_gate_reason=<码>，原因码走
  开放词表（不入 PREPARE_REASONS/ASSERT_REASONS），使「环境/产品/越权」三态可辨。

步 0 键集证据（运行时 settle 实际收到的 stage_id 全集，接线时逐一核对）：
  - agent_activities._run_agent_stage_impl 两处 settle（缓存命中分支 + 结果文件就绪
    分支）：stage_id = AgentStageArgs.stage_id（generic 段 = create_plan/review_plan/
    implement/design_integration_tests/integration_review（仅老票 replay）+ 已退役
    模板段 + fixture 段；新票 path_gate 只对 dev-lane 开 → 实际面为 dev-lane 段）；
  - agent_activities._merge_check_one_scope 自愈 settle：字面 "merge_check"；
  - agent_activities.settle_lane 逐树 settle：args.stage_id（dev_lane 两处派发实际
    传值 = "implement"（integ_join 汇合）与 "arbitrate"（arb_acc 并行汇合））；
  - agent_activities._stub_stage_shortcut 缓存 settle（settle_on_cache）与 arbitrate
    tests-fault 分支 settle：stage_id = "arbitrate"；
  - suggest_next/acceptance_walkthrough/ui_evidence 三个段不走 _settle_worktree_lane
    （walkthrough 报告落 .sandbar、suggest_next 只读分析、ui_evidence 截图归档）——
    规则键仍配置（fail-closed 防未来接线漏配），当前链路为防御性键。
  未知段（键不在规则表）对 path_gate=True 一律 fail-closed 拒绝（reason=unknown_stage）；
  老在途票保护由 path_gate 缺省 False 承担（TicketInput 无此字段 → 永远 False，不追溯）。

本模块零 IO 零进程零网络（「基点已存在」由调用方注入谓词），全部纯函数——单测
（server/engine/tests/test_t260911_03_path_gates.py）与场景可直调。
"""
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

# 拒绝回执的机器可辨键值：is_gate_refusal 以此辨认闸拒绝（区别于其它 settle note）。
PATH_GATE_REASON_KEY = "path_gate_reason="

# 结果/回执文件前缀：引擎运行时目录（.dsh 不进本表——SETTLE_PATHSPEC 已排除）。
# .suyou = 老泳道粘滞名（t260907-04 naming-compat）。这些目录不进 commit（settle
# add 后 reset），但会出现在 status 脏清单里，各段白名单一律放行。
RESULT_FILE_PREFIXES = (".sandbar", ".suyou")  # naming-compat

# 受保护路径名单（真源与期望值文件；匹配立场与写集一致：条目==路径 或 路径以「条目/」
# 为目录前缀）。任何泳道改名单内**且基点已存在**的文件即红（新建放行、落地即护）。
# 显式不在名单：integration/run_scenarios.py（场景登记=正常工作面，避免误伤）。
PROTECTED_PATHS: Tuple[str, ...] = (
    # 共享守卫脚本（t260910-06/-08 两票仲裁段就地改期望值的事故面）
    "integration/t260902-07/tests/test_route_table.py",
    "integration/t260902-07/tests/test_route_lookup.py",
    # 共享电池的期望值/阈值档
    "integration/baselines",
    # 配置真源
    "verify.yaml",
    "server/model-routes.yaml",
    "server/merge-checks.yaml",
    "server/projects.yaml",
    "server/project-registry.ts",
    "server/roles",
    # 契约文档（定稿知识库整目录前缀，免逐文件枚举漏新契约）
    "docs/design",
    # 闸自身自保护（本票出生：新建时 base 不存在 → 放行）
    "server/engine/path_gates.py",
)

# 阶段路径闸规则表：键 = 运行时 settle 实际收到的 stage_id（见模块头「步 0 键集证据」）。
# kind 语义：
#   result_files   仅结果/回执文件（.sandbar/.suyou）——零代码改动段  # naming-compat
#   write_set      写集内 + 结果文件（implement）
#   join           写集 ∪ integration/ + 结果文件（integ_join 汇合：implement+design 两边并集）
#   prefixes       指定目录前缀 + 结果文件（design_integration_tests）
#   ui_dirs        调用方传入的 ui_evidence.dirs 声明目录 + 结果文件（ui_evidence；
#                  声明读不到=空集=fail-closed）
#   ticket_receipts 仅本票场景回执（integration/<ticket_id>/）+ 结果文件（run_integration_tests）
#   test_face      测试面（is_test_face ∪ integration/ 已登记场景脚本）∪ 本票场景
#                  + 结果文件（arbitrate；tests-fault 直接迭代 integration/ 测试集）
#   self_heal      写集 ∪ 本票场景 + 结果文件（merge_check 的 KI-009 自愈专用：收场
#                  语义=替本票未落盘的写集内改动兜底，admission 已由调用方
#                  _dirty_within_write_set 前置把关；merge_check 段自身不产生代码改动）
STAGE_PATH_RULES = {
    "create_plan": {"kind": "result_files"},
    "review_plan": {"kind": "result_files"},
    "implement": {"kind": "write_set"},
    "integ_join": {"kind": "join"},
    "design_integration_tests": {"kind": "prefixes", "prefixes": ("integration",)},
    "ui_evidence": {"kind": "ui_dirs"},
    "run_integration_tests": {"kind": "ticket_receipts"},
    "arbitrate": {"kind": "test_face"},
    "acceptance_walkthrough": {"kind": "result_files"},
    "merge_check": {"kind": "self_heal"},
    "merge": {"kind": "result_files"},
    "suggest_next": {"kind": "result_files"},
}

# 段允许面的人读描述（拒绝回执用）。
_STAGE_FACE_DESC = {
    "result_files": "仅结果/回执文件（零代码改动段）",
    "write_set": "写集内文件 + 结果文件",
    "join": "写集内文件 ∪ integration/ + 结果文件（并行汇合段）",
    "ui_dirs": "ui_evidence 声明目录 + 结果文件",
    "ticket_receipts": "本票场景回执（integration/<ticket_id>/）+ 结果文件",
    "test_face": "测试面（tests/ 目录、test_*.py、integration/ 场景脚本）∪ 本票场景 + 结果文件",
    "self_heal": "写集内文件 ∪ 本票场景 + 结果文件（自愈收场）",
    "prefixes": None,  # prefixes 用规则里的前缀拼
}

# 出路文案（按原因码分派）。
_OUT_Unauthorized = "合法出路：打回目标段或回 main 侧走票"
_OUT_PROTECTED = "合法出路：人审放行或回 main 侧走票"
_OUT_CONFIG = "合法出路：补配后重跑，或回 main 侧走票"


# ---------------- 基础判定（立场镜像 agent_activities 写集条目匹配，测试锁漂移） ----------------

def _is_safe_path(path: Any) -> bool:
    """路径合法性（fail-closed 立场与 _dirty_within_write_set 一致）：非串/空串、
    绝对路径、含反斜杠、含 `..` 段、含 git glob 哨兵字符（?!*[]）→ 一律不安全。"""
    if not isinstance(path, str) or not path:
        return False
    if path.startswith("/") or "\\" in path or path == ".." or path.startswith("../") \
            or "/../" in path or path.endswith("/.."):
        return False
    if any(ch in path for ch in "?!*[]"):
        return False
    return True


def _clean_files(files: Iterable[Any]) -> List[str]:
    """脏文件清单清洗：非串/空串/不安全路径直接丢弃不猜（fail-closed，交由「清单外
    即违规」的立场由调用方兜底——清洗后不安全的条目不进判定，避免畸形输入放大）。"""
    out: List[str] = []
    for f in files if isinstance(files, (list, tuple)) else []:
        if _is_safe_path(f):
            out.append(f)
    return out


def _entries(write_set: Any) -> Tuple[bool, List[str]]:
    """条目表清洗：镜像 _dirty_within_write_set 的立场——write_set 非列表/空/任一条目
    非串或空白 → (False, [])（fail-closed，调用方据此报「补配写集」类原因码）。"""
    if not isinstance(write_set, list) or not write_set:
        return (False, [])
    pats: List[str] = []
    for p in write_set:
        if not isinstance(p, str) or not p.strip():
            return (False, [])
        s = p.strip().rstrip("/")
        if s:
            pats.append(s)
    if not pats:
        return (False, [])
    return (True, pats)


def _within(path: str, entries: Sequence[str]) -> bool:
    """条目匹配：路径 == 条目，或路径以「条目 + /」为目录前缀（条目可写 `app/src`
    指代整个前缀；条目尾斜杠同义）。"""
    return any(path == s or path.startswith(s + "/") for s in entries)


def _is_result_file(path: str) -> bool:
    return _within(path, RESULT_FILE_PREFIXES)


def _is_scenario_script(path: str) -> bool:
    """integration/ 下已登记场景脚本与登记表本身（t260911-03 CF2）：tests-fault 时
    仲裁直接迭代 integration/ 测试集——sc_*.py / sc_*.mjs 场景脚本与
    integration/run_scenarios.py（场景登记=正常工作面，不受保护）都属测试面。
    共享资产仍由受保护闸兜底（如 t260902-07 守卫、integration/baselines）。"""
    if not _is_safe_path(path):
        return False
    if path == "integration/run_scenarios.py":
        return True
    segs = path.split("/")
    if len(segs) < 3 or segs[0] != "integration":
        return False
    base = segs[-1]
    return base.startswith("sc_") and (base.endswith(".py") or base.endswith(".mjs"))


def is_test_face(path: str) -> bool:
    """测试面口径（定稿）：路径含 `tests/` 目录段（含仓库根 tests/ 开头），或文件名
    匹配 test_*.py / *_test.py。conftest.py 等测试辅助不在 tests/ 目录内的不算
    （口径=「tests 目录内或测试文件名」，宁窄勿宽——仲裁段改产品代码必须拦）。"""
    if not _is_safe_path(path):
        return False
    segs = path.split("/")
    if "tests" in segs[:-1] or (len(segs) >= 2 and segs[0] == "tests"):
        return True
    base = segs[-1]
    return base.startswith("test_") and base.endswith(".py") \
        or base.endswith("_test.py")


# ---------------- ① 阶段路径闸 ----------------

def judge_stage_paths(stage_id: str, files: Iterable[Any], write_set: Any = None,
                      ticket_id: str = "", ui_dirs: Any = None
                      ) -> Tuple[bool, List[str], str]:
    """段 × 允许面判定。返回 (allowed, violations, reason_code)；allowed=True 时
    violations 为空、reason_code 为 ""。

    - 键不在 STAGE_PATH_RULES → fail-closed 拒绝（reason=unknown_stage），不允许
      「未知段=放行」——新段/新模板忘配规则 = 被拦 + 单测锁定（源码锁定测试断言
      DevLaneWorkflow.STAGES id 全集 ⊆ 规则键集）。
    - 写集空/缺失（write_set/write_join/self_heal 类）→ reason=write_set_missing，
      出路=补配写集（沿用既有 helper 空写集 fail-closed 立场，显式化）。
    - 结果文件（.sandbar/.suyou）对所有段放行（不进 commit，与 SETTLE_PATHSPEC 排除  # naming-compat
      现实一致）。
    """
    clean = _clean_files(files)
    rule = STAGE_PATH_RULES.get(str(stage_id or ""))
    if rule is None:
        return (False, list(clean), "unknown_stage")
    rest = [f for f in clean if not _is_result_file(f)]
    if not rest:
        return (True, [], "")
    kind = rule.get("kind")
    ws_ok, ws = _entries(write_set)
    ui_ok, ui = _entries(ui_dirs)
    receipt = ("integration/" + str(ticket_id).strip("/")) if str(ticket_id or "").strip("/" ) else ""

    def face(f: str) -> str:
        """单文件判定：返回 ""（允许）或原因码。"""
        if kind == "result_files":
            return "unauthorized_path"
        if kind == "write_set":
            return "" if (ws_ok and _within(f, ws)) else \
                ("write_set_missing" if not ws_ok else "unauthorized_path")
        if kind == "join":
            if _within(f, ("integration",)):
                return ""
            return "" if (ws_ok and _within(f, ws)) else \
                ("write_set_missing" if not ws_ok else "unauthorized_path")
        if kind == "prefixes":
            return "" if _within(f, rule.get("prefixes") or ()) else "unauthorized_path"
        if kind == "ui_dirs":
            return "" if (ui_ok and _within(f, ui)) else \
                ("ui_dirs_missing" if not ui_ok else "unauthorized_path")
        if kind == "ticket_receipts":
            return "" if (receipt and _within(f, (receipt,))) else "unauthorized_path"
        if kind == "test_face":
            if is_test_face(f) or _is_scenario_script(f):
                return ""
            return "" if (receipt and _within(f, (receipt,))) else "unauthorized_path"
        if kind == "self_heal":
            if ws_ok and _within(f, ws):
                return ""
            if receipt and _within(f, (receipt,)):
                return ""
            return "write_set_missing" if not ws_ok else "unauthorized_path"
        return "unknown_stage"  # 规则表内未知 kind：规则表自身配错，同样 fail-closed

    violations = [f for f in rest if face(f)]
    if not violations:
        return (True, [], "")
    return (False, violations, face(violations[0]))


# ---------------- ② 受保护路径闸 ----------------

def judge_protected_paths(files: Iterable[Any],
                          exists_at_base: Optional[Callable[[str], bool]] = None
                          ) -> Tuple[List[str], str]:
    """受保护名单判定。返回 (violations, reason_code)；无命中返回 ([], "")。

    「存在才拦」：名单内文件还要在泳道分叉点（base_ref）已存在才算改真源——新建
    （base 不存在）放行，落地后即受保护（闸不挡自己的出生）。exists_at_base 为 None
    （调用方无法锚定基点）→ 一律按已存在处理（fail-closed 拦），绝不因锚缺失放行。
    """
    clean = _clean_files(files)
    violations: List[str] = []
    for f in clean:
        if not _within(f, PROTECTED_PATHS):
            continue
        if exists_at_base is not None:
            try:
                if not exists_at_base(f):
                    continue
            except Exception:
                pass  # 谓词故障=锚不可知：按已存在处理（fail-closed 拦，不猜）
        violations.append(f)
    if not violations:
        return ([], "")
    return (violations, "protected_path")


# ---------------- 拒绝回执（机读键值 + 点名 + 出路） ----------------

def _fmt_files(files: Sequence[str], cap: int = 3) -> str:
    shown = list(files[:cap])
    tail = "" if len(files) <= cap else "（等 %d 项）" % len(files)
    return "、".join(shown) + tail


def gate_refusal_note(stage_id: str, violations: Sequence[str], reason_code: str) -> str:
    """构造单行拒绝回执：内嵌 path_gate_reason=<码>（is_gate_refusal 以此辨认）+
    点名段与文件 + 合法出路。行内不含换行（settle note 以「；」拼接进 evidence）。"""
    names = _fmt_files(violations)
    if reason_code == "protected_path":
        return ("受保护路径闸拒绝落盘（%sprotected_path）：%s 属保护名单（真源与期望值，"
                "基点已存在），任何泳道不得改——%s"
                % (PATH_GATE_REASON_KEY, names, _OUT_PROTECTED))
    if reason_code == "unknown_stage":
        return ("阶段路径闸拒绝落盘（%sunknown_stage）：段 %s 未配置允许改动面"
                "（fail-closed，不静默免检）——%s"
                % (PATH_GATE_REASON_KEY, stage_id, _OUT_CONFIG))
    if reason_code == "write_set_missing":
        return ("阶段路径闸拒绝落盘（%swrite_set_missing）：段 %s 无写集可判（写集空/缺失），"
                "改动 %s 出白名单面——%s"
                % (PATH_GATE_REASON_KEY, stage_id, names, _OUT_CONFIG))
    if reason_code == "ui_dirs_missing":
        return ("阶段路径闸拒绝落盘（%sui_dirs_missing）：段 %s 读不到 ui_evidence 声明目录，"
                "改动 %s 无白名单可判——%s"
                % (PATH_GATE_REASON_KEY, stage_id, names, _OUT_CONFIG))
    if reason_code == "status_failed":
        return ("路径闸无法判定（%sstatus_failed）：git status 失败，改动清单未知，"
                "fail-closed 不落盘——出路：修复环境后重跑（环境类，进协议三态之「环境」）"
                % PATH_GATE_REASON_KEY)
    rule = STAGE_PATH_RULES.get(str(stage_id or ""))
    desc = _STAGE_FACE_DESC.get(rule.get("kind")) if rule else None
    if rule and rule.get("kind") == "prefixes":
        desc = "仅 %s" % "、".join(rule.get("prefixes") or ())
    return ("阶段路径闸拒绝落盘（%sunauthorized_path）：段 %s 不允许改 %s（本段只许：%s）"
            "——%s"
            % (PATH_GATE_REASON_KEY, stage_id, names,
               desc or "规则表声明面", _OUT_Unauthorized))


def is_gate_refusal(note: str) -> bool:
    """settle note 是否为闸拒绝回执（机器口径：含 path_gate_reason= 键值）。"""
    return PATH_GATE_REASON_KEY in str(note or "")

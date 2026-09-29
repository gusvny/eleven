"""t260917-04：仲裁闸拒回放兼容门源码锁 + 工作流体命令面分支机械强制。

锁的目标形态＝main（2c1b4ee 起）：`ARBITRATE_REFUSAL_PATCH_ID`（常量 id）短路式门 ×3
（run_integration_tests 段入口格式轮次复位点、串行仲裁守门分支、并行纠正用例守门分支）。
本 worktree 的 dev_lane.py 须与 main 同步（implement gen1 S1）后本锁才绿；base(373741c)
树上跑＝红（这正是验收①的无门红演示）。

本文件三件事（工单修向②：把「回放兼容」从人记纪律变成机械门）：
  A. 常量与门位锁（u13 窗形先例：锁结构形态、不锁行号；「注释里不得出现门调用文本
     ——计数即证据」纪律：dev_lane.py 注释/文档串出现该调用文本即计数变多自红）。
  B. FakeMemoGate 双态语义（u12 先例）＋常量 id「唤醒不激活」反例机械注记（R3：
     保真锚落 SDK 源码位）。
  C. AST 机械强制扫描器：工作流体（SCOPE_FILES）中凡 If/While/IfExp 测试位 await
     「命令面方法」而未过 workflow.patched 门的分支，必须登记 BRANCH_REGISTRY 并给
     回放兼容说明，否则红。命令面方法集**自推导**（review C1 闭合要求，禁纯硬编码
     名单——本票事故形态恰是「新包装方法不在任何名单上」）：
       种子 = 方法体内出现 workflow.<SDK 命令> 调用（execute_activity /
         start_activity / execute_child_workflow / start_child_workflow / sleep /
         wait_condition；await 与否皆算）；
       闭包 = 凡 await self._x(...) 边传导，调命令面者亦命令面。
     「过门」判定：测试位直呼 workflow.patched(...)，或调用「纯门包装方法」——体内
     含 workflow.patched( 评值、且不含 SDK 命令调用/命令面 await 的方法（KI-061
     `_blocked_over_limit` 的「纯评值」骨架即此形态；含命令面调用的混合方法不入集，
     防整方法豁免分支的洗白面）。IfExp/While 与 If 同规则扫描（见合成用例）。
     推导集按方法名跨文件合并（本引擎工作流体类族方法名唯一；模块级函数与非 self
     属性调用不在图内，属已声明边界）。SDK 命令名单锚的是 SDK 命令面（版本化外部
     契约），不是本项目包装方法名——后者永远名单不住。

先例取舍清单（review C2 成文要求；来源=t260916-28 LANE_DSH 包 + t260908-01 KI-061）：
  ① workflow.patched 门 parked-False 旧路径 —— 带过来（main 2c1b4ee 三处同门）；
  ② 单一 patch id 同语义包 —— 带过来（三点同一常量 id）；
  ③ u12 FakeMemoGate 双态语义 —— 带过来并扩（b2 常量 id memo 固化反例）；
  ④ u13 窗形源码锁（rindex 窗、锁结构不锁行号）—— 带过来（A 组）；
  ⑤ 「注释不得含门调用文本——计数即证据」纪律 —— 带过来（A 组 count==3 即执行）；
  ⑥ KI-061 unique-per-entry patch id（base#seq，seq 无条件递增）—— 【宿主收敛不带入
    main，缺陷在案】常量 id 在在飞票上的首评落在重放段（旧历史无 marker）→ memo 固化
    False → 该票唤醒后活执行仍拿 False → 新语义（闸拒真因脸）对在飞票永不激活
    （-19/-21 形态；t260907-10 固定 id 热修同族失败，KI-061 docstring 早有成文）。
    本锁 b2 反例机械钉住该机理；README §8.3.2「已知缺陷」段＋KI-094 登记（merge 关卡
    落 notes/debts/known-issues.md）承接，follow-up＝门升级 per-entry 形态；
  ⑦ KI-061 测试开关先例（SANDBAR_TEST_DISABLE_KI061 式）—— 不带入（main 形态无开关；
    若 follow-up 引入，方向性纪律＝单向回放安全、仅限整票全程 DISABLE 的测试台，
    见 gen0 报告与 KI-094 文）。

已知边界（残余风险）：方法体**内部**（非分支测试位）的存量 await 命令调用不在本锁
覆盖面——入口由「分支测试位」规则间接看住；扩面需先议白名单治理成本。

运行：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t260917_04_replay_gate_lock.py -q`（UT 全程禁网络/真
Temporal/真 git，conftest 契约）。
"""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
SRC_DL = (POC / "dev_lane.py").read_text("utf-8")

GATE_CALL = "workflow.patched(ARBITRATE_REFUSAL_PATCH_ID)"

# ---------- A. 常量与门位锁（窗形，不锁行号） ----------


def test_a1_constant_and_exactly_three_gated_sites():
    assert 'ARBITRATE_REFUSAL_PATCH_ID = "dev-lane-arb-refusal-v1"' in SRC_DL
    # 恰三使用点：段入口格式轮次复位点、串行仲裁守门分支、并行纠正用例守门分支。
    # ⑤注释纪律：dev_lane.py 任何注释/文档串出现该调用文本即计数变多自红。
    assert SRC_DL.count(GATE_CALL) == 3, (
        "门使用点恰应 3 处（复位点+两守门分支）；多=注释违规或新分支未登记预期，少=门被拆")
    # 常量行恰好一次定义
    assert SRC_DL.count('ARBITRATE_REFUSAL_PATCH_ID = "dev-lane-arb-refusal-v1"') == 1


def test_a2_serial_site_window_keeps_old_path():
    a = SRC_DL.index("await self._arbitrate_refusal_blocked(res)")
    head = SRC_DL.rindex(GATE_CALL, 0, a)
    until = SRC_DL.index("verdict = parse_arbitration_summary(res.summary)", a)
    window = SRC_DL[head:until]
    # 短路式门控形态：门调用经续行与守门 await 同在一个 if 测试位（门 False 不调守门、
    # 不产生新命令——旧历史逐字走旧路径）
    assert "and await self._arbitrate_refusal_blocked(res)" in window
    assert "continue" in window, "闸拒分支的 continue 语义必须在门后原样保留"
    tail = SRC_DL[until:until + 600]
    assert "arb_format_rounds += 1" in tail, "门 False 时旧格式计数链必须原样可达"


def test_a3_correction_leg_window_keeps_old_path():
    a = SRC_DL.index("await self._arbitrate_refusal_blocked(rraw)")
    head = SRC_DL.rindex(GATE_CALL, 0, a)
    until = SRC_DL.index("arb_done = True", a)
    window = SRC_DL[head:until]
    assert "continue" in window
    # 门 False 时落回同段既有格式计数路径（向前最近一次格式计数=本纠正用例的计数器）
    assert SRC_DL.rindex("arb_format_rounds += 1", 0, a) < a


def test_a4_reset_point_gated():
    # 段入口格式轮次复位点与两守门分支同 id 同语义包：旧重放恒 False 不复位＝与旧代码
    # 逐字一致（复位是命令轨迹敏感变更：老历史计数跨 rework 累积可触发 blocked/纠正
    # 命令，复位为 0 会少发命令）。
    assert ("if %s:\n                    arb_format_rounds = 0" % GATE_CALL) in SRC_DL


# ---------- B. 停泊/活实例双态语义（u12 同款）＋常量 id 固化反例（R3） ----------


class FakeMemoGate:
    """逐语义镜像 temporalio SDK 的 workflow_patch 语义（保真锚，R3）：
    - 契约入口：.venv/lib/python3.9/site-packages/temporalio/workflow.py:1127 `def patched`
      （docstring：未 begin/current workflow 抛错；「identifier may be used repeatedly」
      ＝同 id 跨次复用合法——但同 id 复用即共享同一 memo 判定，跨次固化）；
    - 实现协议：同文件 :767 `def workflow_patch`（worker 侧实现见
      temporalio/worker/workflow_instance.py 的 workflow_patch interceptor：memo 命中
      即返回；首评 `not is_replaying or replaying 且已见该 patch` 固化并记 notified）。
    SDK 升级若改语义，此处注释锚即为 diff 观测点；镜像失真=本组测试红。"""

    def __init__(self, is_replaying: bool):
        self.memo: dict = {}
        self.notified: set = set()
        self.is_replaying = is_replaying

    def patched(self, pid: str) -> bool:
        if pid in self.memo:
            return self.memo[pid]
        use = (not self.is_replaying) or (pid in self.notified)
        self.memo[pid] = use
        if use:
            self.notified.add(pid)
        return use


def test_b1_gate_semantics_two_states():
    parked = FakeMemoGate(is_replaying=True)
    assert parked.patched("dev-lane-arb-refusal-v1") is False, (
        "老历史重放：门恒 False（走旧路径，零新命令）")
    live = FakeMemoGate(is_replaying=False)
    assert live.patched("dev-lane-arb-refusal-v1") is True
    assert live.patched("dev-lane-arb-refusal-v1") is True, "同 id 二次求值 memo 命中（固化）"
    assert "dev-lane-arb-refusal-v1" in live.notified


def test_b2_constant_id_fixation_counter_example():
    """常量 id「唤醒不激活」缺陷的机械注记（-19/-21 形态）：在飞票门首评落在重放段
    （旧历史无 marker）→ memo 固化 False → 同一实例（同一次 workflow run）换修复
    worker 唤醒后的活执行仍拿 False → 新语义（闸拒真因脸）对在飞票永不激活。
    规避形态＝KI-061 `base#seq` per-entry（每次进入新鲜 id，活评 True）；main 现形态
    为常量 id，本缺陷承接于 README §8.3.2「已知缺陷」＋KI-094（follow-up 升级门）。"""
    gate = FakeMemoGate(is_replaying=True)
    pid = "dev-lane-arb-refusal-v1"
    assert gate.patched(pid) is False, "在飞票重放段首评：False 且零命令"
    gate.is_replaying = False  # 换修复 worker 唤醒：重放结束、进入活执行（同一 run 实例）
    assert gate.patched(pid) is False, (
        "常量 id memo 固化：唤醒后活执行仍拿 False＝新语义对在飞票永不激活"
        "（真因脸永不上票面）；规避＝KI-061 base#seq per-entry（每次新鲜 id）")
    assert pid not in gate.notified, "固化 False 全程不得发 marker"


# ---------- C. AST 机械强制扫描器（C1 闭合：命令面自推导 + 纯门包装识别） ----------

# 扫描范围（C4：workflows.py / workflows_v2.py 为真实工作流体，纳入；扩展=加名）
SCOPE_FILES = ("dev_lane.py", "base.py", "workflows.py", "workflows_v2.py")
# SDK 命令面（外部契约，版本化；锚 SDK 不锚本项目包装方法名——后者名单必陈旧）
SDK_COMMANDS = frozenset({
    "execute_activity", "start_activity", "execute_child_workflow",
    "start_child_workflow", "sleep", "wait_condition",
})


def load_source_text(path):
    """读源码文本；非 UTF-8 / 不可读 → (None, 结构化错误)，不炸（review C6 第五态）。"""
    try:
        return Path(path).read_bytes().decode("utf-8"), None
    except UnicodeDecodeError as e:
        return None, "非 UTF-8 源码不可解析：%s（%s）" % (path, e)
    except OSError as e:
        return None, "源码不可读：%s（%s）" % (path, e)


def _parse(text: str, label: str):
    try:
        return ast.parse(text), None
    except SyntaxError as e:
        return None, "%s: 语法不可解析（行 %s: %s）" % (label, getattr(e, "lineno", "?"), e.msg)


def _is_workflow_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "workflow")


def _is_self_call(node: ast.Call) -> bool:
    return (isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self")


def _parents(tree: ast.AST) -> dict:
    return {child: parent for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)}


def _enclosing_func_name(parents: dict, node: ast.AST) -> str:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
        cur = parents.get(cur)
    return "<module>"


def _awaited_self_callees(node: ast.AST) -> set:
    """方法体内 await self._x(...) 的 x 集合。"""
    out = set()
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Await) and isinstance(sub.value, ast.Call)
                and _is_self_call(sub.value)):
            out.add(sub.value.func.attr)
    return out


def derive_command_face(trees: dict) -> set:
    """命令面方法集自推导：种子（体含 workflow.<SDK 命令> 调用）+ await self._x 闭包。"""
    seeds, edges = set(), {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if _is_workflow_call(sub) and sub.func.attr in SDK_COMMANDS:
                    seeds.add(node.name)
                    break
            for callee in _awaited_self_callees(node):
                edges.setdefault(node.name, set()).add(callee)
    closed = set(seeds)
    changed = True
    while changed:
        changed = False
        for caller, callees in edges.items():
            if caller not in closed and callees & closed:
                closed.add(caller)
                changed = True
    return closed


def derive_gate_wrappers(trees: dict, closed: set) -> set:
    """纯门包装方法集：体内含 workflow.patched( 评值、且不含 SDK 命令调用/命令面
    await（只做评值/短路，零命令）。含命令面调用的混合方法不入集（防整方法豁免
    分支的洗白面）。"""
    wrappers = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(_is_workflow_call(sub) and sub.func.attr == "patched"
                       for sub in ast.walk(node)):
                continue
            impure = any(
                (_is_workflow_call(sub) and sub.func.attr in SDK_COMMANDS)
                for sub in ast.walk(node)) or bool(
                    _awaited_self_callees(node) & closed)
            if not impure:
                wrappers.add(node.name)
    return wrappers


def _face_in_test(test: ast.AST, closed: set) -> set:
    """If/While/IfExp 测试位里 await（或直呼）到的命令面：self._x（x∈闭包）与
    workflow.<SDK 命令>。"""
    face = set()
    for node in ast.walk(test):
        if _is_workflow_call(node) and node.func.attr in SDK_COMMANDS:
            face.add("workflow." + node.func.attr)
        if (isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
                and _is_self_call(node.value)
                and node.value.func.attr in closed):
            face.add(node.value.func.attr)
    return face


def _has_patched(test: ast.AST, wrappers: set) -> bool:
    """测试位是否「过门」：直呼 workflow.patched(...)，或调用纯门包装方法。"""
    for node in ast.walk(test):
        if _is_workflow_call(node) and node.func.attr == "patched":
            return True
        if isinstance(node, ast.Call) and _is_self_call(node) \
                and node.func.attr in wrappers:
            return True
    return False


def scan_unpatched_branches(files: dict) -> dict:
    """扫描：测试位含命令面调用而未过 patched 门（含纯门包装）的分支。anchor 不含
    行号（锁结构不锁行号），同形分支用序号区分。"""
    trees = {}
    for label in sorted(files):
        tree, err = _parse(files[label], label)
        if err:
            return {"ok": False, "error": err, "branches": [],
                    "command_face": [], "gate_wrappers": []}
        trees[label] = tree
    closed = derive_command_face(trees)
    wrappers = derive_gate_wrappers(trees, closed)
    branches, seen = [], {}
    for label, tree in trees.items():
        parents = _parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.IfExp)):
                face = _face_in_test(node.test, closed)
                if face and not _has_patched(node.test, wrappers):
                    key = "%s#%s#%s" % (label, _enclosing_func_name(parents, node),
                                        ast.unparse(node.test)[:160])
                    ordinal = seen.get(key, 0)
                    seen[key] = ordinal + 1
                    branches.append({"anchor": "%s#%d" % (key, ordinal),
                                     "face": sorted(face), "label": label,
                                     "line": node.lineno})
    return {"ok": True, "branches": branches, "command_face": sorted(closed),
            "gate_wrappers": sorted(wrappers)}


# 显式登记表（回放兼容说明；与扫描结果**双向精确相等**：新分支未登记=红=下一个
# t260917-01；登记而分支已不在=红=清陈旧条目）。_blocked_over_limit 两处不入「纯门
# 包装」是有意的：其体内含 await self._blocked（命令面）＝混合方法，白名单登记并写明
# 自守机制（unique-per-entry patch id，KI-061）。
BRANCH_REGISTRY = {
    # 260929 集成判停两处（串行 / 并行汇合侧）：外层已处
    # workflow.patched(INTEG_STALL_PATCH_ID) 门内（AST 祖先链核实，自证钉在
    # test_260929_integ_stall_guard.py::test_stall_branches_are_inside_their_patch_gate
    # ——分支挪出门外该钉先红）。旧 history（无 marker）重放整块缺席=分支不可达；
    # _blocked_over_limit 体内另有 KI-061 unique-per-entry 门自守（同上两款）。
    "dev_lane.py#run#await self._blocked_over_limit(stall['note'])#0":
        "260929 集成判停（串行侧）：测量面零变化 ⇒ 转人审；外层 workflow.patched("
        "INTEG_STALL_PATCH_ID) 门内，旧 history 无 marker=整块缺席（重放零新命令）。",
    "dev_lane.py#run#await self._blocked_over_limit(stall2['note'])#0":
        "260929 集成判停（并行汇合侧，同形分支）：同上门与自守。",
    "dev_lane.py#run#await self._blocked_over_limit(route.split(':', 1)[1])#0":
        "KI-061：_blocked_over_limit 内部以 unique-per-entry patch id（seq 无条件递增、"
        "每次进入换 id，memo 不毒化）自守重放，分支选择本身零新命令形态；串行仲裁侧。",
    "dev_lane.py#run#await self._blocked_over_limit(route.split(':', 1)[1])#1":
        "同上（并行汇合侧同形分支，KI-061 同款自守机制）。",
    # t260917-09 豁免超限封面两处（串行/并行汇合侧）：外层已处
    # workflow.patched(TESTS_STREAK_PATCH_ID) 门内（AST 祖先链核实，自证钉在
    # test_t260917_09_tests_streak.py::test_j_exempt_cap_sites_inside_tests_streak_gate
    # ——分支挪出门外该钉先红）。旧 history（无 marker）重放整块缺席=分支不可达；
    # _blocked_over_limit 体内另有 KI-061 unique-per-entry 门自守（同上两款）。
    # 260926 锚点 re-point（KI-122②，宿主直修令）：**分支与门一字未动**——只是封面文案
    # 多了一个具名审计尾注实参（audit=tests_fault_cap_audit_text(...)），锚点文本随之
    # 升级；语义不变（同分支/同门/同 KI-061 自守），「外层门内」自证钉照旧有效。
    "dev_lane.py#run#await self._blocked_over_limit(tests_exempt_cap_blocked_text(tests_exempt_rounds, audit=tests_fault_cap_audit_text(tests_rounds, MAX_TESTS_FAULT_ROUNDS, tests_e#0":
        "t260917-09 + KI-122②：外层 workflow.patched(TESTS_STREAK_PATCH_ID) 门内（旧 "
        "history 重放走旧分支，分支不可达=重放安全）；体内 KI-061 unique-per-entry 自守。"
        "串行仲裁侧连续豁免超限封面（260926 加具名审计尾注实参，语义不变）。",
    "dev_lane.py#run#await self._blocked_over_limit(tests_exempt_cap_blocked_text(tests_exempt_rounds, audit=tests_fault_cap_audit_text(tests_rounds, MAX_TESTS_FAULT_ROUNDS, tests_e#1":
        "同上（并行汇合侧 arb_acc_parallel 同形分支，t260917-09 连续豁免超限封面；"
        "260926 同款具名审计尾注实参）。",
}


def test_c9_real_workflow_files_clean_or_registered():
    files = {}
    for name in SCOPE_FILES:
        text, err = load_source_text(POC / name)
        assert text is not None, err
        files[name] = text
    out = scan_unpatched_branches(files)
    assert out["ok"], out.get("error")
    detected = {b["anchor"]: b for b in out["branches"]}
    unknown = sorted(set(detected) - set(BRANCH_REGISTRY))
    stale = sorted(set(BRANCH_REGISTRY) - set(detected))
    assert not unknown, (
        "发现未过 workflow.patched 门且未登记的命令面分支（下一个 t260917-01 形态）：\n%s\n"
        "处理：给分支补门（family: Same-shaped boolean gate），或在本文件 BRANCH_REGISTRY "
        "登记并写一行回放兼容说明" % "\n".join(
            "%s (line %s, face=%s)" % (detected[a]["anchor"], detected[a]["line"],
                                       ",".join(detected[a]["face"]))
            for a in unknown))
    assert not stale, "登记表陈旧条目（分支已补门/已删除），请清理：%s" % stale
    # 推导集活性自证：闭包必须推出已知命令面方法（防推导静默退化成空集=锁失效）
    for must in ("_run_agent_step", "_blocked", "_blocked_over_limit",
                 "_block_agent_failed", "_arbitrate_refusal_blocked"):
        assert must in out["command_face"], "命令面闭包未推出 %s（推导器退化？）" % must
    # 混合方法不得当纯门包装（洗白面）；本树 KI-061 包装含命令面 await，必不入集
    assert "_blocked_over_limit" not in out["gate_wrappers"], (
        "含命令面 await 的混合方法不得当纯门包装（洗白面）")


# ---------- C 组合成 fixture（红/绿自证 + 畸形输入，验收①） ----------

FIX_COMMON = """
import workflow

class W:
    async def _blocked(self):
        await workflow.wait_condition(lambda: self._done)

    async def _guard(self, res):
        await self._blocked()

    async def run(self, res):
        if await self._guard(res):
            return 1
        return 0
"""
FIX_GOOD = FIX_COMMON.replace(
    "if await self._guard(res):",
    'if workflow.patched("t26091704-fixture-v1") and await self._guard(res):')
FIX_PUREWRAPPER = """
import workflow

class W4:
    def __init__(self):
        self._seq = 0

    async def _blocked(self):
        await workflow.wait_condition(lambda: False)

    def _gate(self):
        self._seq += 1
        return workflow.patched("t26091704-fixture-gate")

    async def run(self, res):
        if self._gate() and await self._blocked():
            return 1
        return 0
"""
FIX_IMPUREWRAPPER = """
import workflow

class W5:
    async def _blocked(self):
        await workflow.wait_condition(lambda: False)

    async def _gate(self, res):
        await self._blocked()
        return workflow.patched("t26091704-fixture-gate")

    async def run(self, res):
        if self._gate(res) and await self._blocked():
            return 1
        return 0
"""
FIX_IFEXP = """
import workflow

class W2:
    async def _blocked(self):
        await workflow.wait_condition(lambda: False)

    async def run(self):
        return 1 if await self._blocked() else 0
"""
FIX_WHILE = """
import workflow

class W3:
    async def _blocked(self):
        await workflow.wait_condition(lambda: False)

    async def run(self):
        while await self._blocked():
            break
        return 0
"""
FIX_SYNTAX = "def broken(:\n    pass\n"
FIX_EMPTY = ""
FIX_NOCLASS = "x = 1\nif x:\n    pass\n"


def test_c5_synthetic_red_green():
    bad = scan_unpatched_branches({"fixture_bad.py": FIX_COMMON})
    assert bad["ok"] and [b["face"] for b in bad["branches"]] == [["_guard"]], bad
    good = scan_unpatched_branches({"fixture_good.py": FIX_GOOD})
    assert good["ok"] and good["branches"] == [], good
    ifx = scan_unpatched_branches({"fixture_ifexp.py": FIX_IFEXP})
    assert [b["face"] for b in ifx["branches"]] == [["_blocked"]], "IfExp 测试位同规则覆盖"
    whl = scan_unpatched_branches({"fixture_while.py": FIX_WHILE})
    assert [b["face"] for b in whl["branches"]] == [["_blocked"]], "While 测试位同规则覆盖"


def test_c5b_pure_wrapper_guards_impure_wrapper_does_not():
    pure = scan_unpatched_branches({"fixture_pw.py": FIX_PUREWRAPPER})
    assert pure["ok"] and pure["branches"] == [], pure
    assert "_gate" in pure["gate_wrappers"]
    impure = scan_unpatched_branches({"fixture_iw.py": FIX_IMPUREWRAPPER})
    assert "_gate" not in impure["gate_wrappers"], "混合方法（含命令面 await）不得入纯门包装集"
    assert [b["face"] for b in impure["branches"]] == [["_blocked"]], (
        "混合方法守着的分支照红（未过门）：防整方法豁免洗白")


def test_c6_derived_closure_on_fixture():
    out = scan_unpatched_branches({"fixture_bad.py": FIX_COMMON})
    assert out["command_face"] == ["_blocked", "_guard", "run"], (
        "闭包：_blocked=种子（wait_condition），_guard 经 await 边传导入集，"
        "run 再从 _guard 传导（传导语义正确，run 亦命令面）")


def test_c8_malformed_inputs_structured():
    bad_syntax = scan_unpatched_branches({"x.py": FIX_SYNTAX})
    assert bad_syntax["ok"] is False and "语法不可解析" in bad_syntax["error"]
    empty = scan_unpatched_branches({"x.py": FIX_EMPTY})
    assert empty["ok"] is True and empty["branches"] == []
    nocls = scan_unpatched_branches({"x.py": FIX_NOCLASS})
    assert nocls["ok"] is True and nocls["branches"] == []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bin_source.py"
        p.write_bytes(b"\xff\xfe\x00<script>")
        text, err = load_source_text(p)
        assert text is None and "非 UTF-8" in (err or "")

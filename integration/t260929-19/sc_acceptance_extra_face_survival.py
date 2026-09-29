#!/usr/bin/env python3
"""sc_acceptance_extra_face_survival.py — create-time acceptance extras 活过段进入的
台面回归棒（t260929-19，灰盒 L3，离线秒级零 docker）。

背景（工单正文实报）：建票入口承诺 acceptance_extra「appended to the first
stage's checklist」（shared.py TicketInput 注释），但 dev_lane._enter 在每次段
进入无条件 `meta["acceptance"] = list(st.acceptance)`——extras 第一次进段即被
模板列表覆盖，台面与任何段 checklist 都看不到（t260929-18 实票动态复现）。
修复方案（review_plan 定稿）：镜像同仓 sibling 先例 base.py:1045-1049 的写侧
闸——首段首次进入保留实例 extras；后续段/首段重入（gen>1，返工形态）用当段
模板列表。本场景把**用户可感知台面契约**钉死：

  A 主棒（工单验收口径原话）：非空 acceptance_extra 建票 → _init 后台面含
    模板首段项＋全部 extras；首段 _enter 后台面**仍然**含全部 extras，且首段
    checklist 同样可见（schema 承诺的第二落点）；
  B 反向锁（不许冻结）：推进到第 2 段后台面恰为第 2 段模板列表——stage-1
    视图不许前携；第 2 段 checklist 亦模板原样；
  C 重入锁（sibling 语义）：首段第二次进入（gen>1，返工形态）后台面=首段
    模板列表（extras 退场是**声明的规则**，非静默截断）；
  D 畸形输入用例（外部输入三态纪律）：模板项重复/空串/纯空白/非字符串条目
    （int/None）——逐条显式降级不炸：台面无重复无空白项，数字/None 不原样
    上脸，且被丢弃条目在台账（timeline 文本）中具名留痕——「explicit 而非
    silent」；
  E 接线锁：_enter 的覆盖必须带守卫（裸 `meta["acceptance"] = list(st.acceptance)`
    出现在 _enter 函数体内=红，防「测试在场但闸被拆」回潮；样式同
    test_t260915_01 §E 源码锁）。

被测面=票面（meta["acceptance"] 经 snapshot 原样可见的那个值）与段 checklist，
不锚内部私有结构（gen 计数实现、sanitizer 函数名）；断言落在 schema 承诺的
语义上。构建方式用既有 UT 壳模式（object.__new__ + workflow 命名空间桩，同
server/engine/tests/test_t260915_01_detail_face.py）——灰盒「理解深、绑定浅」：
驱动是深理解选的攻击面，断言只在台面契约。

intent 分工（防重复）：developer L1（test_t260929_19_acceptance_extra.py）守
sanitizer 真值表与 gen 分支细节；本条守用户台面旅程（建票→首段→推进→重入）
与畸形输入不炸＋显式留痕。全局清单核对：t260915-01 detail-face 场景族 extras
恒空列表（工单证据 6），无同 intent 在册条目。

实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。
temporalio（引擎 venv）缺席=ENV_FAIL exit 2。
"""
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260907-04"))  # 共享 helper：lib_naming.Rec
import lib_naming  # noqa: E402

ENGINE = os.path.join(REPO, "server", "engine")

r = lib_naming.Rec()

# 引擎 venv 优先（temporalio 在场面）；缺场=ENV_FAIL exit 2，不假绿不静默跳过。
VENVPY = os.path.join(ENGINE, ".venv", "bin", "python")
sys.path.insert(0, ENGINE)
try:
    import dev_lane  # noqa: E402
except ImportError as e:  # noqa: F821
    # venv 解释器 realpath 解到框架 python3.9，executable 比对不可靠——按缺依赖
    # 重入一次（守卫位防环：venv 本身缺 temporalio 才判 ENV_FAIL）。
    # 重入一次（守卫位防环：venv 本身缺 temporalio 才判 ENV_FAIL）。
    if os.path.isfile(VENVPY) and not os.environ.get("SC_T260929_19_REEXECD"):
        env = dict(os.environ, SC_T260929_19_REEXECD="1")
        os.execve(VENVPY, [VENVPY, os.path.abspath(__file__)], env)
    print("ENV_FAIL: 引擎依赖缺席（temporalio 家族）：%s" % e)
    print("SUMMARY t260929-19-acceptance-extra-face-survival status=env_fail "
          "cause=external reason=engine-venv-missing")
    sys.exit(2)
from types import SimpleNamespace  # noqa: E402

STAGES = dev_lane.DevLaneWorkflow.STAGES
NOW_DT = datetime.datetime(2026, 9, 29, 12, 0, 0)
FIRST, SECOND = STAGES[0], STAGES[1]


def build_wf(extras):
    """既有 UT 壳模式（test_t260915_01_detail_face.py:415-436）：workflow 命名
    空间桩 + object.__new__，驱动 _init。断言面只用 meta 台面键。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.timeline = []
    wf._gens = {}
    wf.engine_version = 2
    inp = SimpleNamespace(
        ticket_id="t-19", template_id="tpl", project="p", title="t", lane="",
        workspace="", worktree="", branch="", base_ref="", proposal_id="",
        book_path="", epic="", write_set=[], deliverables=[],
        spec="spec", user_request="u", body="u", created=0,
        acceptance_extra=extras, no_file_changes=False, path_gate=False,
        repo_worktrees=[])
    dev_lane.DevLaneWorkflow._init(wf, inp)
    return wf


def face_items(wf):
    return [str(x) for x in wf.meta["acceptance"]]


def check_items(wf, sid):
    return [c["item"] for c in wf.meta["checks"][sid]]


print("== A 主棒：建票→首段进入，extras 全程可见（工单验收口径）")
EXTRAS = ["extra-alpha", "extra-beta"]
wf = build_wf(EXTRAS)
r.check(FIRST.acceptance[0] in face_items(wf),
        "A1 _init 后台面含模板首段项")
r.check(all(x in face_items(wf) for x in EXTRAS),
        "A2 _init 后台面含全部 extras")
dev_lane.DevLaneWorkflow._enter(wf, FIRST.id)
r.check(all(x in face_items(wf) for x in EXTRAS),
        "A3 首段 _enter 后台面仍含全部 extras（缺陷点：无条件覆盖即在此丢）")
r.check(FIRST.acceptance[0] in face_items(wf),
        "A4 首段 _enter 后台面模板项仍在（不丢模板侧）")
r.check(all(x in check_items(wf, FIRST.id) for x in EXTRAS),
        "A5 首段 checklist 含 extras（schema 承诺第二落点）")

print("== B 反向锁：推进第 2 段=当段模板列表，stage-1 视图不冻结前携")
dev_lane.DevLaneWorkflow._enter(wf, SECOND.id)
r.check(face_items(wf) == list(SECOND.acceptance),
        "B1 第 2 段后台面恰为第 2 段模板列表（extras 不冻结前携）")
r.check(check_items(wf, SECOND.id) == list(SECOND.acceptance),
        "B2 第 2 段 checklist 模板原样")

print("== C 重入锁：首段第二次进入（gen>1，返工形态）=模板列表")
wf2 = build_wf(EXTRAS)
dev_lane.DevLaneWorkflow._enter(wf2, FIRST.id)
dev_lane.DevLaneWorkflow._enter(wf2, FIRST.id)
r.check(face_items(wf2) == list(FIRST.acceptance),
        "C1 首段重入后台面=首段模板列表（sibling base.py:1046-1049 语义）")

print("== D 畸形输入用例：显式降级不炸（重复/空/空白/非字符串）")
tmplt_item = FIRST.acceptance[0]
wf3 = build_wf([tmplt_item, "", "   ", 42, None, "extra-gamma"])
items = face_items(wf3)
try:
    r.check(items.count(tmplt_item) == 1, "D1 模板项重复条目不产生重复行")
    r.check(not any(not str(x).strip() for x in items), "D2 空串/纯空白不上脸")
    r.check("42" in items and "None" in items,
            "D3 非字符串条目按声明语义 str() 收敛上脸（不炸不丢）")
    r.check("extra-gamma" in items, "D4 同批合法条目不受畸形邻座牵连")
    ledger = " | ".join(str(e.get("note", "")) for e in wf3.meta.get("log", []))
    r.check(repr(tmplt_item) in ledger and "''" in ledger and "'   '" in ledger,
            "D5 丢弃条目台账具名留痕（explicit 而非 silent）")
except Exception as e:  # noqa: BLE001 —— 畸形输入炸=产品红
    r.check(False, "D 畸形 extras 抛异常 %s: %s" % (type(e).__name__, e))

print("== E 接线锁：_enter 的覆盖必须带守卫（防测试在场闸被拆）")
src = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
body = src.split("def _enter(self, step_id", 1)[1].split("\n    def ", 1)[0]
lines = body.splitlines()
hits = [ln for ln in lines if 'self.meta["acceptance"] = list(st.acceptance)' in ln]
r.check(bool(hits) and all(len(ln) - len(ln.lstrip()) >= 12 for ln in hits),
        "E1 _enter 的 acceptance 覆盖在条件分支内（缩进≥12，非裸覆盖）")

r.finish()

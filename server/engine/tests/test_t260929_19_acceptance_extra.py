"""t260929-19 单测：实例验收增项（acceptance_extra）在 dev-lane 全程不丢。

根因（=票面证据②④）：dev_lane._enter 曾无条件 meta["acceptance"]=list(st.acceptance)，
create 时的实例增项在首段进入即被模板清单覆盖；且 _init 的段清单全从模板构建，
增项也进不了第一段 checklist。修复（同族先例 base.py:1046-1049 / 960 守卫语义）：
  1) _enter：仅首段首次进入（写点 _gen==1，gen 在 908 行先自增）保留增项；
     其余段、首段重入（rework 回打，_gen>1）换成本段模板清单。
  2) _init：增项净化（str 收敛→strip→空白/模板重复/内部重复丢弃，逐项台账
     log 点名）；第一段 checklist = 模板 + 净化后增项。

覆盖口径（=票面 scope 4）：
  A. L1 主杆：init + 首段进入（非空增项）→ 台面 acceptance 与第一段 checklist 均含增项。
  B. 反向锁：推进到 review_plan → 台面=该段模板清单（不把第一段视图冻结前带）。
  C. 重入锁：首段第二次 _enter（_gen==2，精确断言模板清单逐字）→ 守卫依赖
     「先自增 gen 再判守卫」的顺序，顺序被打乱此杆变红。
  D. 畸形输入用例（固定桩，不依赖外部源）：模板重复项、空串/纯空白、非字符串项、
     None/非列表形态——全部显式降级（丢弃且台账 log 点名），绝不崩溃。

运行：主树 venv `.../engine/.venv/bin/python -m pytest server/engine/tests/test_t260929_19_acceptance_extra.py -q`
（UT 全程禁网络/真 Temporal/真 git，conftest 只加 sys.path）。
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402

NOW_DT = datetime.datetime(2026, 9, 29, 12, 0, 0, tzinfo=datetime.timezone.utc)

FIRST_ID = dev_lane.DevLaneWorkflow.STAGES[0].id          # create_plan
SECOND_ID = dev_lane.DevLaneWorkflow.STAGES[1].id         # review_plan
FIRST_ACC = list(dev_lane.DevLaneWorkflow.STAGES[0].acceptance)
SECOND_ACC = list(dev_lane.DevLaneWorkflow.STAGES[1].acceptance)


def _mk_wf():
    """免 Temporal 运行时的 DevLaneWorkflow 壳（_mk_wf 族同款，test_t260915-01 先例）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.timeline = []
    wf._gens = {}
    wf.engine_version = 2
    wf._detail_face_on = False
    return wf


def _inp(extra) -> SimpleNamespace:
    return SimpleNamespace(
        ticket_id="t-ut", template_id="tpl", project="p", title="t", lane="",
        workspace="", worktree="", branch="", base_ref="", proposal_id="",
        book_path="", epic="", write_set=[], deliverables=[], spec="",
        user_request="u", body="u", created=0, acceptance_extra=extra,
        no_file_changes=False, path_gate=False, repo_worktrees=[])


def _init_wf(extra):
    wf = _mk_wf()
    dev_lane.DevLaneWorkflow._init(wf, _inp(extra))
    return wf


def _items(check_list) -> list:
    return [c["item"] for c in check_list]


# ---------- A. L1 主杆：init + 首段进入，增项在台面 ----------

def test_rod_extras_survive_init_and_first_stage_entry():
    wf = _init_wf(["extra-a", "extra-b"])
    assert wf.meta["acceptance"] == FIRST_ACC + ["extra-a", "extra-b"]
    # 首段 checklist 含增项（第二损失路径闭合）
    assert _items(wf.meta["checks"][FIRST_ID]) == FIRST_ACC + ["extra-a", "extra-b"]
    # 首段首次进入（写点 _gen==1）不覆盖
    dev_lane.DevLaneWorkflow._enter(wf, FIRST_ID)
    assert wf.meta["acceptance"] == FIRST_ACC + ["extra-a", "extra-b"]
    assert _items(wf.meta["checks"][FIRST_ID]) == FIRST_ACC + ["extra-a", "extra-b"]


# ---------- B. 反向锁：后段=本段模板清单（不冻结第一段视图） ----------

def test_reverse_lock_second_stage_shows_its_own_template():
    wf = _init_wf(["extra-a"])
    dev_lane.DevLaneWorkflow._enter(wf, SECOND_ID)
    assert wf.meta["acceptance"] == SECOND_ACC          # 逐段模板，非第一段清单
    assert _items(wf.meta["checks"][SECOND_ID]) == SECOND_ACC
    assert "extra-a" not in wf.meta["acceptance"]


# ---------- C. 重入锁：首段第二次进入=模板清单（守卫依赖 gen 先自增顺序） ----------

def test_reentry_lock_first_stage_gen2_is_exact_template_list():
    wf = _init_wf(["extra-a"])
    dev_lane.DevLaneWorkflow._enter(wf, FIRST_ID)
    dev_lane.DevLaneWorkflow._enter(wf, FIRST_ID)       # rework 回打形态，_gen==2
    assert wf.meta["acceptance"] == FIRST_ACC           # 精确逐字（顺序也锁）
    assert wf._gens[FIRST_ID] == 2


# ---------- D. 畸形输入用例：显式降级不崩溃 ----------

def test_malformed_duplicates_dropped_and_named_in_ledger():
    tpl_item = FIRST_ACC[0]
    wf = _init_wf([tpl_item, " " + tpl_item, "extra-a", "extra-a", " extra-a "])
    assert wf.meta["acceptance"] == FIRST_ACC + ["extra-a"]
    notes = [e["note"] for e in wf.meta["log"]]
    assert any("acceptance_extra" in n and "extra-a" in n for n in notes), notes


def test_malformed_blank_and_nonstring_coerced_or_dropped_no_crash():
    wf = _init_wf(["", "   ", 42, None, "extra-b"])
    assert wf.meta["acceptance"] == FIRST_ACC + ["42", "None", "extra-b"]
    notes = [e["note"] for e in wf.meta["log"]]
    assert any("acceptance_extra" in n for n in notes)


def test_malformed_nonlist_and_none_extra_defensive_no_crash():
    # None/缺省 = 老在途 payload 形态：无增项、零台账噪音
    for bad in (None,):
        wf = _init_wf(bad)
        assert wf.meta["acceptance"] == FIRST_ACC
    # 非列表形态（字符串/映射）：整体显式丢弃并台账点名，绝不崩溃、不逐字符迭代
    for bad in ("not-a-list", {"x": 1}):
        wf = _init_wf(bad)
        assert wf.meta["acceptance"] == FIRST_ACC
        assert any("acceptance_extra" in e["note"] for e in wf.meta["log"])


def test_clean_extras_no_ledger_noise():
    wf = _init_wf(["extra-a"])
    assert not any("acceptance_extra" in e["note"] for e in wf.meta["log"])


# ---------- E. 结构性源码锁：_enter 写点必须带守卫 ----------

def test_source_lock_enter_write_is_guarded():
    src = (POC / "dev_lane.py").read_text("utf-8")
    fn = src.split("def _enter(self", 1)[1].split("def _finish(self", 1)[0]
    assert 'self.meta["acceptance"]' in fn
    assert "self.STAGES[0].id" in fn and "self._gen(step_id) > 1" in fn

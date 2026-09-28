#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_wake_session_identity.py — executor 会话身份（t260929-04，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为=「身份永远来自声明，不猜不造；身份缺席=显式不可用，带名字」）：
- A executor_session 显式空串（未声明）→ 零投递尝试（桩零调用、零代建会话）、
  判活面显式 missing（「未声明」≠「正常」≠「读不到」，三态可分辨）——绝不发明
  临时会话 id（身份/档是后续票，显式不作为非静默）；
- B 声明的 id 被宿主拒（session not found 形状）→ wake_failed alert 点名宿主错误
  文本（wakes 契约行只记 accepted 的唤醒——两出口分工），恢复后只对声明 id 投递；
- C 身份溯源：config_provenance.keys.executor_session 能答「哪个文件#哪条键」
  （KI-148/149 教训——「谁声明的」必须可问）。

intent 分工：config 校验真值表归 developer L1（t260928-28 config.test 兜底）；
liveness.executor missing 态的判活面归 t260928-28（本条只消费它做身份终态锚）。
三态：node 缺席=ENV_FAIL exit 2；harness 新协议未落地=FAIL exit 1 点名（TDD 红
属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-04/sc_wake_session_identity.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_wake_harness import (  # noqa: E402
    WakeHarness, ok, ledger_row, summary_and_exit,
)


def main():
    h = WakeHarness()
    h.start()
    try:
        proj = "p1"
        sid = "executor-" + proj
        # A 未声明 executor_session（显式空串）→ 零投递尝试 + 显式 missing
        cfg = h.fixture_config(proj, overrides={"executor_session": ""})
        h.cmd("start", project=proj, config=cfg, now="2026-09-28T10:00:00+08:00")
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-1", 1, "done"))
        ok(h.drain(proj) == 0, "A 未声明身份=零投递尝试（不猜不造）", None)
        st = h.cmd("status", project=proj)["status"]
        ex = (st.get("liveness") or {}).get("executor") or {}
        ok(ex.get("state") == "missing", "A 判活面显式 missing（未声明≠正常≠读不到）", ex)
        h.cmd("restart", project=proj, config=h.fixture_config(proj), now="2026-09-28T10:05:00+08:00")

        # B 声明的 id 被宿主拒 → wake_failed alert 点名宿主错误文本（契约：wakes 行记
        # accepted 的唤醒；被拒投递走 alert 面点名），恢复后只对声明 id 投递
        h.cmd("session_stub_set", present=True,
              prompt_result={"accepted": False, "error": "session not found: " + sid})
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-2", 1, "done"))
        d = h.pump(proj)
        st = h.cmd("status", project=proj)["status"]
        wf = [a for a in (st.get("alerts") or []) if a.get("rule") == "wake_failed"]
        ok(wf and "session not found" in str(wf[-1].get("detail", "")),
           "B 被拒投递走 wake_failed alert 且点名宿主错误文本", wf[-1:] or st.get("alerts"))
        ok(len(d) == 0, "B 被拒=零成功投递", d)
        h.cmd("session_stub_set", present=True, prompt_result={"accepted": True})
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-3", 1, "done"))
        d = h.pump(proj)
        ok(len(d) == 1 and d[0].get("session") == sid, "B 恢复后只对声明 id 投递（无发明 id）", d)
        st = h.cmd("status", project=proj)["status"]

        # C 溯源：executor_session 来源可答
        cp = st.get("config_provenance") or {}
        keys = cp.get("keys") or {}
        ok(str(keys.get("executor_session", "")).startswith(cp.get("file") or "#"),
           "C executor_session 溯源=声明文件#键", keys)
    finally:
        h.finish()


if __name__ == "__main__":
    main()

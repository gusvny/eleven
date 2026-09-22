#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t260922_11_wedge_recovery_journey.py —— dsh 点名撕裂档自动隔离+重试恢复全旅程
（t260922-11 场景①，池=ro，灰盒 L3，进程内夹具+假 dsh 桩秒级零网络零 docker）。

intent（守护的用户可感知行为；KI-059 撕裂族收口——今日 4 起人工隔离的自动化面）：
用户场景=一段 agent 因会话档撕裂被 dsh 拒读而楔死（引擎探针判净→既有检疫不拦），
引擎必须在 spawn 失败且日志点名撕裂时**自动**按点名会话隔离坏档（挪不删留档）、
失败文案不谎报、下一轮 attempt 自动恢复并在回执留注记——今日的人工四步（停摆→
隔离→retry_qc→确认恢复）从此零人工。high-level steps：E 类撕裂档夹具（帧边界跨
记录：整流全合法、逐帧撕裂）+ 运行次序账本假 dsh 桩（首跑=现场实证撕裂文案 rc=1、
次跑=合法回执）→ 真实驱动通用 agent 段活动两次（等价 Temporal RETRY 的同活动重入）：

- T1 全旅程：首轮 raise（rc=1 形状）+文案追加自动隔离注记；坏档挪进隔离区字节级
  留档（挪不删可回溯）；事件记录恰一份（action=已隔离、dsh 原文判据、引擎探针
  两判据=「判净仍隔离」的实证面）；二轮幂等返回成功回执且注记可见；假 dsh 恰两次
  调用（隔离后下一轮干净 spawn）。
- T2 无撕裂文案的失败=零改动：不隔离、无事件、不谎报（现状语义逐字保留）。
- T3 隔离动作失败不谎报：隔离路径占位为文件 → 坏档留原位、绝不报「已隔离」
  （挪后存在性核验的记录真相面）。
- T4 盲区/旧扁平共存不动：同 id 目录旧扁平会话档与未知名文件原位保留——自动处置
  只动点名档，不越盲区纪律半步（误隔离=反向事故）。
- T5 会话身份双缺（无固定会话 id + 日志无点名行）→ 不隔离不误伤、失败照旧响亮。

三态：PASS exit 0 / FAIL exit 1 / 环境缺供（zstd CLI、引擎模块装载）ENV_FAIL exit 2
点名（闸内无跳过态）。实现未落地/行为退化=FAIL（TDD 信号），arbitrate/merge 期必须绿。
T2/T3/T5 无恢复面：二轮 attempt 的预期失败在夹具内吸收（expect_recovery=False），
不外溢进程——场景必须总能走到 SUMMARY 收尾行。

直跑：python3 integration/t260922-11/sc_t260922_11_wedge_recovery_journey.py（cwd=仓库根）。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_wedge import (EXIT_ENV, Fail, TEAR_LINE, drive, knob_guard,  # noqa: E402
                       load_activities, make_args, make_lane, make_stub,
                       tmp_dir, zstd_available)

TICKET, STAGE, ROLE = "t-it-wedge-journey", "implement", "developer"


def quarantine_dir(work: Path) -> Path:
    return work / ".sandbar" / "quarantine"


def run_case(f, aa, *, success_at, extra_line, resume_env=None,
             pre_mangle=None, expect_isolation, expect_recovery=True):
    """跑一轮两连驱动，返回 (raised, res2, state)。"""
    work, dsh, sdir, torn, sid = make_lane(
        "sc-t26092211-journey-", TICKET, STAGE, ROLE)
    original = torn.read_bytes()
    rfile = work / ".sandbar" / ("stage_%s_gen0.json" % STAGE)
    stub, state = make_stub(work, success_at=success_at)
    if pre_mangle:
        pre_mangle(work)
    knobs = {
        "SANDBAR_AGENT_CMD": str(stub),
        "WEDGE_STUB_RESULT_FILE": str(rfile),
        "WEDGE_STUB_EXTRA_LINE": extra_line,
        "WEDGE_STUB_SID": sid if resume_env is None else "",
        "WEDGE_STUB_STATE": str(state),
    }
    if resume_env:
        knobs.update(resume_env)
    raised = None
    res2 = None
    try:
        with knob_guard(**knobs):
            args = make_args(aa, work, TICKET, STAGE, ROLE)
            try:
                drive(aa, args)
            except RuntimeError as e:
                raised = e
            if not rfile.is_file():
                if expect_recovery:
                    res2 = drive(aa, args)  # 下一轮 attempt（同活动重入=RETRY 等价形态）
                else:
                    # 无恢复型子用例（T2/T3/T5）：二轮 attempt 预期照旧失败，异常就
                    # 地吸收——三态契约要求场景总能走到 SUMMARY 收尾行，未捕获异常
                    # 炸进程会冒充 FAIL（t260922-11 验收走查修正；断言零改动）。
                    try:
                        drive(aa, args)
                    except RuntimeError:
                        pass
        f.check(raised is not None, "首轮 attempt 以 infra 失败告终（rc=1 未写结果文件）")
        if expect_isolation:
            f.check(raised is not None and "已自动隔离" in str(raised),
                    "失败文案追加自动隔离注记（票面可见痕）")
            f.check(not torn.exists(), "点名撕裂档挪离原位")
            dsts = list(quarantine_dir(work).glob("torn-%s-*" % sid))
            f.check(len(dsts) == 1 and dsts[0].read_bytes() == original,
                    "隔离区恰一份留档且字节级=原档（挪不删可回溯）")
            evs = list(quarantine_dir(work).glob("session-wedge-%s-%s-*.json" % (TICKET, STAGE)))
            f.check(len(evs) == 1, "事件记录恰一份（与被隔离档同源目录）")
            if evs:
                ev = json.loads(evs[0].read_text(encoding="utf-8"))
                probe = ev.get("probe") or {}
                f.check(ev.get("action") == "quarantined",
                        "事件 action=已隔离（记录真相面）")
                f.check("torn JSONL record" in json.dumps(ev, ensure_ascii=False),
                        "事件含 dsh 原文判据行")
                f.check(probe.get("jsonl_torn") is False and probe.get("zstd_t_rc") == 0,
                        "事件含引擎探针两判据（判净仍隔离=本票立票实证）")
                f.check(sid in str(ev.get("session_id", "")), "事件点名会话身份")
        else:
            f.check(raised is not None and "已自动隔离" not in str(raised),
                    "失败文案不谎报隔离（报错精确）")
            f.check(torn.exists(), "坏档/点名档原位保留（零越界）")
            evs = (list(quarantine_dir(work).glob("session-wedge-*.json"))
                   if quarantine_dir(work).is_dir() else [])
            f.check(all(_action_of(p) != "quarantined" for p in evs),
                    "无「已隔离」事件记录（T3 容忍 move-failed 记录，不容忍假记录）")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return raised, res2, state


def _action_of(event_path: Path):
    try:
        return json.loads(event_path.read_text(encoding="utf-8")).get("action")
    except Exception:
        return "<unreadable>"


def main() -> int:
    if not zstd_available():
        print("ENV_FAIL: zstd CLI 缺席（夹具构造与引擎检疫面共同依赖，环境缺供）")
        return EXIT_ENV
    aa = load_activities()

    f = Fail("t260922-11 场景① dsh 点名撕裂档自动隔离+重试恢复全旅程")

    # ---- T1 全旅程（楔死→自动隔离→RETRY 恢复→三重留痕）----
    raised1, res2, state1 = run_case(
        f, aa, success_at=2, extra_line=TEAR_LINE, expect_isolation=True)
    f.check(res2 is not None and getattr(res2, "status", "") == "ok",
            "下一轮 attempt 幂等返回成功回执（重试恢复）")
    f.check(res2 is not None and "隔离" in ((res2.report or "") + (res2.evidence or "")),
            "成功回执带引擎注记（曾自动隔离…，要求④票面可见面）")
    if state1 is not None and (state1 / "count").is_file():
        f.check((state1 / "count").read_text().strip() == "2",
                "假 dsh 恰被调用两次（隔离后下一轮干净 spawn，不烧第三次）")

    # ---- T2 无撕裂文案的失败=零改动（现状语义）----
    run_case(f, aa, success_at=99, extra_line="some unrelated failure",
             expect_isolation=False, expect_recovery=False)

    # ---- T3 隔离动作失败不谎报（隔离路径占位为文件）----
    def mangle(work: Path):
        q = work / ".sandbar" / "quarantine"
        q.write_text("not a dir", encoding="utf-8")
    run_case(f, aa, success_at=99, extra_line=TEAR_LINE,
             pre_mangle=mangle, expect_isolation=False, expect_recovery=False)

    # ---- T4 盲区/旧扁平共存不动（自动处置不越盲区纪律）----
    work4, dsh4, sdir4, torn4, sid4 = make_lane(
        "sc-t26092211-journey-t4-", TICKET, STAGE, ROLE)
    try:
        legacy = sdir4 / "session-old.zstd"
        legacy.write_bytes(b"legacy torn garbage")
        stranger = dsh4 / "sessions" / "proj" / "probe.session.dat"
        stranger.write_bytes(b"unknown layout")
        rfile4 = work4 / ".sandbar" / ("stage_%s_gen0.json" % STAGE)
        stub4, state4 = make_stub(work4, success_at=99)
        raised4 = None
        with knob_guard(SANDBAR_AGENT_CMD=str(stub4),
                        WEDGE_STUB_RESULT_FILE=str(rfile4),
                        WEDGE_STUB_EXTRA_LINE=TEAR_LINE,
                        WEDGE_STUB_SID=sid4,
                        WEDGE_STUB_STATE=str(state4)):
            args4 = make_args(aa, work4, TICKET, STAGE, ROLE)
            try:
                drive(aa, args4)
                raised4 = None
            except RuntimeError as e:
                raised4 = e
        f.check(raised4 is not None and "已自动隔离" in str(raised4),
                "T4 点名档照常自动隔离")
        f.check(not torn4.exists(), "T4 点名撕裂档挪离原位")
        f.check(legacy.exists() and stranger.exists(),
                "T4 旧扁平会话档与未知名文件原位保留（盲区/豁免纪律不越界）")
    finally:
        shutil.rmtree(work4, ignore_errors=True)

    # ---- T5 会话身份双缺 → 不隔离不误伤 ----
    run_case(f, aa, success_at=99, extra_line=TEAR_LINE,
             resume_env={"SANDBAR_AGENT_RESUME": "0"}, expect_isolation=False,
             expect_recovery=False)

    return f.exit_code()


if __name__ == "__main__":
    sys.exit(main())

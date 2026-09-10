"""失败分类协议 v1 —— pytest 原生钩子对接（t260910-13，零第三方零 junit）。

映射：ERROR（setup 失败/未跑到断言）→ not-checked；FAILED → fail（reason=
assert_mismatch）；PASSED → pass。teardown ERROR 不翻转已判 case（只附记
evidence——C7② 相位合并策略）；同名（nodeid）去重，一行=一个用例由本钩子
的聚合保证。evidence 一行化交给 integration/lib_result.specCase（机械压平）。

装配（K5：pytest_plugins 声明在非根 conftest 是新版 pytest 移除项）：经
integration/conftest.py（rootdir=integration/ 时即为根 conftest）声明
pytest_plugins 引入；或显式 `-p conftest_result_protocol`。
"""
import sys

from lib_result import spec_line

_records = {}   # nodeid -> dict(status=..., evidence=..., dur=..., reason=...)


def _record(nodeid, status, evidence, dur, reason):
    r = _records.setdefault(nodeid, {"status": None, "evidence": "",
                                     "dur": 0.0, "reason": ""})
    r["dur"] += dur or 0.0
    if status is not None:
        r["status"] = status
        r["evidence"] = evidence
        r["reason"] = reason
    elif r["status"] in ("pass", "fail") and evidence:
        # teardown ERROR 不翻转已判 case：只附记证据（C7②）
        r["evidence"] = (r["evidence"] + " | teardown: " + evidence)[-2000:]


def pytest_runtest_logreport(report):
    outcome = report.outcome
    if report.when == "setup":
        if outcome == "failed":
            _record(report.nodeid, "not-checked",
                    str(report.longrepr)[:2000], report.duration, "self_precheck")
        else:
            _record(report.nodeid, None, "", report.duration, "")
    elif report.when == "call":
        if outcome == "failed":
            _record(report.nodeid, "fail",
                    str(report.longrepr)[:2000], report.duration, "assert_mismatch")
        else:
            _record(report.nodeid, "pass", "", report.duration, "")
    else:  # teardown
        if outcome == "failed":
            _record(report.nodeid, None,
                    str(report.longrepr)[:2000], report.duration, "")


def pytest_sessionfinish(session, exitstatus):
    suite = session.config.rootpath.name
    if _records:
        # 规范行必须行首起（闸按行分流）：pytest 进度行「.FE.E [100%]」不带
        # 换行尾，先补一个换行再产行，防首条规范行被拼在进度行后。
        sys.stdout.write("\n")
    for nodeid in sorted(_records):
        r = _records[nodeid]
        # status=None（中断面：零相位报告）→ not-checked 且证据点名「未产出任何
        # 相位报告」——evidence 恒在场，发射器写侧契约（无证据拒发）不被踩
        # （走查 gen1 问题⑥）。
        evidence = r["evidence"] or (
            "用例未产出任何相位报告（会话中断/收集面异常）" if r["status"] is None else "")
        sys.stdout.write(spec_line(
            name=nodeid, suite=suite, status=r["status"] or "not-checked",
            reason=r["reason"] or ("timeout" if r["status"] is None else ""),
            evidence=evidence,
            dur_s=round(r["dur"], 3)))
    sys.stdout.flush()
    _records.clear()

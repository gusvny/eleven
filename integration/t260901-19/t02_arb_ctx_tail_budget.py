#!/usr/bin/env python3
"""t260901-19 T2: arb_ctx assembly budget pin (dev_lane.py :1041 region).

Plan v3: the machine test-result payload injected into the arbitrate prompt is
assembled at dev_lane.py as  json.dumps({...}, ensure_ascii=False)[-4000:]  —
tail preservation, because the failure details sit at the END of the JSON and
must survive the budget cut. This is a static regression pin (same precedent as
verify-lane-config F2/F3): if someone reverts to head-truncation ([:6000]) or
drops the budget entirely, this test FAILs.

Runs on plain python3, zero deps. cwd = lane root.
"""
import pathlib
import sys

passed, failed = 0, 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL %s %s" % (name, detail))


def main():
    src = pathlib.Path("server/dsh/temporal-poc/dev_lane.py").read_text("utf-8")
    lines = src.splitlines()

    # 定位装配语句（t260903-02 分叉重锚：只认带【】的装配行——arbitrate/acceptance
    # 两处装配都要核；FLOW_BRIEF 散文里同词组无括号形，天然排除。锚点抢位事故=
    # 分叉给验收提示词引入词组，首匹配被散文抢走致假红（行为本身尾保完好）。
    idx = [i for i, ln in enumerate(lines) if "【机械集成测试结果】" in ln]
    check("arb-ctx-located", len(idx) >= 1, "assembly marker not found")
    if not idx:
        print("SUMMARY pass=%d skip=0 fail=%d" % (passed, failed))
        sys.exit(1)

    blocks = ["\n".join(lines[max(0, i - 8):i + 8]) for i in idx]  # 每个装配块
    # 断言集不变（原三查保留），仅从单块改每块全查：分叉后 arb_ctx 与 acc_ctx 两处装配
    # 都必须尾保——少一处即红（比原单块版更严，非弱化）。
    check("tail-budget-present", all("[-4000:]" in b for b in blocks),
          "every arb_ctx-style assembly must keep the LAST 4000 chars ([-4000:])")
    check("head-cut-gone", all("[:6000]" not in b for b in blocks),
          "old head-truncation [:6000] must be replaced by tail preservation")
    check("json-payload-intact",
          all(("json.dumps" in b or "_arb_json" in b) and "details" in b for b in blocks))

    print("SUMMARY pass=%d skip=0 fail=%d" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

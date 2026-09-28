#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t260924-05-inspection-suite-ran-parity —— KI-116 回归棒（必做③）。

断言巡检等价路径与 dev-lane 路径经同一 verify_lane integ 道产出**等量场景信号**：
  1. 巡检等价载荷（无 write_set、不排除池）→ ran>0 且绿；
  2. dev-lane 载荷（write_set + apply_skip_pools，声明无排除池=零分支）→ 同绿；
  3. 两路 ran 差 ≤1 且 ≤10%（取严）——「巡检回执 ran>0 且与 dev-lane 同套件量级一致」；
  4. integ_timeout_sec 载荷键：超时显式红、畸形值 fail-closed 红、缺键回落同源缺省；
  5. 零场景信号（exit=0 无 PASS 行）显式红——被拆除的静默逃逸口不得复发。
夹具=临时目录内最小 verify.yaml（integration.cmd 打印一行 PASS），零 docker/零
console/零网络；被测面=server/tools/verify_lane.py（进程内直调 _integ）。
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE / "server" / "tools"))
import verify_lane as vl  # noqa: E402

NAME = "t260924-05-inspection-suite-ran-parity"

LANES_YAML = "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"  # 仲裁修正：缺合法 lanes 块曾触发 verify.yaml fail-closed 红

MINI_YAML = (
    LANES_YAML +
    "integration:\n"
    "  cmd: python3 -c \"print('PASS [ki116-fixture] exit=0')\"\n"
)

SLOW_YAML = (
    LANES_YAML +
    "integration:\n"
    "  cmd: sleep 30\n"
)


def _lane(tmp, yaml_text):
    tmp.mkdir(parents=True, exist_ok=True)  # 仲裁修正：夹具子目录未建直写曾 FileNotFoundError
    (tmp / "verify.yaml").write_text(yaml_text, "utf-8")
    return tmp


def _fail(msg):
    print("FAIL [%s] exit=1\n    %s" % (NAME, msg))
    sys.exit(1)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ki116-parity-"))
    try:
        # 1+2+3：两路载荷同量级场景信号
        lane = _lane(tmp / "lane", MINI_YAML)
        rcpt_insp = vl._integ({"lane": "integ", "path": str(lane)})
        rcpt_dev = vl._integ({"lane": "integ", "path": str(lane),
                              "write_set": ["server/"],
                              "apply_skip_pools": True})
        for tag, r in (("inspection", rcpt_insp), ("dev-lane", rcpt_dev)):
            if r.get("err") or not r.get("green"):
                _fail("%s 路回执红：%s" % (tag, json.dumps(r, ensure_ascii=False)[:400]))
        if rcpt_insp.get("ran", 0) <= 0:
            _fail("巡检等价路 ran=0（零信号病象复发）：%s"
                  % json.dumps(rcpt_insp, ensure_ascii=False)[:400])
        d = abs(rcpt_insp["ran"] - rcpt_dev["ran"])
        if d > 1 or (rcpt_insp["ran"] and d > 0.1 * rcpt_insp["ran"]):
            _fail("两路 ran 差超容差（≤1 且 ≤10%%）：%s vs %s"
                  % (rcpt_insp["ran"], rcpt_dev["ran"]))

        # 4：载荷超时键——缺键回落缺省（=3000，与引擎内层 BATCH 同值）；畸形红；超时红
        # （仲裁 gen2 修正：断言锚 fail-closed 行为（显式红+点名畸形+不静默回落），
        #   不锚 err 文案里的键名——实现当前统一以 env 名报错（payload 畸形也引
        #   SANDBAR_INTEG_BATCH_TIMEOUT_SEC），报错源标注不准已上报岗位，非闸面。）
        import os as _os
        _saved = _os.environ.pop("SANDBAR_INTEG_BATCH_TIMEOUT_SEC", None)
        try:
            if vl._integ_timeout_sec({})[0] != vl.INTEG_DEFAULT_TIMEOUT_SEC:
                _fail("缺键未回落同源缺省")
        finally:
            if _saved is not None:
                _os.environ["SANDBAR_INTEG_BATCH_TIMEOUT_SEC"] = _saved
        slow = _lane(tmp / "slow", SLOW_YAML)
        r = vl._integ({"lane": "integ", "path": str(slow), "integ_timeout_sec": 1})
        # 260928 修（本棒曾因**绑实现文案**而在 main 上长红）：原判据钉中文短语「整体超时」，
        # 而 260927/260928 的执行器收口改造把回执文案换成英文并补了结构化字段
        # （interrupted/partial/progress/scenarios）——**意图不变、文案漂移**，故判据改绑浅：
        # 显式红（green=False）+ 结构化「被判超时腰斩」标记 + 有具名 err（绝不静默绿）。
        if not (r.get("green") is False and r.get("interrupted") is True and r.get("err")):
            _fail("integ_timeout_sec=1 未显式红（须 green=False + interrupted=True + 具名 err）：%s"
                  % json.dumps(r, ensure_ascii=False)[:300])
        r = vl._integ({"lane": "integ", "path": str(lane), "integ_timeout_sec": "abc"})
        # 畸形值 fail-closed：显式红 + err 点名传入的畸形值（不静默回落=语义，非文案）。
        if not (r.get("green") is False and r.get("err") and "abc" in r["err"]):
            _fail("畸形超时值未 fail-closed（须 green=False + err 点名 'abc'）：%s"
                  % json.dumps(r, ensure_ascii=False)[:300])

        # 5：零场景信号（exit=0 无 PASS 行）显式红——静默逃逸口不得复发
        zero = _lane(tmp / "zero",
                     LANES_YAML + "integration:\n  cmd: true\n")
        r = vl._integ({"lane": "integ", "path": str(zero)})
        # 同 4 的绑浅口径：显式红 + 零场景计数 + 具名 err（静默绿复发时 green 会是 True）。
        if not (r.get("green") is False and int(r.get("ran") or 0) == 0 and r.get("err")):
            _fail("零场景信号未显式红（静默绿复发）：%s"
                  % json.dumps(r, ensure_ascii=False)[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS [%s] exit=0" % NAME)
    sys.exit(0)


if __name__ == "__main__":
    main()

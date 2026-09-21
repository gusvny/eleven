#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""例外形探针（t260921-06 看守族的假表条目 cmd，私有台形态样本）。

 mimicking 例外清单条目的形态：被测对象需要私有台的场景——直调
 stage_docker.do_up_public 起独立 temporal 台、用毕 do_down（不经消费缝、
 不消费 SANDBAR_STAGE_BATCH）。看守用它的工程名前缀充当 miniature 窗口里
 「清单内例外」的机械样本（真全轮形态断言：窗口内其余工程名 ⊆ 清单模式）。
回执：ok / probe / project / namespace / port / down。退出码三态同批消费者探针。
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "integration"))
import stage_docker  # noqa: E402


def write_receipt(path, obj):
    try:
        Path(path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print("probe: 回执写不进（%s）：%s" % (path, e), file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("usage: probe_exception_stage.py <receipt_path>", file=sys.stderr)
        return 1
    out_path = sys.argv[1]
    sfx = "".join(ch for ch in os.environ.get("SANDBAR_UT_RUN_SUFFIX", "")
                  if ch.isalnum() or ch in "-_") or ("p%x" % os.getpid())
    project = "t26092106-exc-%s" % sfx
    try:
        state = stage_docker.do_up_public(project, ["temporal"],
                                          {"namespace": project},
                                          stage_docker.DEFAULT_TIMEOUT, keep=False)
    except stage_docker.StageError as e:
        write_receipt(out_path, {"ok": False, "probe": "exception", "error": "%s: %s" % (e.kind, e)})
        print("ENV_FAIL: 例外形探针起台失败（%s）：%s" % (e.kind, e), flush=True)
        return 2 if e.kind == "env" else 1
    down = stage_docker.do_down(project)
    write_receipt(out_path, {
        "ok": True,
        "probe": "exception",
        "project": project,
        "namespace": state.get("namespace"),
        "port": (state.get("ports") or {}).get("temporal"),
        "down": down,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())

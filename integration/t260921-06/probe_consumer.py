#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批消费者探针（t260921-06 看守族的假表条目 cmd，真消费缝面）。

经 lib_gate.require_stage（批消费者族唯一消费缝）申请台/批台命名空间，落回执 JSON：
- 批模式（env SANDBAR_STAGE_BATCH 在场，实现落地后）：缝内 ns-acquire，不新建任何台；
- 旧行为（env 缺席）：逐字现行——自起独立台、用毕 stage_down。
回执字段（供看守断言）：ok / probe / project / ns_arg / batch_env / mode / state / down。
退出码三态：0 全绿；2 缝内环境红（require_stage bail 透传）；1 其它失败。
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "integration" / "t260904-02"))  # lib_gate 所在（消费缝真源）
import lib_gate  # noqa: E402


def write_receipt(path, obj):
    try:
        Path(path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print("probe: 回执写不进（%s）：%s" % (path, e), file=sys.stderr)


class FailShim:
    """lib_gate.require_stage(fail, …) 的 fail 入参垫片：bail=环境红 exit 2。"""

    def __init__(self, out_path):
        self.out_path = out_path

    def bail(self, msg, code=2):
        write_receipt(self.out_path, {"ok": False, "probe": "consumer",
                                      "error": str(msg)[:500],
                                      "batch_env": os.environ.get("SANDBAR_STAGE_BATCH", "")})
        print("ENV_FAIL: %s" % msg, flush=True)
        try:
            sys.exit(int(code) if int(code) != 0 else 2)
        except ValueError:
            sys.exit(2)


def main():
    if len(sys.argv) < 3:
        print("usage: probe_consumer.py <namespace> <receipt_path>", file=sys.stderr)
        return 1
    ns, out_path = sys.argv[1], sys.argv[2]
    project = "t26092106-probe-%s" % lib_batch_suffix()
    stage_mod, state = lib_gate.require_stage(FailShim(out_path), project, ns)
    down = lib_gate.stage_down(stage_mod, project)
    write_receipt(out_path, {
        "ok": True,
        "probe": "consumer",
        "project": project,
        "ns_arg": ns,
        "batch_env": os.environ.get("SANDBAR_STAGE_BATCH", ""),
        "mode": "batch" if os.environ.get("SANDBAR_STAGE_BATCH") else "solo",
        "state": state,
        "down": down,
    })
    return 0


def lib_batch_suffix():
    sfx = "".join(ch for ch in os.environ.get("SANDBAR_UT_RUN_SUFFIX", "")
                  if ch.isalnum() or ch in "-_")
    return sfx or ("p%x" % os.getpid())


if __name__ == "__main__":
    sys.exit(main())

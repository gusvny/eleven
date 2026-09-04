#!/usr/bin/env python3
"""t11-arbitrate-log-faultsurface（KI-013 / t260902-11）

故障面渲染：arbiter 打点的三个实参各喂畸形/边界值，过真 logging：
  - ticket_id 含 %s、%%、全角字符（防实参值干扰格式化）；
  - cwd 为相对路径、含空格、unicode、超长路径；
  - gen=0 与超大 gen。
逐条断言：无 "--- Logging error ---"，且实参值如实出现在渲染结果里。
"""
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sc_t02_arbitrate_log_renders import find_arbitrate_call, render, TARGET  # noqa: E402

CASES = [
    ("ticket 含格式符", ("t%s100%%bad票", 0, str(Path("relative/泳道"))), ("t%s100%%bad票", "relative/泳道")),
    ("cwd 相对路径", ("t1", 0, "relative/泳道"), ("t1", "relative/泳道")),
    ("cwd 含空格与 unicode", ("t1", 3, str(Path("/tmp/has space/泳道 01"))), ("t1", "/tmp/has space/泳道 01")),
    ("gen=0 与超长 cwd", ("t1", 0, "/" + "a" * 300), ("t1", "/" + "a" * 300)),
]


def main() -> int:
    hits = find_arbitrate_call()
    if len(hits) != 1:
        print(f"FAIL arbitrate spawn 打点应恰好 1 处，实际 {len(hits)} 处")
        return 1
    fmt = hits[0].args[0].value
    bad = []
    for label, args, expect_subs in CASES:
        rendered, errout = render(fmt, args)
        if "Logging error" in errout:
            bad.append(f"{label}：stderr 出现 logging error")
        for sub in expect_subs:
            if sub and sub not in rendered:
                bad.append(f"{label}：渲染结果缺 {sub!r}（got {rendered.strip()!r}）")
    if bad:
        for b in bad:
            print(f"FAIL {b}")
        return 1
    print(f"OK {len(CASES)} 组畸形/边界实参全部正常渲染、无 logging error")
    print("SUMMARY cases=%d logging_error=no" % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())

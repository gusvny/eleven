#!/usr/bin/env python3
"""探针 live 档绿档对账 journey（t260922-03，registry: t260922-03-dsh-probe-live-green）。

意图（灰盒，全量判据见 registry intent；桩与驱动见 lib_t26092203.py）：
对 integration/t260916-24/probe_dsh_seam.py 以 PATH 缝注入 npm 桩+dsh 桩
跑 live 档（--reuse-install 现况结构性失灵已作缺陷上报，场景不锚它，见
lib_t26092203.py 头注）——探针必须①不再崩在会话 prompt 拼装（本票根因形状「not all arguments
converted」绝迹）；②五断言+沙箱行为+resume 全 PASS；③退出码 0 结论「全绿」、
秒级、零 traceback、退出后无桩孤儿（资源回收）。判据全落公开契约面（CLI 旗标/
退出码/台账行字面），探针内部实现重构不破。

修复已落本工单树，本场景=回归锁（非 TDD 红；根因形状见票面复现栈），arbitrate/merge
期必须保持绿。环境缺席（探针/zstd/~/.dsh 前置；npm 由 PATH 缝桩供给）=ENV_FAIL exit 2。
"""
import sys

import lib_t26092203 as fx
from lib_env import EXIT_FAIL, EXIT_PASS


def main():
    fx.require_probe_env()
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("：" + detail) if detail else ""))

    rc, out, err, wall, tmp = fx.run_probe("green")
    try:
        blob = out + err
        check("live 档不再崩在 prompt 拼装（本票根因形状绝迹）",
              "not all arguments converted" not in blob and "Traceback" not in blob,
              "rc=%r 墙钟=%.1fs" % (rc, wall))
        check("退出码 0（全绿）", rc == 0, "rc=%r" % rc)
        check("文件名口径断言 PASS（session.v3.jsonl → vN 代口径）",
              "[PASS] a 文件名口径" in out and "session.v3.jsonl" in out)
        check("钉模型断言 PASS（桩路由 %s/%s，SANDBAR_PROBE_EXPECTED_ROUTE 旋钮钉期望）"
              % (fx.STUB_PROVIDER, fx.STUB_MODEL),
              "[PASS] d 钉模型生效" in out and fx.STUB_PROVIDER in out and fx.STUB_MODEL in out)
        check("沙箱行为子用例 PASS（泳道内写成功 + 主库 .git 位越界拒写）",
              "[PASS] c 行为子用例 泳道内写" in out
              and "[PASS] c 行为子用例 主库 .git 越界写" in out)
        check("resume 子用例 PASS（同 DSH_HEADLESS_SESSION 续写，会话文件集不变）",
              "[PASS] e resume 插件" in out)
        check("探针结论行=全绿", "探针结论：全绿" in out)
        check("墙钟秒级（桩档 <60s）", wall < 60, "%.1fs" % wall)
        pids, note = fx.stub_orphans(out)
        check("探针退出后无桩孤儿（spawn 资源回收全终态）", not pids,
              note or ("残留 pid=%s（已代收割）" % pids[:3]))
        if pids:
            fx.reap_orphans(pids)
    finally:
        fx.cleanup(tmp)
    print("== SUMMARY：PASS=%d FAIL=%d ==" % (legs.count(True), legs.count(False)))
    sys.exit(EXIT_PASS if all(legs) else EXIT_FAIL)


if __name__ == "__main__":
    main()

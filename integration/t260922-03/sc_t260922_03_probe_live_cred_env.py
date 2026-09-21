#!/usr/bin/env python3
"""探针 live 档失败归因三态（t260922-03，registry: t260922-03-dsh-probe-live-cred-env）。

意图（灰盒，全量判据见 registry intent；桩与驱动见 lib_t26092203.py）：
①凭据缺失子用例：桩自报 MISSING_CREDENTIAL（路由 stub-route-alpha、补救变量
STUB_API_KEY，即 0.1.5 实测报错形状）后挂住 → 探针必须秒级早停收割（绝不空等到
会话超时的静默挂死形状）、ENV 红退出码 2、点名桩自报的路由与补救变量、零
traceback、收割后无孤儿（spawn 资源回收全终态）；
②产品红保全子用例：桩退出码 3 且日志无凭据字面 → 维持拦停级 FAIL（退出码 1、
FAIL 台账行在场）且零 ENV 行——「环境红不吞产品红、产品红不冒充环境红」双向锁
（lib_env 三态契约 + RUNBOOK_GATE「环境缺=exit 2 补环境重跑」承诺的探针侧兑现）。

判据不锚守望实现（轮询周期/字面量提取方式/文案措辞均可变），只锚用户可感知终态。
修复已落本工单树，本场景=回归锁（非 TDD 红），arbitrate/merge 期必须保持绿。
环境缺席（探针/zstd/npm/~/.dsh 前置）=ENV_FAIL exit 2。
"""
import sys

import lib_t26092203 as fx
from lib_env import EXIT_FAIL, EXIT_PASS


def leg_cred_missing_env():
    """①凭据缺失=环境红：秒级、exit 2、点名路由与补救变量、无崩栈、无孤儿。"""
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] ①凭据缺失 %s%s" % ("PASS" if ok else "FAIL", name,
                                        ("：" + detail) if detail else ""))

    rc, out, err, wall, tmp = fx.run_probe("hang")
    try:
        blob = out + err
        check("秒级早停返回（<30s；守望若退化到只靠 60s 会话超时兜底，此判据即红——"
              "绝不复现静默空等挂死形状）",
              rc is not None and wall < 30, "rc=%r 墙钟=%.1fs" % (rc, wall))
        check("ENV 红退出码 2", rc == 2, "rc=%r" % rc)
        check("点名桩自报路由（%s）" % fx.STUB_ROUTE, fx.STUB_ROUTE in out)
        check("点名补救路径变量（%s）" % fx.STUB_VAR, fx.STUB_VAR in out)
        check("ENV 台账行在场", "[ENV]" in out)
        check("零 traceback（不崩栈）", "Traceback" not in blob)
        pids, note = fx.stub_orphans(out)
        check("收割后无桩孤儿（spawn 资源回收全终态）", not pids,
              note or ("残留 pid=%s（已代收割）" % pids[:3]))
        if pids:
            fx.reap_orphans(pids)
    finally:
        fx.cleanup(tmp)
    return legs


def leg_fail_preserved():
    """②普通失败维持产品红：exit 1、FAIL 行在场、零 ENV 行、零 traceback。"""
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] ②产品红保全 %s%s" % ("PASS" if ok else "FAIL", name,
                                          ("：" + detail) if detail else ""))

    rc, out, err, wall, tmp = fx.run_probe("fail")
    try:
        blob = out + err
        check("拦停级 FAIL 退出码 1", rc == 1, "rc=%r" % rc)
        check("FAIL 台账行在场", "[FAIL]" in out)
        check("零 ENV 行（产品红不冒充环境红）", "[ENV]" not in out)
        check("零 traceback（不崩栈）", "Traceback" not in blob)
    finally:
        fx.cleanup(tmp)
    return legs


def main():
    fx.require_probe_env()
    legs = leg_cred_missing_env() + leg_fail_preserved()
    print("== SUMMARY：PASS=%d FAIL=%d ==" % (legs.count(True), legs.count(False)))
    sys.exit(EXIT_PASS if all(legs) else EXIT_FAIL)


if __name__ == "__main__":
    main()

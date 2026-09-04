#!/usr/bin/env python3
"""场景三态判定共享助手（t260904-12：集成闸无 SKIP 化，定稿 §7.3）。

场景级状态只有 PASS / FAIL / ENV_FAIL / N/A（腿级），退出码契约：
  0 = 全过；1 = 有 FAIL（产品红，含全腿 N/A——无可验对象=设计/覆盖问题，修场景不补环境）；
  2 = 有 ENV_FAIL（环境红：没验成，原因归环境，SUMMARY/输出点名缺什么）。

纪律（防 SKIP 洞复辟）：
- 环境缺失（依赖、测试台、凭据、playwright 等）一律 env_fail()，绝不 exit 0；
- na() 只给以**系统状态**为条件的腿（不以测试环境为条件，如「无该 feature flag 时该腿无对象」）；
  全腿 N/A 的场景按契约记产品红（exit 1）——本助手 fail_if_all_na() 收口该判定；
- 畸形/异常路径同样不许静默绿：宁可 FAIL 显式红。

mjs 侧等价助手 = integration/t260904-05/lib_browser.mjs makeResults()（状态词表
pass/fail/env_fail/na + summarize() 同款退出码优先级）。
"""
import sys

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ENV_FAIL = 2


def env_fail(reason):
    """环境缺失：打印点名缺什么，exit 2（ENV_FAIL 环境红）。绝不 exit 0。"""
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


def na(reason):
    """以系统状态为条件的腿无对象（非环境缺失）。仅返回标记，是否全 N/A 由
    fail_if_all_na() 按场景腿表统一判定。"""
    print("N/A: %s" % reason)


def fail_if_all_na(total_legs, na_legs, scenario=""):
    """全腿 N/A 的场景=红（产品红 exit 1）：没有可验对象是场景设计/覆盖问题。
    total_legs=本场景腿总数；na_legs=其中 N/A 腿数。"""
    if total_legs > 0 and na_legs >= total_legs:
        print("FAIL: 全腿 N/A——场景无可验对象（设计/覆盖问题，修场景而非补环境）%s" % scenario)
        sys.exit(1)

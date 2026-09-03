#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260903-10 场景③：upgrade 消费契约⑧的展示契约（副本在场/缺失两态各判）。

用户视角契约：`sandbar upgrade --dry-run` 读仓内契约⑧同源副本，展示 dsh 版本
区间与已验证点 + 升版必查项命中清单（⑧-2 四条）；副本缺失时 fail-closed 非零
报错点名契约文件——绝不展示假区间。

断言锚全部来自契约⑧承诺面（⑧-1 已验证点 0.1.1-rc.2、⑧-2 四条必查项的
touchpoints 编号 A3/A4/A5/B1/C1/C2/D1、当前版本 0.1.0），不锚文案格式。
纯读面（--dry-run），零端口、零状态写入，池=ro。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_installer import (REPO, Fail, cleanup, make_temp_home, run_cli,  # noqa: E402
                           require_installer_entry)

CONTRACT_REL = os.path.join("docs", "design", "sandbar项目接入契约v1.md")
# ⑧-2 四条必查项锚：touchpoints 编号 或 语义关键词（任一命中即可辨）
FOUR_CHECKS = [
    ("A3", ("settings", "resolve", "层叠")),
    ("A4", ("runner", "装配")),
    ("B1", ("home", "会话", "布局")),
    ("D1", ("SIGTERM", "终止")),
]


def main():
    fail = Fail("t260903-10 ③upgrade 消费契约⑧展示契约")
    entry = require_installer_entry(fail)
    tmp, env = make_temp_home()
    try:
        contract = os.path.join(REPO, CONTRACT_REL)
        rc, out = run_cli(entry, ["upgrade", "--dry-run"], env, timeout=60)
        if os.path.isfile(contract):
            fail.check(rc == 0, "副本在场：upgrade --dry-run 零退出")
            # 版本锚单源化（t260903-12）：断言「展示值=仓根 VERSION 单源值」而非历史字面量。
            sandbar_ver = open(os.path.join(REPO, "VERSION"), encoding="utf-8").read().strip()
            fail.check(sandbar_ver in out, "展示当前 sandbar 版本（单源仓根 VERSION=%s）" % sandbar_ver)
            fail.check("0.1.1-rc.2" in out, "展示 dsh 已验证点 0.1.1-rc.2（⑧-1，不展示假区间）")
            for i, (code, kws) in enumerate(FOUR_CHECKS, 1):
                hit = code in out or any(k in out for k in kws)
                fail.check(hit, "必查项 %d/4 可辨（%s 或 %s）" % (i, code, "/".join(kws)))
        else:
            fail.check(rc != 0, "副本缺失：upgrade 非零退出（fail-closed，不展示假区间）")
            fail.check("契约" in out or "contract" in out.lower(),
                       "报错点名契约文件缺失（out=%s）" % out.strip()[:120])
    finally:
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()

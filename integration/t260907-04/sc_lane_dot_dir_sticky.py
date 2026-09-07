#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_lane_dot_dir_sticky.py — 泳道协调目录 .suyou/→.sandbar/ 过渡契约（t260907-04 正文③）。

intent（用户可感知契约：既有在飞泳道不炸、新泳道落新名、交接零劈叉）：
  1. 纯 .suyou 泳道（在飞存量）：解析恒旧名——读侧回落，且引擎不在此 base 造新名
     目录（粘滞：整生命周期单一名）；
  2. 全新 base：落 .sandbar（创建侧换新名）；
  3. 两名并存的 base：解析恒新名——镜像目录（插件面只写副本）**不参与解析**
     （R-1 回归钉：粘滞判定的输入不得含自身机制可创建的对象，否则新泳道第二段
     进程权威目录中途翻转、非镜像产物静默缺损——t260907-04 review 实锤缺陷）；
  4. 解析重复调用稳定（同 base 十次同结果）。

灰盒：经方案 gen2 定稿的公开帮手 resolve_dot_dir(base) 断言（实现细节重构不得
改契约名；改名须连本场景与方案一起动）。腿 3 即 R-1 缺陷的回归钉。
Hermetic：temp 目录自建自拆，零网络零舞台。
**implement 落地前红属预期（TDD 信号），arbitrate/merge 期必须全绿。**
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

RESOLVE = """
import json, sys
import shared
base = sys.argv[1]
print(json.dumps({"resolved": str(shared.resolve_dot_dir(base))}))
"""


def resolve(base):
    obj, rc, out, err = lib_naming.tp_json(RESOLVE, args=[base])
    if obj is None:
        return None, err[-160:]
    return obj.get("resolved"), ""


def fresh_base(make_old=False, make_new=False):
    base = tempfile.mkdtemp(prefix="t26090704-lane-")
    if make_old:
        os.makedirs(os.path.join(base, ".suyou"))
    if make_new:
        os.makedirs(os.path.join(base, ".sandbar"))
    return base


def main():
    r = lib_naming.Rec()

    print("== 腿1 纯 .suyou 在飞泳道 → 恒旧名，且不造新名目录（粘滞+读侧回落）")
    base = fresh_base(make_old=True)
    v1, err = resolve(base)
    if v1 is None:
        r.env_fail("resolve 求值失败：%s" % err)
    else:
        ok = v1.endswith("/.suyou")
        v2, _ = resolve(base)
        no_new_dir = not os.path.exists(os.path.join(base, ".sandbar"))
        r.check(ok and v2 == v1 and no_new_dir,
                "两次解析均旧名且无新名目录产生（得 %s / %s）" % (v1, v2))

    print("== 腿2 全新 base → 落 .sandbar（创建侧换新名）")
    base = fresh_base()
    v1, err = resolve(base)
    if v1 is None:
        r.env_fail("resolve 求值失败：%s" % err)
    else:
        r.check(v1.endswith("/.sandbar"), "新 base 解析为新名（得 %s）" % v1)

    print("== 腿3 两名并存 → 恒新名（镜像目录不参与解析——R-1 回归钉）")
    base = fresh_base(make_old=True, make_new=True)
    v1, err = resolve(base)
    if v1 is None:
        r.env_fail("resolve 求值失败：%s" % err)
    else:
        v2, _ = resolve(base)
        r.check(v1.endswith("/.sandbar") and v2 == v1,
                "并存 base 恒新名不翻转（得 %s / %s）" % (v1, v2))

    print("== 腿4 R-1 全链：新 base 首写后（镜像造出 .suyou）解析仍新名")
    base = fresh_base()
    v1, err = resolve(base)
    if v1 is None:
        r.env_fail("resolve 求值失败：%s" % err)
    else:
        # 模拟镜像写副作用：首写建新名目录 + 镜像造旧名目录（引擎写侧行为）
        os.makedirs(v1, exist_ok=True)
        os.makedirs(os.path.join(base, ".suyou"), exist_ok=True)
        stable = all(resolve(base)[0].endswith("/.sandbar") for _ in range(3))
        r.check(stable, "镜像目录出现后三次解析恒新名")

    print("== 腿5 解析稳定性（同 base 十次同结果，无隐状态漂移）")
    base = fresh_base(make_old=True)
    vs = {resolve(base)[0] for _ in range(10)}
    r.check(len(vs) == 1 and (list(vs)[0].endswith("/.suyou")),
            "十次解析同结果且为旧名（得 %s）" % vs)

    r.finish()


if __name__ == "__main__":
    main()

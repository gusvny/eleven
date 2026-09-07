#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_dispatcher_lock_fallback.py — 总管单例锁改名过渡契约（t260907-04，server/tools 引用面）。

intent（用户可感知契约：单例防双派，改名不破防）：
  1. 无锁 → 接管，锁文件写入本会话；
  2. 他人持新锁未过期 → lock_held=false 只读不派，锁内容不被改写；
  3. 新锁过期 → 接管；
  4. 旧锁（/tmp/suyou-dispatcher.lock，改名前存量）在 TTL 内且无新锁 → 视为
     held——防旧版 dispatcher 实例与新实例并行双派（过渡回落半边）；
  5. 旧锁过期 → 接管并写**新**锁；旧锁文件只读不写不删（只回落不续命）。

灰盒：锁路径常量经模块内 Path 常量动态发现（名字含 dispatcher.lock）后替换为
temp 副本——不碰真 /tmp 锁（真 dispatcher 可能在跑，写它=干扰生产面）。
发现不了新/旧双常量即腿红（过渡回落未落地，TDD 信号）。
Hermetic：temp 目录；ticket registry 只读。
**implement 落地前腿 4/5 红属预期，arbitrate/merge 期必须全绿。**
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

SNIP = r"""
import json, os, sys, tempfile, time, pathlib
sys.path.insert(0, %r)
sys.path.insert(0, os.path.join(%r, "server", "tools"))  # dispatcher_loop 在 tools 面
import dispatcher_loop as dl
tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26090704-lock-"))
new = tmp / "sandbar-dispatcher.lock"
old = tmp / "suyou-dispatcher.lock"
# 动态发现锁路径常量（Path 且名含 dispatcher.lock），按名归类替换为 temp 副本
consts = {k: v for k, v in vars(dl).items()
          if isinstance(v, pathlib.Path) and "dispatcher.lock" in v.name}
for k, v in consts.items():
    setattr(dl, k, old if "suyou" in v.name else new)
has_new = any("suyou" not in v.name for v in consts.values())
has_old = any("suyou" in v.name for v in consts.values())
mode, sess = sys.argv[1], sys.argv[2]
now = int(time.time())
if mode == "new":
    new.write_text(json.dumps({"session": sess, "ts": now}), encoding="utf-8")
elif mode == "new-expired":
    new.write_text(json.dumps({"session": sess, "ts": now - 700}), encoding="utf-8")
elif mode == "old":
    old.write_text(json.dumps({"session": sess, "ts": now}), encoding="utf-8")
elif mode == "old-expired":
    old.write_text(json.dumps({"session": sess, "ts": now - 700}), encoding="utf-8")
res = dl.run({"session": "probe"})
print(json.dumps({
    "has_new": has_new, "has_old": has_old,
    "lock_held": bool(res.get("lock_held")),
    "new_content": new.read_text(encoding="utf-8") if new.exists() else None,
    "old_content": old.read_text(encoding="utf-8") if old.exists() else None,
}))
""" % (lib_naming.TP, lib_naming.REPO)


def leg(mode, sess="other"):
    obj, rc, out, err = lib_naming.tp_json(SNIP, args=[mode, sess])
    if obj is None:
        return None, err[-160:]
    return obj, ""


def main():
    r = lib_naming.Rec()

    print("== 腿1 无锁 → 接管写锁")
    obj, err = leg("none")
    if obj is None:
        r.env_fail("dispatcher_loop 求值失败：%s" % err)
    else:
        c = json.loads(obj["new_content"]) if obj.get("new_content") else {}
        r.check(obj["lock_held"] and c.get("session") == "probe",
                "接管且新锁写入本会话（held=%s new=%s）" % (obj["lock_held"], c.get("session")))

    print("== 腿2 他人持新锁未过期 → 只读不派不续写")
    obj, err = leg("new", sess="someone")
    if obj is None:
        r.env_fail("求值失败：%s" % err)
    else:
        c = json.loads(obj["new_content"]) if obj.get("new_content") else {}
        r.check(not obj["lock_held"] and c.get("session") == "someone",
                "held=false 且锁内容未被改写（held=%s content=%s）"
                % (obj["lock_held"], c.get("session")))

    print("== 腿3 新锁过期 → 接管")
    obj, err = leg("new-expired", sess="stale")
    if obj is None:
        r.env_fail("求值失败：%s" % err)
    else:
        r.check(obj["lock_held"], "过期新锁被接管（held=%s）" % obj["lock_held"])

    print("== 腿4 旧锁 TTL 内且无新锁 → 视为 held（防新旧实例并行双派）")
    obj, err = leg("old", sess="old-dispatcher")
    if obj is None:
        r.env_fail("求值失败：%s" % err)
    elif not (obj.get("has_new") and obj.get("has_old")):
        r.check(False, "新/旧双锁常量未在册（旧锁回落未落地）")
    else:
        oc = json.loads(obj["old_content"]) if obj.get("old_content") else {}
        r.check(not obj["lock_held"] and oc.get("session") == "old-dispatcher",
                "旧锁活→held=false 且旧锁文件只读（held=%s old=%s）"
                % (obj["lock_held"], oc.get("session")))

    print("== 腿5 旧锁过期 → 接管写新锁，旧锁不写不删")
    obj, err = leg("old-expired", sess="old-stale")
    if obj is None:
        r.env_fail("求值失败：%s" % err)
    elif not (obj.get("has_new") and obj.get("has_old")):
        r.check(False, "新/旧双锁常量未在册（旧锁回落未落地）")
    else:
        oc = json.loads(obj["old_content"]) if obj.get("old_content") else {}
        nc = json.loads(obj["new_content"]) if obj.get("new_content") else {}
        r.check(obj["lock_held"] and nc.get("session") == "probe"
                and oc.get("session") == "old-stale",
                "接管写新锁且旧锁原样（held=%s new=%s old=%s）"
                % (obj["lock_held"], nc.get("session"), oc.get("session")))

    r.finish()


if __name__ == "__main__":
    main()

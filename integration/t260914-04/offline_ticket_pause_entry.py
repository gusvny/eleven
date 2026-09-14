#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline_ticket_pause_entry —— ticket.py pause/resume 正规入口的离线契约腿
（t260914-04，KI-079 收口）。

定位：单组件 UT（run_scenarios 分层规则不进 SCENARIOS；非 sc_ 前缀=共享代码，
lint L5 不拦）。闸内执行由 sc_ticket_pause_gate.py 的 L0b 腿前置调用；平时可单独
秒跑（零 Temporal、零 docker、纯 stdlib）：

    python3 integration/t260914-04/offline_ticket_pause_entry.py   # exit 0=全绿

守的契约面：
  1. 载荷形状：pause/resume 转发 {'op','ticket_id','who','note'} 顶层形状（client.py
     ticket op=pause|resume 的 raw=args 双吃面），逐键相等——KI-079 病灶（宪章教 by、
     裸口只认 who → 事件历史全 op-local）的包装层负锁；
  2. D1 身份闸（review_plan C4②）：by|who 缺失/纯空白 → 本层 ValueError 点名、
     不触 Temporal（正规入口不落 op-local；'op-local' 缺省只留给裸入口）；
  3. id 必填；note 可选透传（缺省空串、非空原样——上限单点=workflow intake
     PAUSE_NOTE_INPUT_LIMIT，本层不抢答，不造第二真源）；
  4. by 主名与 who 别名双读等价（_who 复用面），环绕空白剥离；
  5. 未知 op 仍报「未知 op」（白名单外不放大）；
  6. 直 spawn CLI 面负锁：{} 无 op（白名单外）/缺 by → 结构化回执 + 非零退出，
     绝不空输出（-h/无参/非 JSON/非对象的通用形状归 t260910-06 A 段守——同入口
     同断言已登记在册，此处不重复锁，intent 不重复纪律）。

「who 空白 → workflow refused」语义不在此重复设防（由既有裸入口腿 L3.1 承载，
review_plan C5 分工）。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")

# 红线（t260910-06 同款，先于一切 spawn 钉死）：被测子进程的 Temporal 地址指不可达
# 桩——D1 身份闸若回归成「spawn 才拒收」，子进程只会撞连接拒绝现形，绝不触生产
# 7233/8233；审计同样只落 tmp（load_mod/cli_receipt 共用本进程 env）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)

passed, failed = 0, 0


def check(cond, label, why=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s%s" % (label, ("：%s" % why) if why else ""))


def load_mod(admin_log):
    """载入 ticket.py 模块：审计指 tmp，_poc 换捕获桩（手法=test_ticket_cli.py tk 夹具，
    该文件在写集外故落点改此；桩绝不触真 Temporal）。"""
    spec = importlib.util.spec_from_file_location("ticket_pause_entry_ut", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_pause_entry_ut"] = mod
    os.environ["SANDBAR_ADMIN_LOG"] = admin_log
    os.environ.pop("SANDBAR_CLIENT_ENTRY", None)
    os.environ.pop("SANDBAR_CLIENT_CALL_ID", None)
    spec.loader.exec_module(mod)
    calls = []

    def fake_poc(subcmd, payload):
        calls.append((subcmd, payload))
        return {"ok": True, "result": {"delivered": True, "signal": payload.get("op"),
                                       "who": payload.get("who")}}

    mod._poc = fake_poc
    mod._calls = calls
    return mod


def run_capture(mod, args):
    """跑 run(args) 返回回执；实现缺席/拒收（ValueError 等）回落 None——TDD 红期
    本脚本是逐用例 FAIL 汇总，不许半途 traceback 炸掉掩盖后程用例。"""
    try:
        return mod.run(args)
    except Exception:  # noqa: BLE001——红期非法 op 即走此路
        return None


def expect_value_error(mod, args, frag, label, why_hint=""):
    """断言 run(args) 抛含 frag 的 ValueError 且零 Temporal 接触（桩零调用）。"""
    mod._calls.clear()
    try:
        mod.run(args)
        check(False, label, "未拒收（桩调用=%s）" % mod._calls)
    except ValueError as e:
        check(frag in str(e) and mod._calls == [], label,
              "实得 %r；桩调用=%s%s" % (str(e)[:120], mod._calls, why_hint))
    except Exception as e:  # noqa: BLE001——错误类型本身即契约
        check(False, label, "异常类型 %s：%s" % (type(e).__name__, e))


def cli_receipt(argv):
    """直 spawn ticket.py，返回 (rc, 首个 JSON 回执 dict)。"""
    p = subprocess.run([sys.executable, TICKET_PY] + argv,
                       capture_output=True, text=True, timeout=60)
    receipt = {}
    for ln in (p.stdout or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                receipt = json.loads(ln)
                break
            except Exception:
                continue
    return p.returncode, receipt


def main():
    tmp = tempfile.mkdtemp(prefix="t260914-04-offline-")
    mod = load_mod(os.path.join(tmp, "admin.log"))

    print("== 1 载荷形状（转发 client.py ticket 顶层形状，逐键相等）")
    mod._calls.clear()
    r = run_capture(mod, {"op": "pause", "id": "t1", "by": "宿主", "note": "评审暂停"})
    check(r is not None, "pause op 在白名单（KI-079 验收①的包装层面）",
          "run 抛错/None——op 未实现")
    check(mod._calls == [("ticket", {"op": "pause", "ticket_id": "t1",
                                     "who": "宿主", "note": "评审暂停"})],
          "pause 转发 {'op','ticket_id','who','note'} 逐键相等（by→who、note 透传）",
          str(mod._calls))
    check(r is not None and r.get("delivered") is True and r.get("signal") == "pause",
          "回执原样上抛（_poc_ok 家族契约）", str(r))
    mod._calls.clear()
    r = run_capture(mod, {"op": "resume", "id": "t1", "by": "宿主"})
    check(mod._calls == [("ticket", {"op": "resume", "ticket_id": "t1",
                                     "who": "宿主", "note": ""})],
          "resume 同形状、note 缺省空串（不抢答 intake 上限）", str(mod._calls))

    print("== 2 D1 身份闸（who 必填注入；正规入口不落 op-local）")
    for bad, name in (({}, "缺身份"), ({"by": ""}, "by 空串"), ({"by": "   "}, "by 纯空白"),
                      ({"who": ""}, "who 空串"), ({"who": " \t "}, "who 纯空白")):
        expect_value_error(mod, {"op": "pause", "id": "t1", **bad},
                           "by|who", "pause %s → 拒收点名 by|who 且零 Temporal 接触" % name)

    print("== 3 id 必填 / by-who 双读等价")
    expect_value_error(mod, {"op": "pause", "by": "宿主"}, "需要 id",
                       "pause 缺 id → 拒收点名且零 Temporal 接触")
    expect_value_error(mod, {"op": "resume"}, "需要 id",
                       "resume 缺 id → 拒收点名且零 Temporal 接触")
    mod._calls.clear()
    run_capture(mod, {"op": "resume", "id": "t1", "who": " integration "})
    check(mod._calls and mod._calls[-1][1]["who"] == "integration",
          "who 别名收且环绕空白剥离（_who 双读复用面）", str(mod._calls))

    print("== 4 白名单外不放大")
    expect_value_error(mod, {"op": "nonsense"}, "未知 op",
                       "未知 op 仍报「未知 op」")

    print("== 5 直 spawn CLI 面负锁（结构化+非零，绝不空输出）")
    # -h/无参/非 JSON/非对象的通用形状归 t260910-06 A 段（登记场景，同入口同断言）
    # ——此处只留与本票 op 白名单面直接相邻的一笔，不重复锁。
    rc, receipt = cli_receipt(["{}"])
    err = str(receipt.get("error") or "")
    check(rc == 1 and receipt.get("ok") is False and "未知 op" in err,
          "{} 无 op：退出 1 + 结构化点名未知 op（白名单外面）",
          "rc=%s err=%s" % (rc, err[:120]))
    rc, receipt = cli_receipt([json.dumps({"op": "pause", "id": "t1"})])
    check(rc == 1 and receipt.get("ok") is False and "by|who" in str(receipt.get("error") or ""),
          "CLI 层 pause 缺 by → 结构化拒收点名 by|who（D1 直 spawn 面负锁）",
          "rc=%s out=%s" % (rc, str(receipt)[:160]))

    print("OFFLINE pause-entry: passed=%d failed=%d" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

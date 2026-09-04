# -*- coding: utf-8 -*-
"""t260902-02 t02 —— 归档路径白名单与路径穿越防呆。

用户故事：归档路径由工单 meta（外部输入）拼出，一张 ticket_id 形如 `../../evil`
的畸形工单**绝不能**把文件写到数据目录之外。白名单非法输入必须显式抛错，
且对文件系统零副作用。project_key 同口径（M1-2 既有白名单语义平移）。

跑法：python3 integration/t260902-02/t02_path_guard.py（cwd=泳道根）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

L = fx.Ledger()
KEY = "itestkey"
TICKET = "t-integ-1"

BAD_IDS = ["", "../evil", "..", "a/b", "A", "Bad Id", "-lead", "x" * 42,
           "trail.", "con..", "斜杠\\"]
GOOD_IDS = ["t1", "t-260902-02", "x" * 41, "9start"]  # 1+40=41 上限内


def expect_raise(fn, label):
    try:
        fn()
    except Exception as e:
        L.ok(True, "%s（抛 %s）" % (label, type(e).__name__))
        return str(e)
    L.ok(False, "%s（未抛错）" % label)
    return ""


def main():
    shared = fx.load_module("shared")
    aa = fx.load_module("agent_activities")

    # —— shared.ticket_data_dir 纯函数形状（方案 Step 1 契约）——
    if not hasattr(shared, "ticket_data_dir"):
        L.ok(False, "shared.ticket_data_dir 存在（方案 Step 1 契约）")
        return L.finish()
    L.ok(True, "shared.ticket_data_dir 存在")

    with fx.Sandbox() as sb:
        good = shared.ticket_data_dir(KEY, TICKET)
        L.ok(str(good).startswith(str(sb.root)),
             "合法入参落在数据根内：%s" % good)
        L.ok(str(good).endswith(str(Path(KEY) / "data" / "tickets" / TICKET)),
             "路径形状 <root>/<key>/data/tickets/<id>（实际 %s）" % good)

        for bad in BAD_IDS:
            def _call(b=bad):
                shared.ticket_data_dir(KEY, b)
            expect_raise(_call, "ticket_id=%r 被拒" % bad)
        for bad in ["", "../evil", "A", "-x", "k" * 42]:
            def _call2(b=bad):
                shared.ticket_data_dir(b, TICKET)
            expect_raise(_call2, "project_key=%r 被拒" % bad)
        for gid in GOOD_IDS:
            try:
                shared.ticket_data_dir(KEY, gid)
                L.ok(True, "ticket_id=%r 放行" % gid)
            except Exception as e:
                L.ok(False, "ticket_id=%r 被误拒：%s" % (gid, e))

        # —— 端到端零副作用：畸形 ticket_id 走 activity 也写不出任何东西 ——
        lane = fx.make_lane(sb, lane_name="lane-guard")
        before = sb.files_under(sb.tmp)
        meta = {"stage": "merge", "status": "closed", "sentinel": "guard"}
        for bad in ["../evil", "a/b", ""]:
            def _arch(b=bad):
                fx.invoke_archive(aa, ticket_id=b, project_key=KEY,
                                  worktree=lane, meta=meta)
            expect_raise(_arch, "archive_ticket ticket_id=%r 抛错且零副作用" % bad)
        after = sb.files_under(sb.tmp)
        L.ok(before == after, "畸形入参归档全程零文件系统副作用")

    return L.finish()


def _guarded():
    try:
        return main()
    except Exception as e:
        L.ok(False, "异常逃逸：%s: %s" % (type(e).__name__, str(e)[:300]))
        return L.finish()


if __name__ == "__main__":
    sys.exit(_guarded())

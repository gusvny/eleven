# -*- coding: utf-8 -*-
"""t260902-02 t03 —— 归档 fail-closed 两态 + 坏 JSON 字节级归档 + 会话缺失软处理。

用户故事（故障面）：
1) 归档目标不可写（只读目录/路径被文件占用）→ 归档必须**显式失败**、错误点名
   失败环节——绝不允许「拆了泳道再说」的静默丢报告（工单根因的反面防线）；
2) 泳道里结果文件内容是坏 JSON → 归档照常成功且**按字节**归档（归档是字节级
   拷贝真源，不解析内容；畸形由消费侧判）；
3) 泳道无会话文件 → 不失败，manifest.absent 记缺失类目（同 usage 端点既有降级）。

跑法：python3 integration/t260902-02/t03_fail_closed_idempotent.py（cwd=泳道根）
"""
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

L = fx.Ledger()
KEY = "itestkey"


def main():
    aa = fx.load_module("agent_activities")

    with fx.Sandbox() as sb:
        # —— 故障面 1a：目标父目录只读 → 显式失败，不静默 ——
        lane = fx.make_lane(sb, lane_name="lane-ro")
        ro_dir = sb.archive_dir(KEY, "t-integ-ro").parent
        ro_dir.mkdir(parents=True)
        os.chmod(ro_dir, stat.S_IREAD | stat.S_IEXEC)
        err = ""
        try:
            fx.invoke_archive(aa, ticket_id="t-integ-ro", project_key=KEY,
                              worktree=lane, meta={"stage": "merge"})
        except Exception as e:
            err = str(e)
        finally:
            os.chmod(ro_dir, stat.S_IRWXU)
        L.ok(len(err) > 0, "只读目标目录：归档显式抛错（fail-closed）")
        L.ok(not sb.archive_dir(KEY, "t-integ-ro").joinpath("archive.json").is_file(),
             "只读目标目录：未产出半个 manifest")

        # —— 故障面 1b：目标路径被普通文件占用 → 显式失败 ——
        lane2 = fx.make_lane(sb, lane_name="lane-occ")
        occ = sb.archive_dir(KEY, "t-integ-occ")
        occ.parent.mkdir(parents=True, exist_ok=True)
        occ.write_text("i am a file\n", "utf-8")
        err2 = ""
        try:
            fx.invoke_archive(aa, ticket_id="t-integ-occ", project_key=KEY,
                              worktree=lane2, meta={"stage": "merge"})
        except Exception as e:
            err2 = str(e)
        L.ok(len(err2) > 0, "目标路径被文件占用：归档显式抛错")

        # —— 故障面 2：坏 JSON 结果文件按字节归档，整体仍成功 ——
        lane3 = fx.make_lane(sb, lane_name="lane-bad", bad_stage=True)
        res3 = fx.invoke_archive(aa, ticket_id="t-integ-bad", project_key=KEY,
                                 worktree=lane3, meta={"stage": "merge"})
        bad_src = lane3 / ".suyou" / "stage_implement_gen0.json"
        bad_dst = sb.archive_dir(KEY, "t-integ-bad") / "stages" / "stage_implement_gen0.json"
        L.ok(bad_dst.is_file() and bad_dst.read_bytes() == bad_src.read_bytes(),
             "坏 JSON 结果文件按字节归档（不解析内容、不失败）")
        m3 = sb.manifest(KEY, "t-integ-bad")
        L.ok(m3 is not None and any(f["dst"].endswith("stage_implement_gen0.json")
                                    for f in m3.get("files", [])),
             "坏 JSON 文件照列 manifest")

        # —— 故障面 3：无会话文件 → 软处理，manifest.absent 记缺失 ——
        lane4 = fx.make_lane(sb, lane_name="lane-nosess", with_sessions=False)
        fx.invoke_archive(aa, ticket_id="t-integ-nosess", project_key=KEY,
                          worktree=lane4, meta={"stage": "merge"})
        m4 = sb.manifest(KEY, "t-integ-nosess")
        absent = m4.get("absent") or [] if m4 else []
        L.ok(m4 is not None, "无会话文件：归档照常成功（软处理不 fail）")
        L.ok(any("session" in str(a).lower() for a in absent),
             "absent 记录会话类目缺失（实际 %s）" % absent)

        # —— 幂等：同一票重跑，manifest 不漂 ——
        fx.invoke_archive(aa, ticket_id="t-integ-bad", project_key=KEY,
                          worktree=lane3, meta={"stage": "merge"})
        m3b = sb.manifest(KEY, "t-integ-bad")
        L.ok(m3b is not None
             and [f["dst"] for f in m3b.get("files", [])] == [f["dst"] for f in m3.get("files", [])],
             "fail-closed 场景外重跑 manifest 不漂")

    return L.finish()


def _guarded():
    try:
        return main()
    except Exception as e:
        L.ok(False, "异常逃逸：%s: %s" % (type(e).__name__, str(e)[:300]))
        return L.finish()


if __name__ == "__main__":
    sys.exit(_guarded())

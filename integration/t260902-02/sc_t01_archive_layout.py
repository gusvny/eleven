# -*- coding: utf-8 -*-
"""t260902-02 t01 —— 完结工单归档落位与 archive.json manifest 契约。

用户故事：dev-lane 票签字收口后，工单状态/会话/stage 日志/结算报告的归档真源
出现在机器级数据目录 ~/.sandbar/projects/<key>/data/tickets/<id>/（SANDBAR_PROJECTS_DIR
env 可覆盖），stage 报告**字节级**可回读——「完结工单 stage 报告随泳道拆除丢失」
根治的正面证据。manifest 形状、入档/排除口径按契约 v1 ①c（方案附录 B）。

黑盒手法：fixture 泳道（.suyou/.dsh 全真结构，含排除项诱饵）直调 archive_ticket
activity；断言全在文件系统上。零 Temporal 依赖。

跑法：python3 integration/t260902-02/t01_archive_layout.py（cwd=泳道根）
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

L = fx.Ledger()
KEY = "itestkey"
TICKET = "t-integ-1"


def main():
    aa = fx.load_module("agent_activities")
    with fx.Sandbox() as sb:
        lane = fx.make_lane(sb)
        meta = {"stage": "integration_review", "status": "settled",
                "timeline": [{"at": "2026-09-02T00:00:00", "stage": "implement"}],
                "handoffs": [], "checks": [], "sentinel": "s3nt1nel-01"}
        res = fx.invoke_archive(aa, ticket_id=TICKET, project_key=KEY,
                                worktree=lane, meta=meta)

        adir = sb.archive_dir(KEY, TICKET)
        L.ok(adir.is_dir(), "归档目录落位 %s" % adir.relative_to(sb.root))
        L.ok(adir.joinpath("archive.json").is_file(), "archive.json 已写")

        m = sb.manifest(KEY, TICKET)
        L.ok(m is not None, "archive.json 可解析")
        if m:
            L.ok(m.get("schema") == "v1", "schema=v1（实际 %r）" % m.get("schema"))
            Lok = m.get("ticket_id") == TICKET
            L.ok(Lok, "ticket_id 回写正确（实际 %r）" % m.get("ticket_id"))
            L.ok(m.get("legacy") is False, "legacy=false（新归档非 legacy）")
            try:
                datetime.fromisoformat(str(m.get("archived_at", "")).replace("Z", "+00:00"))
                iso_ok = True
            except ValueError:
                iso_ok = False
            L.ok(iso_ok, "archived_at 是 ISO 时间（实际 %r）" % m.get("archived_at"))
            files = m.get("files") or []
            L.ok(all(("dst" in f and "bytes" in f) for f in files),
                 "files 每条含 dst+bytes（契约 ①c 骨架 src/dst/bytes）")
            paths = [f["dst"] for f in files]
            L.ok(any(p.startswith("stages/") and p.endswith("stage_create_plan_gen0.json") for p in paths),
                 "stage 结果文件入档（stages/ 前缀）")
            L.ok(any(p.startswith("screenshots/") and p.endswith("shot-1.png") for p in paths),
                 "UI 截图入档且保留相对层级")
            L.ok(any(p.startswith("sessions/") for p in paths),
                 "会话事件文件入档（sessions/ 前缀）")
            L.ok(isinstance(m.get("excluded_rules"), list) and len(m["excluded_rules"]) > 0,
                 "excluded_rules 记录排除口径")

        # —— meta 快照原样入 manifest（带 sentinel 防实现自造数据）——
        mm = (m or {}).get("meta") or {}
        L.ok(mm.get("sentinel") == "s3nt1nel-01", "meta 快照原样入 manifest（sentinel 回声）")

        # —— 字节级回读：归档副本与泳道原件逐字节一致 ——
        src = lane / ".suyou" / "stage_create_plan_gen0.json"
        dst = adir / "stages" / "stage_create_plan_gen0.json"
        L.ok(dst.is_file() and dst.read_bytes() == src.read_bytes(),
             "stage 报告归档副本与原件字节一致")
        sshot_src = lane / ".suyou" / "screenshots" / "shot-1.png"
        sshot_dst = adir / "screenshots" / "shot-1.png"
        L.ok(sshot_dst.is_file() and sshot_dst.read_bytes() == sshot_src.read_bytes(),
             "UI 截图归档副本与原件字节一致")

        # —— 排除项绝不入档（含凭据红线）——
        archived = sb.files_under(adir)
        banned = [p for p in archived
                  if ("agent_" in p and p.endswith(".log"))
                  or p.startswith("model_patch_") or p.startswith("resume_patch_")
                  or ".credentials" in p or "profiles" in p]
        L.ok(not banned, "排除项零入档（agent_*.log/patch yml/凭据/profiles）：%s" % banned)

        # —— 幂等重跑：同一输入两遍产物一致（Temporal 重试安全）——
        res2 = fx.invoke_archive(aa, ticket_id=TICKET, project_key=KEY,
                                 worktree=lane, meta=meta)
        m2 = sb.manifest(KEY, TICKET)
        L.ok(m2 is not None and [f["dst"] for f in m2.get("files", [])] == paths,
             "重跑后 files 清单一致（无重复/漂移）")
        L.ok(len([p for p in sb.files_under(adir) if p.endswith("archive.json")]) == 1,
             "重跑不产生第二份 manifest")

    return L.finish()


def _guarded():
    try:
        return main()
    except Exception as e:
        L.ok(False, "异常逃逸：%s: %s" % (type(e).__name__, str(e)[:300]))
        return L.finish()


if __name__ == "__main__":
    sys.exit(_guarded())

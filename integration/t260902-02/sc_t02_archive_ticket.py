#!/usr/bin/env python3
"""t02 —— archive_ticket activity 全路径（M1-3 契约 ①c 的写侧真源）。

fixture 泳道（tmp）：三系入档（stage_*.json 含坏 JSON 原样 / screenshots 保层级 /
.dsh/sessions 含 slug 子目录）+ 排除面（agent_*.log / model_patch / resume_patch /
.credentials.yaml 不入档）+ 幂等重跑 + 损坏 manifest 拒重产 + 引用缺失拒重产 +
.suyou 缺失灰面代理文件 + .dsh 缺失记 absent + legacy 诚实过账 + 只读目标 fail-closed。  # naming-compat

temporalio 桩（只挡模块级依赖）；activity 为 async，asyncio.run 直跑 .fn。
跑法：python3 integration/t260902-02/t02_archive_ticket.py（cwd=泳道根）
"""
import asyncio
import json
import logging
import os
import stat
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
POC = REPO / "server" / "engine"

_tmod = types.ModuleType("temporalio")
_amod = types.ModuleType("temporalio.activity")


class _ActivityStub:
    logger = logging.getLogger("temporalio-stub-t02")

    def defn(self, fn=None, **kw):
        return (lambda f: f) if fn is None else fn

    def heartbeat(self, *a, **kw):
        pass


_amod.activity = _ActivityStub()
_tmod.activity = _ActivityStub()
sys.modules.setdefault("temporalio", _tmod)
sys.modules.setdefault("temporalio.activity", _amod)
sys.path.insert(0, str(POC))

from shared import ArchiveArgs  # noqa: E402
import agent_activities as aa  # noqa: E402

PASS = FAIL = ENV_FAIL = 0  # 三态契约：0=PASS、1=FAIL（产品红）、2=ENV_FAIL（环境红）
ROOT = tempfile.mkdtemp(prefix="t02-sb-")


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)


def make_lane(with_suyou=True, with_dsh=True):
    lane = Path(tempfile.mkdtemp(prefix="t02-lane-"))
    if with_suyou:
        (lane / ".suyou" / "screenshots" / "sub").mkdir(parents=True)  # naming-compat
        (lane / ".suyou" / "stage_create_plan_gen0.json").write_text(  # naming-compat
            '{"status":"ok"}', encoding="utf-8")
        (lane / ".suyou" / "stage_implement_gen0.json").write_text(  # naming-compat
            "{not valid json", encoding="utf-8")   # 坏 JSON 原样入档
        (lane / ".suyou" / "screenshots" / "a.png").write_bytes(b"\x89PNG fake-a")  # naming-compat
        (lane / ".suyou" / "screenshots" / "sub" / "b.png").write_bytes(b"\x89PNG fake-b")  # naming-compat
        (lane / ".suyou" / "agent_create_plan_gen0.log").write_text("spawn log", encoding="utf-8")  # naming-compat
        (lane / ".suyou" / "model_patch_create_plan_gen0.yml").write_text("x: 1", encoding="utf-8")  # naming-compat
        (lane / ".suyou" / "resume_patch_create_plan_gen0.yml").write_text("y: 2", encoding="utf-8")  # naming-compat
    if with_dsh:
        (lane / ".dsh" / "sessions" / "repo--slug--").mkdir(parents=True)
        (lane / ".dsh" / "sessions" / "repo--slug--" / "sess1.zst").write_bytes(b"zstd-bytes")
        (lane / ".dsh" / "sessions" / "repo--slug--" / "agent_create_plan_gen0.log").write_text(
            "session spawn log", encoding="utf-8")
        (lane / ".dsh" / ".credentials.yaml").write_text("key: secret", encoding="utf-8")
        (lane / ".dsh" / "profiles").mkdir()
    return lane


def _unwrap(act):
    """桩下 activity 是裸函数；真 temporalio 下是 ActivityDefinition(.fn)。"""
    return getattr(act, "fn", act)


def run_archive(lane, tid="t02-case", project="suyou", legacy=False, meta=None):
    args = ArchiveArgs(ticket_id=tid, project_key=project,
                       worktree=str(lane), meta=meta or {"stage": "merge"})
    if legacy:
        args.legacy = True
    return asyncio.run(_unwrap(aa.archive_ticket)(args))


def main():
    os.environ["SANDBAR_PROJECTS_DIR"] = ROOT
    try:
        # ---- case 1：三系入档 + 排除面 + 坏 JSON 原样 + 字节真值 ----
        lane = make_lane()
        res = run_archive(lane)
        ok(res.ok and res.retained, "归档成功且泳道保留（待 teardown）")
        dst = Path(res.archive_path)
        ok(str(dst).startswith(ROOT + "/suyou/data/tickets/t02-case"), "归档落位 data/tickets/<id>/")
        man = json.loads((dst / "archive.json").read_text(encoding="utf-8"))
        ok(man["schema"] == "v1" and man["legacy"] is False, "manifest schema v1 / legacy false")
        dsts = {f["dst"] for f in man["files"]}
        ok("stages/stage_create_plan_gen0.json" in dsts, "stage 结果入档 stages/")
        ok("stages/stage_implement_gen0.json" in dsts, "坏 JSON stage 文件也入档（字节级拷贝）")
        ok((dst / "stages/stage_implement_gen0.json").read_text(encoding="utf-8") == "{not valid json",
           "坏 JSON 原样字节保留（不解析不修复）")
        ok("screenshots/a.png" in dsts and "screenshots/sub/b.png" in dsts,
           "UI 截图入档且保相对层级")
        ok("sessions/repo--slug--/sess1.zst" in dsts, "会话落盘入档 sessions/（slug 层级）")
        ok(not any("agent_" in d and d.endswith(".log") for d in dsts), "agent_*.log 不入档")
        ok(not any("model_patch" in d or "resume_patch" in d for d in dsts), "patch yml 不入档")
        ok(not any("credentials" in d for d in dsts), "凭据绝不入档")
        ok(not (dst / ".dsh").exists(), "归档目录内无 .dsh 泄漏")
        sizes = {f["dst"]: f["bytes"] for f in man["files"]}
        ok(all((dst / k).stat().st_size == v for k, v in sizes.items() if v > 0),
           "manifest 字节数=归档侧 stat 真值")
        ok(man["meta"].get("stage") == "merge", "meta 快照随 manifest 落档")
        ok(not man["absent"], "全量泳道无 absent 记录")

        # ---- case 2：幂等重跑（引用校验通过，零异常）----
        res2 = run_archive(lane)
        ok(res2.ok, "幂等重跑成功（引用校验通过）")

        # ---- case 3：损坏 manifest 拒重产（灰面 fail-closed）----
        (dst / "archive.json").write_text("{corrupted", encoding="utf-8")
        try:
            run_archive(lane)
            ok(False, "损坏 manifest → ArchiveManifestError（不静默重产）")
        except aa.ArchiveManifestError:
            ok(True, "损坏 manifest → ArchiveManifestError（不静默重产）")
        # 人工处置=删除灰面 manifest，重跑恢复真档
        (dst / "archive.json").unlink()
        run_archive(lane)

        # ---- case 4：manifest 引用文件被删 → 拒重产 ----
        (dst / "stages" / "stage_create_plan_gen0.json").unlink()
        try:
            run_archive(lane)
            ok(False, "引用缺失 → ArchiveManifestError（可能已被覆写，人工处置）")
        except aa.ArchiveManifestError:
            ok(True, "引用缺失 → ArchiveManifestError（可能已被覆写，人工处置）")
        (dst / "stages" / "stage_create_plan_gen0.json").write_text("{}", encoding="utf-8")
        # 注意：手工补回的文件与 manifest bytes 不符——但校验只看「引用存在」，
        # 自愈重拷会覆盖为真值；这里验证自愈路径：
        res4 = run_archive(lane)
        ok(res4.ok and (dst / "stages" / "stage_create_plan_gen0.json").read_text() == '{"status":"ok"}',
           "引用存在但内容被改 → 重拷自愈回真值")

        # ---- case 5：.suyou 缺失灰面 → 代理文件 + .dsh 缺失 → absent ----  # naming-compat
        lane2 = make_lane(with_suyou=False, with_dsh=False)
        res5 = run_archive(lane2, tid="t02-gray")
        dst5 = Path(res5.archive_path)
        man5 = json.loads((dst5 / "archive.json").read_text(encoding="utf-8"))
        ok(res5.ok, "灰面泳道归档不失败（代理文件语义）")
        ok(any(f["bytes"] == 0 for f in man5["files"]), "manifest 记代理文件（bytes=0 标记）")
        proxy = dst5 / "stages" / "stage_implement_gen0.json"
        ok(proxy.is_file() and "代理文件" in proxy.read_text(encoding="utf-8"),
           "代理文件落盘且明牌说明（不伪造内容）")
        ok(any("sessions" in a for a in man5["absent"]), ".dsh 缺失记 absent（软处理）")

        # ---- case 6：legacy 诚实过账 ----
        res6 = run_archive(lane, tid="t02-legacy", legacy=True)
        man6 = json.loads((Path(res6.archive_path) / "archive.json").read_text(encoding="utf-8"))
        ok(res6.ok and res6.retained is False, "legacy 过账成功且 retained=False")
        ok(man6["legacy"] is True and man6["files"] == [] and man6["absent"] == ["worktree"],
           "legacy manifest：files 空 + absent worktree")
        ok("不可恢复" in (man6.get("reason") or ""), "legacy reason 明牌（不伪造不补产）")

        # ---- case 7：只读目标 fail-closed（不静默降级）----
        lane3 = make_lane()
        ro_dir = Path(ROOT) / "suyou" / "data" / "tickets"
        os.chmod(ro_dir, stat.S_IRUSR | stat.S_IXUSR)   # 0550：不可写
        try:
            run_archive(lane3, tid="t02-readonly")
            ok(False, "只读目标 → fail-closed 上抛（OSError）")
        except OSError:
            ok(True, "只读目标 → fail-closed 上抛（OSError）")
        finally:
            os.chmod(ro_dir, stat.S_IRWXU)

        # ---- case 8：非法 project_key / ticket_id 在边界即拒 ----
        for bad_args, label in [
                (dict(project="../evil"), "archive 入参 project_key 穿越被拒"),
                (dict(tid="-bad"), "archive 入参 ticket_id 非法被拒")]:
            try:
                args = ArchiveArgs(ticket_id=bad_args.get("tid", "t02-x"),
                                   project_key=bad_args.get("project", "suyou"),
                                   worktree=str(make_lane()))
                asyncio.run(_unwrap(aa.archive_ticket)(args))
                ok(False, label)
            except ValueError:
                ok(True, label)
    finally:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, FAIL, ENV_FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

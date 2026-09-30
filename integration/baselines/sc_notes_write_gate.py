#!/usr/bin/env python3
"""机械闸守卫：dev-lane 工单禁写 notes/（宿主令 260904）。

背景：t260904-01/03 两单的 lane 侧票据账（KI 行/epic 记录）在 main 侧与
integration 直修同区相撞、多次合并冲突（含一次语义冲突须人工取舍）；且
notes/epics/ 出现过未跟踪草案直落账本目录。宿主拍板：notes/ = 票据/知识库
账本，归 main 侧（integration/宿主）直管，工单一律不写——三执法点机械化：

  A. 合并闸 verify_lane：diff 触 notes/（A/M/T/D 任一状态）= 红，独立于写集
     判定——**声明了 notes/ 也拦**（防自授权）；D 同拦（删账=丢账，与运行时
     前缀「D=清退放行」口径不同）；写集外的普通文件判越界照旧（不误伤）。
  B. 建单侧 ticket.create：写集含 notes/ → 创建即拒（人话指路结算 note）。
  C. 粗判据面：本仓 verify.yaml write_allow 无 notes/（防回潮静态守卫）。

跑法：python3 -B integration/baselines/sc_notes_write_gate.py（cwd=仓根）
纯本地：tmp git 仓 + 真子进程 verify_lane/admin 参数校验，零 Temporal 零端口。
"""
import importlib.util
import json
import subprocess
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADMIN = REPO / "server" / "admin.py"

_ok = _fail = 0


def ok(cond, label):
    global _ok, _fail
    print(("  ok " if cond else "  FAIL ") + label)
    _ok, _fail = _ok + (1 if cond else 0), _fail + (0 if cond else 1)


def section(t):
    print("\n== " + t)


def sh(*cmd, cwd=None, env=None):
    """子进程壳。env 缺省=None → 继承本进程 env；**调执行器/闸的调用点必须显式传
    clean_narrowing_env()**（260930：继承的收窄旋钮会把内层面收窄）。"""
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None, env=env)


VERIFY_YAML = """schema: v1
lanes:
  code:
    write_allow:
      - integration/
    checks:
      - id: t-always-green
        cmd: "true"
"""


def mk_repo():
    """tmp git 仓 + 最小 verify.yaml；返回 (repo, base)——base=初 commit。"""
    repo = Path(tempfile.mkdtemp(prefix="notes-gate-"))
    (repo / "verify.yaml").write_text(VERIFY_YAML, encoding="utf-8")
    (repo / "integration").mkdir()
    (repo / "integration" / ".keep").write_text("", encoding="utf-8")
    sh("git", "init", "-q", "-b", "main", cwd=repo)
    sh("git", "add", "-A", cwd=repo)
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=repo)
    base = sh("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    return repo, base


def commit_touch(repo, rel, content, delete=False):
    p = repo / rel
    if delete:
        p.unlink()
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "touch " + rel, cwd=repo)


def verify_lane(repo, base, write_set=None):
    """真子进程调 admin.py verify_lane；返回 (ok, 白名单检查项明细文本)。"""
    payload = {"lane": "code", "path": str(repo), "base": base, "require_base": True}
    if write_set is not None:
        payload["write_set"] = write_set
    # 260930：闸调用点清单点 helper（继承的收窄旋钮会把内层闸收窄）
    r = sh(sys.executable, str(ADMIN), "call", "verify_lane", json.dumps(payload), cwd=repo,
           env=clean_narrowing_env())
    try:
        out = json.loads(r.stdout)          # 整段 JSON（merge_check 同款，非末行）
    except (ValueError, IndexError):
        return None, "回执不是 JSON：%r" % r.stdout[-200:]
    checks = ((out.get("result") or {}).get("checks") or [])
    for c in checks:
        if c.get("check") == "写集白名单":
            return c.get("level"), json.dumps(c, ensure_ascii=False)
    return None, "(无写集白名单项) checks=%s" % json.dumps(checks, ensure_ascii=False)[:200]


def load_ticket_module():
    spec = importlib.util.spec_from_file_location("ticket_gate", REPO / "server" / "tools" / "ticket.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    print("机械闸守卫：dev-lane 工单禁写 notes/（宿主令 260904）")

    # ---- A. 合并闸 verify_lane：四态真子进程 ----
    section("A1 声明了 notes/ 也拦（防自授权）——A 新增 notes/")
    repo, base = mk_repo()
    commit_touch(repo, "notes/debts/known-issues.md", "| KI-099 | 越界尝试 |\n")
    ok_flag, detail = verify_lane(repo, base, write_set=["notes/", "integration/"])
    ok(ok_flag == "red" and "notes/ 禁写" in detail and "宿主令 260904" in detail,
       "红且文案点名禁写与拍板来源（detail=%s…）" % detail[:80])

    section("A2 D 删账同拦（删账=丢账，不走清退口径）")
    repo, base = mk_repo()
    commit_touch(repo, "notes/legacy.md", "旧账\n")           # 先入库
    base2 = sh("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    commit_touch(repo, "notes/legacy.md", "", delete=True)     # 再删
    ok_flag, detail = verify_lane(repo, base2, write_set=["notes/", "integration/"])
    ok(ok_flag == "red" and "notes/ 禁写" in detail, "删除 notes/ 亦红（detail=%s…）" % detail[:80])

    section("A3 不误伤：写集内普通文件（integration/）照常绿")
    repo, base = mk_repo()
    commit_touch(repo, "integration/x.py", "print(1)\n")
    ok_flag, detail = verify_lane(repo, base, write_set=["integration/"])
    ok(ok_flag == "green", "写集内 integration/ 改动白名单项绿（%s）" % detail[:80])

    section("A4 粗判据路径（无 write_set）同样禁 notes/")
    repo, base = mk_repo()
    commit_touch(repo, "notes/epics/draft.md", "# 草案直落账本\n")
    ok_flag, detail = verify_lane(repo, base, write_set=None)
    ok(ok_flag == "red" and "notes/ 禁写" in detail, "粗判据分支同拦（detail=%s…）" % detail[:80])

    # ---- B. 建单闸：纯函数面（不触 Temporal） ----
    section("B 建单侧写集校验（ticket.validate_write_set_no_notes）")
    ticket = load_ticket_module()
    for ws in (["notes/"], ["notes"], ["integration/", "notes/debts/"], ["notes/epics/x.md"]):
        try:
            ticket.validate_write_set_no_notes(ws)
            ok(False, "写集 %s 应被拒" % ws)
        except ValueError as e:
            ok("宿主令 260904" in str(e) and "结算 note" in str(e),
               "写集 %s 建单即拒且人话指路（%s…）" % (ws, str(e)[:60]))
    for ws in ([], ["server/"], ["integration/", "server/"], None):
        try:
            ticket.validate_write_set_no_notes(ws)
            ok(True, "写集 %s 正常放行" % ws)
        except ValueError as e:
            ok(False, "写集 %s 误拒：%s" % (ws, e))

    # ---- C. 粗判据表静态守卫：本仓 write_allow 无 notes/ ----
    section("C verify.yaml write_allow 无 notes/（防回潮）")
    vy = (REPO / "verify.yaml").read_text(encoding="utf-8")
    wl = vy.split("write_allow:")[1].split("checks:")[0] if "write_allow:" in vy else ""
    ok(not any(l.strip().lstrip("- ").strip() in ("notes", "notes/") for l in wl.splitlines()),
       "write_allow 条目无 notes/（除名注释行不算活口）")

    print("\nSC sc_notes_write_gate pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

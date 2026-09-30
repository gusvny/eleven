#!/usr/bin/env python3
"""t260902-10 集成场景②：KI-015 端到端回归（真 git，非桩）——大 diff 白名单既不假红也不漏检。

用户可感知故障面（KI-015）：白名单 diff 大于裁剪窗时——
  a) 末尾裁剪把首行裁成半截路径 → 假越界误阻断（假阳性）；
  b) 裁点之前的文件静默不检 → 越界文件漏报（假阴性）。
本场景在 /tmp 真 git 仓库构造 >2349 字节多行 diff，经 admin.py call（合并闸同款路径）
双向断言：越界文件（排序恰在 diff 首行=历史上被裁掉的那行）必被点名；全部在写集内时零假红。
"""
import json
import shutil
import subprocess
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
import tempfile
from pathlib import Path

LANE = Path.cwd()
PY = sys.executable
PAD = "y" * 30  # 路径垫长，保证 diff 总量远超历史裁剪窗（>2349 字节）


def git(*args, cwd):
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError("git %s 失败: %s" % (args[0], (p.stderr or "")[-200:]))
    return p.stdout.strip()


def run_verify(project_root, base, write_set):
    args = {"lane": "code", "path": str(project_root), "base": base,
            "require_base": True, "write_set": write_set}
    p = subprocess.run([PY, "server/admin.py", "call", "verify_lane", json.dumps(args)],
                       capture_output=True, text=True, timeout=120,
                       env=clean_narrowing_env())   # 260930：闸调用点清单点 helper
    if p.returncode != 0:
        raise AssertionError("admin call 非零退出: %s" % (p.stderr or p.stdout)[-300:])
    payload = json.loads(p.stdout)
    assert payload.get("ok"), "admin call 报错: %s" % payload
    return payload["result"]


def main():
    root = Path(tempfile.mkdtemp(prefix="t26090210-ki015-"))
    try:
        git("init", cwd=root)
        git("config", "user.email", "t@t", cwd=root)
        git("config", "user.name", "t", cwd=root)
        (root / "a.txt").write_text("base\n", encoding="utf-8")
        git("add", "a.txt", cwd=root)
        git("commit", "-m", "base", cwd=root)
        base_sha = git("rev-parse", "HEAD", cwd=root)

        pkg = root / "server" / "pkg"
        pkg.mkdir(parents=True)
        # 越界文件：字典序最靠前 → diff --name-only 的首行（KI-015 中正是被裁掉的行）
        outside = "server/pkg/aaa_outside_%s.py" % PAD
        inside = ["server/pkg/f%02d_inwrite_%s.py" % (i, PAD) for i in range(60)]
        # verify.yaml 是项目自身声明文件，也在本 diff 内、合法在写集内
        inside.append("verify.yaml")
        for rel in [outside] + inside:
            (root / rel).write_text("# %s\n" % rel, encoding="utf-8")
        # 引擎要求项目有 verify.yaml（缺失=整道关闭）；白名单判据走工单 write_set 精判
        (root / "verify.yaml").write_text(
            "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/\n",
            encoding="utf-8")
        git("add", "-A", cwd=root)
        git("commit", "-m", "big diff", cwd=root)

        diff_bytes = len(git("diff", "--name-only", base_sha + "...HEAD", cwd=root).encode())
        assert diff_bytes > 2349, "diff 构造不足 %d 字节（需 >2349）" % diff_bytes

        # 断言一（防假阴性）：越界文件虽在 diff 首行（裁剪窗边缘），仍被点名判红
        res1 = run_verify(root, base_sha, inside)
        reds = [(c["check"], i.get("detail", "")) for c in res1["checks"] if c["level"] == "red"
                for i in c.get("items", [])]
        assert not res1["green"], "存在越界文件却判绿（静默漏检——KI-015 假阴性复发）"
        assert len(reds) == 1, "应恰有一条越界红，实际 %d 条: %s" % (len(reds), reds)
        assert "aaa_outside" in reds[0][1], "红项应点名真实越界路径（而非半截假路径首行）: %s" % reds[0][1]

        # 断言二（防假阳性）：全部文件都在写集内 → 零假红（大 diff 不产生半截路径假越界）
        res2 = run_verify(root, base_sha, inside + [outside])
        reds2 = [(c["check"], i.get("detail", "")) for c in res2["checks"] if c["level"] == "red"
                 for i in c.get("items", [])]
        assert res2["green"], "全量在写集内却判红（假越界——KI-015 假阳性复发）: %s" % reds2

        print("PASS 大diff白名单双向断言（diff=%d字节, 越界点名+全量零假红）" % diff_bytes)
        print("SUMMARY: 2/2 PASS")
        return 0
    except AssertionError as e:
        print("FAIL %s" % e)
        print("SUMMARY: 失败")
        return 1
    except Exception as e:
        print("FAIL 异常 %s: %s" % (type(e).__name__, e))
        print("SUMMARY: 失败")
        return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

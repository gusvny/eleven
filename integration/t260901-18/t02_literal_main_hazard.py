#!/usr/bin/env python3
"""t02 字面 main vs merge-base 的语义钉（两点 diff 口径）。

用户场景保护：防止后人把白名单 base「简化」回字面 main——两点 diff 下，
泳道落后 main（还没并 main）时，字面 main 会把 main 侧新文件算进泳道 diff
→ 误判照旧。本用例纯 git 复刻 _diff_names 的两点 diff，把两种形态钉死：
  形态一（泳道落后 main）：字面 main 必含 main 侧文件（假阳性），merge-base 不含。
  形态二（泳道已并 main）：两者等价（此时字面 main 恰好不炸——但不能据此互推）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t18lib import ok, finish, make_repo, commit, git, mkdtemp, rmtree


def two_point_diff(repo, base: str):
    p = git(repo, "-c", "core.quotepath=false", "diff", "--name-only", base + "..HEAD")
    assert p.returncode == 0, "git diff 失败: %s" % p.stderr
    return p.stdout.split()


def main() -> int:
    tmp = mkdtemp()
    try:
        repo = make_repo(tmp)

        # 共同祖先：main 与 lane 分叉点
        (repo / "w.txt").write_text("w\n", "utf-8")
        fork = commit(repo, "fork point")
        git(repo, "branch", "-M", "main")

        # 泳道只改自己的文件；main 侧推进他单文件（泳道未并 main = 落后形态）
        git(repo, "checkout", "-q", "-b", "lane", fork)
        (repo / "w.txt").write_text("w lane\n", "utf-8")
        commit(repo, "泳道改动")
        git(repo, "checkout", "-q", "main")
        (repo / "main_side.tsx").write_text("export const M = 1\n", "utf-8")
        commit(repo, "main 侧他单文件")
        git(repo, "checkout", "-q", "lane")

        d_literal = two_point_diff(repo, "main")
        ok("main_side.tsx" in d_literal,
           "落后形态：字面 main 两点 diff 含 main 侧文件（假阳性，复现误判形态）")
        ok("w.txt" in d_literal and len(d_literal) == 2,
           "落后形态：字面 main 把泳道改动与 main 改动混在一起（口径脏）")

        mb = git(repo, "merge-base", "main", "lane").stdout.strip()
        ok(mb == fork, "落后形态：merge-base=分叉点（%s…）" % mb[:7])
        d_mb = two_point_diff(repo, mb)
        ok(d_mb == ["w.txt"],
           "落后形态：merge-base 两点 diff 只有泳道自己的改动（白名单语义）")

        # 形态二：泳道并入 main 后，字面 main 与 merge-base 等价
        git(repo, "merge", "-q", "--no-edit", "main")
        mb2 = git(repo, "merge-base", "main", "lane").stdout.strip()
        ok(two_point_diff(repo, "main") == two_point_diff(repo, mb2),
           "已并 main 形态：字面 main ≡ merge-base（但不可据此互推——形态一已证不等价）")

        return finish()
    finally:
        rmtree(tmp)


if __name__ == "__main__":
    sys.exit(main())

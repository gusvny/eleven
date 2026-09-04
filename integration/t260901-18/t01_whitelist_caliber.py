#!/usr/bin/env python3
"""t01 白名单口径行为差：KI-010 复刻（旧口径必红）+ 修复解锁（merge-base 必绿）
+ 真越界仍红（修复不许变成全放行）。

用户场景：t260901-16/14 活着期间，13 号灯箱文件经 main 被泳道 merge 进来；
合并闸白名单把「他单文件」误判成「本单越界」red=5，把修复闸口径的工单自己卡死。
本用例在 tmp 假仓复刻全链路，真跑 verify_lane 白名单判定。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t18lib import (ok, finish, make_repo, commit, write_verify_yaml,
                    verify_lane_code, whitelist_items, git, mkdtemp, rmtree)

WRITE_SET = ["w.txt"]


def main() -> int:
    tmp = mkdtemp()
    try:
        repo = make_repo(tmp)
        write_verify_yaml(repo)

        # 工单 create：钉死 base_ref（主树 HEAD）
        (repo / "w.txt").write_text("w\n", "utf-8")
        base_ref = commit(repo, "base（create 时钉死）")
        git(repo, "branch", "-M", "main")

        # 他泳道（13 号灯箱）落入 main——不在本单 write_set
        (repo / "lightbox.tsx").write_text("export const Lightbox = 1\n", "utf-8")
        commit(repo, "13号灯箱并入 main")

        # 本泳道：从钉死 base_ref 开工，改 write_set 内文件，再 merge main 解锁
        git(repo, "checkout", "-q", "-b", "lane", base_ref)
        (repo / "w.txt").write_text("w lane\n", "utf-8")
        commit(repo, "泳道改 w.txt")
        assert git(repo, "merge", "-q", "--no-edit", "main").returncode == 0

        # A. 旧口径复刻（对照桩）：base=钉死 base_ref → 必须红，且红因=lightbox.tsx
        r_old = verify_lane_code(repo, base_ref, WRITE_SET)
        items = whitelist_items(r_old)
        ok(items is not None and len(items) > 0, "旧口径复刻：白名单出红（KI-010 形态）")
        ok(any("lightbox.tsx" in it.get("detail", "") for it in (items or [])),
           "旧口径复刻：红因点到 lightbox.tsx（他单文件），不是含糊文案")

        # B. 新口径解锁：base=merge-base(main, lane) → 必须绿
        mb = git(repo, "merge-base", "main", "lane").stdout.strip()
        ok(bool(mb), "merge-base 解析成功（%s…）" % mb[:7])
        r_new = verify_lane_code(repo, mb, WRITE_SET)
        ok(r_new.get("green") is True and whitelist_items(r_new) == [],
           "新口径：白名单绿（他单灯箱文件不再误判越界）")

        # C. 真越界回归：泳道再加 write_set 外文件 → 必须红，且只点 rogue 不点 lightbox
        (repo / "rogue.py").write_text("print('out of write set')\n", "utf-8")
        commit(repo, "泳道越界改动")
        mb2 = git(repo, "merge-base", "main", "lane").stdout.strip()
        r_rogue = verify_lane_code(repo, mb2, WRITE_SET)
        items_c = whitelist_items(r_rogue) or []
        ok(r_rogue.get("green") is False and any("rogue.py" in it.get("detail", "") for it in items_c),
           "真越界仍红（修复没把闸打穿）")
        ok(not any("lightbox.tsx" in it.get("detail", "") for it in items_c),
           "真越界红因不含 lightbox.tsx（精度：只点泳道自己的越界）")

        return finish()
    finally:
        rmtree(tmp)


if __name__ == "__main__":
    sys.exit(main())
